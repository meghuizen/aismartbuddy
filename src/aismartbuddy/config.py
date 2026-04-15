"""Configuration constants and runtime config for AISmartBuddy."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version

SERVER_NAME = "aismartbuddy"

try:
    SERVER_VERSION = version("aismartbuddy")
except Exception:
    SERVER_VERSION = "0.1.0"  # fallback for development

DEFAULT_MAX_ROWS = 1000
DEFAULT_MAX_CHARS = 50000
DEFAULT_SESSION_TIMEOUT = 3600
DEFAULT_CURSOR_TIMEOUT = 300
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_USER_ID = "default"
DEFAULT_PROJECT_ID = "default"
DEFAULT_HOLON_TRUNCATE_CHARS = 60
DEFAULT_HOLON_TRUNCATE_LONG = 80


@dataclass
class RuntimeConfig:
    """Runtime configuration populated by CLI args."""

    temp_dir: str | None = None
    max_rows: int = DEFAULT_MAX_ROWS
    max_chars: int = DEFAULT_MAX_CHARS
    session_timeout: int = DEFAULT_SESSION_TIMEOUT
    cursor_timeout: int = DEFAULT_CURSOR_TIMEOUT
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    transport: str = "stdio"

    # Multi-tenant identity defaults (used when no Bearer token and no tool parameter)
    default_user_id: str = DEFAULT_USER_ID
    default_project_id: str = DEFAULT_PROJECT_ID

    # DuckDB engine tuning
    duckdb_threads: int = 0  # 0 = auto-detect
    duckdb_memory_limit: str = "256MB"

    # LadybugDB engine tuning
    ladybug_buffer_pool_size: int = 256 * 1024 * 1024  # 256MB
    ladybug_max_threads: int = 0  # 0 = auto-detect

    # Holon display truncation — how many chars of context/description to
    # show in holon_view / holon_query output. Role_in_parent and projection
    # stay hardcoded at 40 chars (those fields are short by convention).
    holon_truncate_chars: int = DEFAULT_HOLON_TRUNCATE_CHARS
    holon_truncate_long: int = DEFAULT_HOLON_TRUNCATE_LONG

    # Reasoning-surface exposure. Default is the collapsed public registry:
    # modern think_* tools plus non-overlapping bridge tools. Legacy V2
    # reasoning tools can be re-exposed for compatibility/debugging.
    expose_legacy_reasoning_tools: bool = False

    # Microsoft Entra ID OAuth (optional). When BOTH tenant_id and audience
    # are set, the server validates incoming Bearer tokens against the
    # configured tenant. Requires the [entra] optional dep group installed.
    # See src/aismartbuddy/auth.py.
    entra_tenant_id: str | None = None
    entra_audience: str | None = None
    entra_required_scope: str | None = None
    entra_resource_server_url: str | None = None  # public URL of this server


# Module-level singleton — set by __main__.py before server starts
runtime_config: RuntimeConfig = RuntimeConfig()
