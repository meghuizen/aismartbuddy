# AISmartBuddy MCP Server — Target Architecture Implementation Plan

## Verbatim Requirements

### Original Request

> use clear-thought and map each item on the todo list and process this sequential and come up with the comprehensive plan but also validate it to the philosophy of the mcp server

The user provided an extensive target architecture document (≈800 lines) specifying 31 numbered items across 6 phases plus philosophy principles, tool taxonomy, mode selection heuristics, and a framework coverage matrix. Verbatim preserved in section "Target Architecture Document Reference" at the bottom of this plan.

### Clarifications

**Q1 — Scope/Timeline (31 items, ~4000 LoC estimate).**
**A:** "All 6 phases deep."

**Q2 — Breaking renames (think_model→scaffold, think_science→hypothesize, merge think_visualize/think_graph_validate).**
**A:** "dont rename, this about process version which tools to use, find proper names, but make sure you don't make the mistakes of conflicting the 2."

→ Interpretation: new tools (scaffold, hypothesize, self_assess) are NET-NEW and COEXIST with the existing think_model / think_science / think_monitor. They serve different roles (strict entry-point forcing functions vs. flexible mid-analysis logging). No renames. No removals. No field-requirement upgrades on existing tools.

**Q3 — score_evaluate finding_batch (forcing-function tension).**
**A:** "Implement with warning." Output explicitly notes single-submission loses incremental self-assessment discipline.

**Q4 — Phase 6 (Event Bus + Memory Palace).**
**A:** "both are not needed at all for now. no need to mention either."

→ Phase 6 DROPPED entirely from plan. Items 30-31 omitted.

---

## TLDR

Transform AISmartBuddy from 49 tools to ~64 tools by adding 15 new capabilities (batch operations, strict forcing-function entry points, new thinking modes, infrastructure) while preserving every existing tool unchanged. All changes additive — no renames, no removals, no breaking changes. Implementation sequenced in 5 phases (Phase 0 through Phase 5) with Phase 0 (performance hardening) and Phase 1 (batch operations) delivering the largest round-trip savings. The target architecture's philosophy (forcing-functions-first, batch-without-losing-structure, bridge-don't-unify, ceremony-costs-tokens) is validated against each item with explicit pass/fail tracking.

---

## Context

### Why this change is being made

Empirical observation from a recent ~67-call analytical session showed 48% of calls were either ceremony (logging reasoning already complete), structural analysis on data too small to yield insights, or navigation duplicating information already held. One call (holon_view cross_level with 11 holons) timed out on response serialization. The current server design treats every structured-thinking tool as a single-unit call, which makes complex analyses verbose and slow. The target architecture introduces batch operations, strict forcing-function entry points for deep analysis, additional thinking modes (EXPLORE, DIVERGE, ITERATE), and session-level bridges between backends — intended to cut typical complex-analysis tool-call count from ~67 to ~11+N while preserving the distinct value of each tool category.

### What prompted it

1. Confirmed timeout on `holon_view(cross_level)` (fixed in commit 105d763 during this working session)
2. User-authored target architecture document specifying six thinking modes, SCAFFOLD→ELABORATE→ASSESS workflow, batch APIs, and temporal knowledge graphs
3. 48% ceremony rate observed in structured analytical workflows

### Intended outcome

A server that supports both formal structured analysis (scaffold, hypothesize, self_assess, iterate-with-metrics, temporal KG) and lightweight recording (preserved think_model, think_science, think_monitor, think_collaborate, think_visualize). AI selects tools by thinking mode, not by "which version." Batch operations eliminate 40-60% of round trips. Unified sessions with multiple backends eliminate cross-backend friction while preserving engine isolation.

---

## Current State Inventory (source of truth)

Data gathered via Explore agents over `src/aismartbuddy/` and `tests/`. File:line references are authoritative.

### Tool count: 49 (matches architecture document)

| File | Count | Tools |
|------|-------|-------|
| `tools/sql.py` | 7 | sql_create_session, sql_query, sql_query_next, sql_import, sql_import_batch, sql_schema, sql_destroy_session |
| `tools/graph.py` | 16 | graph_create_session, graph_query, graph_query_next, graph_import, graph_schema, graph_destroy_session, graph_statistics, graph_neighbors, graph_find_connections, graph_analyze, graph_compare, graph_cross_reference, graph_knowledge_add, graph_knowledge_relate, graph_knowledge_infer, graph_knowledge_summary |
| `tools/think.py` | 16 | think_create_session, think_graph, think_graph_validate, think_graph_delegate, think_decide, think_model, think_debug, think_argue, think_collaborate, think_science, think_monitor, think_visualize, think_summarize, think_destroy_session, think_interfere, think_interfere_state |
| `tools/holon.py` | 5 | holon_create, holon_update, holon_view, holon_analyze, holon_query |
| `tools/score.py` | 3 | score_rubric, score_evaluate, score_gate |
| `tools/meta.py` | 1 | suggest_database |
| `tools/youtube.py` | 1 | get_youtube_information |

Registration site: `server.py:236-295` (`_TOOLS` list). Annotation presets (`_DEFAULT`, `_READONLY`, `_READONLY_OPEN`, `_DESTRUCTIVE`) at `server.py:215-233` — distribution is 27/18/1/3.

Note: Five graph tools (`graph_neighbors`, `graph_find_connections`, `graph_analyze`, `graph_compare`, `graph_cross_reference`) exist alongside the `graph_knowledge_*` family — all counted in the 16-tool graph.py total. Four private helpers in `tools/graph.py` (`_analyze_orphans`, `_analyze_hubs`, `_analyze_categories`, `_analyze_cross_connections`) are NOT tools and not counted.

### Session model

- Three session types (`sql`, `graph`, `think`) each bound to `(user_id, project_id)` via `identity.resolve_identity()` (priority: ctx.client_id → param → config default → "default"). 128-bit session_id entropy.
- SessionManager singleton at `session.py:64-360`. Per-session `threading.Lock`. Pop-then-lock destroy protocol (`session.py:241-260`).
- Temp layout: `{base}/aismartbuddy/{user_id}/{project_id}/{session_id}/` with backend-specific files (`data.duckdb`, `graph.lbug`, none for think).
- Auto-create only for think sessions (via `_get_or_create_think_session` at `tools/think.py:157`); sql/graph require explicit create.

### BaseEngine contract

Abstract at `engines/__init__.py:21-189`:
- `connect()`, `execute(query)`, `execute_arrow(query)`, `execute_paged(query, page_size)`, `fetch_next_page(cursor_id)`, `cleanup_expired_cursors(timeout)`, `close_all_cursors()`, `close()`
- Cursor tracking: thread-safe `dict[cursor_id → (iterator, last_accessed)]`

DuckDBEngine + LadybugEngine extend BaseEngine. ThinkingEngine is a separate class (not BaseEngine subclass) with mutation API (`add_node`, `add_model`, `add_argument`, etc.) plus `@_synchronized` RLock decorator on mutation methods.

### Existing batch operations

Only `sql_import_batch` exists (`tools/sql.py:188-228` + `engines/duckdb_engine.py::import_batch`). All other batch APIs proposed in this plan are net-new.

### Current truncation knobs

- `SessionManager.max_rows=1000`, `max_chars=50000` — table output caps applied in `formatting.py:19-54`
- `graph.py:347` path-finding `max_depth = min(max_depth, 8)`
- `holon.py` — hard-coded `[:40]`, `[:60]`, `[:80]` slices on display fields
- `tools/__init__.py:66` — `effective_limit` for query pagination
- Shipped this session: `_MAX_CROSS_DESC=20`, `_MAX_ZOOM_CHILDREN=20`, `_MAX_SIDEWAYS_SIBLINGS=20`, `_MAX_FEEDBACK_PAIRS=50`

### RuntimeConfig (18 fields)

At `config.py:25-61`: `temp_dir`, `max_rows`, `max_chars`, `session_timeout`, `cursor_timeout`, `host`, `port`, `transport`, `default_user_id`, `default_project_id`, `duckdb_threads`, `duckdb_memory_limit`, `ladybug_buffer_pool_size`, `ladybug_max_threads`, `entra_tenant_id`, `entra_audience`, `entra_required_scope`, `entra_resource_server_url`. Module singleton at `config.py:61`.

### Test infrastructure

- 13 test files + `conftest.py`, ~278 tests
- Direct function calls (no MCP client). Tools invoked as `await tool_fn(...)`.
- Pattern: session_manager fixture + module-level singleton injection (`session_mod.session_manager = session_manager`).
- `_extract_field(result, prefix)` helper in `tests/test_think_tools.py:267`; the equivalent helper in `tests/test_holon_tools.py:22` is simply named `_extract`. New test files should pick one or define their own to avoid import ambiguity.
- **Coverage gaps**: zero tests for all `graph_knowledge_*` tools; zero tool-level tests for SQL and Graph wrapper tools (only engine-level tests).

---

## Guiding Principles

These derive from the target architecture document, section 4.1, and govern every design decision in this plan.

| # | Principle | Operational Rule |
|---|---|---|
| 1 | **Forcing functions first** | New entry-point tools DEMAND structured fields (required `limitations`, required `falsifiability ≥ 20 chars`, required `steps`/`reasoning`/`conclusion`). Server-side validation rejects lazy submissions. |
| 2 | **Batch without losing structure** | Batch APIs preserve per-item schema validation. `scaffold(items=[7 pathways])` enforces the same per-item constraints as `scaffold(items=[1 pathway])`. |
| 3 | **Bridge, don't unify** | Engines remain isolated (DuckDB ≠ LadybugDB ≠ ThinkingEngine). Unified sessions are a **facade** over child sessions. Data movement between backends requires an explicit `bridge` call. |
| 4 | **Ceremony costs tokens** | No new ceremony tools. Existing ceremony tools (think_collaborate, think_visualize, think_graph_validate) are preserved unchanged (per user instruction) but NOT promoted; description text nudges toward higher-value alternatives. |
| 5 | **Token-optimized output** | All new tools emit compact pipe-delimited text or CSV. Long-form content truncated to display caps (`[:60]`, `[:40]`) matching existing patterns. |
| 6 | **Session isolation** | Multi-backend sessions route per-tool to isolated backend sessions. Per-session locking preserved. Temp directory hierarchy preserved. |

### The dual-family rule (user-directed)

Two parallel tool families will coexist with DIFFERENT roles. The AI selects based on analytical context, not by "new vs old":

| Strict Forcing-Function Family | Role | Flexible Logging Family | Role |
|---|---|---|---|
| `scaffold` | Entry point: decomposition with mandatory steps/reasoning/conclusion per item | `think_model` | Mid-analysis: apply a named model with flexible fields |
| `hypothesize` | Entry point: falsifiable hypothesis generation (≥20 char falsifiability required) | `think_science` | Record progression through scientific method stages |
| `self_assess` | Entry point: one-shot knowledge calibration (non-empty limitations required) | `think_monitor` | Ongoing metacognitive monitoring across iterations |

**Non-conflict rule**: the two families must be documented as orthogonal in purpose, not as "v1/v2." Tool descriptions will use phrases like "Use scaffold at analysis START to force decomposition rigor" vs. "Use think_model mid-analysis to log the application of a named model." Tests verify both families coexist (shared fixtures, no conflicting session state).

---

## Scope & Non-Goals

### In scope (this plan)

Phase 0 through Phase 5 — all items 1 through 29 from the target architecture document.

### Out of scope

- **Phase 6 entirely** — Event Bus and Memory Palace. Not needed per user direction.
- **Renames** — think_model/think_science/think_monitor are preserved unchanged.
- **Removals** — think_collaborate, think_visualize, think_graph_validate are preserved. Descriptions may be tweaked to nudge usage.
- **Field requirement upgrades on existing tools** — existing tools keep their current optional fields. Strict variants are new tools.
- **New engines** — DuckDB, LadybugDB, ThinkingEngine all stay. No Postgres, no DynamoDB, no vector store.
- **Multi-agent real subagent calls** — `think_collaborate` stays simulated; no orchestration.
- **Description length optimization** — the target doc's §8 target of <6000 tokens across all descriptions is noted but not enforced in this plan (measurable follow-up).

---

## PHASE 0 — Performance Fixes

Prerequisite for all later phases. P0 already shipped in commit 105d763 during this working session.

### P0 — Fix holon_view(cross_level) timeout ✅ DONE

**Status**: Complete (commit 105d763, this session).
- Capped descendants at 20 with overflow hint
- Truncated `role` to 40 chars in `_holon_summary_line`
- Applied cap pattern to zoom_in, sideways (same session, follow-up)

No further work required for P0.

### P1 — Configurable display truncation

**Goal**: Remove hard-coded `[:40]`, `[:60]`, `[:80]` slices in `tools/holon.py`. Route through `RuntimeConfig`.

**Files to modify**:
- `src/aismartbuddy/config.py` — add `holon_display_truncate_chars: int = 60`, `holon_display_truncate_long: int = 80`
- `src/aismartbuddy/tools/holon.py` — replace hard-coded slices at lines 113, 120, 323, 341, 365, 470, 509, 543, 569, 571, 604, 617, 622, 851, 893, 989, 992, 1104, 1105, 1240, 1271, 1290 with `cfg.runtime_config.holon_display_truncate_chars` (or `_long` for 80-char slices)
- `src/aismartbuddy/__main__.py` — add CLI flags `--holon-truncate-chars`, `--holon-truncate-long` (envvar fallbacks)

**Acceptance**: Tests continue passing. New test `test_holon_display_truncate_configurable` overrides `runtime_config.holon_display_truncate_chars = 30` and asserts `_holon_summary_line` respects the override.

**Non-goal**: Per-call parameter on every holon tool. That's API bloat. Single config source.

### P2 — Computation depth limits

#### P2a — `max_depth` on `graph_knowledge_infer(chains)`

**Files**:
- `src/aismartbuddy/tools/graph.py::graph_knowledge_infer` — add `max_depth: int = 5` parameter, pass to engine
- `src/aismartbuddy/engines/ladybug_engine.py` — in `infer_chains` method, bound recursive Cypher with `*1..{max_depth}` range

**Acceptance**: `graph_knowledge_infer(session_id, inference_type="chains", max_depth=3)` returns paths of length ≤3.

#### P2b — `timeout_ms` on `graph_query`

**Files**:
- `src/aismartbuddy/tools/graph.py::graph_query` — add `timeout_ms: int = 10000` parameter
- Wrap `anyio.to_thread.run_sync(...)` call in `anyio.fail_after(timeout_ms / 1000)` — on timeout, return error string "Query timed out after {timeout_ms}ms. Consider adding LIMIT clause or scoping via WHERE."

**Acceptance**: Simulated long-running Cypher (e.g., cartesian of 10k×10k test data) terminates within timeout + returns graceful error.

#### P2c — `max_pairs` on `holon_analyze(feedback_loops)` ✅ DONE

**Status**: Complete (commit 105d763, this session). `_MAX_FEEDBACK_PAIRS = 50` in `holon.py`. Output includes truncation hint.

#### P2d — `max_items_per_category` on `think_summarize`

**Files**:
- `src/aismartbuddy/tools/think.py::think_summarize` — add `max_items_per_category: int = 20` parameter; iterate ThinkingEngine collections (nodes, decisions, models, debugs, arguments, sciences, monitors, visualizes, interferes) truncating each at the cap

**Acceptance**: Session with 100 ThoughtNodes returns at most 20 in the summary with "... (80 more)" footer.

### P3 — Single-call batching (reframed from "parallelism")

**Reframe**: The original item specified "server-side parallelism for batch operations." However, DuckDB connections are single-threaded, LadybugDB's concurrency model is per-connection, and ThinkingEngine uses an RLock. Genuine parallelism is blocked by engine constraints. The latency savings come from eliminating MCP transport round-trips, not from concurrent execution.

**Revised goal**: Phase 1 batch APIs execute sequentially within a single tool call, under one engine lock acquisition. The user-visible benefit is N→1 round trips, not N→1 wall-clock time.

Implementation is Phase 1. No separate work required for P3.

### P4 — Response size monitoring

**Goal**: Detect tools that return unexpectedly large payloads (prevents future cross_level-style timeouts) and auto-truncate above 500KB.

**Files**:
- `src/aismartbuddy/tools/__init__.py` — add `size_guarded(fn)` decorator. Wraps async tool function; measures `len(result.encode("utf-8"))`. If > 50KB: log warning. If > 200KB: log error. If > 500KB: return truncated prefix + "`\n\n[Response truncated at 500KB. Use pagination or more specific query.]`"
- Apply decorator to: every tool returning variable-length data (all SQL query tools, graph query tools, holon_view, holon_query, holon_analyze, think_summarize, graph_knowledge_summary, graph_statistics, session_export, session_snapshot[list])

**Acceptance**: Test that fabricates a 1MB response asserts truncation message present and size ≤500KB.

**Metric**: Add `response_size_bytes` field to each tool's observability log entry (requires logging infrastructure — use `logger.debug` per tool call).

---

## PHASE 1 — Batch Operations (Items 5-10)

Highest-ROI phase: empirical 40-60% round-trip reduction on complex workflows.

### Item 5 — `children` parameter on `think_graph`

**Files**:
- `src/aismartbuddy/tools/think.py::think_graph` — add parameters:
  - `children: list[dict] | None = None` — each child: `{thought: str, metadata: dict | None}`
  - `expected_children: int | None = None` — planning horizon; on action=synthesize, emit warning if actual child count ≠ expected
- `src/aismartbuddy/engines/thinking_engine.py::ThinkingEngine` — add helper `add_node_with_children(parent_thought, parent_meta, children) → (parent_id, child_ids)` under `@_synchronized`

**Semantics**:
- If `children` is provided: create parent node first, then iterate creating each child with `parent_id = parent.id`. All under one RLock acquisition. Returns parent_id + child_ids[].
- If `children` is None: current behavior preserved.
- If `action="synthesize"` and `expected_children` set: look up actual children, append "WARNING: expected {N} children, found {M}" to output.

**Return format** (new lines appended when batched):
```
Session: {sid} | Node: {parent_id} | Action: branch | Batch: {N} children
Children: {child_id_1}, {child_id_2}, ...
```

**Test**: `test_think_graph_children_batch` — asserts 1 parent + 3 children created from single call, all with same `parent_id`, independently addressable by `revise` action.

### Item 6 — `holons` batch parameter on `holon_create`

**Files**:
- `src/aismartbuddy/tools/holon.py::holon_create` — add parameters:
  - `holons: list[dict] | None = None` — each item: `{ref: str, name: str, description: str, parent_ref: str | None, role_in_parent: str, context: str, rules: list[str], properties: list[str], projection: str}`
- `src/aismartbuddy/engines/thinking_engine.py::ThinkingEngine` — add helper `add_holons_batch(items) → dict[ref, holon_id]` under `@_synchronized`

**Semantics**:
- Topological sort of items by parent_ref dependency. Items with `parent_ref` referencing an existing `holon_id` or `None` are roots-of-batch.
- Cycle detected → raise ValueError with offending refs.
- Iterate in topological order, resolving `parent_ref` via (a) another item's allocated ID, or (b) existing `holon_id`. If neither: raise ValueError.
- All-or-nothing: any error raised before any state mutation. Validate full batch first, then apply under single RLock.

**Return format**:
```
Session: {sid} | Batch: {N} holons created
Refs: {ref_1}={id_1}, {ref_2}={id_2}, ...
Holarchy: {holarchy_id} (if new holarchy created)
```

**Test**: `test_holon_create_batch_with_refs` — creates 5 holons (1 root, 4 children referencing root by temp ref). Asserts all 5 have correct parent_id set via ref resolution.

### Item 7 — `chain` parameter on `think_argue`

**Files**:
- `src/aismartbuddy/tools/think.py::think_argue` — add parameter `chain: list[dict] | None = None`. Each entry: `{type: str, claim: str, premises: list[str], conclusion: str, confidence: float, strengths: list[str], weaknesses: list[str], responds_to_index: int | None}`
- `src/aismartbuddy/engines/thinking_engine.py::ThinkingEngine.add_argument` — support batch via new method `add_argument_chain(chain) → (chain_id, argument_ids[])`

**Semantics**:
- Types: `thesis | antithesis | synthesis | objection | rebuttal`
- Process in submission order. `responds_to_index` must reference a prior index in the same submission or existing argument_id.
- Single chain_id groups all entries (new field on argument records).
- Returns chain_id + argument_ids[] in submission order.

**Test**: `test_think_argue_chain_full_dialectic` — submit [thesis, antithesis, synthesis] in one call. Assert all three share a chain_id, synthesis has responds_to_index referencing thesis and antithesis.

### Item 8 — `knowledge_batch` tool (NEW)

**Files**:
- `src/aismartbuddy/tools/graph.py` — add new tool `knowledge_batch`
- `src/aismartbuddy/engines/ladybug_engine.py` — add method `knowledge_batch(nodes, relations) → (node_count, relation_count, node_ids)`
- `src/aismartbuddy/server.py:236-298` — register new tool with `_DEFAULT` annotation preset

**Signature**:
```python
async def knowledge_batch(
    session_id: str,
    nodes: list[dict] | None = None,      # each: {entity, entity_type, confidence, properties, source, valid_from, valid_to}
    relations: list[dict] | None = None,  # each: {from_name, to_name, relation, weight, justification, source}
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: Context | None = None,
) -> str
```

**Semantics**:
- **Cypher strategy selection** (performed during implementation, driven by engine capability check):
  - **Preferred**: extend `LadybugEngine` to support parameterized Cypher via prepared statements if KuzuDB exposes this. Then `UNWIND $nodes AS n CREATE (:Concept {...})` with parameter binding. Fastest, safe from injection.
  - **Fallback A**: UNWIND over inline list literal, constructed by the tool. Each node item serialized as Cypher map literal with careful escaping of string values (quotes, backslashes, newlines). Single Cypher statement to the engine. Still one round-trip.
  - **Fallback B** (used if both above blocked): sequential inserts inside a loop under one session lock. Still delivers N→1 round-trip to the MCP client, but N round-trips to the engine. Acceptable degradation.
- Phase 2 (relations): same strategy, matching source/target by entity name with `MATCH (a {entity: ...}), (b {entity: ...}) CREATE (a)-[:...]->(b)`.
- Implementation must validate the chosen strategy via a smoke test before committing — check `LadybugEngine.execute()` signature and behavior with parameterized input.
- Temporal fields (`valid_from`, `valid_to`) default to current time / null if omitted. Temporal filtering support is Phase 5 Item 28 — in this phase, fields are stored but not used for filtering (matches no-breaking-changes rule).

**Return**:
```
Session: {sid} | Nodes: {N} | Relations: {M}
Node IDs: {id_1}, {id_2}, ...
```

**Test**: `test_knowledge_batch_30_nodes_50_relations` — create 30 nodes + 50 relations in one call. Assert counts returned, assert `graph_knowledge_summary` shows all.

### Item 9 — `finding_batch` action on `score_evaluate` (with warning)

**Files**:
- `src/aismartbuddy/tools/score.py::score_evaluate` — add action `finding_batch`
- `src/aismartbuddy/engines/thinking_engine.py::ThinkingEngine.add_evaluation_finding` — support batch via `add_evaluation_findings(eval_id, findings) → list[running_score]`

**Semantics**:
- User passes `findings: list[dict]` where each dict is the same shape as a single `finding` call.
- Server applies each finding sequentially, computing running score after each.
- Returns array of running scores (one per finding) + final state.
- **WARNING appended to output**:
  ```
  ⚠ finding_batch loses the incremental self-assessment forcing function.
    Each finding was committed before seeing its running score.
    Prefer action=finding for iterative scoring when feasible.
  ```

**Return format**:
```
Session: {sid} | Evaluation: {eid} | Batch: {N} findings applied
Running scores: 10.0 → 9.2 → 8.5 → 8.0 → 7.1
Final: 7.1 (threshold: 9.0) | Status: BELOW_THRESHOLD
⚠ finding_batch loses incremental forcing. Prefer action=finding.
```

**Test**: `test_score_evaluate_finding_batch_warning` — submit 3 findings in batch. Assert warning text present in output. Assert all 3 findings stored. Assert running score array correct.

### Item 10 (was P3) — Single-call batching

Already addressed. No separate work.

### Phase 1 — acceptance criteria

- All 5 new batch capabilities shipped with tests
- No existing tests broken
- 277 (current) + ~15 new tests passing
- Response format examples documented in CLAUDE.md update

---

## PHASE 2 — Unified Sessions + Bridges (Items 11-13)

Most architecturally invasive phase. Changes SessionManager internals.

### Item 11 — Unified `session_create` (facade over child sessions)

**Architecture decision**: Unified session is a **facade**, not an engine merge. A parent session_id maps to one or more child session_ids (one per backend). Every tool call resolves parent → child for its backend.

**Files**:
- `src/aismartbuddy/session.py` — add:
  ```python
  @dataclass
  class ParentSession:
      parent_id: str
      user_id: str
      project_id: str
      children: dict[str, str]      # backend_name → child_session_id
      created_at: datetime
      last_accessed: datetime
  ```
  + new SessionManager fields: `_parent_sessions: dict[str, ParentSession]`
  + new methods:
    - `create_parent_session(user_id, project_id, backends: list[str]) → parent_id` — creates one child session per backend, stores mapping, returns parent_id
    - `resolve_backend_session(session_id, backend) → SessionInfo` — if session_id is a parent, look up child for `backend` and return its SessionInfo. If session_id is a direct child, return its SessionInfo unchanged (backwards compat). Raises if backend not in parent's children.
- `src/aismartbuddy/tools/__init__.py` — add helper wrapping `resolve_backend_session` for use in every tool entry point

- `src/aismartbuddy/tools/<module>.py` (NEW tool file for session infra): add:
  ```python
  async def session_create(
      backends: list[str] = ["think"],
      project_id: str | None = None,
      user_id: str | None = None,
      ctx: Context | None = None,
  ) -> str
  ```

**Semantics**:
- `backends` validates against `{"think", "graph", "sql"}` — any other value → ValueError.
- Creates one SessionInfo per backend under same (user_id, project_id).
- Returns parent_id (also 128-bit hex). Child IDs are internal implementation detail.
- `session_destroy(parent_id)` destroys all children.

**Backwards compatibility**:
- Existing `think_create_session`, `graph_create_session`, `sql_create_session` remain unchanged. They create a single-backend SessionInfo directly (bypass ParentSession). The session_id returned is a direct child ID.
- Every existing tool that takes `session_id` gains the ability to accept EITHER a parent_id OR a direct child session_id. Routing via `resolve_backend_session`.

**Files touched** (every tool — ~53 entry points):
- `tools/sql.py` — 7 tools: resolve via `resolve_backend_session(session_id, "sql")`
- `tools/graph.py` — 20 tools: resolve via `resolve_backend_session(session_id, "graph")`
- `tools/think.py` — 16 tools: resolve via `resolve_backend_session(session_id, "think")`
- `tools/holon.py` — 5 tools: resolve via `resolve_backend_session(session_id, "think")`
- `tools/score.py` — 3 tools: resolve via `resolve_backend_session(session_id, "think")`

**Test**: 
- `test_unified_session_three_backends` — create parent with `["think","graph","sql"]`. Use parent_id with `sql_query`, `graph_query`, `think_graph`. All three succeed, each operating on its own backend's data.
- `test_unified_session_missing_backend_error` — create parent with `["think"]`. Attempt `graph_query(session_id=parent_id)`. Expect graceful error "session has no graph backend."
- `test_backwards_compat_child_id_still_works` — call `think_create_session` as before. Use returned id with tools. Must still work.

### Item 12 — `bridge` tool

**Files**:
- `src/aismartbuddy/tools/bridge.py` (NEW) — single tool `bridge(session_id, action, source_id, ...)` with actions:
  - `think_to_graph` — every ThoughtNode becomes a KG node (`entity = thought[:80]`, `entity_type = "thought"`, properties include `depth`, `parent_id`, `metadata`). Parent-child edges become `derived_from` relations.
  - `holons_to_graph` — every holon in specified holarchy becomes a KG node (`entity = name`, `entity_type = "holon"`, properties include `level`, `projection`, `context`). Parent-child → `part_of` relations.
  - `graph_to_sql` — KG nodes projected as a SQL table (columns: entity, entity_type, confidence, source, valid_from, valid_to, properties_json).
  - `score_to_sql` — evaluation findings → SQL table (columns: evaluation_id, dimension, severity, blocking, description, running_score).

**Semantics**:
- Bridge requires parent session with BOTH source and target backends (e.g., `think_to_graph` requires `backends=["think", "graph"]`). Missing target → actionable error.
- Operations idempotent: second call to same bridge upserts (MATCH or CREATE per entity).
- All-or-nothing: accumulate mutations, apply under one engine lock per side (think-side read, graph-side write).

**Test**:
- `test_bridge_think_to_graph` — 10 ThoughtNodes in tree structure. Bridge. Assert 10 KG nodes + 9 derived_from edges.
- `test_bridge_holons_to_graph` — 5-holon hierarchy. Bridge. Assert 5 KG nodes + 4 part_of edges.
- `test_bridge_missing_backend_error` — parent with `["think"]` only. Attempt `think_to_graph`. Expect error "bridge requires graph backend in session."

### Item 13 — Route existing tools to correct backend

Already scoped as part of Item 11 touch points. No separate work.

**Phase 2 acceptance**:
- Parent session can host multiple backends
- Every existing tool accepts parent_id OR direct child id
- No existing tests broken
- New tests: ~8 (3 unified_session + 3 bridge + 2 backwards compat)

---

## PHASE 3 — New Forcing-Function Tools + New Modes (Items 14-20)

All additive. No renames. Existing tools (think_model, think_science, think_monitor) preserved verbatim.

### Item 14 — `scaffold` (NEW tool, coexists with think_model)

**Role**: Strict entry-point forcing function for MODE 5 analysis. Required fields force decomposition rigor.

**Files**:
- `src/aismartbuddy/tools/scaffold.py` (NEW)
- `src/aismartbuddy/engines/thinking_engine.py` — extend `add_model` or add new `add_scaffold(model, items, session_id) → (session_id, item_ids)` method with strict validation

**Signature**:
```python
async def scaffold(
    model: str,                         # first_principles|design_review|root_cause|pre_mortem|...
    items: list[dict],                  # each: {id: str, problem: str, steps: list[str], reasoning: str, conclusion: str, connects_to: list[str] | None, metadata: dict | None}
    session_id: str | None = None,
    auto_graph: bool = False,           # if true: each item becomes a KG node; requires graph backend
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: Context | None = None,
) -> str
```

**Validation** (server rejects):
- `model` must be in allowed set (same 13 models as think_model).
- `items` must be length ≥ 1.
- Each item's `problem`, `steps` (len ≥ 1), `reasoning` (non-empty), `conclusion` (non-empty) are REQUIRED.
- Each item's `id` must be unique within batch.
- If `auto_graph=True`: session must have graph backend → else error "auto_graph requires graph backend. Use session_create(backends=['think','graph'])."

**Semantics**:
- Items processed under one RLock acquisition.
- Each item becomes a ThoughtNode with category=`scaffold`, `metadata.model`, `metadata.scaffold_item_id` = item.id.
- If `auto_graph`: also create KG node per item + edges from `connects_to` references.
- Returns session_id + item_ids[] (+ graph_node_ids[] if auto_graph).

**Description differentiation from think_model**:
- scaffold: "Apply a structured mental model at ANALYSIS START. Forces separate problem/steps/reasoning/conclusion per item. Rejects lazy submissions (missing required fields). Use when structuring a problem space for deep analysis."
- think_model (UNCHANGED): "Apply a named mental model with flexible fields for mid-analysis exploration. Use for single-problem reflection or iterative model application."

**Test**: `test_scaffold_multi_item_first_principles` — submit 7 items with required fields. Assert all 7 thoughtnodes created. `test_scaffold_missing_reasoning_rejected` — submit item with empty reasoning. Assert ValueError. `test_scaffold_auto_graph_without_backend_rejected` — missing graph backend. Assert error.

### Item 15 — `hypothesize` (NEW tool, coexists with think_science)

**Role**: Strict hypothesis generation with mandatory falsifiability.

**Files**:
- `src/aismartbuddy/tools/hypothesize.py` (NEW)
- `src/aismartbuddy/engines/thinking_engine.py` — add `add_hypothesis(items) → ids[]` method
- `src/aismartbuddy/tools/__init__.py` — add constant `MIN_FALSIFIABILITY_CHARS = 20`

**Signature**:
```python
async def hypothesize(
    items: list[dict],      # each: {id, observation, question, hypothesis: {statement, variables: [{name, role}], assumptions, confidence, falsifiability}, alternative_hypotheses: list[str] | None, connects_to: list[str] | None}
    session_id: str | None = None,
    auto_graph: bool = False,
    user_id, project_id, ctx,
) -> str
```

**Validation**:
- `items` length ≥ 1
- Each item's `observation`, `question`, `hypothesis.statement`, `hypothesis.confidence` required
- `hypothesis.variables`: at least 1, each must specify role ∈ {independent, dependent, controlled}
- `hypothesis.assumptions`: at least 1
- `hypothesis.falsifiability`: REQUIRED, MIN 20 chars — server rejects with actionable message: "Falsifiability must state a specific observation that would disprove this hypothesis. Minimum 20 chars. Got: '{truncated_value}'"

**Description differentiation from think_science**:
- hypothesize: "Generate falsifiable hypotheses in one batch. Falsifiability field REJECTED below 20 chars. Use at analysis start for claims that need testing."
- think_science (UNCHANGED): "Iterate through scientific method stages (observation → hypothesis → experiment → analysis → conclusion). Use for staged exploration with revisions."

**Test**: `test_hypothesize_rejects_short_falsifiability` — submit with 15-char falsifiability. Assert error message includes "Minimum 20 chars."

### Item 16 — `self_assess` (NEW tool, coexists with think_monitor)

**Role**: One-shot calibration forcing limitations enumeration.

**Files**:
- `src/aismartbuddy/tools/self_assess.py` (NEW)
- `src/aismartbuddy/engines/thinking_engine.py` — add `add_self_assessment(...)` method

**Signature**:
```python
async def self_assess(
    task: str,
    knowledge: dict,    # {domain, level, confidence, limitations: list[str]}
    claims: list[dict], # each: {claim, status, confidence, evidence, falsifiability?, alternatives?}
    session_id: str | None = None,
    user_id, project_id, ctx,
) -> str
```

**Validation**:
- `knowledge.level` ∈ {expert, proficient, familiar, basic, minimal, none}
- `knowledge.limitations`: REQUIRED, length ≥ 1, each non-empty — server rejects empty list with "Limitations must state what you don't know. Add at least one limitation."
- `claims`: length ≥ 1; each with required claim, status ∈ {fact, inference, speculation, uncertain}, evidence

**Returns**: session_id + assessment_id + `overall_confidence` (weighted mean of claim confidences weighted by status: fact=1.0, inference=0.75, speculation=0.5, uncertain=0.25).

**Description differentiation from think_monitor**:
- self_assess: "One-shot knowledge calibration at analysis START. Rejects empty limitations. Use before committing to an analytical approach."
- think_monitor (UNCHANGED): "Multi-iteration metacognitive monitoring across analysis. Use for ongoing confidence tracking through staged assessment."

**Test**: `test_self_assess_rejects_empty_limitations`, `test_self_assess_overall_confidence_weighted`.

### Item 17 — `auto_graph` on scaffold/hypothesize

Already specified inline with Items 14 and 15. Shared logic in a helper `tools/__init__.py::_materialize_auto_graph(session_id, nodes, edges)` that Phase 2's unified session routing + Phase 1's knowledge_batch enable.

**Dependencies**: Phase 1 Item 8 (knowledge_batch) + Phase 2 Item 11 (unified sessions).

### Item 18 — `brainstorm` (NEW tool)

**Role**: MODE 3 DIVERGE — anti-forcing-function; demands quantity and diversity.

**Files**:
- `src/aismartbuddy/tools/brainstorm.py` (NEW)
- `src/aismartbuddy/engines/thinking_engine.py` — add `add_brainstorm(ideas, topic, constraints, style) → (brainstorm_id, idea_ids, cluster_suggestions)`

**Signature**:
```python
async def brainstorm(
    topic: str,
    ideas: list[dict],    # each: {idea: str, spark: str}
    min_ideas: int = 10,
    constraints: list[str] | None = None,
    style: str = "wild",  # wild|constrained|analogical|inversion
    session_id: str | None = None,
    user_id, project_id, ctx,
) -> str
```

**Validation**:
- `len(ideas) >= min_ideas` — else REJECT with: "Brainstorm submitted {N} ideas but min_ideas={M}. Generate more ideas before converging. Quantity before quality."
- `style` ∈ {wild, constrained, analogical, inversion}
- Each idea: non-empty `idea` and `spark` fields

**Semantics**:
- No `conclusion` field exists — this enforces "no convergence during divergence."
- `cluster_suggestions`: server-side keyword clustering. For each idea, extract top-3 content-word tokens (minus stopwords). Group ideas sharing ≥2 tokens. Returns theme-groups with idea IDs. Simple approach (Jaccard on token sets), no embeddings.
- Returns brainstorm_id + idea_ids[] + cluster_suggestions.

**Test**: `test_brainstorm_rejects_below_min_ideas`, `test_brainstorm_clusters_share_keywords`.

### Item 19 — `data_profile` and `data_anomalies` (NEW tools for MODE 2)

#### `data_profile`

**Files**:
- `src/aismartbuddy/tools/sql.py` — add `data_profile(session_id, table, columns, include) → str`
- `src/aismartbuddy/engines/duckdb_engine.py` — add `profile_table(table, columns, include) → pa.Table`

**Semantics**:
- Use DuckDB's native `SUMMARIZE` statement for the base profile.
- Additional per-column stats computed via parametrized queries (p5/p25/p75/p95 via `quantile_cont`, outlier counts via z-score).
- Return formatted CSV via Arrow → Polars → `write_csv()`.

**Test**: `test_data_profile_100_row_table` — assert output contains column-level stats for all expected columns.

#### `data_anomalies`

**Files**:
- `src/aismartbuddy/tools/sql.py` — add `data_anomalies(session_id, table, columns, method, threshold) → str`
- `src/aismartbuddy/engines/duckdb_engine.py` — methods `anomalies_zscore(table, cols, threshold)`, `anomalies_iqr(table, cols, threshold)`

**Semantics**:
- `method="zscore"`: compute z-score per column via `(val - avg) / stddev` window function; flag rows with `abs(z) > threshold` (default 3.0).
- `method="iqr"`: compute p25/p75, flag rows outside `[p25 - 1.5*iqr, p75 + 1.5*iqr]`.
- `method="isolation_forest"`: **DEFERRED** (requires external lib). Raise NotImplementedError with actionable hint.
- Return flagged rows (limited to `max_rows`) + per-column anomaly counts + suggested investigation SQL.

**Test**: `test_data_anomalies_zscore`, `test_data_anomalies_iqr`.

### Item 20 — `iterate` (NEW tool for MODE 4)

**Files**:
- `src/aismartbuddy/tools/iterate.py` (NEW)
- `src/aismartbuddy/engines/thinking_engine.py` — add IterationRecord dataclass + methods `start_iteration(goal)`, `record_attempt(iter_id, attempt)`, `iteration_status(iter_id)`, `conclude_iteration(iter_id, conclusion)`

**Signature**:
```python
async def iterate(
    action: str,   # start|attempt|status|conclude
    session_id: str | None = None,
    goal: str | None = None,
    attempt: dict | None = None,    # {approach, result, learning, metric_name?, metric_value?}
    conclusion: str | None = None,
    iteration_id: str | None = None,
    user_id, project_id, ctx,
) -> str
```

**Semantics (base behavior — metric ratcheting deferred to Phase 5 Item 27)**:
- `start`: creates IterationRecord with goal. Returns iteration_id.
- `attempt`: requires approach/result/learning. Appends to iteration. Returns attempt_number and simple trend ("N of K attempts").
- `status`: returns full history compactly.
- `conclude`: stores conclusion, marks iteration complete. Returns summary.

**Test**: `test_iterate_full_cycle` — start → 3 attempts → status → conclude.

---

## PHASE 4 — Infrastructure (Items 21-26)

Mostly additive. Existing tools preserved.

### Item 21 — `session_export`

**Files**:
- `src/aismartbuddy/tools/infra.py` (NEW — or reuse `meta.py`) — `session_export(session_id, format, include) → str`

**Signature**:
```python
async def session_export(
    session_id: str,
    format: str = "markdown",   # markdown|json|summary
    include: list[str] | None = None,   # thoughts|holons|knowledge|scores|arguments|iterations|scaffolds|hypotheses
    user_id, project_id, ctx,
) -> str
```

**Semantics**:
- `markdown`: structured document with H2 sections per include category. Uses existing `_render_*` helpers.
- `json`: `dataclasses.asdict()` dump of ThinkingEngine state (plus graph/sql summaries if in parent session).
- `summary`: calls existing `think_summarize` output directly.
- `include=None`: all categories. Otherwise only listed.
- Respects `@size_guarded` decorator — large sessions truncated at 500KB with hint.

**Files touched**:
- Engines need `to_dict()` or `export_state()` method for JSON export. ThinkingEngine: add `export_state() → dict`. DuckDB/LadybugDB: defer or export schema + row counts only.

**Test**: `test_session_export_markdown_all`, `test_session_export_json_structured`.

### Item 22 — `session_snapshot`

**Files**:
- `src/aismartbuddy/tools/infra.py` — `session_snapshot(session_id, action, ...) → str`
- Snapshot storage: `{temp_base_dir}/aismartbuddy/snapshots/{snapshot_id}/`

**Signature**:
```python
async def session_snapshot(
    session_id: str,
    action: str,        # save|restore|list
    snapshot_id: str | None = None,
    label: str | None = None,
    user_id, project_id, ctx,
) -> str
```

**Semantics**:
- `save`:
  - ThinkingEngine: call `export_state()` → JSON → write to `{snapshot_id}/thinking.json`
  - DuckDB: copy `data.duckdb` to `{snapshot_id}/data.duckdb` (atomic copy while holding session lock)
  - LadybugDB: copy `graph.lbug` to `{snapshot_id}/graph.lbug`
  - Record metadata (label, timestamp, user_id, project_id, parent backends list) in `{snapshot_id}/meta.json`
- `restore`: reverse — stop engines, replace files, restart engines. Requires session be held exclusively.
- `list`: read all metadata files in snapshots dir filtered to user_id/project_id.

**Test**: `test_session_snapshot_save_restore` — create, save, mutate, restore, verify state rolled back.

**Risk**: Pickle-free design required (Python version fragility). ThinkingEngine uses JSON export. DuckDB/LadybugDB use file-copy. No pickle anywhere.

### Item 23 — `workflow`

**Files**:
- `src/aismartbuddy/tools/infra.py` — `workflow(action, session_id, template, phases) → str`
- Soft state stored in SessionInfo metadata dict (new field `workflow_state: dict | None`).

**Signature**:
```python
async def workflow(
    action: str,   # start|advance|status|checkpoint
    session_id: str,
    template: str | None = None,    # analysis|research|design_review|custom
    phases: list[dict] | None = None,   # for custom
    user_id, project_id, ctx,
) -> str
```

**Semantics**:
- Templates:
  - `analysis`: SCAFFOLD → ELABORATE → ASSESS
  - `research`: OBSERVE → HYPOTHESIZE → VALIDATE → CONCLUDE
  - `design_review`: DECOMPOSE → COMPARE → SCORE → RECOMMEND
- `status`: returns current phase + recommended tools + completion % of prior phases.
- `advance`: moves to next phase. Does NOT block tool calls.
- `checkpoint`: lightweight self-check — "You are in SCAFFOLD phase. Have you called scaffold/hypothesize? [yes/no]." Informational only.

**Principle**: soft advisory. Tool calls NEVER rejected because of workflow state. The AI can ignore workflow entirely.

**Test**: `test_workflow_analysis_template_advances`.

### Item 24 — `rubric_templates`

**Files**:
- `src/aismartbuddy/templates/rubrics/*.json` (NEW) — 6 JSON template files:
  - `security_review.json`, `architecture_review.json`, `code_review.json`, `research_quality.json`, `hypothesis_strength.json`, `documentation_completeness.json`
- `src/aismartbuddy/tools/score.py` — `rubric_templates(action, template_id, session_id)` tool

**Semantics**:
- `list`: returns all available templates with descriptions.
- `load`: applies selected template to session as rubric (calls `score_rubric(action="create", ...)` internally with template data). Returns rubric_id.

**Test**: `test_rubric_templates_list`, `test_rubric_templates_load_security_review`.

### Item 25 — `min_nodes` validation on `graph_knowledge_infer`

**Files**:
- `src/aismartbuddy/tools/graph.py::graph_knowledge_infer` — add parameter `min_nodes_override: int = 10`
- Before running inference, query node count. If < `min_nodes_override`: return early with message:
  ```
  Graph has {N} nodes. Minimum {M} recommended for meaningful {inference_type}.
  Add more knowledge before inferring. Use knowledge_batch for bulk-add.
  ```

**Test**: `test_graph_knowledge_infer_rejects_small_graph`.

### Item 26 — Description tweaks (NOT removal, NOT merge)

Per user direction "dont make the mistakes of conflicting the 2" and "dont rename," this item is reduced to description-only changes.

**Files**:
- `src/aismartbuddy/tools/think.py` — edit docstrings for:
  - `think_collaborate`: append "Note: single-LLM personas produce theatrical rather than genuine disagreement. For real dialectic with premises/strengths/weaknesses, use `think_argue`."
  - `think_visualize`: append "Note: stores diagram specs as session metadata. For diagrams inline with reasoning, prefer `think` with `metadata={type: 'diagram', elements: [...]}`."
  - `think_graph_validate`: append "Note: records a structural self-assessment. For validating individual nodes inline, prefer `think(action='think', thought='Validation: ...', parent_id=target_id)`."

**NO tool removal. NO merge. NO think action=validate. Existing behavior preserved verbatim.**

---

## PHASE 5 — Framework Gap Closure (Items 27-29)

### Item 27 — Metric ratcheting on `iterate`

**Files**:
- `src/aismartbuddy/tools/iterate.py` — extend action="attempt" to accept optional `metric_name`, `metric_value`
- `src/aismartbuddy/engines/thinking_engine.py::IterationRecord` — add fields `metric_name: str | None`, `best_metric: float | None`, `metric_history: list[float]`, `stagnation_threshold: int = 3`

**Semantics**:
- On attempt with metric: compare to `best_metric`. If greater (or less for "lower_is_better" — handled via sign flip): mark `is_improvement=True`, update `best_metric`.
- Stagnation detection: if last N attempts all worse than best, set `stagnation_detected=True`.
- Status action: returns best, trend (improving/stagnating/regressing), stagnation_detected, suggested_action (iterate/radical/conclude).

**Test**: `test_iterate_metric_ratchet_improves`, `test_iterate_stagnation_detected_after_3`.

### Item 28 — Temporal knowledge graph

**Files**:
- `src/aismartbuddy/engines/ladybug_engine.py` — ensure KG node creation includes `valid_from` (default: now) and `valid_to` (default: null) properties
- `src/aismartbuddy/tools/graph.py::graph_knowledge_add` — add parameters `valid_from: str | None`, `valid_to: str | None`
- `src/aismartbuddy/tools/graph.py::graph_knowledge_invalidate` (NEW tool) — sets `valid_to` on matching entity
- `src/aismartbuddy/tools/graph.py::graph_knowledge_infer` — add `as_of: str | None` parameter; filter Cypher queries: `WHERE n.valid_from <= $as_of AND (n.valid_to IS NULL OR n.valid_to > $as_of)`
- `src/aismartbuddy/tools/graph.py::graph_query` — add `as_of: str | None` parameter; same filter

**Migration for existing data**:
- On LadybugDB session open: run `MATCH (n) WHERE n.valid_from IS NULL SET n.valid_from = datetime('1970-01-01T00:00:00Z') RETURN count(n)`. Idempotent backfill for older graphs.

**Semantics** (backwards-compatibility-preserving):
- **Default (as_of=None)**: queries behave EXACTLY as today — no temporal filtering, all nodes returned including those with non-null `valid_to`. This preserves existing `graph_query` / `graph_knowledge_infer` call semantics. No existing test breaks.
- **as_of=<ISO datetime>**: temporal filter applied — `WHERE n.valid_from <= $as_of AND (n.valid_to IS NULL OR n.valid_to > $as_of)`.
- **as_of="now"** (sentinel): equivalent to passing current UTC timestamp — useful for "current facts only" queries that explicitly opt in to temporal filtering.
- `graph_knowledge_invalidate(entity, reason)`: sets `valid_to = now()`, records reason in node property. Does NOT delete.
- Critical: the "no breaking changes" guarantee depends on this design. Defaulting to `valid_to IS NULL` filtering would change behavior for every existing graph_query caller. DO NOT implement that shortcut.

**Test**: `test_knowledge_temporal_valid_to_excludes_current`, `test_knowledge_as_of_historical_query`, `test_knowledge_invalidate_preserves_node`.

### Item 29 — `think_interfere` ban list enforcement

**Verification first**: read `src/aismartbuddy/tools/think.py::think_interfere` implementation + ThinkingEngine's `add_fragment` to check whether banned terms from `set_domain` are validated.

**If not enforced**:
- `ThinkingEngine.add_fragment` — before storing fragment text, run regex check against banned terms list (from domain setup).
- Reject with: `"Fragment contains banned term '{term}'. Rewrite without domain-specific vocabulary. Phase 1 requires pre-linguistic fragments."`
- Ban lifted at `stress_test` phase (Phase 4 of Interference Protocol).

**If enforced already**: verify via test, close item.

**Test**: `test_think_interfere_ban_list_rejects_domain_vocab`.

---

## Philosophy Validation Matrix

For each principle, verify each phase's items comply. ✓ = aligned, ⚠ = tension with mitigation, ✗ = violation (none accepted).

| Phase | Item | P1 Forcing | P2 Batch | P3 Bridge | P4 Ceremony | P5 Tokens | P6 Isolation |
|---|---|---|---|---|---|---|---|
| 0 | P0 holon_view truncate ✅ | n/a | n/a | n/a | ✓ | ✓ | ✓ |
| 0 | P1 config truncation | n/a | n/a | n/a | ✓ | ✓ | ✓ |
| 0 | P2a chains max_depth | n/a | n/a | n/a | ✓ | ✓ | ✓ |
| 0 | P2b graph_query timeout | n/a | n/a | n/a | ✓ | ✓ | ✓ |
| 0 | P2d summarize cap | n/a | n/a | n/a | ✓ | ✓ | ✓ |
| 0 | P4 size_guarded | n/a | n/a | n/a | ✓ | ✓ | ✓ |
| 1 | 5 think.children | n/a | ✓ per-child validation | n/a | ✓ | ✓ | ✓ |
| 1 | 6 holons batch | n/a | ✓ | n/a | ✓ | ✓ | ✓ |
| 1 | 7 argue chain | n/a | ✓ per-entry type validation | n/a | ✓ | ✓ | ✓ |
| 1 | 8 knowledge_batch | n/a | ✓ per-node validation | n/a | ✓ | ✓ | ✓ |
| 1 | 9 finding_batch | ⚠ loses incremental — warning appended | ✓ | n/a | ✓ | ✓ | ✓ |
| 2 | 11 unified session | n/a | n/a | ✓ facade preserves isolation | ✓ | ✓ | ✓ |
| 2 | 12 bridge | n/a | n/a | ✓ explicit, named | ✓ | ✓ | ✓ |
| 3 | 14 scaffold | ✓ required fields + reject | ✓ per-item | n/a | ✓ not ceremony | ✓ | ✓ |
| 3 | 15 hypothesize | ✓ falsifiability ≥20 | ✓ per-item | n/a | ✓ | ✓ | ✓ |
| 3 | 16 self_assess | ✓ limitations required | n/a single-shot | n/a | ✓ | ✓ | ✓ |
| 3 | 17 auto_graph | n/a | ✓ | ✓ uses bridge pattern internally | ✓ | ✓ | ✓ |
| 3 | 18 brainstorm | ✓ anti-FF (min_ideas) | ✓ items required | n/a | ✓ | ✓ | ✓ |
| 3 | 19 data_profile | n/a | n/a | n/a | ✓ replaces 5-10 calls | ✓ | ✓ |
| 3 | 20 iterate | n/a | n/a | n/a | ✓ lightweight | ✓ | ✓ |
| 4 | 21 session_export | n/a | n/a | n/a | ✓ | ✓ size-guarded | ✓ |
| 4 | 22 snapshot | n/a | n/a | ✓ no pickle | ✓ | ✓ | ✓ |
| 4 | 23 workflow | ⚠ could become ceremony — soft advisory only | n/a | n/a | ⚠ mitigated via optional+non-blocking | ✓ | ✓ |
| 4 | 24 rubric_templates | n/a | n/a | n/a | ✓ reuse | ✓ | ✓ |
| 4 | 25 min_nodes | n/a | n/a | n/a | ✓ rejects wasteful calls | ✓ | ✓ |
| 4 | 26 desc tweaks | n/a | n/a | n/a | ✓ no removals | ✓ | ✓ |
| 5 | 27 ratchet | ✓ numeric forcing | n/a | n/a | ✓ | ✓ | ✓ |
| 5 | 28 temporal KG | n/a | n/a | ✓ explicit time dimension | ✓ | ✓ | ✓ |
| 5 | 29 ban list | ✓ vocab rejection | n/a | n/a | ✓ | ✓ | ✓ |

Two ⚠ tensions, both mitigated:
1. **finding_batch** forfeits incremental forcing. Mitigation: warning text in every output + explicit documentation recommending individual `finding` action.
2. **workflow** could devolve into ceremony. Mitigation: soft-advisory design, never blocks tool calls, cheap to invoke, no spamming unsolicited advice.

---

## Coexistence Rules (dual-family discipline)

Per user direction "make sure you don't make the mistakes of conflicting the 2."

### Description conventions

Strict forcing-function tools use these phrases in their description:
- "at analysis START" or "entry point"
- "REJECTS" (lazy/empty/short submissions)
- "Forces you to..."
- "Use for..." → formal/rigorous/deep

Flexible logging tools use these phrases:
- "mid-analysis" or "iterative"
- "flexible" / "exploratory"
- "Record" (rather than "demand")
- "Use for..." → quick/lightweight/iterative

### Test coexistence

Test suite includes explicit `test_scaffold_and_think_model_coexist`, `test_hypothesize_and_think_science_coexist`, `test_self_assess_and_think_monitor_coexist`. Each creates a session, uses both tools, asserts outputs distinct and no state collision.

### Documentation (CLAUDE.md update)

New section "Dual tool families" added to CLAUDE.md:
```
Some capabilities have BOTH a strict entry-point version and a flexible logging version:

| Analysis start (strict)  | Mid-analysis (flexible) |
| scaffold                 | think_model             |
| hypothesize              | think_science           |
| self_assess              | think_monitor           |

The strict tools enforce structural thoroughness (required fields, minimum lengths).
Use them when STARTING a deep analysis to force decomposition rigor.

The flexible tools preserve iteration and revision. Use them mid-analysis when
applying a model, recording progression, or tracking ongoing confidence without
committing to a strict schema up front.

The two families are DIFFERENT tools for DIFFERENT moments — not v1/v2.
```

---

## Test Strategy

### Test files to add

| New File | Tests | Purpose |
|---|---|---|
| `tests/test_batch_ops.py` | ~20 | Items 5-9 (think.children, holons batch, argue chain, knowledge_batch, finding_batch) |
| `tests/test_unified_sessions.py` | ~10 | Items 11-13 (session_create multi-backend, bridge, backwards compat) |
| `tests/test_scaffold.py` | ~8 | Item 14 (scaffold + coexistence with think_model) |
| `tests/test_hypothesize.py` | ~6 | Item 15 (+ coexistence with think_science) |
| `tests/test_self_assess.py` | ~5 | Item 16 (+ coexistence with think_monitor) |
| `tests/test_brainstorm.py` | ~5 | Item 18 |
| `tests/test_data_explore.py` | ~10 | Items 19 (profile + anomalies) |
| `tests/test_iterate.py` | ~6 | Item 20 + Item 27 (metric ratchet) |
| `tests/test_session_infra.py` | ~12 | Items 21-23 (export, snapshot, workflow) |
| `tests/test_rubric_templates.py` | ~6 | Item 24 |
| `tests/test_temporal_kg.py` | ~8 | Item 28 |
| `tests/test_interfere_bans.py` | ~3 | Item 29 |
| `tests/test_performance_guards.py` | ~8 | Items P1, P2a, P2b, P2d, P4 |

Total new tests: ~107 added to existing ~277. Post-implementation target: ~384 tests all passing.

### Test patterns (follow existing conventions from `conftest.py`)

- Direct function call: `from aismartbuddy.tools.scaffold import scaffold; result = await scaffold(model=..., items=...)`
- `_extract_field(result, "Session:")` for parsing pipe-delimited output
- Fixture injection of `session_manager` singleton via `_init_session_manager` fixture (see `test_holon_tools.py` pattern)
- `async def test_*` + `@pytest.mark.anyio` decorator

### Coverage backfill (addresses existing gap)

Add tests for currently untested tools — graph_knowledge_add, graph_knowledge_relate, graph_knowledge_infer, graph_knowledge_summary — at least 15 tests across these to reach minimum coverage before Phase 5 Item 28 (temporal KG) modifies them.

---

## Breaking Changes

**NONE.**

Per user direction, no renames, no removals, no field-requirement upgrades on existing tools.

Existing tests (278) continue passing unmodified. Existing tool signatures unchanged. Existing session creation flows unchanged (alongside new `session_create`).

New tools are purely additive. Tool count: 49 → ~64.

---

## Implementation Order (ticket-sized chunks)

### Milestone M0: Performance (Phase 0)
1. **M0-1**: P1 — `holon_display_truncate_chars` config + wire through 22 holon.py slices + CLI flag + test
2. **M0-2**: P2a — `max_depth` on `graph_knowledge_infer(chains)` + ladybug engine bound + test
3. **M0-3**: P2b — `timeout_ms` on `graph_query` + anyio.fail_after wrapper + test
4. **M0-4**: P2d — `max_items_per_category` on `think_summarize` + test
5. **M0-5**: P4 — `@size_guarded` decorator in tools/__init__.py + apply to 8 tools + test

### Milestone M1: Batch Operations (Phase 1)
6. **M1-1**: Item 5 — `think_graph(children=...)` + `expected_children` + engine helper + 5 tests
7. **M1-2**: Item 6 — `holon_create(holons=...)` + topological resolution + 6 tests
8. **M1-3**: Item 7 — `think_argue(chain=...)` + engine helper + 4 tests
9. **M1-4**: Item 8 — `knowledge_batch` tool + Cypher UNWIND ingest + 4 tests
10. **M1-5**: Item 9 — `score_evaluate(action="finding_batch")` + warning text + 3 tests

### Milestone M2: Unified Sessions (Phase 2)
11. **M2-1**: `ParentSession` dataclass + SessionManager methods (`create_parent_session`, `resolve_backend_session`, `destroy_parent_session`) + unit tests for each method
12. **M2-2**: `session_create` tool + `resolve_backend_session` helper + backwards compat tests
13. **M2-3a**: Route SQL tools (7 tools) via `resolve_backend_session(sid, "sql")`; run full SQL test subset
14. **M2-3b**: Route Graph tools (16 tools) via `resolve_backend_session(sid, "graph")`; run full Graph test subset
15. **M2-3c**: Route Think tools (16 tools) via `resolve_backend_session(sid, "think")` AND handle auto-create tension (see semantics below); run full Think test subset
16. **M2-3d**: Route Holon tools (5 tools) + Score tools (3 tools) via `resolve_backend_session(sid, "think")`; run full subset
17. **M2-4**: `bridge` tool (4 actions) + engine-specific Cypher / SQL DDL + 6 tests

**Auto-create tension resolution (M2-3c)**: Think/Holon/Score tools currently call `_get_or_create_think_session(ctx)` when `session_id` is None. With parent sessions, new behavior:
- `session_id=None`: preserved behavior — auto-create a standalone (non-parent) think session.
- `session_id=<parent_id>` where parent has `think` in backends: route to child think session.
- `session_id=<parent_id>` where parent LACKS `think` backend: return error "Parent session does not include 'think' backend. Recreate with session_create(backends=['think',...]) or use separate think_create_session." NO auto-creation within parent. Explicit is better than implicit.
- `session_id=<direct_child_id>` (backwards compat): route directly, skip parent lookup.

### Milestone M3: New Forcing Functions + Modes (Phase 3)
15. **M3-1**: `scaffold` tool + required-field validation + auto_graph + 8 tests (incl. coexistence)
16. **M3-2**: `hypothesize` tool + MIN_FALSIFIABILITY_CHARS constant + 6 tests (incl. coexistence)
17. **M3-3**: `self_assess` tool + required limitations validation + overall_confidence computation + 5 tests (incl. coexistence)
18. **M3-4**: `brainstorm` tool + min_ideas enforcement + keyword clustering + 5 tests
19. **M3-5**: `data_profile` tool + DuckDB SUMMARIZE integration + 5 tests
20. **M3-6**: `data_anomalies` tool + zscore + iqr methods + 5 tests
21. **M3-7**: `iterate` tool (base behavior — no ratchet yet) + 3 tests

### Milestone M4: Infrastructure (Phase 4)
22. **M4-1**: `session_export` + markdown/json/summary formatters + `ThinkingEngine.export_state()` + 4 tests
23. **M4-2**: `session_snapshot` + JSON-free snapshot format + save/restore/list + 5 tests
24. **M4-3**: `workflow` tool + 4 templates + advisory-only semantics + 3 tests
25. **M4-4**: Create 6 rubric JSON templates + `rubric_templates` tool + 6 tests
26. **M4-5**: `min_nodes_override` on `graph_knowledge_infer` + early-return logic + 2 tests
27. **M4-6**: 3 docstring updates (think_collaborate, think_visualize, think_graph_validate) — no code change

### Milestone M5: Framework Gap Closure (Phase 5)
28. **M5-1**: Iterate metric ratcheting + stagnation detection + 4 tests
29. **M5-2**: Temporal KG — schema fields + backfill migration + invalidate tool + as_of parameter on infer/query + 8 tests + coverage backfill for graph_knowledge_* tools
30. **M5-3**: Verify/add think_interfere ban list enforcement + 3 tests

### Suggested cadence

- M0 and M1 are independent of all others — can proceed in parallel.
- **Core Phase 3 tools (scaffold, hypothesize, self_assess, brainstorm) do NOT require M2.** They can ship without auto_graph capability. If Phase 2 is delayed, ship Phase 3 core + add auto_graph later as an enhancement.
- `auto_graph` capability alone requires M2 (it uses the bridge pattern internally to materialize KG nodes from forcing-function outputs). Tag this as an optional add-on to M3-1 / M3-2, gated on M2 completion.
- M3 blocks M4-1 (session_export references scaffold/hypothesize/iterate state — needs the state machines to exist).
- M5 can proceed after M1 (temporal KG reuses knowledge_batch for test data).

### Documentation touch points within milestones

Documentation is part of each milestone, not a trailing task:
- **M0**: update CLAUDE.md tool count (49) + describe new truncation config knobs
- **M1**: add "Batch operations" section to CLAUDE.md with call-pattern examples
- **M2**: add "Unified sessions (parent / child facade)" section to CLAUDE.md; new `.meridian/docs/unified-sessions.md` with frontmatter
- **M3**: add "Dual tool families" section to CLAUDE.md; new `.meridian/docs/dual-tool-families.md`; add "Thinking modes" section to CLAUDE.md
- **M4**: update Architecture diagram in CLAUDE.md to include new modules (bridge.py, scaffold.py, hypothesize.py, self_assess.py, brainstorm.py, iterate.py, infra.py)
- **M5**: add "Temporal knowledge graph" subsection to CLAUDE.md; new `.meridian/docs/temporal-kg.md`

---

## Risk Matrix (top 10)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Batch operations hold RLock too long, blocking other agents on same session | Med | Med | Per-batch size caps (max 100 items per call); add timing assertion in tests |
| 2 | Unified session routing breaks on null/missing child for unrequested backend | Med | High | Fail-fast error messages; explicit test for "session has no X backend" |
| 3 | LadybugDB lacks UNWIND support → knowledge_batch falls back to sequential inserts | Low | Med | Verify Cypher support in Phase 1; fallback to sequential with note in code |
| 4 | Pickle version fragility in session_snapshot → restore fails across Python minor versions | High if used | High | Explicit NO-PICKLE policy: JSON for ThinkingEngine, file-copy for DB engines |
| 5 | Temporal KG migration of existing graphs fails silently | Med | High | Log node count before/after migration; abort session load if mismatch |
| 6 | `finding_batch` encourages bypassing incremental forcing, regressing analysis quality | Med | Med | Warning text in every output; CLAUDE.md guidance recommends individual finding |
| 7 | scaffold vs think_model confusion — AI picks wrong tool | Med | Low | Description differentiation + explicit coexistence test + CLAUDE.md section |
| 8 | workflow tool becomes ceremony when AI follows its advice mechanically | Low | Low | Soft advisory; AI free to ignore; never blocks calls |
| 9 | size_guarded truncation hides real bugs (tool producing 1GB output) | Low | Med | Log ERROR at 200KB threshold so oversize is visible even when not truncated |
| 10 | data_anomalies "isolation_forest" method raises NotImplementedError confusingly | Low | Low | Clear error message with fallback instructions; document in tool description |
| 11 | M2-3 touches every tool (49 entry points) — regression surface is huge | **High** | Med | Split M2-3 into M2-3a/b/c/d by module (SQL / Graph / Think / Holon+Score). Run full relevant test subset between each. No cross-module changes in one commit. |
| 12 | Parent-session auto-create of missing think backend creates silent state inconsistencies | Med | Med | Explicit error instead of auto-create when parent lacks requested backend (see M2-3c semantics) |
| 13 | knowledge_batch Cypher UNWIND feasibility blocked by LadybugEngine missing parameter support | Med | Low | Three-tier fallback in Item 8 Semantics (parameterized → inline literal → sequential); smoke test chosen strategy before committing |

---

## Verification Plan

### Per-milestone acceptance

Each milestone (M0 through M5) is complete when:
- All listed tests pass: `uv run pytest tests/ -v`
- Lint clean: `uv run ruff check src/ tests/`
- Type check clean: `uv run pyright`
- Manual smoke test: start server via `uv run python -m aismartbuddy --transport sse --port 8000` and exercise new tools via MCP client or curl

### Final verification (all milestones complete)

```bash
# 1. Full test suite
uv run pytest tests/ -v                    # Expect ~384 tests, all pass

# 2. Lint + format
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 3. Type check
uv run pyright

# 4. Tool count verification
uv run python -c "
from aismartbuddy.server import _TOOLS
print(f'Tool count: {len(_TOOLS)}')
for fn, preset in _TOOLS:
    print(f'  {fn.__name__}')
"
# Expect: ~64 tools (49 existing + 15 new)

# 5. End-to-end complex analysis (manual, Claude Desktop)
#    Run a Zinnia-style Security Model analysis with target ≤12 tool calls:
#    session_create → scaffold(items=7) → holon_create(holons=[root,parent,9 children]) →
#    holon_query(resolution=holarchy) → holon_analyze(coherence) →
#    think(action=branch,children=[findings]) → score_rubric/evaluate → session_export
#    Confirm count ≤12 + N scoring findings.
```

### Observability check (Phase 0 P4 output)

Sample a week of usage after deployment. Log entries with `response_size_bytes > 50KB` should be rare and tied to known large-output tools (session_export, graph_knowledge_summary). If any other tool produces >50KB responses, investigate for truncation bugs.

---

## Documentation Updates

### CLAUDE.md updates required

1. **Tool count correction**: "49 tools" → current count + mention of ~68 after implementation
2. **New "Dual tool families" section** (text in "Coexistence Rules" above)
3. **New "Thinking modes" section** — six modes with selection heuristic from target architecture
4. **New "Batch operations" section** — pattern for batch-aware calls with code examples
5. **Updated "Architecture" diagram** — add bridge.py, scaffold.py, hypothesize.py, self_assess.py, brainstorm.py, iterate.py modules
6. **New "Temporal knowledge graph" subsection** — valid_from/valid_to semantics + `as_of` parameter
7. **Update "Multi-Tenant Model" section** — unified session (parent) vs. direct child session_id

### `.meridian/api-docs/` updates

- Update `mcp-python-sdk.md` if new FastMCP patterns are used (unlikely; current patterns suffice)
- No new external API docs needed

### `.meridian/docs/` new files

- `.meridian/docs/dual-tool-families.md` — decision rationale for scaffold/think_model coexistence
- `.meridian/docs/batch-operations.md` — pattern guide for implementing new batch tools
- `.meridian/docs/unified-sessions.md` — facade architecture + child session routing
- `.meridian/docs/temporal-kg.md` — temporal query semantics + migration notes

Each with frontmatter: `summary: ...`, `read_when: ...`.

---

## Plan Review

Before execution begins, run the **plan-reviewer** agent with this plan file path + the target architecture document + the current exploration findings. The plan must score 9+ to proceed.

Key review questions:
- Does the plan resolve the user's "don't conflict the 2" constraint explicitly? (Yes, section "Coexistence Rules")
- Is every Phase 6 item excluded? (Yes, section "Scope & Non-Goals")
- Does finding_batch carry the warning per user direction? (Yes, Item 9 spec)
- Are file paths and function signatures accurate against current code? (Validated via Explore agents; spot-check during review)

---

## Target Architecture Document Reference

The user's full target architecture document (≈800 lines) describing the 31 items, mode selection heuristic, SCAFFOLD→ELABORATE→ASSESS framework, tool taxonomy, and framework coverage matrix is preserved verbatim in the conversation transcript. Items referenced in this plan:

- P0-P4 → Target doc §9.5 "Required Performance Fixes"
- Items 5-10 → Target doc §10 "Phase 1 — Batch Operations"
- Items 11-13 → Target doc §10 "Phase 2 — Unified Sessions + Bridges"
- Items 14-20 → Target doc §10 "Phase 3 — Enhanced Scaffolding + New Modes"
- Items 21-26 → Target doc §10 "Phase 4 — Infrastructure"
- Items 27-29 → Target doc §10 "Phase 5 — Framework Gap Closure"
- Items 30-31 → Target doc §10 "Phase 6 — Compound Intelligence" — **OUT OF SCOPE per user direction**

Tool taxonomy reference: Target doc §4.2 "Target Tool Taxonomy" (6 categories).

Philosophy principles reference: Target doc §4.1 "Design Principles" (6 principles).

---

## TLDR (end)

15 new tools added across 5 phases to support batch operations, new thinking modes (EXPLORE/DIVERGE/ITERATE), unified sessions with backend bridges, temporal knowledge graphs, and strict forcing-function entry points (scaffold/hypothesize/self_assess). All additions are purely additive: no renames, no removals, no breaking changes to existing 53 tools. Two tool families coexist (strict entry-point vs. flexible logging) with explicit coexistence rules and description conventions. Expected impact: 40-60% round-trip reduction on complex analyses, zero regression on existing flows.
