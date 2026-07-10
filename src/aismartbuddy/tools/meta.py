"""Meta tools for helping AI choose the right database."""

from __future__ import annotations

from aismartbuddy.engines.thinking_engine import ReasoningProgress, ThinkingEngine
from aismartbuddy.framework_catalog import framework_catalog
from aismartbuddy.tools import get_session_manager

# Weighted keyword sets for database recommendation
_GRAPH_INDICATORS = {
    "relationship": 3,
    "relationships": 3,
    "connected": 2,
    "network": 3,
    "hierarchy": 3,
    "hierarchical": 3,
    "path": 2,
    "shortest path": 4,
    "traversal": 3,
    "traverse": 3,
    "graph": 3,
    "link": 2,
    "links": 2,
    "node": 2,
    "nodes": 2,
    "edge": 2,
    "edges": 2,
    "social": 2,
    "dependency": 2,
    "dependencies": 2,
    "genealogy": 3,
    "recommendation": 2,
    "influence": 2,
    "reachable": 3,
    "neighbor": 2,
    "neighbors": 2,
    "community": 2,
    "cluster": 1,
    "tree": 2,
    "parent": 1,
    "child": 1,
    "ancestor": 2,
    "descendant": 2,
    "cypher": 3,
}

_SQL_INDICATORS = {
    "aggregate": 2,
    "aggregation": 2,
    "sum": 2,
    "count": 1,
    "average": 2,
    "tabular": 3,
    "time series": 3,
    "timeseries": 3,
    "filter": 1,
    "sort": 1,
    "join": 2,
    "pivot": 3,
    "window function": 3,
    "analytics": 3,
    "analytical": 3,
    "statistics": 2,
    "statistical": 2,
    "report": 2,
    "csv": 2,
    "sql": 3,
    "table": 1,
    "column": 1,
    "row": 1,
    "group by": 3,
    "order by": 2,
    "percentile": 2,
    "median": 2,
    "variance": 2,
    "correlation": 2,
    "regression": 2,
    "forecast": 2,
    "trend": 2,
    "metric": 2,
    "kpi": 2,
    "dashboard": 2,
    "parquet": 3,
    "olap": 3,
}


async def suggest_database(use_case: str) -> str:
    """Given a description of what you want to do with data,
    recommends whether to use SQL or Graph database and explains why.

    Use this when unsure whether to create a SQL session (DuckDB) or
    Graph session (LadybugDB/Cypher) for your data task.

    Examples:
    - "analyze sales trends over time" → SQL
    - "find shortest path between users in a social network" → Graph
    - "import CSV data and run aggregations" → SQL
    - "model entity relationships and traverse connections" → Graph

    Args:
        use_case: Description of what you want to accomplish with the data.

    Returns:
        Recommendation (SQL or Graph) with explanation and example queries.
    """
    text = use_case.lower()

    graph_score = 0
    sql_score = 0

    for keyword, weight in _GRAPH_INDICATORS.items():
        if keyword in text:
            graph_score += weight

    for keyword, weight in _SQL_INDICATORS.items():
        if keyword in text:
            sql_score += weight

    if graph_score > sql_score:
        return (
            f"Recommendation: **Graph database** (graph_create_session)\n\n"
            f"Why: Your use case involves {_top_matches(text, _GRAPH_INDICATORS)}, "
            f"which are naturally modeled as graph structures.\n\n"
            f"Graph databases excel at:\n"
            f"- Traversing relationships (friends-of-friends, supply chains)\n"
            f"- Finding shortest paths between entities\n"
            f"- Modeling hierarchies and networks\n"
            f"- Pattern matching across connected data\n\n"
            f"Example Cypher queries:\n"
            f"```\n"
            f"CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING);\n"
            f"CREATE REL TABLE Knows (FROM Person TO Person, since INT64);\n"
            f"MATCH (a:Person)-[:Knows]->(b:Person) RETURN a.name, b.name;\n"
            f"MATCH p = shortest_path((a:Person)-[:Knows*]->(b:Person))\n"
            f"  WHERE a.name = 'Alice' AND b.name = 'Bob' RETURN nodes(p);\n"
            f"```"
        )
    elif sql_score > graph_score:
        return (
            f"Recommendation: **SQL database** (sql_create_session)\n\n"
            f"Why: Your use case involves {_top_matches(text, _SQL_INDICATORS)}, "
            f"which are best handled with SQL analytics.\n\n"
            f"SQL databases excel at:\n"
            f"- Aggregations and analytics (SUM, AVG, COUNT, window functions)\n"
            f"- Filtering and sorting large datasets\n"
            f"- Joining tabular data from multiple sources\n"
            f"- Time-series analysis and trend detection\n"
            f"- Importing and querying CSV/JSON/Parquet files\n\n"
            f"Example SQL queries:\n"
            f"```sql\n"
            f"SELECT category, SUM(amount), AVG(amount)\n"
            f"FROM sales GROUP BY category ORDER BY SUM(amount) DESC;\n\n"
            f"SELECT *, LAG(value) OVER (ORDER BY date) AS prev_value\n"
            f"FROM metrics WHERE date >= '2024-01-01';\n"
            f"```"
        )
    else:
        return (
            "Both databases could work for this use case.\n\n"
            "**Use SQL** (sql_create_session) if your focus is:\n"
            "- Tabular data, aggregations, analytics, filtering/sorting\n\n"
            "**Use Graph** (graph_create_session) if your focus is:\n"
            "- Relationships between entities, paths, networks, hierarchies\n\n"
            "You can also create both and use each for what it does best."
        )


async def suggest_reasoning(
    task: str,
    session_id: str | None = None,
    intent: str = "auto",
    depth: str = "standard",
    constraints: list[str] | None = None,
    available_sources: list[str] | None = None,
) -> str:
    """Select and optionally store an ordered route through existing reasoning tools."""

    clean_constraints = [str(value).strip() for value in constraints or [] if str(value).strip()]
    clean_sources = [str(value).strip() for value in available_sources or [] if str(value).strip()]
    route = framework_catalog.recommend(task, intent=intent, depth=depth)

    stored_session = ""
    if session_id:
        info = get_session_manager().resolve_backend_session(session_id, "think")
        engine = info.engine
        if not isinstance(engine, ThinkingEngine):
            raise ValueError(f"Session '{session_id}' has no thinking backend")
        progress = ReasoningProgress(
            task=task.strip(),
            intent=route.intent,
            depth=route.depth,
            frameworks=list(route.frameworks),
            steps=[
                {"phase": step.phase, "tool": step.tool, "purpose": step.purpose}
                for step in route.steps
            ],
            constraints=clean_constraints,
            available_sources=clean_sources,
        )
        engine.set_reasoning_progress(progress)
        stored_session = session_id

    lines = [
        f"Intent: {route.intent} | Depth: {route.depth} | Confidence: {route.confidence:.2f}",
        f"Entry tool: {route.steps[0].tool}",
        f"Expected calls: {len(route.steps)}",
        f"Frameworks: {', '.join(route.frameworks) or '(none)'}",
        f"Why: {route.rationale}",
        "",
        "Route:",
    ]
    for index, step in enumerate(route.steps, start=1):
        lines.append(f"{index}. [{step.phase}] {step.tool} — {step.purpose}")
    lines.extend(["", "Completion gates:"])
    lines.extend(f"- {criterion}" for criterion in route.completion_criteria)
    if route.alternatives:
        lines.extend(["", f"Alternatives: {', '.join(route.alternatives)}"])
    if clean_constraints:
        lines.append(f"Constraints retained: {len(clean_constraints)}")
    if clean_sources:
        lines.append(f"Available sources retained: {len(clean_sources)}")
    if stored_session:
        lines.append(
            f"Stored in session: {stored_session} | next_tool: {route.steps[0].tool}"
        )
    return "\n".join(lines)


def _top_matches(text: str, indicators: dict[str, int]) -> str:
    """Return top matching keywords for explanation."""
    matches = [(kw, w) for kw, w in indicators.items() if kw in text]
    matches.sort(key=lambda x: x[1], reverse=True)
    top = [kw for kw, _ in matches[:3]]
    if not top:
        return "patterns consistent with this database type"
    return ", ".join(top)
