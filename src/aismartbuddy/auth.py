"""Optional Microsoft Entra ID (Azure AD) OAuth token verifier.

Imports `httpx` and `pyjwt` — both pulled in by the `[entra]` optional
dependency group. Without that extra, this module fails to import; that
is the intended failure mode (clearly diagnosed in server.py:_maybe_build_auth).

Activated only when both AISMARTBUDDY_ENTRA_TENANT and
AISMARTBUDDY_ENTRA_AUDIENCE are set. When active, every MCP tool call
requires a Bearer token issued by the configured Entra tenant for the
configured audience; MCP v2's bearer auth context resolves to the Entra `oid`
claim (stable principal object ID), which the multi-tenant model in
`identity.py` uses as `user_id`.

Configure on the Entra side:
- Register an app, expose an API scope (e.g. `mcp.invoke`)
- Set audience to `api://<application-id-uri>`
- Tokens issued to that audience for the right tenant validate here.

See README.md "Remote deployment → Option B" for end-to-end recipes.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from mcp.server.auth.provider import AccessToken, TokenVerifier

logger = logging.getLogger("aismartbuddy.auth")

# Cache JWKS for this many seconds before next refresh. Entra rotates keys
# periodically; if we encounter an unknown key ID, we force a refresh
# regardless of cache age.
_JWKS_CACHE_TTL = 3600


class EntraTokenVerifier(TokenVerifier):
    """Validates Bearer tokens issued by Microsoft Entra ID (Azure AD).

    Verification:
    1. Fetch the tenant JWKS (cached for 1h, force-refreshed on key miss)
    2. Look up the public key by `kid` from the token header
    3. Verify RS256 signature, audience, and issuer
    4. Optionally check that a required scope is present in `scp`
    5. Return AccessToken with `client_id` = Entra `oid` (stable across renames)
    """

    def __init__(
        self,
        tenant_id: str,
        audience: str,
        required_scope: str | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._audience = audience
        self._required_scope = required_scope
        self._issuer = (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        self._jwks_url = (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0
        self._lock = Lock()

    @property
    def issuer(self) -> str:
        return self._issuer

    async def _get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch JWKS, with simple TTL cache and force-refresh option."""
        now = time.time()
        if (
            not force_refresh
            and self._jwks is not None
            and (now - self._jwks_fetched_at) < _JWKS_CACHE_TTL
        ):
            return self._jwks
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._jwks_url)
            resp.raise_for_status()
            jwks = resp.json()
        with self._lock:
            self._jwks = jwks
            self._jwks_fetched_at = now
        return jwks

    @staticmethod
    def _find_key(jwks: dict[str, Any], kid: str) -> Any:
        """Find an RSA public key in JWKS by `kid`. Returns None on miss."""
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return RSAAlgorithm.from_jwk(key)
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify the Bearer token. Returns None on any failure (per MCP contract).

        Returning None — rather than raising — is deliberate: the MCP auth
        middleware uses None to signal "401 Unauthorized" without leaking
        why (timing-attack resistant).
        """
        # 1. Decode header (no signature check yet) to find `kid`
        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            if not kid:
                return None
        except jwt.PyJWTError:
            return None

        # 2. Look up the signing key, force-refreshing JWKS if it's not found
        jwks = await self._get_jwks()
        key = self._find_key(jwks, kid)
        if key is None:
            jwks = await self._get_jwks(force_refresh=True)
            key = self._find_key(jwks, kid)
            if key is None:
                logger.warning("No matching JWKS key for kid=%s", kid)
                return None

        # 3. Verify signature + claims
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
        except jwt.PyJWTError as exc:
            logger.debug("JWT verification failed: %s", exc)
            return None

        # 4. Stable principal ID — Entra `oid` survives renames/email changes
        principal_id = payload.get("oid") or payload.get("sub")
        if not principal_id:
            return None

        # 5. Scope check (Entra v2 puts space-delimited scopes in `scp`)
        scopes_str = payload.get("scp", "")
        scopes = scopes_str.split() if scopes_str else []
        if self._required_scope and self._required_scope not in scopes:
            logger.debug(
                "Token missing required scope %r (has %s)",
                self._required_scope, scopes,
            )
            return None

        return AccessToken(
            token=token,
            client_id=principal_id,
            scopes=scopes,
            expires_at=payload.get("exp"),
        )
