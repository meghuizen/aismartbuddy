"""Multi-tenant identity resolution.

Resolves (user_id, project_id) for each MCP tool call from:
1. MCP v2 bearer-token auth context — highest priority
2. Explicit tool parameter — used when no auth context
3. RuntimeConfig defaults (which may come from env vars via CLI)
4. Literal "default" fallback

Also validates identity strings as safe path components to prevent
filesystem traversal when used in temp directory paths.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from aismartbuddy import config as cfg

if TYPE_CHECKING:
    from mcp.server.mcpserver import Context

# Allow letters, digits, underscore, hyphen, dot. 1-64 chars.
# Rejects: path separators, null bytes, empty, overly long names, "..", absolute paths.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def validate_identity(value: str, label: str) -> str:
    """Validate an identity string as a safe path component.

    Raises:
        ValueError: If the value contains unsafe characters, is empty,
            too long, or equals "." or "..".
    """
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string, got {type(value).__name__}")
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"Invalid {label}: {value!r}. "
            "Must be 1-64 characters, alphanumeric plus '_.-' only."
        )
    if value in (".", ".."):
        raise ValueError(f"Invalid {label}: {value!r} (reserved path component)")
    return value


def resolve_identity(
    ctx: Context | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
) -> tuple[str, str]:
    """Resolve (user_id, project_id) from ctx + parameters + config defaults.

    Priority order for user_id:
        1. get_access_token().client_id if present (Bearer authentication)
        2. ctx.client_id request metadata when supplied by an unauthenticated host
        3. explicit user_id parameter
        4. cfg.runtime_config.default_user_id (from --default-user-id or env var)
        5. Literal "default"

    Priority order for project_id:
        1. explicit project_id parameter
        2. cfg.runtime_config.default_project_id
        3. Literal "default"

    Both values are validated as safe path components.

    Returns:
        (user_id, project_id) tuple of validated strings.

    Raises:
        ValueError: If any resolved value fails path-component validation.
    """
    # Resolve user_id. In MCP v2 bearer identity lives in the auth context;
    # Context.client_id is request metadata and is not authoritative for auth.
    resolved_user: str | None = None
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access_token = get_access_token()
    except LookupError:
        access_token = None
    if access_token is not None and access_token.client_id:
        resolved_user = access_token.client_id
    if ctx is not None:
        # Retain request-metadata client_id as a non-authenticated fallback.
        client_id = getattr(ctx, "client_id", None)
        if resolved_user is None and client_id:
            resolved_user = client_id
    if resolved_user is None and user_id:
        resolved_user = user_id
    if resolved_user is None:
        resolved_user = cfg.runtime_config.default_user_id or "default"

    # Resolve project_id
    resolved_project: str | None = None
    if project_id:
        resolved_project = project_id
    if resolved_project is None:
        resolved_project = cfg.runtime_config.default_project_id or "default"

    validate_identity(resolved_user, "user_id")
    validate_identity(resolved_project, "project_id")

    return resolved_user, resolved_project
