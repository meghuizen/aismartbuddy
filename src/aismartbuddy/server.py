"""FastMCP server assembly — tool, prompt, and resource registration."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from mcp.server.fastmcp import FastMCP

from aismartbuddy import config as cfg
from aismartbuddy.config import SERVER_NAME
from aismartbuddy.session import SessionManager

logger = logging.getLogger("aismartbuddy.server")


async def _periodic_cleanup(interval: int = 300) -> None:
    """Background task that cleans up expired sessions and cursors every `interval` seconds."""
    from aismartbuddy import session as session_mod

    while True:
        await anyio.sleep(interval)
        try:
            if session_mod.session_manager is not None:
                count = await anyio.to_thread.run_sync(
                    session_mod.session_manager.cleanup_expired
                )
                if count > 0:
                    logger.info("Periodic cleanup removed %d expired sessions", count)
        except Exception:
            logger.exception("Error in periodic cleanup")


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize SessionManager + YouTubeClient, start background cleanup,
    shutdown cleanly."""
    from aismartbuddy import session as session_mod
    from aismartbuddy import youtube_client as yt_mod

    rc = cfg.runtime_config
    session_mod.session_manager = SessionManager(
        temp_base_dir=rc.temp_dir,
        session_timeout=rc.session_timeout,
        cursor_timeout=rc.cursor_timeout,
        max_rows=rc.max_rows,
        max_chars=rc.max_chars,
        duckdb_threads=rc.duckdb_threads,
        duckdb_memory_limit=rc.duckdb_memory_limit,
        ladybug_buffer_pool_size=rc.ladybug_buffer_pool_size,
        ladybug_max_threads=rc.ladybug_max_threads,
    )
    logger.info("SessionManager initialized")

    # Best-effort YouTube client init — failure does not block server startup.
    # The get_youtube_information tool checks `if youtube_client is None` at
    # call-time and raises a clear error if init didn't succeed.
    try:
        yt_mod.youtube_client = yt_mod.YouTubeClient.create()
    except Exception:
        logger.exception(
            "YouTubeClient init failed; get_youtube_information will be unavailable"
        )
        yt_mod.youtube_client = None

    async with anyio.create_task_group() as tg:
        tg.start_soon(_periodic_cleanup)
        try:
            yield
        finally:
            tg.cancel_scope.cancel()

    session_mod.session_manager.cleanup_all()
    if yt_mod.youtube_client is not None:
        yt_mod.youtube_client.close()
        yt_mod.youtube_client = None
    logger.info("Server shutdown complete")


# Create the FastMCP server instance
mcp = FastMCP(SERVER_NAME, lifespan=app_lifespan)


# ──────────────────────────────────────────────
# Tool registration
# ──────────────────────────────────────────────

from aismartbuddy.tools.graph import (  # noqa: E402
    graph_analyze,
    graph_compare,
    graph_create_session,
    graph_cross_reference,
    graph_destroy_session,
    graph_find_connections,
    graph_import,
    graph_knowledge_add,
    graph_knowledge_infer,
    graph_knowledge_relate,
    graph_knowledge_summary,
    graph_neighbors,
    graph_query,
    graph_query_next,
    graph_schema,
    graph_statistics,
)
from aismartbuddy.tools.holon import (  # noqa: E402
    holon_analyze,
    holon_create,
    holon_query,
    holon_update,
    holon_view,
)
from aismartbuddy.tools.meta import suggest_database  # noqa: E402
from aismartbuddy.tools.score import (  # noqa: E402
    score_evaluate,
    score_gate,
    score_rubric,
)
from aismartbuddy.tools.sql import (  # noqa: E402
    sql_create_session,
    sql_destroy_session,
    sql_import,
    sql_import_batch,
    sql_query,
    sql_query_next,
    sql_schema,
)
from aismartbuddy.tools.think import (  # noqa: E402
    think_argue,
    think_collaborate,
    think_create_session,
    think_debug,
    think_decide,
    think_destroy_session,
    think_graph,
    think_graph_delegate,
    think_graph_validate,
    think_interfere,
    think_interfere_state,
    think_model,
    think_monitor,
    think_science,
    think_summarize,
    think_visualize,
)
from aismartbuddy.tools.youtube import get_youtube_information  # noqa: E402

# Annotation presets
_DEFAULT = {
    "readOnlyHint": False, "destructiveHint": False,
    "idempotentHint": False, "openWorldHint": False,
}
_READONLY = {
    "readOnlyHint": True, "destructiveHint": False,
    "idempotentHint": True, "openWorldHint": False,
}
# For read-only tools that interact with EXTERNAL services (network calls).
# Per MCP spec, openWorldHint=True signals to hosts that the tool may
# produce side-effects beyond the local server (rate limiting, IP exposure).
_READONLY_OPEN = {
    "readOnlyHint": True, "destructiveHint": False,
    "idempotentHint": True, "openWorldHint": True,
}
_DESTRUCTIVE = {
    "readOnlyHint": False, "destructiveHint": True,
    "idempotentHint": False, "openWorldHint": False,
}

# (function, name, title, annotations)
_TOOLS: list[tuple] = [
    (sql_create_session, "sql_create_session", "Create SQL Session", _DEFAULT),
    (sql_query, "sql_query", "Execute SQL Query", _DEFAULT),
    (sql_query_next, "sql_query_next", "Next Page of SQL Results", _READONLY),
    (sql_import, "sql_import", "Import Data into SQL Table", _DEFAULT),
    (sql_import_batch, "sql_import_batch", "Import Multiple Data Chunks into SQL Table", _DEFAULT),
    (sql_schema, "sql_schema", "Get SQL Database Schema", _READONLY),
    (sql_destroy_session, "sql_destroy_session", "Destroy SQL Session", _DESTRUCTIVE),
    (graph_create_session, "graph_create_session", "Create Graph Session", _DEFAULT),
    (graph_query, "graph_query", "Execute Cypher Query", _DEFAULT),
    (graph_query_next, "graph_query_next", "Next Page of Graph Results", _READONLY),
    (graph_import, "graph_import", "Import Data into Graph", _DEFAULT),
    (graph_schema, "graph_schema", "Get Graph Database Schema", _READONLY),
    (graph_destroy_session, "graph_destroy_session", "Destroy Graph Session", _DESTRUCTIVE),
    (graph_statistics, "graph_statistics", "Graph Overview and Statistics", _READONLY),
    (graph_neighbors, "graph_neighbors", "Explore Node Neighborhood", _READONLY),
    (graph_find_connections, "graph_find_connections", "Find Paths Between Nodes", _READONLY),
    (graph_analyze, "graph_analyze", "Run Graph Analytics", _READONLY),
    (graph_compare, "graph_compare", "Compare Two Graphs", _READONLY),
    (graph_cross_reference, "graph_cross_reference", "Cross-Reference Graph Nodes", _READONLY),
    (graph_knowledge_add, "graph_knowledge_add", "Add Knowledge Entity", _DEFAULT),
    (graph_knowledge_relate, "graph_knowledge_relate", "Add Knowledge Relationship", _DEFAULT),
    (graph_knowledge_infer, "graph_knowledge_infer", "Run Knowledge Inference", _READONLY),
    (graph_knowledge_summary, "graph_knowledge_summary", "Knowledge Graph Summary", _READONLY),
    (suggest_database, "suggest_database", "Suggest SQL or Graph Database", _READONLY),
    (
        get_youtube_information,
        "get_youtube_information",
        "Get YouTube Video Information",
        _READONLY_OPEN,
    ),
    # Thinking tools (Layer 1 — ephemeral, in-memory)
    (think_create_session, "think_create_session", "Create Thinking Session", _DEFAULT),
    (think_graph, "think_graph", "Thought Graph", _DEFAULT),
    (think_graph_validate, "think_graph_validate", "Validate Thought Graph", _DEFAULT),
    (think_graph_delegate, "think_graph_delegate", "Delegate Thought Subtree", _DEFAULT),
    (think_decide, "think_decide", "Structured Decision Analysis", _DEFAULT),
    (think_model, "think_model", "Apply Mental Model", _DEFAULT),
    (think_debug, "think_debug", "Systematic Debugging Approach", _DEFAULT),
    (think_argue, "think_argue", "Structured Argumentation", _DEFAULT),
    (think_collaborate, "think_collaborate", "Collaborative Reasoning", _DEFAULT),
    (think_science, "think_science", "Scientific Method Inquiry", _DEFAULT),
    (think_monitor, "think_monitor", "Metacognitive Monitoring", _DEFAULT),
    (think_visualize, "think_visualize", "Visual Reasoning", _DEFAULT),
    (think_summarize, "think_summarize", "Thinking Session Summary", _READONLY),
    (think_destroy_session, "think_destroy_session", "Destroy Thinking Session", _DESTRUCTIVE),
    # Interference Protocol (structured novelty generation)
    (think_interfere, "think_interfere", "Interference Protocol", _DEFAULT),
    (think_interfere_state, "think_interfere_state", "Interference Protocol State", _READONLY),
    # Holonic workspace (multi-level domain modeling)
    (holon_create, "holon_create", "Create Holon", _DEFAULT),
    (holon_update, "holon_update", "Update Holon", _DEFAULT),
    (holon_view, "holon_view", "Navigate Holarchy", _READONLY),
    (holon_analyze, "holon_analyze", "Analyze Holarchy", _DEFAULT),
    (holon_query, "holon_query", "Query Holarchy", _READONLY),
    # Scoring (mechanical evaluation with rubrics)
    (score_rubric, "score_rubric", "Scoring Rubric", _DEFAULT),
    (score_evaluate, "score_evaluate", "Evaluate with Score", _DEFAULT),
    (score_gate, "score_gate", "Scoring Gate Check", _READONLY),
]

for func, name, title, annot in _TOOLS:
    mcp.tool(name=name, annotations={"title": title, **annot})(func)


# ──────────────────────────────────────────────
# Prompt registration
# ──────────────────────────────────────────────


@mcp.prompt("aismartbuddy-guide")
async def aismartbuddy_guide() -> str:
    """Overview of AISmartBuddy capabilities — SQL, Graph, and Thinking tools."""
    return """\
You have access to AISmartBuddy, which provides SQL, Graph, and Thinking tools.

## SQL Sessions (DuckDB)
Best for: tabular data, analytics, aggregations, joins,
window functions, time-series, CSV/JSON/Parquet import.
- Create: sql_create_session → get session_id
- Query: sql_query(session_id, "SELECT ...") → CSV results
- Import: sql_import(session_id, table_name, csv_data) → auto-creates table
- Schema: sql_schema(session_id) → list tables and columns
- Cleanup: sql_destroy_session(session_id)

## Graph Sessions (LadybugDB/Cypher)
Best for: relationships, networks, hierarchies, path finding,
connected data, pattern matching.

### Core Tools
- Create: graph_create_session → get session_id
- Query: graph_query(session_id, "MATCH ...") → table results
- Import: graph_import(session_id, table, csv, schema=...) → nodes/rels
- Schema: graph_schema(session_id) → graph structure
- Cleanup: graph_destroy_session(session_id)

### Analytics Tools
- graph_statistics(session_id) → full graph overview in one call
- graph_neighbors(session_id, name, type, depth) → N-hop neighborhood
- graph_find_connections(session_id, from, type, to, type) → all paths
- graph_analyze(session_id, "hubs"|"orphans"|"categories"|"cross_connections")

### Comparison Tools (cross-reference two graphs)
- graph_compare(session_a, session_b, "structure"|"nodes"|"properties")
- graph_cross_reference(session_a, session_b, "Gene", "name") → CSV diff

IMPORTANT: Always CREATE NODE TABLE before creating nodes.

## Choosing Between SQL and Graph
Use suggest_database("your use case") for a recommendation.
- Tabular + analytics → SQL
- Relationships + traversal → Graph
- You can use both in the same conversation.

## YouTube
Single-call tool to ingest a YouTube video's metadata and transcript.
- get_youtube_information(url_or_id, language="en") →
    title + description + available transcript languages + timed transcript
- Accepts: raw 11-char video ID, watch?v=, youtu.be/, embed/, shorts/ URLs
- Optional: include_transcript=False (metadata only),
    include_timestamps=False (plain text, no [MM:SS] prefix)
- Cached as XML at OS temp dir; subsequent calls with same video+language
    return instantly
- Caching policy: ONLY full success is cached. Partial/degraded responses
    (transcript disabled, language not available, video processing,
    rate-limited) include an actionable error block under `## Transcript`
    with a stable category code, upstream message, and a hint — and are
    NOT cached, so a future call will re-attempt.
- For long videos: write the response to a file via your filesystem tool
    before processing, to avoid burning context on the inline transcript.

## Thinking Sessions (Structured Reasoning)
In-memory sessions for structured AI reasoning. Auto-created on first tool call.

### Thought Graph (progressive complexity)
- think_graph(thought="...") → new root node (simple sequential start)
- think_graph(thought="...", parent_id="<prev>") → chain thoughts sequentially
- think_graph(thought="...", action="branch", parent_id="...") → decompose into sub-problems
- think_graph(thought="...", action="synthesize", parent_id="...") → combine children's findings
- think_graph(thought="...", action="revise", node_id="...") → update with history
- think_graph_validate(session_id, target_id, check_type, result, details) → structural validation
- think_graph_delegate(session_id, node_id, action="package") → delegate to subagent
- think_graph_delegate(session_id, node_id, action="receive", result="...") → receive results

### Other Thinking Tools
- think_decide(decision_statement, options, analysis_type, stage, ...) → multi-criteria decisions
- think_model(model_name, problem) → 13 models: first_principles, assumptions_xray,
    fishbone, value_of_info, swot, pre_mortem, design_review, complexity, root_cause, ...
- think_debug(approach_name, issue) → debugging approaches (binary_search, divide_conquer, etc.)
- think_argue(claim, premises, conclusion, argument_type, ...) → dialectical reasoning
- think_collaborate(topic, personas, contributions, stage, ...) → multi-perspective analysis
- think_science(stage, inquiry_id, iteration, ...) → scientific method
- think_monitor(task, stage, overall_confidence, ...) → metacognitive self-monitoring
- think_visualize(operation, diagram_id, diagram_type, ...) → visual reasoning

### Interference Protocol (Structured Novelty Generation)
- think_interfere(action="set_domain", target_domain="...") → start protocol
- think_interfere(action="add_source", protocol_id, source_domain, law, isomorphism)
- think_interfere(action="add_fragment", protocol_id, fragment)
- think_interfere(action="crystallize", protocol_id, name, properties)
- think_interfere(action="stress_test", protocol_id, audit_type, audit_result)
- think_interfere_state(session_id, protocol_id) → full state query

### Utility
- think_summarize(session_id) → token-optimized summary of all thinking
- think_destroy_session(session_id) → free memory

Sessions auto-create: omit session_id on first call, pass returned ID to subsequent calls.

### Socratic Method (think_graph pattern)
Use think_graph to do Socratic inquiry on any claim:
  1. think_graph(thought="Claim: ...", action="branch") -> root
  2. think_graph(thought="CLARIFICATION: What do we mean?", parent_id=root)
  3. think_graph(thought="ASSUMPTIONS: What must be true?", parent_id=root)
  4. think_graph(thought="EVIDENCE: What supports/contradicts?", parent_id=root)
  5. think_graph(thought="PERSPECTIVES: Other viewpoints?", parent_id=root)
  6. think_graph(thought="IMPLICATIONS: What follows?", parent_id=root)
  7. think_graph(thought="Synthesis", action="synthesize", parent_id=root)

## Holonic Workspace (Multi-Level Domain Modeling)
Model domains where entities are simultaneously wholes and parts.
Holons can participate in multiple holarchies simultaneously.

- holon_create(name, description, parent_id) → create holon in holarchy
- holon_update(holon_id, action="join_holarchy", holarchy_id, parent_id) → multi-membership
- holon_view(holon_id, action="zoom_in") → descend with parent context preserved
- holon_view(holon_id, action="zoom_out") → ascend with synthesis prompt
- holon_view(holon_id, action="memberships") → see all holarchies
- holon_analyze(action="bridge", from_id, to_id) → find path between distant holons
- holon_analyze(action="coherence", holon_a_id, holon_b_id) → coherence check
- holon_analyze(action="propagate_up", holon_id, insight) → cascade insight upward
- holon_analyze(action="feedback_loops", holarchy_id) → detect bidirectional causal loops
- holon_analyze(action="leverage_points") → find structurally important holons
- holon_query(question, vantage_id, resolution) → perspectival context assembly

## Scoring (Mechanical Evaluation)
Separate AI judgment from scoring. AI submits findings; server computes scores.
- score_rubric(action="create", rubric_id, dimensions, ...) → define scoring framework
- score_rubric(action="list") → show rubrics
- score_evaluate(action="start", rubric_id, context) → begin evaluation
- score_evaluate(action="finding", evaluation_id, dimension, severity, ...) → submit finding
- score_evaluate(action="finalize", evaluation_id, summary) → close + verdict
- score_gate(action="gate", evaluation_id) → pass/fail check (for hooks)
- score_gate(action="list", rubric_id) → evaluation history

## When to Use Each Tool (Methodology)

### Before designing:
- think_model(assumptions_xray) on key claims you're about to build on
- holon_create to model the domain at multiple levels

### Before finalizing a design:
- think_model(pre_mortem): "Assume this failed — what went wrong?"
- think_model(design_review): "What breaks this? State machine gaps?"
- think_model(complexity): "Is this over-engineered?"

### Before implementing:
- score_rubric + score_evaluate to define quality criteria upfront
- think_graph with depends_on for task ordering

### During investigation:
- holon_analyze(bridge) to find causal chains between distant concepts
- holon_analyze(coherence) to check if two findings are consistent
- think_model(fishbone) to categorize causes you might be missing

### After implementation:
- score_evaluate(finding) for each issue found during review
- score_gate to check pass/fail programmatically

### Cross-referencing:
All tools accept refs: list[str] to link outputs across tools.
Example: a scoring finding can reference a thought graph node ID.

## Token Efficiency
SQL results default to CSV format (2-3x fewer tokens than JSON).
Thinking tools use compact text output (~60% fewer tokens than JSON).
Always destroy sessions when done to free resources."""


@mcp.prompt("sql-guide")
async def sql_guide() -> str:
    """DuckDB SQL syntax reference and import patterns."""
    return """## DuckDB SQL Reference

### Create Tables
CREATE TABLE users (id INTEGER, name VARCHAR, age INTEGER, created DATE);

### Insert Data
INSERT INTO users VALUES (1, 'Alice', 30, '2024-01-15');

### Query Patterns
-- Aggregation
SELECT department, COUNT(*), AVG(salary) FROM employees GROUP BY department;

-- Window Functions
SELECT name, salary, RANK() OVER (ORDER BY salary DESC) FROM employees;

-- CTEs
WITH top_sales AS (SELECT * FROM sales WHERE amount > 1000)
SELECT region, SUM(amount) FROM top_sales GROUP BY region;

-- Date Functions
SELECT date_trunc('month', order_date), SUM(total) FROM orders GROUP BY 1;

### Import via sql_import (6 formats supported)
sql_import supports: csv, tsv, txt, json, jsonl, parquet
- CSV (default): auto-detects headers, types, delimiters
- TSV: tab-delimited, same auto-detection
- TXT: generic delimited, specify delimiter="|" or ";"
- JSON: array of objects [{"col": "val"}, ...]
- JSONL: one JSON object per line
- Parquet: base64-encoded binary data

### Multi-chunk import
sql_import_batch(session_id, "table", [chunk1, chunk2, ...])
First chunk creates the table, rest append rows.

### Custom delimiters
sql_import(session_id, "t", data, data_format="txt", delimiter="|")"""


@mcp.prompt("graph-guide")
async def graph_guide() -> str:
    """LadybugDB Cypher syntax reference — schema-first graph database."""
    return """\
## LadybugDB Cypher Reference

CRITICAL: You MUST create tables BEFORE creating data!

### Schema Creation (always first!)
CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING);
CREATE REL TABLE Follows (FROM Person TO Person, since INT64);

### Create and Query Nodes
CREATE (p:Person {id: 1, name: 'Alice'});
MATCH (a:Person)-[:Follows]->(b:Person) RETURN a.name, b.name;

### Path Finding
-- Shortest path
MATCH p = shortest_path((a:Person)-[:Follows*]->(b:Person))
WHERE a.name = 'Alice' AND b.name = 'Bob'
RETURN nodes(p), rels(p);
-- All paths up to depth 5
MATCH p = (a:Person)-[:Follows*1..5]->(b:Person)
WHERE a.name = 'Alice' RETURN [n IN nodes(p) | n.name];
-- Or use: graph_find_connections(session, "Alice", "Person", "Bob", "Person")

### Aggregation
MATCH (p:Person)-[:LivesIn]->(c:City)
RETURN c.name, count(p) AS pop ORDER BY pop DESC;

### Analytical Patterns
-- Find orphan nodes (no relationships)
MATCH (n:Person) WHERE NOT EXISTS { MATCH (n)-[]-() }
RETURN n.name;
-- Variable-length traversal (1 to 5 hops)
MATCH (start:Gene)-[:Regulates*1..5]->(end:Gene)
RETURN DISTINCT end.name;
-- Cross-type pattern matching
MATCH (g:Gene)-[:ParticipatesIn]->(p:Pathway)
WHERE g.direction = 'elevated' AND p.status = 'suppressed'
RETURN g.name, p.name;
-- Grouping with CASE
MATCH (g:Gene) RETURN g.system,
  sum(CASE WHEN g.direction='elevated' THEN 1 ELSE 0 END) AS up,
  sum(CASE WHEN g.direction='reduced' THEN 1 ELSE 0 END) AS down;

### Quick Analytics (use these tools instead of raw Cypher)
- graph_statistics(session_id) → full overview in 1 call
- graph_neighbors(session_id, "IL6", "Gene", depth=2) → neighborhood
- graph_find_connections(session_id, "AVP", "Gene", "IL6", "Gene")
- graph_analyze(session_id, "hubs") → most connected nodes
- graph_analyze(session_id, "orphans") → disconnected nodes
- graph_analyze(session_id, "categories") → property breakdown

### Key Differences from Neo4j
- Schema required before data (CREATE NODE TABLE first!)
- COPY FROM instead of LOAD CSV
- Semicolons required
- 1-based string indexing (not 0-based)
- No MERGE with ON CREATE/ON MATCH"""


@mcp.prompt("knowledge-guide")
async def knowledge_guide() -> str:
    """How to build and query knowledge graphs."""
    return """\
## Knowledge Graph Guide

Knowledge graph tools layer semantic patterns on top of the graph database.
They enforce confidence scores, provenance, and semantic relationship types.

### Adding Knowledge Entities
graph_knowledge_add(session_id, "Mitochondrial Dysfunction",
  entity_type="concept", confidence=0.9, source="paper_xyz")

Entity types: concept, entity, fact, evidence, question, insight

### Adding Relationships
graph_knowledge_relate(session_id, "IL-6", "Inflammation",
  relation="causes", weight=0.95,
  justification="IL-6 is primary driver of systemic inflammation")

Relation types: supports, contradicts, refines, causes, prevents,
requires, part_of, similar_to, derived_from

### Running Inference
graph_knowledge_infer(session_id, "contradictions")
  → finds nodes connected by both supports AND contradicts
graph_knowledge_infer(session_id, "gaps")
  → finds uncertain hubs (high degree, low confidence)
graph_knowledge_infer(session_id, "chains")
  → finds transitive support chains (A→B→C)
graph_knowledge_infer(session_id, "clusters")
  → groups of tightly connected knowledge

### Full Summary
graph_knowledge_summary(session_id)
  → complete overview: entities by type, confidence distribution,
    top hubs, relationships by type

### Mixing with Raw Cypher
Knowledge tools create standard KnowledgeNode tables and typed
relationship tables. You can query them with graph_query too:
graph_query(session_id,
  "MATCH (n:KnowledgeNode) WHERE n.confidence < 0.5 RETURN n.name;")
"""


@mcp.prompt("import-guide")
async def import_guide() -> str:
    """How to import data into SQL and Graph databases."""
    return """\
## Data Import Guide

### SQL — Supported Formats (6 total)
| Format | data_format | Description |
|--------|-------------|-------------|
| CSV | "csv" | Comma-separated (default). Auto-detects headers & types |
| TSV | "tsv" | Tab-separated. Same auto-detection |
| TXT | "txt" | Custom delimiter — set delimiter="|" or ";" |
| JSON | "json" | Array of objects: [{"col": "val"}, ...] |
| JSONL | "jsonl" | One JSON object per line |
| Parquet | "parquet" | Base64-encoded binary Parquet data |

### SQL — Single Import
sql_import(session_id, "sales",
  "date,product,amount\\n2024-01-01,Widget,100",
  data_format="csv")

### SQL — Custom Delimiter (pipe-separated)
sql_import(session_id, "data",
  "id|name|value\\n1|Alice|100",
  data_format="txt", delimiter="|")

### SQL — JSON Import
sql_import(session_id, "users",
  '[{"name":"Alice","age":30},{"name":"Bob","age":25}]',
  data_format="json")

### SQL — Multi-Chunk Batch Import
sql_import_batch(session_id, "logs", [
  "ts,level,msg\\n2024-01-01,INFO,started",
  "ts,level,msg\\n2024-01-02,WARN,slow query"
], data_format="csv")

### Graph — Node Import
graph_import(session_id, "Person",
  "id,name,age\\n1,Alice,30\\n2,Bob,25",
  table_type="node",
  schema="id INT64 PRIMARY KEY, name STRING, age INT64")

### Graph — Relationship Import
graph_import(session_id, "Follows",
  "from,to,since\\n1,2,2024",
  table_type="relationship", schema="since INT64",
  from_table="Person", to_table="Person")

### Tips
- CSV is the most token-efficient format for bulk tabular data
- Use sql_import_batch when data is split across sources
- For large datasets, import CSV instead of many INSERT statements
- Parquet is best for preserving exact types (numeric precision, dates)"""


# ──────────────────────────────────────────────
# Resource registration
# ──────────────────────────────────────────────


def _format_session_list(sessions, scope_label: str) -> str:
    """Shared formatter for session-listing resources."""
    if not sessions:
        return f"No active sessions in {scope_label}."
    lines = [f"Active sessions ({scope_label}):"]
    for s in sessions:
        lines.append(
            f"  {s.session_id} | {s.session_type} | "
            f"user={s.user_id} project={s.project_id} | "
            f"created {s.created_at.strftime('%H:%M:%S')}"
        )
    return "\n".join(lines)


@mcp.resource("aismartbuddy://sessions/{user_id}/{project_id}")
async def list_project_sessions(user_id: str, project_id: str) -> str:
    """List active sessions for a specific (user_id, project_id).

    Scoped resource — only sessions owned by that identity tuple are returned.
    Invalid user_id/project_id returns an error message (no data leak).
    """
    from aismartbuddy.identity import validate_identity
    from aismartbuddy.session import session_manager

    if session_manager is None:
        return "Server not initialized"

    try:
        validate_identity(user_id, "user_id")
        validate_identity(project_id, "project_id")
    except ValueError:
        # Don't echo the attempted value — avoid aiding probing
        return "Error: invalid user_id or project_id format"

    sessions = session_manager.list_sessions(user_id=user_id, project_id=project_id)
    return _format_session_list(sessions, f"user={user_id} project={project_id}")


@mcp.resource("aismartbuddy://sessions")
async def list_my_sessions() -> str:
    """List sessions owned by the authenticated caller.

    Requires Bearer authentication — without ctx.client_id, returns a helpful
    error (NOT a data dump). For unauthenticated scenarios, use the scoped
    template `aismartbuddy://sessions/{user_id}/{project_id}` instead.
    """
    # FastMCP doesn't auto-inject ctx into resource handlers at this SDK version,
    # so we can't read ctx.client_id here without a broader API change.
    # Return a helpful hint instead of leaking all sessions.
    return (
        "To list your sessions, use the scoped resource "
        "aismartbuddy://sessions/{user_id}/{project_id}. "
        "The unscoped resource is disabled to prevent cross-tenant enumeration."
    )
