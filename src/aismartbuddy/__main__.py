"""CLI entry point for AISmartBuddy MCP server."""

from __future__ import annotations

import click
from dotenv import load_dotenv

# Load .env before Click parses envvar= options
load_dotenv()

from aismartbuddy.config import (  # noqa: E402
    DEFAULT_CURSOR_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_ROWS,
    DEFAULT_PORT,
    DEFAULT_PROJECT_ID,
    DEFAULT_SESSION_TIMEOUT,
    DEFAULT_USER_ID,
    SERVER_VERSION,
    RuntimeConfig,
)


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    envvar="AISMARTBUDDY_TRANSPORT",
    help="Transport protocol (default: stdio).",
)
@click.option(
    "--port", type=int, default=DEFAULT_PORT,
    envvar="AISMARTBUDDY_PORT", help="Port for SSE transport.",
)
@click.option(
    "--host", type=str, default=DEFAULT_HOST,
    envvar="AISMARTBUDDY_HOST", help="Host for SSE transport.",
)
@click.option(
    "--temp-dir", type=str, default=None,
    envvar="AISMARTBUDDY_TEMP_DIR", help="Override temp directory for databases.",
)
@click.option(
    "--max-rows", type=int, default=DEFAULT_MAX_ROWS,
    envvar="AISMARTBUDDY_MAX_ROWS", help="Max rows per query result.",
)
@click.option(
    "--max-chars", type=int, default=DEFAULT_MAX_CHARS,
    envvar="AISMARTBUDDY_MAX_CHARS", help="Max characters per response.",
)
@click.option(
    "--session-timeout", type=int, default=DEFAULT_SESSION_TIMEOUT,
    envvar="AISMARTBUDDY_SESSION_TIMEOUT", help="Session timeout in seconds.",
)
@click.option(
    "--cursor-timeout", type=int, default=DEFAULT_CURSOR_TIMEOUT,
    envvar="AISMARTBUDDY_CURSOR_TIMEOUT", help="Pagination cursor timeout in seconds.",
)
@click.option(
    "--duckdb-threads", type=int, default=0,
    envvar="AISMARTBUDDY_DUCKDB_THREADS", help="DuckDB worker threads (0=auto).",
)
@click.option(
    "--duckdb-memory-limit", type=str, default="256MB",
    envvar="AISMARTBUDDY_DUCKDB_MEMORY_LIMIT", help="DuckDB memory limit (e.g. '512MB').",
)
@click.option(
    "--ladybug-buffer-size", type=int, default=256 * 1024 * 1024,
    envvar="AISMARTBUDDY_LADYBUG_BUFFER_SIZE", help="LadybugDB buffer pool size in bytes.",
)
@click.option(
    "--ladybug-threads", type=int, default=0,
    envvar="AISMARTBUDDY_LADYBUG_THREADS", help="LadybugDB worker threads (0=auto).",
)
@click.option(
    "--default-user-id", type=str, default=DEFAULT_USER_ID,
    envvar="AISMARTBUDDY_DEFAULT_USER_ID",
    help="Default user_id when no Bearer token and no tool parameter.",
)
@click.option(
    "--default-project-id", type=str, default=DEFAULT_PROJECT_ID,
    envvar="AISMARTBUDDY_DEFAULT_PROJECT_ID",
    help="Default project_id when no tool parameter provided.",
)
@click.option(
    "--entra-tenant-id", type=str, default=None,
    envvar="AISMARTBUDDY_ENTRA_TENANT",
    help="Entra ID tenant ID. Set with --entra-audience to enable OAuth.",
)
@click.option(
    "--entra-audience", type=str, default=None,
    envvar="AISMARTBUDDY_ENTRA_AUDIENCE",
    help="Expected token audience (e.g. 'api://<app-id-uri>').",
)
@click.option(
    "--entra-required-scope", type=str, default=None,
    envvar="AISMARTBUDDY_ENTRA_REQUIRED_SCOPE",
    help="Required scope on the token (e.g. 'mcp.invoke').",
)
@click.option(
    "--entra-resource-server-url", type=str, default=None,
    envvar="AISMARTBUDDY_ENTRA_RESOURCE_SERVER_URL",
    help="Public URL of this MCP server (for OAuth resource metadata).",
)
def main(
    transport: str,
    port: int,
    host: str,
    temp_dir: str | None,
    max_rows: int,
    max_chars: int,
    session_timeout: int,
    cursor_timeout: int,
    duckdb_threads: int,
    duckdb_memory_limit: str,
    ladybug_buffer_size: int,
    ladybug_threads: int,
    default_user_id: str,
    default_project_id: str,
    entra_tenant_id: str | None,
    entra_audience: str | None,
    entra_required_scope: str | None,
    entra_resource_server_url: str | None,
) -> None:
    """AISmartBuddy — MCP server with SQL and graph database capabilities."""
    # Store runtime config for server lifespan to read
    from aismartbuddy import config as cfg

    cfg.runtime_config = RuntimeConfig(
        temp_dir=temp_dir,
        max_rows=max_rows,
        max_chars=max_chars,
        session_timeout=session_timeout,
        cursor_timeout=cursor_timeout,
        host=host,
        port=port,
        transport=transport,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit,
        ladybug_buffer_pool_size=ladybug_buffer_size,
        ladybug_max_threads=ladybug_threads,
        default_user_id=default_user_id,
        default_project_id=default_project_id,
        entra_tenant_id=entra_tenant_id,
        entra_audience=entra_audience,
        entra_required_scope=entra_required_scope,
        entra_resource_server_url=entra_resource_server_url,
    )

    # Print startup info to stderr (stdout is used by stdio transport)
    click.echo(f"AISmartBuddy v{SERVER_VERSION}", err=True)
    click.echo(f"Transport: {transport}", err=True)
    click.echo(f"Max rows: {max_rows} | Max chars: {max_chars}", err=True)
    click.echo(f"Session timeout: {session_timeout}s | Cursor timeout: {cursor_timeout}s", err=True)
    if temp_dir:
        click.echo(f"Temp dir: {temp_dir}", err=True)

    from aismartbuddy.server import mcp

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "sse":
        click.echo(f"SSE server: http://{host}:{port}", err=True)
        mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    main()
