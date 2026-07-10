"""AISmartBuddy tool modules.

Helpers here implement the multi-tenant execution contract:
- Every engine call is dispatched via run_sync (async safety).
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

import functools
import logging
import re
from typing import TYPE_CHECKING, Any, Callable, TypeVar

import anyio

from aismartbuddy.concurrency import run_sync
from aismartbuddy.engines.thinking_engine import ThinkingEngine
from aismartbuddy.formatting import format_arrow_result, format_result

if TYPE_CHECKING:
    from aismartbuddy.session import SessionInfo, SessionManager

T = TypeVar("T")

# Response size guard thresholds (in bytes). Apply to tools returning
# variable-length data (queries, holon views, summaries, exports).
_SIZE_WARN_BYTES = 50 * 1024  # 50KB — log warn, return as-is
_SIZE_ERROR_BYTES = 200 * 1024  # 200KB — log error, return as-is
_SIZE_TRUNCATE_BYTES = 500 * 1024  # 500KB — truncate + append hint

_logger = logging.getLogger("aismartbuddy.size_guard")


def size_guarded(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: log/truncate oversized tool responses to protect transport.

    Wraps an async tool function. Measures the UTF-8 byte size of the
    returned string. Logs at warn/error thresholds; truncates at the hard
    cap and appends an actionable hint to the response.

    Wraps tools that return variable-length data: SQL/graph query tools,
    holon_view, holon_query, holon_analyze, think_summarize, etc.
    """
    if not callable(fn):  # defensive: decorator misuse
        return fn

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = await fn(*args, **kwargs)
        if not isinstance(result, str):
            return result
        requested_chars = kwargs.get("max_chars")
        if (
            isinstance(requested_chars, int)
            and requested_chars > 0
            and len(result) > requested_chars
        ):
            suffix = "\n\n[Output truncated. Narrow the query or request another page.]"
            return result[: max(0, requested_chars - len(suffix))] + suffix
        size_bytes = len(result.encode("utf-8"))
        tool_name = getattr(fn, "__name__", "?")
        if size_bytes > _SIZE_TRUNCATE_BYTES:
            _logger.error(
                "Tool %s response %d bytes exceeds %d hard cap — truncating",
                tool_name,
                size_bytes,
                _SIZE_TRUNCATE_BYTES,
            )
            # Truncate at byte boundary, decode tolerant
            cut = result.encode("utf-8")[:_SIZE_TRUNCATE_BYTES]
            prefix = cut.decode("utf-8", errors="ignore")
            return (
                f"{prefix}\n\n"
                f"[Response truncated at {_SIZE_TRUNCATE_BYTES // 1024}KB. "
                "Use pagination, scope via WHERE, or request a more specific query.]"
            )
        if size_bytes > _SIZE_ERROR_BYTES:
            _logger.error(
                "Tool %s response %d bytes exceeds %d threshold",
                tool_name,
                size_bytes,
                _SIZE_ERROR_BYTES,
            )
        elif size_bytes > _SIZE_WARN_BYTES:
            _logger.warning(
                "Tool %s response %d bytes exceeds %d threshold",
                tool_name,
                size_bytes,
                _SIZE_WARN_BYTES,
            )
        return result

    return wrapper


def get_session_manager() -> SessionManager:
    """Get the active SessionManager singleton. Raises if not initialized."""
    from aismartbuddy.session import session_manager

    if session_manager is None:
        raise RuntimeError("SessionManager not initialized. Server not started properly.")
    return session_manager


def track_reasoning_progress(tool_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a successful reasoning tool call on the session's selected route."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*args, **kwargs)
            if not isinstance(result, str):
                return result
            match = re.search(r"(?:Session|session_id):\s*([A-Za-z0-9_-]+)", result)
            candidate = match.group(1) if match else kwargs.get("session_id")
            if not candidate:
                return result
            try:
                info = get_session_manager().resolve_backend_session(str(candidate), "think")
                engine = info.engine
                if isinstance(engine, ThinkingEngine):
                    engine.record_reasoning_tool(tool_name)
            except (RuntimeError, ValueError):
                # Tracking is advisory and must never turn a successful tool
                # operation into a failure.
                _logger.debug("Could not record reasoning progress for %s", tool_name)
            return result

        return wrapper

    return decorate


def resolve_backend_session(session_id: str, backend: str):  # SessionInfo
    """Resolve session_id (parent OR direct child) to backend SessionInfo.

    Backwards-compatible helper for tool entry points: pass the user-provided
    session_id and the backend type the tool needs. Works with both the new
    parent_id facade and the existing direct child session_ids.
    """
    return get_session_manager().resolve_backend_session(session_id, backend)


def resolve_active_or_provided_session_id(session_id: str | None) -> str | None:
    """Return explicit session_id or the currently active session id."""
    if session_id:
        return session_id
    return get_session_manager().get_active_session_id()


def effective_session_id(session_id: str | None, info: SessionInfo) -> str | None:
    """Return the effective parent_id for auto_graph materialisation.

    Always walks up from info.session_id to the parent when one exists, so
    materialize_auto_graph can resolve the graph backend sibling regardless of
    whether the caller passed the parent_id, a child id, or omitted session_id.
    If info.session_id has no parent, returns the explicit session_id (which
    must then already be a parent_id), or None.
    """
    mgr = get_session_manager()
    parent = mgr.find_parent_for_child(info.session_id)
    if parent is not None:
        return parent.parent_id
    return session_id


def resolve_auto_graph(per_call: bool, info: SessionInfo) -> bool:
    """Determine whether auto_graph materialisation should run.

    Per-call flag takes priority. When False, checks the ParentSession.auto_graph
    policy so that session_create(auto_graph=True) propagates automatically
    without per-call flags on every tool invocation.
    """
    if per_call:
        return True
    mgr = get_session_manager()
    parent = mgr.find_parent_for_child(info.session_id)
    return parent.auto_graph if parent is not None else False


# ── Items[] forcing-function helpers ──────────────────────────────────


def validate_items(
    items: list[dict],
    required: list[str],
    *,
    tool: str = "tool",
    item_validators: dict[str, Callable[[Any], str | None]] | None = None,
) -> None:
    """Validate items[] payload against per-item required fields.

    Each item must have all `required` field names with truthy values. Each
    item must have a unique `id`. Optional `item_validators` is a dict from
    field name → validator callable; the callable returns None on success or
    an error message string. Raises ValueError on the FIRST violation
    (fail-fast — no partial state).

    Args:
        items: list of dicts to validate.
        required: field names that MUST be present and truthy on every item.
        tool: name of the calling tool (for error messages).
        item_validators: optional per-field extra checks (e.g. min length).
    """
    if not items:
        raise ValueError(
            f"{tool}.items must be a non-empty list — items[] is the "
            "forcing-function contract; if you have nothing to decompose, "
            "do not call this tool."
        )
    seen_ids: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{tool}.items[{i}] must be a dict")
        if not item.get("id"):
            raise ValueError(f"{tool}.items[{i}] missing 'id'")
        if item["id"] in seen_ids:
            raise ValueError(f"{tool}.items[{i}] duplicate id '{item['id']}'")
        seen_ids.add(item["id"])
        for f in required:
            v = item.get(f)
            if v is None or v == "" or v == [] or v == {}:
                raise ValueError(
                    f"{tool}.items[{i}] ({item['id']}) "
                    f"missing required '{f}' — strict items[] form rejects "
                    "lazy submissions."
                )
        if item_validators:
            for fname, check in item_validators.items():
                if fname in item:
                    err = check(item[fname])
                    if err:
                        raise ValueError(f"{tool}.items[{i}] ({item['id']}) field '{fname}': {err}")


def collect_item_refs(item: dict) -> list[str]:
    """Build the unified `refs` list for a record from an items[] dict.

    Combines `connects_to` (the structural cross-ref the AI declares) and
    `refs` (explicit reference list) into a single deduped list. Insertion
    order preserved. This is the single-source-of-truth populator for the
    `refs` field on every record produced by an items[] handler.
    """
    seen: dict[str, None] = {}
    for key in ("connects_to", "refs"):
        for r in item.get(key) or []:
            if isinstance(r, str) and r and r not in seen:
                seen[r] = None
    return list(seen.keys())


class AutoGraphResult(int):
    """Node count with truthful edge creation and skip metadata."""

    edges_created: int
    edges_skipped: int

    def __new__(cls, nodes_created: int, edges_created: int, edges_skipped: int):
        value = int.__new__(cls, nodes_created)
        value.edges_created = edges_created
        value.edges_skipped = edges_skipped
        return value

    def __str__(self) -> str:
        return (
            f"{int(self)} | graph edges created: {self.edges_created} "
            f"| skipped refs: {self.edges_skipped}"
        )


async def materialize_auto_graph(
    parent_session_id: str,
    items: list[dict],
    *,
    source_tag: str,
    entity_type: str = "concept",
    description_field: str = "conclusion",
    edge_label: str = "DerivedFrom",
    ref_field: str = "connects_to",
    ref_resolver: Callable[[Any], str | None] | None = None,
) -> AutoGraphResult:
    """Materialise items[] outputs as KnowledgeNode rows + outgoing edges.

    Requires the parent session (resolved via resolve_backend_session) to
    have a 'graph' backend. Each item becomes a KnowledgeNode where:
      - name = item['id']
      - description = item.get(description_field, '')[:200]
      - entity_type, source = passed-in tags
    For each item, every entry in ``item.get(ref_field, [])`` becomes an
    ``edge_label`` edge from this item's id to the referenced target.

    ``ref_resolver`` (optional) is applied to every ref value before the edge
    is built. It returns the final node-name string the edge should point to,
    or None to mean "use the value as-is". Use it for tools whose ref field
    holds int batch-indexes (think_argue.responds_to_index, think_graph.parent_ref)
    or batch-ref strings that need lookup against an existing ref→id map
    (holon_create). Resolver returns of ``None`` fall through to ``str(ref)``.

    Returns the number of KnowledgeNode rows created.

    Raises ValueError if the session has no graph backend.
    """
    mgr = get_session_manager()
    try:
        graph_info = mgr.resolve_backend_session(parent_session_id, "graph")
    except ValueError as e:
        raise ValueError(
            f"auto_graph requires a graph backend in this session. "
            f"Create the session via session_create(backends=['think','graph']). "
            f"Underlying: {e}"
        ) from e

    # Local import to keep cycle-free at module import time
    from datetime import datetime, timezone

    from aismartbuddy.tools.graph import escape_cypher_string

    ts = datetime.now(timezone.utc).isoformat()

    auto_graph_logger = logging.getLogger("aismartbuddy.auto_graph")

    def _do() -> AutoGraphResult:
        with graph_info.lock:
            try:
                graph_info.engine.execute(
                    "CREATE NODE TABLE IF NOT EXISTS KnowledgeNode ("
                    "id SERIAL PRIMARY KEY, name STRING, description STRING, "
                    "entity_type STRING, confidence DOUBLE, "
                    "source STRING, created_at STRING, domain STRING, "
                    "authority STRING);"
                )
            except Exception as e:
                # Typically "already exists" from LadybugDB's idempotent
                # DDL — safe to skip. Log at DEBUG so real DDL failures
                # (connection, permission, syntax) remain traceable.
                auto_graph_logger.debug("CREATE NODE TABLE KnowledgeNode skipped: %s", e)
            try:
                graph_info.engine.execute(
                    f"CREATE REL TABLE IF NOT EXISTS {edge_label} ("
                    "FROM KnowledgeNode TO KnowledgeNode, "
                    "weight DOUBLE, justification STRING, "
                    "source STRING, created_at STRING);"
                )
            except Exception as e:
                auto_graph_logger.debug("CREATE REL TABLE %s skipped: %s", edge_label, e)

            n = 0
            for item in items:
                eid = escape_cypher_string(item["id"])
                desc_raw = str(item.get(description_field, ""))[:200]
                desc = escape_cypher_string(desc_raw)
                et = escape_cypher_string(entity_type)
                src = escape_cypher_string(source_tag)
                domain_val = escape_cypher_string(str(item.get("domain", "")))
                graph_info.engine.execute(
                    f"CREATE (k:KnowledgeNode {{name: '{eid}', "
                    f"description: '{desc}', entity_type: '{et}', "
                    f"confidence: 1.0, source: '{src}', "
                    f"created_at: '{ts}', domain: '{domain_val}', "
                    f"authority: 'inferred'}});"
                )
                n += 1

            edges_created = 0
            edges_skipped = 0
            for item in items:
                src_id = escape_cypher_string(item["id"])
                for ref in item.get(ref_field) or []:
                    if ref_resolver is not None:
                        resolved = ref_resolver(ref)
                        target_value = resolved if resolved is not None else str(ref)
                    else:
                        target_value = str(ref)
                    if not target_value:
                        edges_skipped += 1
                        continue
                    tgt = escape_cypher_string(target_value)
                    try:
                        _, source_rows = graph_info.engine.execute(
                            f"MATCH (a:KnowledgeNode {{name: '{src_id}'}}) RETURN count(a);"
                        )
                        _, target_rows = graph_info.engine.execute(
                            f"MATCH (b:KnowledgeNode {{name: '{tgt}'}}) RETURN count(b);"
                        )
                        source_count = int(source_rows[0][0]) if source_rows else 0
                        target_count = int(target_rows[0][0]) if target_rows else 0
                        if source_count == 0 or target_count == 0:
                            edges_skipped += 1
                            continue
                        graph_info.engine.execute(
                            f"MATCH (a:KnowledgeNode {{name: '{src_id}'}}), "
                            f"(b:KnowledgeNode {{name: '{tgt}'}}) "
                            f"CREATE (a)-[:{edge_label} {{weight: 1.0, "
                            f"justification: 'auto_graph', "
                            f"source: '{escape_cypher_string(source_tag)}', "
                            f"created_at: '{ts}'}}]->(b);"
                        )
                        edges_created += source_count * target_count
                    except Exception as exc:
                        edges_skipped += 1
                        auto_graph_logger.debug(
                            "Skipped auto_graph edge %s -> %s: %s", src_id, tgt, exc
                        )
            return AutoGraphResult(n, edges_created, edges_skipped)

    return await run_sync(_do)


async def run_with_lock(
    info: SessionInfo,
    sync_fn: Callable[[], T],
    abandon_on_cancel: bool = False,
) -> T:
    """Run sync_fn in a worker thread while holding info.lock.

    Use this for any engine operation that needs per-session serialization.
    The lock is acquired INSIDE the worker thread (threading.Lock is sync).

    If ``abandon_on_cancel`` is True (used when wrapped in a timeout scope),
    cancellation abandons the thread instead of waiting for it. The thread
    continues running but its result is discarded — only safe for idempotent
    reads. Writes under abandon_on_cancel=True can produce partial state.
    """

    def _locked() -> T:
        with info.lock:
            return sync_fn()

    return await run_sync(
        _locked,
        abandon_on_cancel=abandon_on_cancel,
    )


async def execute_and_format(
    info: SessionInfo,
    mgr: SessionManager,
    query: str,
    output_format: str = "csv",
    offset: int | None = None,
    limit: int | None = None,
    paginate: bool = False,
    next_tool: str = "sql_query_next",
    timeout_ms: int | None = None,
) -> str:
    """Shared query execution + formatting logic for SQL and graph tools.

    Handles Arrow path, pagination (cursor + offset/limit), and legacy fallback.
    Acquires info.lock for all engine operations (multi-agent safety).

    If ``timeout_ms`` is provided, wraps execution in ``anyio.fail_after``.
    On timeout, returns a graceful error string instead of raising.
    """
    effective_limit = limit if limit is not None else mgr.max_rows

    abandon = timeout_ms is not None and timeout_ms > 0

    async def _run() -> str:
        return await _execute_inner(
            info,
            mgr,
            query,
            output_format,
            offset,
            effective_limit,
            paginate,
            next_tool,
            abandon_on_cancel=abandon,
        )

    if not abandon:
        return await _run()

    assert timeout_ms is not None  # abandon is True only when timeout_ms > 0
    try:
        with anyio.fail_after(timeout_ms / 1000.0):
            return await _run()
    except TimeoutError:
        return (
            f"Query timed out after {timeout_ms}ms. "
            "Consider adding LIMIT, scoping via WHERE, or raising timeout_ms."
        )


async def _execute_inner(
    info: SessionInfo,
    mgr: SessionManager,
    query: str,
    output_format: str,
    offset: int | None,
    effective_limit: int,
    paginate: bool,
    next_tool: str,
    abandon_on_cancel: bool = False,
) -> str:
    if paginate:
        cursor_id, table = await run_with_lock(
            info,
            lambda: info.engine.execute_paged(query, effective_limit),
            abandon_on_cancel=abandon_on_cancel,
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

    # Standard query — windowed Arrow path. This avoids materializing the
    # entire result set before slicing for the common non-paginated flow.
    table, has_more = await run_with_lock(
        info,
        lambda: info.engine.execute_windowed(
            query,
            offset=offset or 0,
            limit=effective_limit,
        ),
        abandon_on_cancel=abandon_on_cancel,
    )

    if table is not None:
        pagination_meta = None
        if table.num_rows > 0 and ((offset or 0) > 0 or has_more):
            start = offset or 0
            end = start + table.num_rows - 1
            parts = [f"# Page: rows {start}-{end}"]
            if has_more:
                parts.append("has_more: true")
            pagination_meta = " | ".join(parts)
        return format_arrow_result(
            table,
            effective_limit,
            mgr.max_chars,
            output_format,
            pagination_meta,
        )

    # Fallback to legacy tuple path
    columns, rows = await run_with_lock(
        info,
        lambda: info.engine.execute(query),
        abandon_on_cancel=abandon_on_cancel,
    )
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
