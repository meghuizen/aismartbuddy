"""SQL database tools backed by DuckDB."""

from __future__ import annotations

import anyio
from mcp.server.fastmcp import Context

from aismartbuddy.formatting import format_result, format_schema_compact
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import (
    execute_and_format,
    fetch_next_and_format,
    get_session_manager,
    run_with_lock,
)


def _require_sql_session(session_id: str):
    """Validate and return a SQL session.

    Uses session_id as capability token — possession of a valid session_id
    is sufficient. Tools that have ctx identity can pass it to get_session
    for additional enforcement.
    """
    mgr = get_session_manager()
    info = mgr.get_session(session_id)
    if info.session_type != "sql":
        raise ValueError(f"Session '{session_id}' is a {info.session_type} session, not SQL.")
    return mgr, info


async def sql_create_session(
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Create a new SQL database session. Returns a session_id token.

    Use this session_id in all subsequent sql_* tool calls.
    SQL sessions use DuckDB — ideal for tabular data, analytics,
    aggregations, joins, window functions, and time-series analysis.

    Multi-tenant: the session is bound to (user_id, project_id). If Bearer
    auth is configured, user_id comes from ctx.client_id (parameter ignored);
    otherwise the parameter (or a configured default) is used. project_id
    is always taken from the parameter or the configured default.

    Example: sql_create_session(project_id="analytics") → returns session_id

    Args:
        user_id: Owner identity. Ignored when Bearer auth is configured
            (ctx.client_id wins). Default: configured default_user_id.
        project_id: Project scope. Default: configured default_project_id.

    Returns:
        Session ID and connection details (including resolved user/project).
    """
    resolved_user, resolved_project = resolve_identity(ctx, user_id, project_id)
    mgr = get_session_manager()
    info = await anyio.to_thread.run_sync(
        lambda: mgr.create_session("sql", resolved_user, resolved_project)
    )
    return (
        f"SQL session created.\n"
        f"session_id: {info.session_id}\n"
        f"user_id: {info.user_id} | project_id: {info.project_id}\n"
        f"Use this session_id in sql_query, sql_import, sql_schema, sql_destroy_session."
    )


async def sql_query(
    session_id: str,
    query: str,
    output_format: str = "csv",
    offset: int | None = None,
    limit: int | None = None,
    paginate: bool = False,
) -> str:
    """Execute a SQL query against a session's database.

    Supports all SQL: CREATE TABLE, INSERT, SELECT, UPDATE, DELETE,
    analytical functions, window functions, CTEs, etc.
    Results returned in token-efficient CSV format by default.

    Pagination: For large results exceeding max_rows, use either:
    - offset/limit for random access: sql_query(sid, q, offset=1000, limit=500)
    - paginate=True for cursor-based sequential paging (most efficient for full scans)
      Returns first page + cursor_id; use sql_query_next to get subsequent pages.

    Example: sql_query(session_id, "SELECT * FROM users WHERE age > 25")

    See also: sql_query_next for cursor-based pagination, sql_schema for table info.

    Args:
        session_id: Session token from sql_create_session.
        query: SQL statement to execute.
        output_format: Result format — "csv" (default, most token-efficient) or "table".
        offset: Skip this many rows from the start (for random-access paging).
        limit: Return at most this many rows (overrides server max_rows).
        paginate: If True, use cursor-based paging. Returns first page + cursor_id.

    Returns:
        Query results formatted according to output_format.
    """
    mgr, info = _require_sql_session(session_id)
    return await execute_and_format(
        info, mgr, query, output_format, offset, limit, paginate,
        next_tool="sql_query_next",
    )


async def sql_query_next(session_id: str, cursor_id: str) -> str:
    """Fetch the next page of results from a paginated SQL query.

    Use after sql_query(..., paginate=True) returns a cursor_id.
    Returns the next page of results. When the last page is reached,
    the response includes "has_more: false" and the cursor is auto-closed.

    Example: sql_query_next(session_id, "abc123def456")

    See also: sql_query with paginate=True to start pagination.

    Args:
        session_id: Session token from sql_create_session.
        cursor_id: Cursor token from a previous sql_query(..., paginate=True) call.

    Returns:
        Next page of query results, or end-of-results message.
    """
    mgr, info = _require_sql_session(session_id)
    return await fetch_next_and_format(
        info, mgr, cursor_id, next_tool="sql_query_next",
    )


async def sql_import(
    session_id: str,
    table_name: str,
    data: str,
    data_format: str = "csv",
    create_table: bool = True,
    delimiter: str | None = None,
) -> str:
    """Import tabular data into a SQL session table.

    Supports multiple formats with automatic schema detection.
    For bulk imports, CSV is the most token-efficient format.

    Supported formats:
    - "csv" — Comma-separated values (default). Auto-detects headers and types.
    - "tsv" — Tab-separated values. Same auto-detection as CSV.
    - "txt" — Generic delimited text. Use `delimiter` to specify the separator.
    - "json" — JSON array of objects, e.g. [{"name": "Alice", "age": 30}, ...].
    - "jsonl" — JSON Lines (one JSON object per line).
    - "parquet" — Apache Parquet binary format. Data must be base64-encoded.

    For custom delimiters (pipe, semicolon, etc.), use data_format="txt"
    with delimiter="|" or delimiter=";".

    Example: sql_import(session_id, "users", "name,age\\nAlice,30\\nBob,25")

    Args:
        session_id: Session token from sql_create_session.
        table_name: Name for the target table.
        data: The data to import as a string. For parquet, base64-encode the binary.
        data_format: Format of the data — "csv" (default), "tsv", "txt",
            "json", "jsonl", or "parquet".
        create_table: If True (default), auto-creates table from data.
            If False, appends rows to an existing table.
        delimiter: Optional custom delimiter character for delimited formats
            (e.g., "|" for pipe-delimited, ";" for semicolon-delimited).
            Only used with csv/tsv/txt formats. Overrides default delimiter.

    Returns:
        Import confirmation with row count.
    """
    mgr, info = _require_sql_session(session_id)
    count = await run_with_lock(
        info,
        lambda: info.engine.import_data(
            table_name, data, data_format, create_table, delimiter
        ),
    )
    action = "Created table and imported" if create_table else "Appended"
    return f"{action} {count} rows into '{table_name}' (format: {data_format})."


async def sql_import_batch(
    session_id: str,
    table_name: str,
    chunks: list[str],
    data_format: str = "csv",
    delimiter: str | None = None,
) -> str:
    """Import multiple data chunks into a single SQL table.

    Use this when you have data split across multiple sources, pages,
    or when the data is too large to send in a single tool call.
    The first chunk creates the table with auto-detected schema,
    and subsequent chunks append rows.

    Each chunk should include column headers (for CSV/TSV) or be a
    complete JSON array (for JSON). All chunks must have the same schema.

    Example: sql_import_batch(session_id, "logs", [chunk1, chunk2, chunk3])

    Args:
        session_id: Session token from sql_create_session.
        table_name: Name for the target table.
        chunks: List of data strings to import sequentially.
        data_format: Format of all chunks — "csv" (default), "tsv", "txt",
            "json", "jsonl", or "parquet".
        delimiter: Optional custom delimiter for delimited formats.

    Returns:
        Import confirmation with total row count and chunk count.
    """
    mgr, info = _require_sql_session(session_id)
    total = await run_with_lock(
        info,
        lambda: info.engine.import_batch(
            table_name, chunks, data_format, delimiter
        ),
    )
    return (
        f"Imported {total} rows into '{table_name}' "
        f"from {len(chunks)} chunks (format: {data_format})."
    )


async def sql_schema(session_id: str, table_name: str | None = None) -> str:
    """Get database schema information.

    Without table_name: lists all tables in the database.
    With table_name: shows column names, types, and constraints for that table.

    Example: sql_schema(session_id) or sql_schema(session_id, "users")

    Args:
        session_id: Session token from sql_create_session.
        table_name: Optional — specific table to describe.

    Returns:
        Schema information in compact format.
    """
    mgr, info = _require_sql_session(session_id)

    if table_name:
        columns, rows = await run_with_lock(
            info, lambda: info.engine.describe_table(table_name)
        )
        return format_result(columns, rows, mgr.max_rows, mgr.max_chars, "table")
    else:
        tables = await run_with_lock(info, info.engine.get_tables)
        if not tables:
            return "No tables in database. Use sql_import or sql_query with CREATE TABLE."
        schema_list = []
        for tbl in tables:
            cols, rows = await run_with_lock(
                info, lambda t=tbl: info.engine.describe_table(t)
            )
            col_info = [(row[0], row[1]) for row in rows]
            schema_list.append({"name": tbl, "columns": col_info})
        return format_schema_compact(schema_list)


async def sql_destroy_session(session_id: str) -> str:
    """Destroy a SQL session and clean up all temporary data.

    Always call this when done to free resources.

    Args:
        session_id: Session token to destroy.

    Returns:
        Confirmation message.
    """
    mgr, info = _require_sql_session(session_id)
    # destroy_session handles its own locking (pop-then-lock protocol)
    await anyio.to_thread.run_sync(lambda: mgr.destroy_session(session_id))
    return f"SQL session '{session_id}' destroyed and cleaned up."
