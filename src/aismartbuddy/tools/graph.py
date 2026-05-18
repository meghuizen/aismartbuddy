"""Graph database tools backed by LadybugDB (Cypher query language)."""

from __future__ import annotations

import csv
import io
import logging
import re

import anyio
from mcp.server.fastmcp import Context

from aismartbuddy.engines import BaseEngine
from aismartbuddy.formatting import format_result
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import (
    execute_and_format,
    fetch_next_and_format,
    get_session_manager,
    resolve_active_or_provided_session_id,
    run_with_lock,
    size_guarded,
)

logger = logging.getLogger("aismartbuddy.tools.graph")


def _require_graph_session(session_id: str | None):
    """Validate and return a graph session.

    Accepts a direct graph session_id OR a parent session_id whose backends
    include "graph".
    """
    session_id = resolve_active_or_provided_session_id(session_id)
    if not session_id:
        raise ValueError(
            "session_id is required unless an active session is set. "
            "Use think_set_active_session(session_id)."
        )
    mgr = get_session_manager()
    info = mgr.resolve_backend_session(session_id, "graph")
    return mgr, info


def _require_graph_session_pair(session_id_a: str, session_id_b: str):
    """Validate and return two graph sessions for comparison tools."""
    mgr = get_session_manager()
    info_a = mgr.resolve_backend_session(session_id_a, "graph")
    info_b = mgr.resolve_backend_session(session_id_b, "graph")
    return mgr, info_a, info_b


def escape_cypher_string(value: str) -> str:
    """Escape a string value for safe interpolation into Cypher single-quoted strings.

    Public so other tool modules (auto_graph helper) can reuse without
    reaching into a private name. Keep `_escape_cypher_string` alias for
    in-module callers that already use it.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


# Module-internal alias preserved for existing callers in graph.py and
# tools that imported the underscored form.
_escape_cypher_string = escape_cypher_string


def _validate_id(name: str, label: str = "identifier") -> str:
    """Validate a Cypher identifier (table name, property name)."""
    BaseEngine._validate_identifier(name, label)
    return name


async def graph_create_session(
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Create a new graph database session. Returns a session_id token.

    Use this session_id in all subsequent graph_* tool calls.
    Graph sessions use Cypher query language — ideal for relationship data,
    networks, hierarchies, path finding, and connected data analysis.

    IMPORTANT: You must CREATE NODE TABLE before creating nodes.
    LadybugDB requires schema-first: define tables, then insert data.

    Multi-tenant: bound to (user_id, project_id). If Bearer auth is configured,
    user_id comes from ctx.client_id (parameter ignored); otherwise the
    parameter (or configured default) is used.

    Example: graph_create_session(project_id="social") → returns session_id

    Args:
        user_id: Owner identity. Ignored when Bearer auth is configured.
        project_id: Project scope. Default: configured default_project_id.

    Returns:
        Session ID and connection details.
    """
    resolved_user, resolved_project = resolve_identity(ctx, user_id, project_id)
    mgr = get_session_manager()
    info = await anyio.to_thread.run_sync(
        lambda: mgr.create_session("graph", resolved_user, resolved_project)
    )
    return (
        f"Graph session created.\n"
        f"session_id: {info.session_id}\n"
        f"user_id: {info.user_id} | project_id: {info.project_id}\n"
        f"Uses Cypher query language. Remember: CREATE NODE TABLE before CREATE nodes.\n"
        f"Use this session_id in graph_query, graph_import, graph_schema, graph_destroy_session."
    )


async def graph_query(
    session_id: str | None = None,
    query: str = "",
    output_format: str = "csv",
    offset: int | None = None,
    limit: int | None = None,
    paginate: bool = False,
    timeout_ms: int = 10000,
) -> str:
    """Execute a Cypher query against a graph session.

    Supports schema creation (CREATE NODE TABLE, CREATE REL TABLE),
    data creation (CREATE), queries (MATCH...RETURN), imports (COPY FROM),
    and all standard Cypher operations.

    IMPORTANT: Statements must end with semicolons.

    Pagination: For large results exceeding max_rows, use either:
    - offset/limit for random access: graph_query(sid, q, offset=1000, limit=500)
    - paginate=True for cursor-based sequential paging (most efficient for full scans)
      Returns first page + cursor_id; use graph_query_next to get subsequent pages.

    Timeout: execution is bounded by ``timeout_ms`` (default 10s). On timeout,
    returns a graceful error string instead of hanging. Set ``timeout_ms=0``
    to disable the timeout (not recommended for interactive use).

    Common error: missing semicolon at end of Cypher statement.

    Example: graph_query(session_id, "MATCH (n:Person) RETURN n.name LIMIT 10;")

    See also: graph_query_next for cursor pagination, graph_schema for table info.

    Args:
        session_id: Session token from graph_create_session.
        query: Cypher query to execute.
        output_format: Result format — "csv" (default, most token-efficient) or "table".
        offset: Skip this many rows from the start (for random-access paging).
        limit: Return at most this many rows (overrides server max_rows).
        paginate: If True, use cursor-based paging. Returns first page + cursor_id.
        timeout_ms: Hard deadline in milliseconds (default 10000 = 10s).
            0 disables the timeout.

    Returns:
        Query results in the chosen format, or a timeout error message.
    """
    mgr, info = _require_graph_session(session_id)
    return await execute_and_format(
        info,
        mgr,
        query,
        output_format,
        offset,
        limit,
        paginate,
        next_tool="graph_query_next",
        timeout_ms=timeout_ms if timeout_ms > 0 else None,
    )


async def graph_import(
    session_id: str | None = None,
    table_name: str = "",
    data: str = "",
    table_type: str = "node",
    schema: str | None = None,
    from_table: str | None = None,
    to_table: str | None = None,
) -> str:
    """Import CSV data into a graph session.

    For nodes: provide table_name, data (CSV), and schema.
    For relationships: also provide from_table and to_table.
    Keep CSV rows general-purpose and reusable across domains; common shapes
    include entity-score tables and edge lists derived from imported SQL data.

    Reusable node input shapes:
    - entity-score table: `entity,score,direction,panel,source`
    - ranked list: `entity,rank,metric,source`

    Reusable relationship input shapes:
    - edge list: `from,to,relation,weight,source`
    - pathway membership: `from,to,panel,source`

    Args:
        session_id: Session token from graph_create_session.
        table_name: Name of the node or relationship table.
        data: CSV content with header row.
        table_type: "node" (default) or "relationship".
        schema: Column definitions. Example: "id INT64 PRIMARY KEY, name STRING, age INT64".
        from_table: Source node table name (required for relationships).
        to_table: Target node table name (required for relationships).

    Returns:
        Import confirmation with row count.
    """
    mgr, info = _require_graph_session(session_id)
    count = await run_with_lock(
        info,
        lambda: info.engine.import_csv(table_name, data, table_type, schema, from_table, to_table),
    )
    return f"Imported {count} {table_type}s into '{table_name}'."


async def graph_schema(session_id: str | None = None) -> str:
    """Get graph database schema — node tables, relationship tables, and their properties.

    Args:
        session_id: Session token from graph_create_session.

    Returns:
        Schema information showing all tables and their structure.
    """
    mgr, info = _require_graph_session(session_id)
    columns, rows = await run_with_lock(info, info.engine.get_schema)
    if not rows:
        return "No tables in graph database. Create tables with graph_query or graph_import."
    return format_result(columns, rows, mgr.max_rows, mgr.max_chars, "table")


async def graph_destroy_session(session_id: str | None = None) -> str:
    """Destroy a graph session and clean up all temporary data.

    Always call this when done to free resources.

    Args:
        session_id: Session token to destroy.

    Returns:
        Confirmation message.
    """
    mgr, info = _require_graph_session(session_id)
    await anyio.to_thread.run_sync(lambda: mgr.destroy_session(info.session_id))
    return f"Graph session '{info.session_id}' destroyed and cleaned up."


async def graph_query_next(session_id: str | None = None, cursor_id: str = "") -> str:
    """Fetch the next page of results from a paginated graph query.

    Use after graph_query(..., paginate=True) returns a cursor_id.
    Returns the next page of results. When the last page is reached,
    the response includes "has_more: false" and the cursor is auto-closed.

    Example: graph_query_next(session_id, "abc123def456")

    See also: graph_query with paginate=True to start pagination.

    Args:
        session_id: Session token from graph_create_session.
        cursor_id: Cursor token from a previous graph_query(..., paginate=True) call.

    Returns:
        Next page of query results, or end-of-results message.
    """
    mgr, info = _require_graph_session(session_id)
    return await fetch_next_and_format(
        info,
        mgr,
        cursor_id,
        next_tool="graph_query_next",
    )


# ── Analytical graph tools ───────────────────────────────────────


@size_guarded
async def graph_statistics(session_id: str | None = None) -> str:
    """Get a complete overview of the graph in one call.

    Returns node counts by type, relationship counts by type,
    total nodes/edges, and the top 5 most-connected nodes.
    Use this to get a "holistic view" of the graph before diving into queries.

    Args:
        session_id: Session token from graph_create_session.

    Returns:
        Compact graph overview with all statistics.
    """
    mgr, info = _require_graph_session(session_id)
    stats = await run_with_lock(info, info.engine.get_statistics)

    lines = ["## Graph Overview"]
    lines.append(f"Total: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    lines.append("")

    if stats["node_tables"]:
        lines.append("### Node Tables")
        for name, count in stats["node_tables"].items():
            lines.append(f"  {name}: {count}")

    if stats["rel_tables"]:
        lines.append("### Relationship Tables")
        for name, count in stats["rel_tables"].items():
            lines.append(f"  {name}: {count}")

    return "\n".join(lines)


async def graph_neighbors(
    session_id: str | None = None,
    node_name: str = "",
    node_type: str = "",
    depth: int = 1,
    direction: str = "both",
) -> str:
    """Get the N-hop neighborhood of a specific node.

    Returns all nodes and relationships within `depth` hops of the target node.
    Use this to "focus on a sub-part" of the graph around a specific entity.

    Args:
        session_id: Session token from graph_create_session.
        node_name: Name of the node to explore.
        node_type: Node table name (e.g., "Gene", "Pathway").
        depth: How many hops to explore (default 1, max 5).
        direction: "both" (default), "outgoing", or "incoming".

    Returns:
        Neighborhood nodes and their relationship to the target.
    """
    mgr, info = _require_graph_session(session_id)
    _validate_id(node_type, "node_type")
    safe_name = _escape_cypher_string(node_name)
    depth = min(depth, 5)

    if direction == "outgoing":
        pattern = f"(start:{node_type} {{name: '{safe_name}'}})-[r*1..{depth}]->(neighbor)"
    elif direction == "incoming":
        pattern = f"(neighbor)-[r*1..{depth}]->(start:{node_type} {{name: '{safe_name}'}})"
    else:
        pattern = f"(start:{node_type} {{name: '{safe_name}'}})-[r*1..{depth}]-(neighbor)"

    cypher = (
        f"MATCH p = {pattern} "
        f"RETURN DISTINCT labels(neighbor) AS type, neighbor.name AS name, length(p) AS hops "
        f"ORDER BY hops, name LIMIT 50;"
    )
    columns, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
    if not rows:
        return f"No neighbors found for {node_type} '{node_name}' within {depth} hops."
    return format_result(columns, rows, mgr.max_rows, mgr.max_chars, "table")


@size_guarded
async def graph_focus_summary(
    session_id: str | None = None,
    node_names: list[str] | None = None,
    node_type: str = "",
    depth: int = 1,
    direction: str = "both",
) -> str:
    """Summarize multiple graph neighborhoods in one call.

    Use this when you want focused inspection around several important nodes
    without spending one round trip per `graph_neighbors` call.

    Args:
        session_id: Session token from graph_create_session.
        node_names: Node names to inspect (up to 10).
        node_type: Node table name (e.g., "Gene", "Pathway", "KnowledgeNode").
        depth: How many hops to explore around each node (default 1, max 5).
        direction: "both" (default), "outgoing", or "incoming".

    Returns:
        Compact multi-node neighborhood summary.
    """
    if not node_names:
        raise ValueError("node_names must be non-empty")
    mgr, info = _require_graph_session(session_id)
    _validate_id(node_type, "node_type")
    depth = min(depth, 5)
    names = []
    seen: set[str] = set()
    for raw in node_names[:10]:
        name = str(raw).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        raise ValueError("node_names must contain at least one non-empty name")

    sections = [
        "## Graph Focus Summary",
        f"Node type: {node_type} | Depth: {depth} | Direction: {direction}",
        f"Nodes requested: {', '.join(names)}",
    ]

    for node_name in names:
        safe_name = _escape_cypher_string(node_name)
        if direction == "outgoing":
            pattern = f"(start:{node_type} {{name: '{safe_name}'}})-[r*1..{depth}]->(neighbor)"
        elif direction == "incoming":
            pattern = f"(neighbor)-[r*1..{depth}]->(start:{node_type} {{name: '{safe_name}'}})"
        else:
            pattern = f"(start:{node_type} {{name: '{safe_name}'}})-[r*1..{depth}]-(neighbor)"

        cypher = (
            f"MATCH p = {pattern} "
            "RETURN DISTINCT labels(neighbor) AS type, "
            "neighbor.name AS name, length(p) AS hops "
            "ORDER BY hops, name LIMIT 20;"
        )
        columns, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
        sections.append(f"\n### {node_name}")
        if not rows:
            sections.append(
                f"No neighbors found for {node_type} '{node_name}' within {depth} hops."
            )
            continue
        sections.append(format_result(columns, rows, mgr.max_rows, mgr.max_chars, "table"))

    return "\n".join(sections)


async def graph_find_connections(
    session_id: str | None = None,
    from_name: str = "",
    from_type: str = "",
    to_name: str = "",
    to_type: str = "",
    max_depth: int = 5,
    max_paths: int = 20,
) -> str:
    """Find all paths between two nodes in the graph.

    Returns paths ordered by length (shortest first), showing intermediate nodes.
    Use for path finding, shortest path analysis, and connection discovery.

    Args:
        session_id: Session token from graph_create_session.
        from_name: Name of the source node.
        from_type: Table type of the source node (e.g., "Gene").
        to_name: Name of the target node.
        to_type: Table type of the target node.
        max_depth: Maximum path length to search (default 5, max 8).
        max_paths: Maximum number of paths to return (default 20).

    Returns:
        Paths between the two nodes with intermediate nodes listed.
    """
    mgr, info = _require_graph_session(session_id)
    _validate_id(from_type, "from_type")
    _validate_id(to_type, "to_type")
    safe_from = _escape_cypher_string(from_name)
    safe_to = _escape_cypher_string(to_name)
    max_depth = min(max_depth, 8)
    max_paths = min(max_paths, 50)

    cypher = (
        f"MATCH p = (a:{from_type} {{name: '{safe_from}'}})"
        f"-[*1..{max_depth}]-"
        f"(b:{to_type} {{name: '{safe_to}'}}) "
        f"RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops "
        f"ORDER BY hops LIMIT {max_paths};"
    )
    columns, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
    if not rows:
        return (
            f"No paths found between {from_type} '{safe_from}' and "
            f"{to_type} '{safe_to}' within {max_depth} hops."
        )
    return format_result(columns, rows, mgr.max_rows, mgr.max_chars, "table")


async def _analyze_orphans(info, mgr, stats) -> str:
    """Find nodes with no relationships across all node tables."""
    all_results = []
    for table_name in stats["node_tables"]:
        cypher = (
            f"MATCH (n:{table_name}) "
            f"WHERE NOT EXISTS {{ MATCH (n)-[]-() }} "
            f"RETURN '{table_name}' AS type, n.name AS name;"
        )
        _, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
        all_results.extend(rows)
    if not all_results:
        return "No orphan nodes found — all nodes have at least one relationship."
    return format_result(["type", "name"], all_results, mgr.max_rows, mgr.max_chars, "table")


async def _analyze_hubs(info, mgr, stats) -> str:
    """Find the 10 most-connected nodes (highest degree)."""
    all_results = []
    for table_name in stats["node_tables"]:
        cypher = (
            f"MATCH (n:{table_name})-[r]-() "
            f"RETURN '{table_name}' AS type, n.name AS name, count(r) AS degree "
            f"ORDER BY degree DESC LIMIT 10;"
        )
        _, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
        all_results.extend(rows)
    all_results.sort(key=lambda r: r[2], reverse=True)
    top = all_results[:10]
    if not top:
        return "No connected nodes found."
    return format_result(["type", "name", "degree"], top, mgr.max_rows, mgr.max_chars, "table")


async def _analyze_categories(info, mgr, stats) -> str:
    """Group nodes by type and key properties."""
    lines = ["## Node Categories"]
    for table_name, count in stats["node_tables"].items():
        lines.append(f"\n### {table_name} ({count} nodes)")
        for prop in ["direction", "status", "category", "activation_status", "system"]:
            cypher = (
                f"MATCH (n:{table_name}) WHERE n.{prop} IS NOT NULL "
                f"RETURN n.{prop} AS {prop}, count(n) AS cnt ORDER BY cnt DESC;"
            )
            try:
                _, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
                if rows:
                    for row in rows:
                        lines.append(f"  {prop}={row[0]}: {row[1]}")
            except Exception as exc:
                logger.debug("Property query failed for %s.%s: %s", table_name, prop, exc)
                continue
    return "\n".join(lines)


async def _analyze_cross_connections(info, mgr, stats) -> str:
    """Find nodes that bridge different relationship types."""
    all_results = []
    for table_name in stats["node_tables"]:
        rel_types = list(stats["rel_tables"].keys())
        if len(rel_types) < 2:
            continue
        for i, rt1 in enumerate(rel_types):
            for rt2 in rel_types[i + 1 :]:
                cypher = (
                    f"MATCH (n:{table_name})-[:{rt1}]-() "
                    f"MATCH (n)-[:{rt2}]-() "
                    f"RETURN DISTINCT '{table_name}' AS type, n.name AS name, "
                    f"'{rt1}+{rt2}' AS bridges;"
                )
                try:
                    _, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
                    all_results.extend(rows)
                except Exception as exc:
                    logger.warning("Cross-connection query failed: %s", exc)
                    continue
    if not all_results:
        return "No cross-connection nodes found."
    seen: set[tuple] = set()
    unique = []
    for row in all_results:
        key = (row[1], row[2])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return format_result(
        ["type", "name", "bridges"], unique[:20], mgr.max_rows, mgr.max_chars, "table"
    )


async def _analyze_feedback_loops(info, mgr, stats) -> str:
    """Detect simple directed cycles in the graph."""
    try:
        cols, rows = await run_with_lock(
            info,
            lambda: info.engine.execute(
                "MATCH (a)-[r1]->(b)-[r2]->(a) "
                "RETURN DISTINCT a.name AS node_a, b.name AS node_b, "
                "type(r1) AS edge_ab, type(r2) AS edge_ba LIMIT 20;"
            ),
        )
    except Exception:
        return "No feedback loops found."
    if not rows:
        return "No feedback loops found."
    return format_result(cols, rows, mgr.max_rows, mgr.max_chars, "table")


async def _analyze_motifs(info, mgr, stats) -> str:
    """Find recurring small motifs such as mutual pairs and feed-forward triads."""
    lines = ["## Graph Motifs"]
    try:
        _, mutual_rows = await run_with_lock(
            info,
            lambda: info.engine.execute(
                "MATCH (a)-[r1]->(b)-[r2]->(a) "
                "RETURN DISTINCT a.name AS left_node, b.name AS right_node "
                "LIMIT 20;"
            ),
        )
    except Exception:
        mutual_rows = []
    if mutual_rows:
        lines.append(f"Mutual pairs: {len(mutual_rows)}")
        for row in mutual_rows[:10]:
            lines.append(f"  {row[0]} <-> {row[1]}")
    try:
        _, triad_rows = await run_with_lock(
            info,
            lambda: info.engine.execute(
                "MATCH (a)-[r1]->(b)-[r2]->(c), (a)-[r3]->(c) "
                "RETURN DISTINCT a.name AS start, b.name AS middle, c.name AS end "
                "LIMIT 20;"
            ),
        )
    except Exception:
        triad_rows = []
    if triad_rows:
        lines.append(f"Feed-forward triads: {len(triad_rows)}")
        for row in triad_rows[:10]:
            lines.append(f"  {row[0]} -> {row[1]} -> {row[2]} and {row[0]} -> {row[2]}")
    if len(lines) == 1:
        return "No recurring motifs found."
    return "\n".join(lines)


async def _analyze_bottlenecks(info, mgr, stats) -> str:
    """Approximate bottlenecks via high connectivity across relationship types."""
    all_results = []
    for table_name in stats["node_tables"]:
        cypher = (
            f"MATCH (n:{table_name})-[r]-() "
            f"RETURN '{table_name}' AS type, n.name AS name, count(r) AS degree "
            f"ORDER BY degree DESC LIMIT 10;"
        )
        try:
            _, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
            all_results.extend(rows)
        except Exception:
            continue
    if not all_results:
        return "No bottlenecks found."
    all_results.sort(key=lambda row: row[2], reverse=True)
    return format_result(
        ["type", "name", "degree"], all_results[:20], mgr.max_rows, mgr.max_chars, "table"
    )


async def _analyze_domain_bridges(info, mgr, stats) -> str:
    """Find edges carrying different domain metadata between knowledge nodes."""
    rel_tables = [
        table_name
        for table_name in stats["rel_tables"]
        if table_name.lower() not in {"derivedfrom", "partof"}
    ]
    rows: list[tuple] = []
    for rel in rel_tables:
        cypher = (
            f"MATCH (a:KnowledgeNode)-[r:{rel}]->(b:KnowledgeNode) "
            "WHERE r.domain IS NOT NULL AND r.domain <> '' "
            "RETURN DISTINCT a.name AS from_node, b.name AS to_node, r.domain AS domain, "
            f"'{rel}' AS relation LIMIT 20;"
        )
        try:
            _, rel_rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
            rows.extend(rel_rows)
        except Exception:
            continue
    if not rows:
        return "No domain bridges found."
    return format_result(
        ["from_node", "to_node", "domain", "relation"],
        rows[:20],
        mgr.max_rows,
        mgr.max_chars,
        "table",
    )


async def graph_analyze(session_id: str | None = None, analysis_type: str = "") -> str:
    """Run pre-built analytical queries on the graph.

    Saves you from writing complex Cypher for common graph analysis tasks.

    Args:
        session_id: Session token from graph_create_session.
        analysis_type: Type of analysis to run:
            - "orphans" — find nodes with no relationships
            - "hubs" — find the 10 most-connected nodes (highest degree)
            - "categories" — group all nodes by type and key properties
            - "cross_connections" — find nodes linking different node types
            - "motifs" — recurring small subgraph patterns
            - "bottlenecks" — high-connectivity bridge nodes
            - "domain_bridges" — cross-domain relationships using edge domain metadata
            - "feedback_loops" — simple directed cycles

    Returns:
        Analysis results in table format.
    """
    mgr, info = _require_graph_session(session_id)
    stats = await run_with_lock(info, info.engine.get_statistics)

    dispatch = {
        "orphans": _analyze_orphans,
        "hubs": _analyze_hubs,
        "categories": _analyze_categories,
        "cross_connections": _analyze_cross_connections,
        "motifs": _analyze_motifs,
        "bottlenecks": _analyze_bottlenecks,
        "domain_bridges": _analyze_domain_bridges,
        "feedback_loops": _analyze_feedback_loops,
    }
    handler = dispatch.get(analysis_type)
    if handler is None:
        options = ", ".join(dispatch.keys())
        return f"Unknown analysis_type: '{analysis_type}'. Options: {options}"
    return await handler(info, mgr, stats)


async def graph_compare(
    session_id_a: str,
    session_id_b: str,
    compare_type: str = "structure",
) -> str:
    """Compare two graph sessions to find differences and similarities.

    Use this to cross-reference different datasets, patients, or time points.

    Args:
        session_id_a: First graph session.
        session_id_b: Second graph session.
        compare_type: What to compare:
            - "structure" — compare node/edge counts and table schemas
            - "nodes" — find nodes in A but not B, and vice versa (by name)
            - "properties" — for shared nodes, compare property values

    Returns:
        Comparison results showing overlap and differences.
    """
    mgr, info_a, info_b = _require_graph_session_pair(session_id_a, session_id_b)

    stats_a = await run_with_lock(info_a, info_a.engine.get_statistics)
    stats_b = await run_with_lock(info_b, info_b.engine.get_statistics)

    if compare_type == "structure":
        lines = ["## Graph Structure Comparison"]
        lines.append(f"Graph A: {stats_a['total_nodes']} nodes, {stats_a['total_edges']} edges")
        lines.append(f"Graph B: {stats_b['total_nodes']} nodes, {stats_b['total_edges']} edges")
        lines.append("")
        all_tables = set(stats_a["node_tables"]) | set(stats_b["node_tables"])
        if all_tables:
            lines.append("### Node Tables")
            for t in sorted(all_tables):
                ca = stats_a["node_tables"].get(t, 0)
                cb = stats_b["node_tables"].get(t, 0)
                diff = cb - ca
                marker = f" ({'+' if diff > 0 else ''}{diff})" if diff != 0 else ""
                lines.append(f"  {t}: A={ca}, B={cb}{marker}")
        all_rels = set(stats_a["rel_tables"]) | set(stats_b["rel_tables"])
        if all_rels:
            lines.append("### Relationship Tables")
            for t in sorted(all_rels):
                ca = stats_a["rel_tables"].get(t, 0)
                cb = stats_b["rel_tables"].get(t, 0)
                diff = cb - ca
                marker = f" ({'+' if diff > 0 else ''}{diff})" if diff != 0 else ""
                lines.append(f"  {t}: A={ca}, B={cb}{marker}")
        return "\n".join(lines)

    elif compare_type == "nodes":
        lines = ["## Node Comparison"]
        shared_tables = set(stats_a["node_tables"]) & set(stats_b["node_tables"])
        for table_name in sorted(shared_tables):
            _, rows_a = await run_with_lock(
                info_a,
                lambda t=table_name: info_a.engine.execute(
                    f"MATCH (n:{t}) RETURN n.name ORDER BY n.name;"
                ),
            )
            _, rows_b = await run_with_lock(
                info_b,
                lambda t=table_name: info_b.engine.execute(
                    f"MATCH (n:{t}) RETURN n.name ORDER BY n.name;"
                ),
            )
            names_a = {r[0] for r in rows_a}
            names_b = {r[0] for r in rows_b}
            shared = names_a & names_b
            only_a = names_a - names_b
            only_b = names_b - names_a
            lines.append(f"\n### {table_name}")
            lines.append(f"  Shared: {len(shared)}")
            if only_a:
                lines.append(f"  Only in A ({len(only_a)}): {', '.join(sorted(only_a)[:10])}")
            if only_b:
                lines.append(f"  Only in B ({len(only_b)}): {', '.join(sorted(only_b)[:10])}")
        return "\n".join(lines)

    elif compare_type == "properties":
        lines = ["## Property Comparison (shared nodes)"]
        shared_tables = set(stats_a["node_tables"]) & set(stats_b["node_tables"])
        for table_name in sorted(shared_tables):
            _, rows_a = await run_with_lock(
                info_a,
                lambda t=table_name: info_a.engine.execute(
                    f"MATCH (n:{t}) RETURN n.name, n.* ORDER BY n.name;"
                ),
            )
            _, rows_b = await run_with_lock(
                info_b,
                lambda t=table_name: info_b.engine.execute(
                    f"MATCH (n:{t}) RETURN n.name, n.* ORDER BY n.name;"
                ),
            )
            dict_a = {r[0]: r[1:] for r in rows_a}
            dict_b = {r[0]: r[1:] for r in rows_b}
            shared_names = set(dict_a) & set(dict_b)
            diffs = []
            for name in sorted(shared_names):
                if dict_a[name] != dict_b[name]:
                    diffs.append(f"  {name}: A={dict_a[name]} vs B={dict_b[name]}")
            if diffs:
                lines.append(f"\n### {table_name} differences")
                lines.extend(diffs[:20])
            else:
                lines.append(f"\n### {table_name}: all shared nodes identical")
        return "\n".join(lines)

    else:
        return f"Unknown compare_type: '{compare_type}'. Options: structure, nodes, properties"


async def graph_cross_reference(
    session_id_a: str,
    session_id_b: str,
    node_type: str,
    key_property: str = "name",
) -> str:
    """Cross-reference nodes between two graph sessions.

    Returns a merged CSV view showing which nodes appear in both sessions,
    only in A, or only in B, with property differences for shared nodes.
    Essential for comparing patient profiles or time-series data.

    Args:
        session_id_a: First graph session.
        session_id_b: Second graph session.
        node_type: Node table to cross-reference (e.g., "Gene").
        key_property: Property to match nodes on (default: "name").

    Returns:
        CSV table with status (both/only_A/only_B) and property comparison.
    """
    mgr, info_a, info_b = _require_graph_session_pair(session_id_a, session_id_b)
    _validate_id(node_type, "node_type")
    _validate_id(key_property, "key_property")

    _, rows_a = await run_with_lock(
        info_a,
        lambda: info_a.engine.execute(
            f"MATCH (n:{node_type}) RETURN n.{key_property}, n.* ORDER BY n.{key_property};"
        ),
    )
    _, rows_b = await run_with_lock(
        info_b,
        lambda: info_b.engine.execute(
            f"MATCH (n:{node_type}) RETURN n.{key_property}, n.* ORDER BY n.{key_property};"
        ),
    )

    dict_a = {r[0]: r[1:] for r in rows_a}
    dict_b = {r[0]: r[1:] for r in rows_b}
    all_keys = sorted(set(dict_a) | set(dict_b))

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([key_property, "status", "values_A", "values_B"])

    for key in all_keys:
        in_a = key in dict_a
        in_b = key in dict_b
        if in_a and in_b:
            status = "both"
        elif in_a:
            status = "only_A"
        else:
            status = "only_B"
        vals_a = str(dict_a.get(key, ""))
        vals_b = str(dict_b.get(key, ""))
        writer.writerow([key, status, vals_a, vals_b])

    result = output.getvalue()
    total = len(all_keys)
    both = sum(1 for k in all_keys if k in dict_a and k in dict_b)
    only_a = sum(1 for k in all_keys if k in dict_a and k not in dict_b)
    only_b = sum(1 for k in all_keys if k not in dict_a and k in dict_b)

    header = (
        f"# Cross-reference: {node_type} by {key_property}\n"
        f"# Total: {total} | Both: {both} | Only A: {only_a} | Only B: {only_b}\n"
    )
    return header + result


# ── Knowledge Graph Tools ─────────────────────────────────────────

_DEFAULT_ENTITY_TYPES = {"concept", "entity", "fact", "evidence", "question", "insight"}
_ENTITY_TYPE_ALIASES = {"hypothesis": "question"}
_DEFAULT_RELATION_TYPES = {
    "supports",
    "contradicts",
    "refines",
    "causes",
    "prevents",
    "requires",
    "part_of",
    "similar_to",
    "derived_from",
}


def _normalize_entity_type(entity_type: str) -> str:
    """Map user-facing aliases onto the persisted KnowledgeNode taxonomy."""
    return _ENTITY_TYPE_ALIASES.get(entity_type, entity_type)


def _normalize_relation_table_name(relation: str) -> str:
    """Convert any user relation label into a safe relation-table identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", relation.strip()).strip("_")
    if not cleaned:
        raise ValueError("relation must be a non-empty string")
    parts = [part.capitalize() for part in cleaned.split("_") if part]
    table_name = "".join(parts) or "Relation"
    _validate_id(table_name, "relation_table")
    return table_name


async def graph_knowledge_add(
    session_id: str | None = None,
    entity: str = "",
    entity_type: str = "concept",
    properties: dict | None = None,
    confidence: float = 1.0,
    source: str = "ai",
    authority: str | None = None,
    items: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Add a knowledge node with provenance metadata to the graph.

    This is a higher-level tool that enforces knowledge graph conventions:
    typed entities, confidence scores, and provenance tracking.

    The first call auto-creates a KnowledgeNode table if it doesn't exist.
    Batch mode: pass items=[{entity, entity_type?, confidence?, properties?,
    source?, authority?}, ...] to create multiple nodes in one call. Each
    item is one entity.

    Args:
        session_id: Session token from graph_create_session.
        entity: Name/label of the knowledge entity.
        entity_type: Documented defaults: concept, entity, fact, evidence,
            question, insight. Any non-empty string is accepted and registered
            as provided. Alias accepted: hypothesis -> question.
        properties: Optional dict of additional properties (stored as description).
        confidence: Confidence score 0.0 to 1.0 (default 1.0).
        source: Provenance — who/what added this (default "ai").
        authority: Optional authority tier — one of
            ``ground_truth | primary | inferred | external``. Stored on the
            node so downstream tools can rank knowledge by trust level.

    Returns:
        Confirmation with node details.
    """
    mgr, info = _require_graph_session(session_id)
    if items is not None:
        return await knowledge_batch(
            session_id=session_id,
            nodes=items,
            relations=None,
            idempotency_key=idempotency_key,
        )

    if idempotency_key:
        cached = mgr.get_idempotent_result(info.session_id, idempotency_key)
        if cached is not None:
            return cached

    entity_type = _normalize_entity_type(entity_type)
    if not entity_type.strip():
        raise ValueError("entity_type must be a non-empty string")
    confidence = max(0.0, min(1.0, confidence))

    if authority is not None and authority not in {
        "ground_truth",
        "primary",
        "inferred",
        "external",
    }:
        raise ValueError(
            f"authority must be one of ground_truth|primary|inferred|external, "
            f"got {authority!r}"
        )
    authority_val = authority or ""

    safe_name = _escape_cypher_string(entity)
    safe_source = _escape_cypher_string(source)
    safe_type = _escape_cypher_string(entity_type)
    safe_authority = _escape_cypher_string(authority_val)
    desc = _escape_cypher_string(str(properties) if properties else "")

    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()

    # Ensure KnowledgeNode table exists
    try:
        await run_with_lock(
            info,
            lambda: info.engine.execute(
                "CREATE NODE TABLE IF NOT EXISTS KnowledgeNode ("
                "id SERIAL PRIMARY KEY, name STRING, description STRING, "
                "entity_type STRING, confidence DOUBLE, "
                "source STRING, created_at STRING, authority STRING);"
            ),
        )
    except Exception:
        pass  # Table may already exist

    await run_with_lock(
        info,
        lambda: info.engine.execute(
            f"CREATE (n:KnowledgeNode {{"
            f"name: '{safe_name}', "
            f"description: '{desc}', "
            f"entity_type: '{safe_type}', "
            f"confidence: {confidence}, "
            f"source: '{safe_source}', "
            f"created_at: '{ts}', "
            f"authority: '{safe_authority}'"
            f"}});"
        ),
    )
    result = f"Added {entity_type}: '{entity}' (confidence: {confidence}, source: {source})"
    if idempotency_key:
        mgr.store_idempotent_result(info.session_id, idempotency_key, result)
    return result


async def graph_knowledge_relate(
    session_id: str | None = None,
    from_name: str = "",
    to_name: str = "",
    relation: str = "",
    weight: float = 1.0,
    justification: str = "",
    source: str = "ai",
    domain: str | None = None,
    directionality: str | None = None,
    confidence_basis: str | None = None,
    items: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Add a semantic relationship between two knowledge nodes.

    Creates weighted, justified relationships with provenance.
    The first call for each relation type auto-creates the relationship table.
    Batch mode: pass items=[{from_name, to_name, relation, weight?, justification?,
    source?, domain?, directionality?, confidence_basis?}, ...] to create
    multiple semantic relationships in one call.

    Args:
        session_id: Session token from graph_create_session.
        from_name: Name of the source knowledge node.
        to_name: Name of the target knowledge node.
        relation: Semantic relationship type. Documented defaults are
            supports, contradicts, refines, causes, prevents, requires,
            part_of, similar_to, derived_from. Any non-empty string is accepted.
        weight: Relationship strength 0.0 to 1.0 (default 1.0).
        justification: Why this relationship exists (free text).
        source: Provenance — who/what added this.
        domain: Optional origin domain for this edge.
        directionality: Optional semantic direction class
            (causal/correlative/structural/temporal/logical).
        confidence_basis: Optional evidence basis
            (experimental/theoretical/analogical/inferred/assumed).

    Returns:
        Confirmation with relationship details.
    """
    mgr, info = _require_graph_session(session_id)
    if items is not None:
        return await knowledge_batch(
            session_id=session_id,
            nodes=None,
            relations=items,
            idempotency_key=idempotency_key,
        )

    if idempotency_key:
        cached = mgr.get_idempotent_result(info.session_id, idempotency_key)
        if cached is not None:
            return cached
    if not relation.strip():
        raise ValueError("relation must be a non-empty string")
    weight = max(0.0, min(1.0, weight))

    safe_from = _escape_cypher_string(from_name)
    safe_to = _escape_cypher_string(to_name)
    safe_just = _escape_cypher_string(justification)
    safe_source = _escape_cypher_string(source)
    safe_domain = _escape_cypher_string(domain or "")
    safe_directionality = _escape_cypher_string(directionality or "")
    safe_confidence_basis = _escape_cypher_string(confidence_basis or "")
    rel_table = _normalize_relation_table_name(relation)

    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()

    # Ensure relationship table exists
    try:
        await run_with_lock(
            info,
            lambda rt=rel_table: info.engine.execute(
                f"CREATE REL TABLE IF NOT EXISTS {rt} ("
                f"FROM KnowledgeNode TO KnowledgeNode, "
                f"weight DOUBLE, justification STRING, "
                f"source STRING, domain STRING, directionality STRING, "
                f"confidence_basis STRING, created_at STRING);"
            ),
        )
    except Exception:
        pass  # Table may already exist

    await run_with_lock(
        info,
        lambda rt=rel_table: info.engine.execute(
            f"MATCH (a:KnowledgeNode {{name: '{safe_from}'}}), "
            f"(b:KnowledgeNode {{name: '{safe_to}'}}) "
            f"CREATE (a)-[:{rt} {{"
            f"weight: {weight}, "
            f"justification: '{safe_just}', "
            f"source: '{safe_source}', "
            f"domain: '{safe_domain}', "
            f"directionality: '{safe_directionality}', "
            f"confidence_basis: '{safe_confidence_basis}', "
            f"created_at: '{ts}'"
            f"}}]->(b);"
        ),
    )
    result = (
        f"Related: '{from_name}' --[{relation} w={weight}]--> '{to_name}'"
        f"{f' ({justification})' if justification else ''}"
    )
    if idempotency_key:
        mgr.store_idempotent_result(info.session_id, idempotency_key, result)
    return result


async def knowledge_batch(
    session_id: str | None = None,
    nodes: list[dict] | None = None,
    relations: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """[ELABORATE] Bulk-create knowledge graph nodes and relations in one call.

    Use INSTEAD of multiple sequential graph_knowledge_add /
    graph_knowledge_relate calls when adding 3+ items. Same per-item
    validation as the single-item tools — invalid items abort the batch.
    Each node entry should be one entity and each relation entry should be
    one semantic relationship. Batch mode reduces round-trips; it is not a
    place to pack multiple entities or multiple meanings into one dict.

    Two-phase: nodes are created first (so relations can match), then
    relations. All operations execute under a single session lock —
    other agents on the same session serialize.

    Args:
        session_id: Session token from graph_create_session.
        nodes: List of node dicts. Each: {entity, entity_type?, confidence?,
            properties?, source?, authority?}. entity is required;
            entity_type defaults to "concept", confidence to 1.0, source to "ai".
            Alias accepted: hypothesis -> question. entity_type is open-ended.
            authority (optional) must be one of
            ``ground_truth | primary | inferred | external`` when supplied.
        relations: List of relation dicts. Each: {from_name, to_name, relation,
            weight?, justification?, source?, domain?, directionality?,
            confidence_basis?}. relation is open-ended; documented defaults are
            supports/contradicts/refines/causes/prevents/requires/
            part_of/similar_to/derived_from.

    Returns:
        Counts of nodes/relations created plus any per-item errors.
    """
    from datetime import datetime, timezone

    mgr, info = _require_graph_session(session_id)
    if idempotency_key:
        cached = mgr.get_idempotent_result(info.session_id, idempotency_key)
        if cached is not None:
            return cached
    nodes = nodes or []
    relations = relations or []
    if not nodes and not relations:
        raise ValueError("knowledge_batch requires at least one node or relation")

    # Phase 0: validate all items up front (fail-fast per plan)
    for i, n in enumerate(nodes):
        if not n.get("entity"):
            raise ValueError(f"nodes[{i}] missing 'entity'")
        et = _normalize_entity_type(n.get("entity_type", "concept"))
        if not str(et).strip():
            raise ValueError(f"nodes[{i}] entity_type must be non-empty")
        auth = n.get("authority")
        if auth is not None and auth not in {
            "ground_truth",
            "primary",
            "inferred",
            "external",
        }:
            raise ValueError(
                f"nodes[{i}] authority must be one of "
                f"ground_truth|primary|inferred|external, got {auth!r}"
            )
    for i, r in enumerate(relations):
        if not r.get("from_name") or not r.get("to_name"):
            raise ValueError(f"relations[{i}] missing 'from_name' or 'to_name'")
        rel = r.get("relation")
        if not str(rel or "").strip():
            raise ValueError(f"relations[{i}] relation must be non-empty")

    ts = datetime.now(timezone.utc).isoformat()

    # Phase 1: ensure KnowledgeNode table + insert all nodes
    def _insert_nodes() -> int:
        try:
            info.engine.execute(
                "CREATE NODE TABLE IF NOT EXISTS KnowledgeNode ("
                "id SERIAL PRIMARY KEY, name STRING, description STRING, "
                "entity_type STRING, confidence DOUBLE, "
                "source STRING, created_at STRING, authority STRING);"
            )
        except Exception:
            pass
        count = 0
        for n in nodes:
            entity = _escape_cypher_string(n["entity"])
            etype = _escape_cypher_string(_normalize_entity_type(n.get("entity_type", "concept")))
            conf = max(0.0, min(1.0, float(n.get("confidence", 1.0))))
            src = _escape_cypher_string(n.get("source", "ai"))
            props = _escape_cypher_string(str(n["properties"]) if n.get("properties") else "")
            authority_val = _escape_cypher_string(n.get("authority") or "")
            info.engine.execute(
                f"CREATE (n:KnowledgeNode {{"
                f"name: '{entity}', description: '{props}', "
                f"entity_type: '{etype}', confidence: {conf}, "
                f"source: '{src}', created_at: '{ts}', "
                f"authority: '{authority_val}'"
                f"}});"
            )
            count += 1
        return count

    # Phase 2: ensure rel tables + insert all relations
    def _insert_relations() -> tuple[int, list[str]]:
        count = 0
        errors: list[str] = []
        for i, r in enumerate(relations):
            relation = r["relation"]
            rel_table = _normalize_relation_table_name(relation)
            try:
                info.engine.execute(
                    f"CREATE REL TABLE IF NOT EXISTS {rel_table} ("
                    f"FROM KnowledgeNode TO KnowledgeNode, "
                    f"weight DOUBLE, justification STRING, "
                    f"source STRING, domain STRING, directionality STRING, "
                    f"confidence_basis STRING, created_at STRING);"
                )
            except Exception:
                pass
            from_n = _escape_cypher_string(r["from_name"])
            to_n = _escape_cypher_string(r["to_name"])
            weight = max(0.0, min(1.0, float(r.get("weight", 1.0))))
            just = _escape_cypher_string(r.get("justification", ""))
            src = _escape_cypher_string(r.get("source", "ai"))
            edge_domain = _escape_cypher_string(r.get("domain", ""))
            edge_directionality = _escape_cypher_string(r.get("directionality", ""))
            edge_confidence_basis = _escape_cypher_string(r.get("confidence_basis", ""))
            try:
                info.engine.execute(
                    f"MATCH (a:KnowledgeNode {{name: '{from_n}'}}), "
                    f"(b:KnowledgeNode {{name: '{to_n}'}}) "
                    f"CREATE (a)-[:{rel_table} {{"
                    f"weight: {weight}, justification: '{just}', "
                    f"source: '{src}', domain: '{edge_domain}', "
                    f"directionality: '{edge_directionality}', "
                    f"confidence_basis: '{edge_confidence_basis}', "
                    f"created_at: '{ts}'"
                    f"}}]->(b);"
                )
                count += 1
            except Exception as e:
                errors.append(f"relations[{i}]: {e}")
        return count, errors

    # Atomic: both phases run inside one lock acquisition so concurrent
    # agents cannot observe nodes-without-relations.
    def _insert_all() -> tuple[int, int, list[str]]:
        n = _insert_nodes()
        r, errs = _insert_relations()
        return n, r, errs

    n_count, r_count, r_errors = await run_with_lock(info, _insert_all)

    parts = [
        f"Session: {info.session_id}",
        f"Nodes added: {n_count}",
        f"Relations added: {r_count}",
    ]
    out = " | ".join(parts)
    if r_errors:
        out += "\nRelation errors:\n  " + "\n  ".join(r_errors)
    if idempotency_key:
        mgr.store_idempotent_result(info.session_id, idempotency_key, out)
    return out


@size_guarded
async def graph_knowledge_infer(
    session_id: str | None = None,
    inference_type: str = "",
    max_depth: int = 5,
    min_nodes_override: int = 10,
) -> str:
    """Run inference-like analytical queries on a knowledge graph.

    Finds patterns, contradictions, gaps, and chains in the knowledge.

    Args:
        session_id: Session token from graph_create_session.
        inference_type: Type of inference to run:
            - "contradictions" — pairs connected by both supports AND contradicts
            - "gaps" — high-degree nodes with low avg edge confidence
            - "chains" — transitive support chains (A supports B, B supports C)
            - "clusters" — groups of tightly connected nodes
            - "convergence" — nodes supported by 2+ distinct domains
            - "weak_links" — assumed/analogical links lacking corroboration
            - "prediction_conflicts" — competing hypothesis/question nodes disagreeing on a target
        max_depth: For chains, bounds the transitive search depth (default 5,
            clamped to [2, 10]). Lower values terminate faster on large graphs;
            higher values find longer support chains.

    Returns:
        Inference results.
    """
    mgr, info = _require_graph_session(session_id)
    # Bound max_depth to prevent runaway transitive closure
    max_depth = max(2, min(max_depth, 10))
    try:
        stats = await run_with_lock(info, info.engine.get_statistics)
    except Exception:
        stats = {"rel_tables": {}}

    # Early-return if graph is too small to yield meaningful inference
    try:
        cols, rows = await run_with_lock(
            info,
            lambda: info.engine.execute("MATCH (n:KnowledgeNode) RETURN count(n) AS c;"),
        )
        node_count = int(rows[0][0]) if rows else 0
    except Exception:
        node_count = 0
    if node_count < min_nodes_override:
        return (
            f"Graph has {node_count} nodes. Minimum {min_nodes_override} "
            f"recommended for meaningful {inference_type}. Add more knowledge "
            "before inferring (use knowledge_batch for bulk-add)."
        )

    if inference_type == "contradictions":
        support_tables = [
            name
            for name in stats["rel_tables"]
            if any(token in name.lower() for token in ("support", "refine", "derive"))
        ] or ["Supports"]
        conflict_tables = [
            name
            for name in stats["rel_tables"]
            if any(token in name.lower() for token in ("contradict", "oppose", "prevent"))
        ] or ["Contradicts"]
        rows = []
        cols = ["from_node", "to_node", "support_relation", "conflict_relation"]
        for support_table in support_tables:
            for conflict_table in conflict_tables:
                cypher = (
                    f"MATCH (a:KnowledgeNode)-[:{support_table}]->(b:KnowledgeNode) "
                    f"MATCH (a)-[:{conflict_table}]->(b) "
                    f"RETURN a.name AS from_node, b.name AS to_node, "
                    f"'{support_table}' AS support_relation, "
                    f"'{conflict_table}' AS conflict_relation;"
                )
                try:
                    _, rel_rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
                    rows.extend(rel_rows)
                except Exception:
                    continue
        if not rows:
            return "No contradictions found — no nodes are both supported and contradicted."
        return format_result(cols, rows, mgr.max_rows, mgr.max_chars, "table")

    elif inference_type == "gaps":
        # Find nodes with many connections but low average confidence
        cypher = (
            "MATCH (n:KnowledgeNode)-[r]-() "
            "RETURN n.name, n.entity_type, n.confidence, count(r) AS degree "
            "ORDER BY n.confidence ASC, degree DESC LIMIT 20;"
        )
        try:
            cols, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
        except Exception:
            return "No knowledge nodes found."
        if not rows:
            return "No knowledge gaps detected."
        lines = ["## Knowledge Gaps (low confidence, high connectivity)"]
        for row in rows:
            conf = row[2] if row[2] is not None else 0
            if conf < 0.7:
                lines.append(f"  {row[0]} ({row[1]}): confidence={conf:.2f}, connections={row[3]}")
        if len(lines) == 1:
            return "No significant knowledge gaps — all nodes have confidence >= 0.7."
        return "\n".join(lines)

    elif inference_type == "chains":
        # Find transitive relation chains up to max_depth hops across all relation types
        cypher = (
            f"MATCH (a:KnowledgeNode)-[r*2..{max_depth}]->(b:KnowledgeNode) "
            "RETURN a.name AS chain_start, b.name AS chain_end "
            "LIMIT 20;"
        )
        try:
            cols, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
        except Exception:
            return "No relation chains found."
        if not rows:
            return "No transitive relation chains found."
        return format_result(cols, rows, mgr.max_rows, mgr.max_chars, "table")

    elif inference_type == "clusters":
        # Find clusters of tightly connected knowledge nodes
        cypher = (
            "MATCH (a:KnowledgeNode)-[r]-(b:KnowledgeNode) "
            "RETURN a.name, a.entity_type, "
            "collect(DISTINCT b.name) AS connected_to, count(r) AS edges "
            "ORDER BY edges DESC LIMIT 15;"
        )
        try:
            cols, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
        except Exception:
            return "No knowledge clusters found."
        if not rows:
            return "No clusters — knowledge nodes are not interconnected."
        return format_result(cols, rows, mgr.max_rows, mgr.max_chars, "table")

    elif inference_type == "convergence":
        cypher = (
            "MATCH (a:KnowledgeNode)-[r]->(b:KnowledgeNode) "
            "WHERE r.domain IS NOT NULL AND r.domain <> '' "
            "WITH b, count(DISTINCT r.domain) AS domains, "
            "collect(DISTINCT r.domain) AS domain_list "
            "WHERE domains >= 2 "
            "RETURN b.name AS target, domains, domain_list "
            "ORDER BY domains DESC LIMIT 20;"
        )
        try:
            cols, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
        except Exception:
            return "No convergence found."
        if not rows:
            return "No convergence found."
        return format_result(cols, rows, mgr.max_rows, mgr.max_chars, "table")

    elif inference_type == "weak_links":
        weak_rows: list[tuple] = []
        for rel_table in stats["rel_tables"]:
            cypher = (
                f"MATCH (a:KnowledgeNode)-[r:{rel_table}]->(b:KnowledgeNode) "
                "WHERE r.confidence_basis = 'assumed' OR r.confidence_basis = 'analogical' "
                f"RETURN a.name AS from_node, b.name AS to_node, '{rel_table}' AS relation, "
                "r.confidence_basis AS confidence_basis LIMIT 20;"
            )
            try:
                _, rows = await run_with_lock(info, lambda c=cypher: info.engine.execute(c))
                weak_rows.extend(rows)
            except Exception:
                continue
        if not weak_rows:
            return "No weak links found."
        return format_result(
            ["from_node", "to_node", "relation", "confidence_basis"],
            weak_rows[:20],
            mgr.max_rows,
            mgr.max_chars,
            "table",
        )

    elif inference_type == "prediction_conflicts":
        cypher = (
            "MATCH (a:KnowledgeNode)-[r1]->(target:KnowledgeNode)<-[r2]-(b:KnowledgeNode) "
            "WHERE a.name <> b.name "
            "AND (a.entity_type = 'question' OR a.entity_type = 'hypothesis') "
            "AND (b.entity_type = 'question' OR b.entity_type = 'hypothesis') "
            "AND type(r1) <> type(r2) "
            "RETURN a.name AS hypothesis_a, type(r1) AS relation_a, "
            "target.name AS target, b.name AS hypothesis_b, type(r2) AS relation_b "
            "LIMIT 20;"
        )
        try:
            cols, rows = await run_with_lock(info, lambda: info.engine.execute(cypher))
        except Exception:
            return "No prediction conflicts found."
        if not rows:
            return "No prediction conflicts found."
        return format_result(cols, rows, mgr.max_rows, mgr.max_chars, "table")

    else:
        return (
            f"Unknown inference_type: '{inference_type}'. "
            "Options: contradictions, gaps, chains, clusters, convergence, "
            "weak_links, prediction_conflicts"
        )


@size_guarded
async def graph_knowledge_summary(session_id: str | None = None) -> str:
    """Get a comprehensive knowledge graph summary in one call.

    Returns: entity counts by type, relationship counts by type,
    confidence distribution, top hubs, identified gaps and contradictions.
    This is the "total knowledge perspective" for the AI.

    Args:
        session_id: Session token from graph_create_session.

    Returns:
        Complete knowledge graph overview.
    """
    mgr, info = _require_graph_session(session_id)

    lines = ["## Knowledge Graph Summary"]

    # Entity counts by type
    try:
        cols, rows = await run_with_lock(
            info,
            lambda: info.engine.execute(
                "MATCH (n:KnowledgeNode) "
                "RETURN n.entity_type, count(n) AS cnt, "
                "avg(n.confidence) AS avg_conf "
                "ORDER BY cnt DESC;"
            ),
        )
        if rows:
            lines.append("\n### Entities by Type")
            total = 0
            for row in rows:
                conf = row[2] if row[2] is not None else 0
                lines.append(f"  {row[0]}: {row[1]} (avg confidence: {conf:.2f})")
                total += row[1]
            lines.append(f"  **Total: {total} entities**")
    except Exception:
        lines.append("\nNo KnowledgeNode table found. Use graph_knowledge_add first.")
        return "\n".join(lines)

    # Relationship counts
    stats = await run_with_lock(info, info.engine.get_statistics)
    rel_tables = {
        k: v
        for k, v in stats.get("rel_tables", {}).items()
        if k
        not in (
            "ParticipatesIn",
            "Regulates",
            "CompensatesFor",
            "DrivesProcess",
            "CellExpresses",
            "PathwayInteracts",
            "ProducesPhenotype",
        )
    }
    if rel_tables:
        lines.append("\n### Relationships")
        for name, count in rel_tables.items():
            lines.append(f"  {name}: {count}")

    # Confidence distribution
    try:
        cols, rows = await run_with_lock(
            info,
            lambda: info.engine.execute(
                "MATCH (n:KnowledgeNode) "
                "RETURN "
                "sum(CASE WHEN n.confidence >= 0.9 THEN 1 ELSE 0 END) AS high, "
                "sum(CASE WHEN n.confidence >= 0.5 AND n.confidence < 0.9 "
                "THEN 1 ELSE 0 END) AS medium, "
                "sum(CASE WHEN n.confidence < 0.5 THEN 1 ELSE 0 END) AS low;"
            ),
        )
        if rows and rows[0]:
            lines.append("\n### Confidence Distribution")
            lines.append(f"  High (>=0.9): {rows[0][0]}")
            lines.append(f"  Medium (0.5-0.9): {rows[0][1]}")
            lines.append(f"  Low (<0.5): {rows[0][2]}")
    except Exception:
        pass

    # Top hubs
    try:
        cols, rows = await run_with_lock(
            info,
            lambda: info.engine.execute(
                "MATCH (n:KnowledgeNode)-[r]-() "
                "RETURN n.name, n.entity_type, n.confidence, "
                "count(r) AS degree "
                "ORDER BY degree DESC LIMIT 5;"
            ),
        )
        if rows:
            lines.append("\n### Top Hubs")
            for row in rows:
                conf = row[2] if row[2] is not None else 0
                lines.append(f"  {row[0]} ({row[1]}): {row[3]} connections, confidence={conf:.2f}")
    except Exception:
        pass

    return "\n".join(lines)
