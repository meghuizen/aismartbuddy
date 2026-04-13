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


# Module-level singleton — set by __main__.py before server starts
runtime_config: RuntimeConfig = RuntimeConfig()
