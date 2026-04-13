"""AISmartBuddy tool modules.

Helpers here implement the multi-tenant execution contract:
- Every engine call is dispatched via anyio.to_thread.run_sync (async safety).
- Inside that thread, we acquire info.lock to serialize concurrent tool calls
  that share the same session (multi-agent safety).
- Two-session tools (graph_compare, graph_cross_reference) make sequential
  run_with_lock calls on each session's info object — the operations are
  read-only and don't need atomic-pair semantics, so sequential locking is
  sufficient and deadlock-free.
- ThinkingEngine mutation methods are internally serialized via a decorator
  in thinking_engine.py, so think/holon/score tools are multi-agent safe
  without needing run_with_lock at the call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypeVar

import anyio

from aismartbuddy.formatting import format_arrow_result, format_result

if TYPE_CHECKING:
    from aismartbuddy.session import SessionInfo, SessionManager

T = TypeVar("T")


def get_session_manager() -> SessionManager:
    """Get the active SessionManager singleton. Raises if not initialized."""
    from aismartbuddy.session import session_manager

    if session_manager is None:
        raise RuntimeError("SessionManager not initialized. Server not started properly.")
    return session_manager


async def run_with_lock(info: SessionInfo, sync_fn: Callable[[], T]) -> T:
    """Run sync_fn in a worker thread while holding info.lock.

    Use this for any engine operation that needs per-session serialization.
    The lock is acquired INSIDE the worker thread (threading.Lock is sync).
    """
    def _locked() -> T:
        with info.lock:
            return sync_fn()
    return await anyio.to_thread.run_sync(_locked)


async def execute_and_format(
    info: SessionInfo,
    mgr: SessionManager,
    query: str,
    output_format: str = "csv",
    offset: int | None = None,
    limit: int | None = None,
    paginate: bool = False,
    next_tool: str = "sql_query_next",
) -> str:
    """Shared query execution + formatting logic for SQL and graph tools.

    Handles Arrow path, pagination (cursor + offset/limit), and legacy fallback.
    Acquires info.lock for all engine operations (multi-agent safety).
    """
    effective_limit = limit if limit is not None else mgr.max_rows

    if paginate:
        cursor_id, table = await run_with_lock(
            info, lambda: info.engine.execute_paged(query, effective_limit)
        )
        if table is None:
            return "OK"

        pagination_meta = None
        if cursor_id:
            pagination_meta = (
                f"# has_more: true | cursor_id: {cursor_id} | "
                f'next: {next_tool}(session_id, "{cursor_id}")'
            )
        return format_arrow_result(
            table, effective_limit, mgr.max_chars, output_format, pagination_meta
        )

    # Standard query — Arrow path with optional offset/limit
    table = await run_with_lock(info, lambda: info.engine.execute_arrow(query))

    if table is not None:
        if offset is not None and offset > 0:
            import polars as pl

            df = pl.from_arrow(table)
            total = df.height
            df = df.slice(offset, effective_limit)
            table = df.to_arrow()
            end = offset + table.num_rows - 1
            pagination_meta = f"# Page: rows {offset}-{end} of {total}"
            return format_arrow_result(
                table, effective_limit, mgr.max_chars, output_format, pagination_meta
            )
        return format_arrow_result(table, effective_limit, mgr.max_chars, output_format)

    # Fallback to legacy tuple path
    columns, rows = await run_with_lock(info, lambda: info.engine.execute(query))
    return format_result(columns, rows, effective_limit, mgr.max_chars, output_format)


async def fetch_next_and_format(
    info: SessionInfo,
    mgr: SessionManager,
    cursor_id: str,
    next_tool: str = "sql_query_next",
) -> str:
    """Shared next-page fetch logic for SQL and graph pagination tools."""
    def _fetch() -> tuple[Any, bool]:
        table = info.engine.fetch_next_page(cursor_id)
        has_more = info.engine.cursor_exists(cursor_id) if table is not None else False
        return table, has_more

    table, has_more = await run_with_lock(info, _fetch)

    if table is None:
        return "# End of results — cursor closed."

    if has_more:
        pagination_meta = (
            f"# has_more: true | cursor_id: {cursor_id} | "
            f'next: {next_tool}(session_id, "{cursor_id}")'
        )
    else:
        pagination_meta = "# has_more: false — this is the last page."

    return format_arrow_result(table, mgr.max_rows, mgr.max_chars, "csv", pagination_meta)
