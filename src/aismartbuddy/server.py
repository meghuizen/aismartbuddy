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
                count = await anyio.to_thread.run_sync(session_mod.session_manager.cleanup_expired)
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
        logger.exception("YouTubeClient init failed; get_youtube_information will be unavailable")
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


def _maybe_build_entra_auth() -> tuple[object | None, object | None]:
    """Return (token_verifier, AuthSettings) when Entra OAuth is configured.

    Activated only when BOTH `entra_tenant_id` and `entra_audience` are
    set in RuntimeConfig (via CLI flags or AISMARTBUDDY_ENTRA_* env vars).
    Lazy-imports `aismartbuddy.auth` so users without the [entra] optional
    dep group only hit ImportError when they actually try to enable OAuth
    — and the error explains how to fix it.
    """
    rc = cfg.runtime_config
    if not rc.entra_tenant_id and not rc.entra_audience:
        return None, None  # OAuth disabled — normal startup
    if not (rc.entra_tenant_id and rc.entra_audience):
        logger.warning(
            "Partial Entra OAuth config — both AISMARTBUDDY_ENTRA_TENANT "
            "and AISMARTBUDDY_ENTRA_AUDIENCE must be set. Running without "
            "auth."
        )
        return None, None

    try:
        from mcp.server.auth.settings import AuthSettings

        from aismartbuddy.auth import EntraTokenVerifier
    except ImportError as exc:
        logger.error(
            "Entra OAuth requested but the [entra] dependency group is not "
            "installed. Reinstall with: `uv pip install aismartbuddy[entra]` "
            "or `uv sync --extra entra`. Underlying error: %s",
            exc,
        )
        # Fail closed — server starts but no tools are reachable since
        # auth was requested but couldn't be wired.
        raise SystemExit(1) from exc

    verifier = EntraTokenVerifier(
        tenant_id=rc.entra_tenant_id,
        audience=rc.entra_audience,
        required_scope=rc.entra_required_scope,
    )
    auth_settings = AuthSettings(
        issuer_url=verifier.issuer,
        resource_server_url=(rc.entra_resource_server_url or f"http://{rc.host}:{rc.port}"),
        required_scopes=([rc.entra_required_scope] if rc.entra_required_scope else []),
    )
    logger.info(
        "Entra OAuth enabled: tenant=%s audience=%s required_scope=%s",
        rc.entra_tenant_id,
        rc.entra_audience,
        rc.entra_required_scope or "(none)",
    )
    return verifier, auth_settings


# Create the FastMCP server instance, optionally with Entra OAuth wired in.
_token_verifier, _auth_settings = _maybe_build_entra_auth()
_mcp_kwargs: dict[str, object] = {"lifespan": app_lifespan}
if _token_verifier is not None:
    _mcp_kwargs["token_verifier"] = _token_verifier
    _mcp_kwargs["auth"] = _auth_settings
mcp = FastMCP(SERVER_NAME, **_mcp_kwargs)


# ──────────────────────────────────────────────
# Tool registration
# ──────────────────────────────────────────────

from aismartbuddy.tools.brainstorm import brainstorm  # noqa: E402
from aismartbuddy.tools.graph import (  # noqa: E402
    graph_analyze,
    graph_compare,
    graph_create_session,
    graph_cross_reference,
    graph_destroy_session,
    graph_find_connections,
    graph_focus_summary,
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
    knowledge_batch,
)
from aismartbuddy.tools.holon import (  # noqa: E402
    holon_analyze,
    holon_create,
    holon_query,
    holon_update,
    holon_view,
)
from aismartbuddy.tools.infra import (  # noqa: E402
    session_create,
    session_destroy,
)
from aismartbuddy.tools.iterate import iterate  # noqa: E402
from aismartbuddy.tools.meta import suggest_database  # noqa: E402
from aismartbuddy.tools.reasoning_v2 import (  # noqa: E402
    argue,
    compare_models,
    extract_findings_from_graph,
    extract_findings_from_sql,
    hypothesize,
    mine_patterns,
    model_system,
    reason_get,
    reason_graph,
    reason_index,
    reason_refs,
    reason_trace,
    scaffold,
    self_assess,
    session_export,
    session_resume,
    synthesize_conclusion,
    test_interventions,
    workflow_validate,
)
from aismartbuddy.tools.refs import think_refs_query  # noqa: E402
from aismartbuddy.tools.score import (  # noqa: E402
    rubric_templates,
    score_evaluate,
    score_gate,
    score_rubric,
)
from aismartbuddy.tools.sql import (  # noqa: E402
    data_anomalies,
    data_profile,
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
    think_bridge,
    think_constraint,
    think_create_session,
    think_debug,
    think_decide,
    think_destroy_session,
    think_evidence,
    think_export_session,
    think_get_path,
    think_get_session_links,
    think_get_subtree,
    think_graph,
    think_graph_delegate,
    think_graph_validate,
    think_hypothesis,
    think_interfere,
    think_interfere_state,
    think_link_sessions,
    think_model,
    think_monitor,
    think_rules,
    think_science,
    think_set_active_session,
    think_summarize,
    think_topology,
    think_validate,
)
from aismartbuddy.tools.youtube import get_youtube_information  # noqa: E402

# Annotation presets
_DEFAULT = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}
_READONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
# For read-only tools that interact with EXTERNAL services (network calls).
# Per MCP spec, openWorldHint=True signals to hosts that the tool may
# produce side-effects beyond the local server (rate limiting, IP exposure).
_READONLY_OPEN = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_DESTRUCTIVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}


# (function, name, title, annotations)
def _build_tool_specs(expose_legacy_reasoning_tools: bool | None = None) -> list[tuple]:
    expose_legacy = (
        cfg.runtime_config.expose_legacy_reasoning_tools
        if expose_legacy_reasoning_tools is None
        else expose_legacy_reasoning_tools
    )
    tools: list[tuple] = [
        (sql_create_session, "sql_create_session", "Create SQL Session", _DEFAULT),
        (sql_query, "sql_query", "Execute SQL Query", _DEFAULT),
        (sql_query_next, "sql_query_next", "Next Page of SQL Results", _READONLY),
        (sql_import, "sql_import", "Import Data into SQL Table", _DEFAULT),
        (
            sql_import_batch,
            "sql_import_batch",
            "Import Multiple Data Chunks into SQL Table",
            _DEFAULT,
        ),
        (sql_schema, "sql_schema", "Get SQL Database Schema", _READONLY),
        (data_profile, "data_profile", "Statistical Data Profile (EXPLORE)", _READONLY),
        (data_anomalies, "data_anomalies", "Detect Statistical Anomalies (EXPLORE)", _READONLY),
        (sql_destroy_session, "sql_destroy_session", "Destroy SQL Session", _DESTRUCTIVE),
        (graph_create_session, "graph_create_session", "Create Graph Session", _DEFAULT),
        (graph_query, "graph_query", "Execute Cypher Query", _DEFAULT),
        (graph_query_next, "graph_query_next", "Next Page of Graph Results", _READONLY),
        (graph_import, "graph_import", "Import Data into Graph", _DEFAULT),
        (graph_schema, "graph_schema", "Get Graph Database Schema", _READONLY),
        (graph_destroy_session, "graph_destroy_session", "Destroy Graph Session", _DESTRUCTIVE),
        (graph_statistics, "graph_statistics", "Graph Overview and Statistics", _READONLY),
        (graph_neighbors, "graph_neighbors", "Explore Node Neighborhood", _READONLY),
        (
            graph_focus_summary,
            "graph_focus_summary",
            "Summarize Multiple Graph Neighborhoods",
            _READONLY,
        ),
        (graph_find_connections, "graph_find_connections", "Find Paths Between Nodes", _READONLY),
        (graph_analyze, "graph_analyze", "Run Graph Analytics", _READONLY),
        (graph_compare, "graph_compare", "Compare Two Graphs", _READONLY),
        (graph_cross_reference, "graph_cross_reference", "Cross-Reference Graph Nodes", _READONLY),
        (graph_knowledge_add, "graph_knowledge_add", "Add Knowledge Entity", _DEFAULT),
        (graph_knowledge_relate, "graph_knowledge_relate", "Add Knowledge Relationship", _DEFAULT),
        (knowledge_batch, "knowledge_batch", "Bulk Add Knowledge Nodes and Relations", _DEFAULT),
        (graph_knowledge_infer, "graph_knowledge_infer", "Run Knowledge Inference", _READONLY),
        (graph_knowledge_summary, "graph_knowledge_summary", "Knowledge Graph Summary", _READONLY),
        (suggest_database, "suggest_database", "Suggest SQL or Graph Database", _READONLY),
        (session_create, "session_create", "Create Unified Multi-Backend Session", _DEFAULT),
        (session_destroy, "session_destroy", "Destroy Unified Session", _DESTRUCTIVE),
        (
            get_youtube_information,
            "get_youtube_information",
            "Get YouTube Video Information",
            _READONLY_OPEN,
        ),
        (think_create_session, "think_create_session", "Create Thinking Session", _DEFAULT),
        (think_destroy_session, "think_destroy_session", "Destroy Thinking Session", _DESTRUCTIVE),
        (think_graph, "think_graph", "Thought Graph", _DEFAULT),
        (think_graph_delegate, "think_graph_delegate", "Thought Graph Delegation", _DEFAULT),
        (think_graph_validate, "think_graph_validate", "Validate Thought Graph Node", _DEFAULT),
        (think_get_subtree, "think_get_subtree", "Get Thought Subtree", _READONLY),
        (think_get_path, "think_get_path", "Get Thought Path", _READONLY),
        (think_export_session, "think_export_session", "Export Thought Session", _READONLY),
        (think_set_active_session, "think_set_active_session", "Set Active Session", _DEFAULT),
        (think_link_sessions, "think_link_sessions", "Link Sessions", _DEFAULT),
        (think_get_session_links, "think_get_session_links", "Get Session Links", _READONLY),
        (think_decide, "think_decide", "Decision Framework", _DEFAULT),
        (think_model, "think_model", "Mental Model Analysis", _DEFAULT),
        (think_hypothesis, "think_hypothesis", "Competing Hypotheses", _DEFAULT),
        (think_constraint, "think_constraint", "Constraint Registry", _DEFAULT),
        (think_topology, "think_topology", "Domain-Neutral Topology", _DEFAULT),
        (think_evidence, "think_evidence", "Evidence Provenance Chains", _DEFAULT),
        (think_bridge, "think_bridge", "Cross-System Thinking Bridge", _READONLY),
        (think_rules, "think_rules", "Manage Weighted Rule Profiles", _DEFAULT),
        (think_validate, "think_validate", "Validate Against Rule Profiles", _DEFAULT),
        (think_debug, "think_debug", "Systematic Debugging", _DEFAULT),
        (think_argue, "think_argue", "Structured Argumentation", _DEFAULT),
        (think_science, "think_science", "Scientific Method Inquiry", _DEFAULT),
        (think_monitor, "think_monitor", "Knowledge Boundary Assessment", _DEFAULT),
        (think_summarize, "think_summarize", "Summarize Thinking Session", _READONLY),
        (think_interfere, "think_interfere", "Interference Protocol", _DEFAULT),
        (think_interfere_state, "think_interfere_state", "Interference Protocol State", _READONLY),
        (think_refs_query, "think_refs_query", "Find Cross-References by Entity ID", _READONLY),
        (brainstorm, "brainstorm", "Brainstorm (DIVERGE)", _DEFAULT),
        (iterate, "iterate", "Iterate (ITERATE)", _DEFAULT),
        (
            extract_findings_from_sql,
            "extract_findings_from_sql",
            "Extract Findings From SQL",
            _DEFAULT,
        ),
        (
            extract_findings_from_graph,
            "extract_findings_from_graph",
            "Extract Findings From Graph",
            _DEFAULT,
        ),
        (holon_create, "holon_create", "Create Holon", _DEFAULT),
        (holon_update, "holon_update", "Update Holon", _DEFAULT),
        (holon_view, "holon_view", "Navigate Holarchy", _READONLY),
        (holon_analyze, "holon_analyze", "Analyze Holarchy", _DEFAULT),
        (holon_query, "holon_query", "Query Holarchy", _READONLY),
        (score_rubric, "score_rubric", "Scoring Rubric", _DEFAULT),
        (score_evaluate, "score_evaluate", "Evaluate with Score", _DEFAULT),
        (score_gate, "score_gate", "Scoring Gate Check", _READONLY),
        (rubric_templates, "rubric_templates", "List/Load Pre-built Rubrics", _DEFAULT),
    ]
    if expose_legacy:
        tools.extend(
            [
                (scaffold, "scaffold", "Scaffold Structured Analysis", _DEFAULT),
                (hypothesize, "hypothesize", "Generate Structured Hypotheses", _DEFAULT),
                (argue, "argue", "Structured Argument Chain", _DEFAULT),
                (self_assess, "self_assess", "Knowledge Boundary Assessment", _DEFAULT),
                (reason_graph, "reason_graph", "Reason Graph", _DEFAULT),
                (model_system, "model_system", "Model Multi-Scale System", _DEFAULT),
                (mine_patterns, "mine_patterns", "Mine Structured Patterns", _DEFAULT),
                (test_interventions, "test_interventions", "Test Interventions", _DEFAULT),
                (compare_models, "compare_models", "Compare Models", _DEFAULT),
                (reason_trace, "reason_trace", "Grounded Reason Trace", _DEFAULT),
                (
                    synthesize_conclusion,
                    "synthesize_conclusion",
                    "Synthesize Grounded Conclusion",
                    _DEFAULT,
                ),
                (reason_index, "reason_index", "Reason Artifact Index", _READONLY),
                (reason_get, "reason_get", "Get Reason Artifact", _READONLY),
                (reason_refs, "reason_refs", "Find Reason References", _READONLY),
                (
                    session_resume,
                    "session_resume",
                    "Resume Structured Reasoning Session",
                    _READONLY,
                ),
                (
                    session_export,
                    "session_export",
                    "Export Structured Reasoning Session",
                    _READONLY,
                ),
                (workflow_validate, "workflow_validate", "Validate Workflow Coverage", _READONLY),
            ]
        )
    return tools


_TOOLS = _build_tool_specs()

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
- graph_focus_summary(session_id, [name1, name2], type, depth) → batch neighborhood summary
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

## Structured Thinking
Primary surface for analysis:
- think_create_session(project_id="analysis") → standalone think session
- session_create(backends=["think","graph","sql"], mode="analyze") → parent session
- think_set_active_session(session_id) → make one session implicit for later think/sql/graph calls
- think_model(items=[...]) → structured scaffold with a named mental model
- Batch rule: each items[] entry is one semantic unit. Use batch mode to
  submit several atomic thoughts/problems/hypotheses at once, not to hide a
  long multi-part essay inside one entry.
- think_rules(...) → create weighted hard/soft rule profiles and bind them to plans
- think_validate(...) → validate a thought/model/decision/holon/evaluation against bound rules
- think_science(items=[...]) → observation/question/hypothesis/experiment chain
- think_decide(items=[...]) → explicit options/criteria/recommendation
- think_graph(...) → concise thought graph nodes; branch instead of writing essays
- think_argue(chain=[...]) → thesis/antithesis/synthesis chains
- think_monitor(items=[...]) → last-step calibration of claims and limitations
- score_evaluate(..., use_bound_profiles=true) → carry rule validation into scoring finalization
- think_interfere(...) → structured novelty generation via interference protocol
- think_refs_query(entity_id, session_id) → find records that cite an entity id
- think_summarize(session_id) → token-optimized summary of the session

Migration map for older reasoning concepts:
- scaffold → think_model
- hypothesize → think_science
- self_assess → think_monitor
- reason_graph → think_graph
- extract_findings_from_sql / extract_findings_from_graph stay public as bridge tools

Recommended analysis flow for assay-heavy domains:
- sql_import / sql_import_batch using one of the supported table formats
- data_profile / data_anomalies before narrative reasoning
- extract_findings_from_sql for reusable, addressable findings
- think_model(items=[...]) to separate measured signal from inferred mechanism
- think_science(items=[...]) to force competing explanations and falsification tests
- think_monitor(items=[...]) to record tissue/assay/confounder limits before conclusions

Metadata conventions for think_graph and related tools:
- metadata.knowledge_refs → knowledge graph entity names
- metadata.hypothesis_refs → think_hypothesis ids
- metadata.constraint_refs → think_constraint ids
- metadata.evidence_refs → think_evidence ids
- metadata.topology_refs → think_topology ids
- metadata.claim_type → fact | inference | speculation | assumption
- metadata.domain → domain label

Cross-system tools:
- think_hypothesis(...) → competing hypothesis registry with ranking
- think_constraint(...) → hard/soft constraint registry and validations
- think_topology(...) → abstract structural topology and analog search support
- think_evidence(...) → provenance chains and evidence strength
- think_bridge(...) → "show me everything related to X" across subsystems
- think_get_subtree / think_get_path / think_export_session → resumable read-back
- think_link_sessions / think_get_session_links → cross-session project structure

Useful orchestration patterns:
- Analogical reasoning:
  think_topology.abstract -> think_interfere -> think_hypothesis -> think_constraint
- Constraint sweep:
  think_constraint.list -> think_hypothesis.compare ->
  think_constraint.validate -> think_hypothesis.invalidate
- Abductive ranking:
  think_hypothesis.compare -> think_evidence.chain/strength -> think_hypothesis.discriminate
- System decomposition:
  holon_create -> holon_analyze(feedback_loops/leverage_points) -> think_topology.abstract
- Design review:
  think_model(design_review) -> think_model(pre_mortem) -> think_model(assumptions_xray)
- Root cause analysis:
  think_model(root_cause) -> think_hypothesis.register -> think_constraint.check_all
- KUBA adoption analysis:
  think_model(model_name="kuba") -> think_graph branch per stage ->
  think_argue thesis/antithesis/synthesis
- Agile feature decomposition:
  think_model(kuba) -> think_graph(feature/story branches) -> score_evaluate with agile rubrics

Recommended persona archetypes for cross-domain review:
- Domain Specialist -> deep local expertise, risk of domain lock-in
- Domain Alien -> foreign-domain structural reasoning, risk of over-abstraction
- Constraint Auditor -> hard-limit checking, risk of over-pruning novel ideas
- Epistemologist -> evidence/inference hygiene, risk of over-caution
- Synthesis Integrator -> convergence across views, risk of shallow technical detail
- Even without a dedicated think_collaborate tool, these persona templates can
  guide delegated passes, dialectical review, or branch-by-branch analysis.

Rubric guidance:
- rubric_templates are defaults, not contracts
- adapt dimensions, weights, and thresholds to the actual problem
- add missing dimensions when the template does not capture the real risk
- security-critical or high-stakes work usually needs custom weighting
- useful templates include discovery_value, code_quality, agile_feature,
  agile_user_story, agile_task, research_hypothesis, plus the omics templates

### Explore / Diverge / Iterate
- data_profile(session_id, table) → profile tabular data first
- data_anomalies(session_id, table, columns, method) → anomaly scan
- brainstorm(topic, ideas=[...]) → divergence without convergence
- iterate(action=...) → build-test-learn attempts with optional metrics
- think_debug(items=[...]) → structured debugging loops

### Retrieval
- reason_index(session_id, ...) → list stored artifacts
- reason_get(session_id, artifact_id) → fetch one artifact with links
- reason_refs(session_id, artifact_id) → inbound references
- session_resume(session_id) → compact operational context
- workflow_validate(session_id) → coverage / sequencing check

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
- score_evaluate(action="start", session_id, rubric_id, context) → begin evaluation
- score_evaluate(action="start_with_rubric", session_id, rubric_id, dimensions, context)
  → create rubric + start in one call
- score_evaluate(action="finding", evaluation_id, dimension, severity, ...)
  → submit one scored finding
- score_evaluate(action="batch_findings", evaluation_id, findings=[...])
  → sequential batch scoring in one call
- score_evaluate(action="review", evaluation_id)
  → current score, coverage, recent findings, open dimensions
- score_evaluate(action="note", evaluation_id, dimension, severity, description)
  → lightweight finding stub
- score_evaluate(action="finalize", evaluation_id, summary) → close + verdict
- score_gate(action="gate", evaluation_id) → pass/fail check (for hooks)
- score_gate(action="list", session_id, rubric_id) → evaluation history

## When to Use Each Tool (Methodology)

### Before designing:
- think_model(model_name="assumptions_xray", items=[...]) on key claims
- holon_create to model the domain at multiple levels

### Before finalizing a design:
- think_model(model_name="pre_mortem", items=[...])
- think_model(model_name="design_review", items=[...])
- think_model(model_name="complexity", items=[...])

### Before implementing:
- score_rubric + score_evaluate to define quality criteria upfront
- think_graph for concise task ordering and dependencies

### During investigation:
- holon_analyze(bridge) to find causal chains between distant concepts
- holon_analyze(coherence) to check if two findings are consistent
- think_model(model_name="fishbone", items=[...]) to categorize causes

### After implementation:
- score_evaluate(finding) for each issue found during review
- score_gate to check pass/fail programmatically

### Cross-referencing:
All reasoning tools accept refs/connects_to so artifacts stay linked.
Example: a thought can reference a scaffold item id,
then think_refs_query can retrieve the backlinks.
Scoring actions also accept analysis_refs so findings can cite think_* or extracted-finding ids.

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
- Reusable input shapes:
  - entity-score table: entity,score,direction,panel,source
  - differential table: feature,log2fc,pvalue,padj
  - ranked list: entity,rank,metric,source
  - wide matrix: feature,sample_a,sample_b,...

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
- graph_focus_summary(session_id, ["IL6", "TNF"], "Gene", depth=2) → batch focus summary
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
- Parquet is best for preserving exact types (numeric precision, dates)
- Preferred workflow:
  import → data_profile → data_anomalies → extract_findings_from_sql
  → think_model / think_science"""


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
