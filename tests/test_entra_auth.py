"""Tests for the Entra ID OAuth token verifier.

We generate a real RSA keypair via cryptography, sign JWTs with the
private key, expose the public key as a JWKS, and mock httpx to return
that JWKS. This exercises the full verification path (signature, audience,
issuer, scopes) without hitting Microsoft.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from aismartbuddy.auth import EntraTokenVerifier

# ── Fixtures: RSA keypair + JWKS shim ─────────────────────────


_TENANT_ID = "11111111-2222-3333-4444-555555555555"
_AUDIENCE = "api://aismartbuddy"
_KID = "test-key-1"
_ISSUER = f"https://login.microsoftonline.com/{_TENANT_ID}/v2.0"


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[Any, Any]:
    """A 2048-bit RSA keypair shared across module tests for speed."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def jwks_dict(rsa_keypair) -> dict[str, Any]:
    """JWKS document containing the public key, formatted as Entra would."""
    _, public_key = rsa_keypair
    pub_numbers = public_key.public_numbers()

    def _b64uint(value: int) -> str:
        # Big-endian unsigned bytes, then base64url-encoded with no padding
        import base64
        n_bytes = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")

    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": _KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64uint(pub_numbers.n),
                "e": _b64uint(pub_numbers.e),
            }
        ]
    }


def _sign(
    rsa_keypair,
    *,
    audience: str = _AUDIENCE,
    issuer: str = _ISSUER,
    oid: str = "alice-oid",
    scp: str = "mcp.invoke",
    expires_in: int = 3600,
    kid: str = _KID,
) -> str:
    """Sign a JWT with the test RSA private key."""
    private_key, _ = rsa_keypair
    now = int(time.time())
    payload = {
        "aud": audience,
        "iss": issuer,
        "oid": oid,
        "sub": "alice-sub",
        "scp": scp,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def patched_httpx(jwks_dict):
    """Patch httpx.AsyncClient to return our JWKS instead of hitting the network.

    Yields a `MagicMock` so tests can introspect call_count for cache testing.
    """
    response = MagicMock()
    response.json.return_value = jwks_dict
    response.raise_for_status = MagicMock()

    client_instance = MagicMock()
    client_instance.get = AsyncMock(return_value=response)
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=False)

    client_class = MagicMock(return_value=client_instance)
    with patch("aismartbuddy.auth.httpx.AsyncClient", client_class):
        yield client_instance


# ── Tests ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_valid_token_returns_access_token(rsa_keypair, patched_httpx):
    verifier = EntraTokenVerifier(
        tenant_id=_TENANT_ID, audience=_AUDIENCE, required_scope="mcp.invoke"
    )
    token = _sign(rsa_keypair)

    result = await verifier.verify_token(token)

    assert result is not None
    assert result.client_id == "alice-oid"
    assert "mcp.invoke" in result.scopes
    assert result.token == token
    assert result.expires_at is not None


@pytest.mark.anyio
async def test_wrong_audience_rejected(rsa_keypair, patched_httpx):
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    token = _sign(rsa_keypair, audience="api://different-app")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_wrong_issuer_rejected(rsa_keypair, patched_httpx):
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    token = _sign(rsa_keypair, issuer="https://login.microsoftonline.com/other/v2.0")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_expired_token_rejected(rsa_keypair, patched_httpx):
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    # Negative expires_in → already-expired token
    token = _sign(rsa_keypair, expires_in=-60)

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_missing_required_scope_rejected(rsa_keypair, patched_httpx):
    verifier = EntraTokenVerifier(
        tenant_id=_TENANT_ID, audience=_AUDIENCE, required_scope="mcp.admin"
    )
    # Token has scp="mcp.invoke" but verifier requires "mcp.admin"
    token = _sign(rsa_keypair, scp="mcp.invoke")

    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_no_required_scope_accepts_any(rsa_keypair, patched_httpx):
    """When required_scope=None, any (or no) scope is accepted."""
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    token = _sign(rsa_keypair, scp="")

    result = await verifier.verify_token(token)
    assert result is not None
    assert result.scopes == []


@pytest.mark.anyio
async def test_unknown_kid_triggers_jwks_refresh(rsa_keypair, patched_httpx, jwks_dict):
    """If a token's kid isn't in cached JWKS, we force-refresh once."""
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    # First call with the known kid populates cache
    await verifier.verify_token(_sign(rsa_keypair))
    initial_calls = patched_httpx.get.call_count

    # Now sign a token with a DIFFERENT kid and watch refresh happen
    token = _sign(rsa_keypair, kid="rotated-key")
    result = await verifier.verify_token(token)

    # Force-refresh adds one more httpx call
    assert patched_httpx.get.call_count == initial_calls + 1
    # Verification still fails because rotated-key isn't actually in JWKS
    assert result is None


@pytest.mark.anyio
async def test_jwks_is_cached(rsa_keypair, patched_httpx):
    """Multiple tokens within the cache TTL share a single JWKS fetch."""
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)

    for _ in range(5):
        await verifier.verify_token(_sign(rsa_keypair))

    # Only one network call across 5 verifications
    assert patched_httpx.get.call_count == 1


@pytest.mark.anyio
async def test_garbage_token_rejected(patched_httpx):
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    assert await verifier.verify_token("not-a-jwt") is None
    assert await verifier.verify_token("") is None
    assert await verifier.verify_token("a.b.c") is None


@pytest.mark.anyio
async def test_token_without_kid_rejected(rsa_keypair, patched_httpx):
    """A JWT that omits `kid` from its header is rejected."""
    private_key, _ = rsa_keypair
    now = int(time.time())
    payload = {
        "aud": _AUDIENCE,
        "iss": _ISSUER,
        "oid": "alice",
        "iat": now,
        "exp": now + 3600,
    }
    # No `kid` in headers
    token = jwt.encode(payload, private_key, algorithm="RS256")

    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    assert await verifier.verify_token(token) is None


@pytest.mark.anyio
async def test_oid_preferred_over_sub(rsa_keypair, patched_httpx):
    """`oid` is the stable principal ID; falls back to `sub` if absent."""
    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    token = _sign(rsa_keypair, oid="oid-value")
    result = await verifier.verify_token(token)
    assert result is not None
    assert result.client_id == "oid-value"


@pytest.mark.anyio
async def test_falls_back_to_sub_when_oid_missing(rsa_keypair, patched_httpx):
    private_key, _ = rsa_keypair
    now = int(time.time())
    payload = {
        "aud": _AUDIENCE,
        "iss": _ISSUER,
        "sub": "sub-only",
        # No `oid`
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": _KID})

    verifier = EntraTokenVerifier(tenant_id=_TENANT_ID, audience=_AUDIENCE)
    result = await verifier.verify_token(token)
    assert result is not None
    assert result.client_id == "sub-only"


# ── Server wiring tests ───────────────────────────────────────


def test_server_no_auth_when_env_unset(monkeypatch):
    """Without Entra env vars, _maybe_build_entra_auth returns (None, None)
    and the server starts unauthenticated."""
    from aismartbuddy import config as cfg
    from aismartbuddy.server import _maybe_build_entra_auth

    monkeypatch.setattr(cfg, "runtime_config", cfg.RuntimeConfig())
    verifier, settings = _maybe_build_entra_auth()
    assert verifier is None
    assert settings is None


def test_server_partial_config_logs_warning_returns_none(monkeypatch, caplog):
    """Setting only one of tenant/audience logs a warning, returns no auth."""
    import logging as pylogging

    from aismartbuddy import config as cfg
    from aismartbuddy.server import _maybe_build_entra_auth

    monkeypatch.setattr(
        cfg,
        "runtime_config",
        cfg.RuntimeConfig(entra_tenant_id="some-tenant"),  # audience missing
    )
    with caplog.at_level(pylogging.WARNING, logger="aismartbuddy.server"):
        verifier, settings = _maybe_build_entra_auth()
    assert verifier is None
    assert settings is None
    assert any("Partial Entra OAuth config" in r.message for r in caplog.records)


def test_server_full_config_wires_verifier(monkeypatch):
    """Both tenant + audience set → verifier and AuthSettings returned."""
    from aismartbuddy import config as cfg
    from aismartbuddy.server import _maybe_build_entra_auth

    monkeypatch.setattr(
        cfg,
        "runtime_config",
        cfg.RuntimeConfig(
            entra_tenant_id=_TENANT_ID,
            entra_audience=_AUDIENCE,
            entra_required_scope="mcp.invoke",
        ),
    )
    verifier, settings = _maybe_build_entra_auth()
    assert verifier is not None
    assert settings is not None
    assert isinstance(verifier, EntraTokenVerifier)
    assert settings.required_scopes == ["mcp.invoke"]


def test_jwks_dict_is_valid_json(jwks_dict):
    """Sanity check: the fixture JWKS round-trips through JSON cleanly."""
    serialized = json.dumps(jwks_dict)
    assert json.loads(serialized) == jwks_dict
