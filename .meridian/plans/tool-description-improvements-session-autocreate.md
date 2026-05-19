# Plan: Tool Description Improvements + SQL/Graph Session Auto-Create

## Verbatim Requirements

### Original Request
> The think_bridge tool description hints at this ("query thought graph, hypotheses, constraints, evidence, topology") however it's not fully clear on when to use it for what. Also: knowledge_batch exists and would have been perfect for Phase 5, but I didn't know its schema or whether it could handle the volume (51 nodes, 49 edges) in a single call. The tool description says "[ELABORATE] Bulk-create knowledge graph nodes and relations in one call" -- that's exactly what I needed. But without seeing the parameter schema and knowing the limits, I defaulted to building the graph manually. Make the graph queryable for the things I actually needed. graph_analyze and graph_statistics probably do some of this. But the descriptions are too terse for me to know if they do exactly what I need without trial and error. If the descriptions explicitly said "computes degree centrality, betweenness centrality, cycle detection, and minimum vertex cut" I would have used them. The descriptions use tags like [ELABORATE], [SCAFFOLD], [ASSESS], [INFRA] -- useful for categorisation but they don't tell me the PARAMETER SCHEMA. If the key parameters were in the description itself (even abbreviated), I could choose faster. Don't make me create and destroy sessions. Auto-create on first call, auto-persist, auto-resume. The session lifecycle should be invisible. If I call think_graph and there's no session, make one. If the conversation ends, clean up automatically. Every session_create call is friction that pushes me toward stateless tools.

### Clarifications
**Q:** For SQL and graph session auto-creation: what engine config when auto-creating?
**A:** In-memory defaults (same as calling sql_create_session or graph_create_session with no options).

**Q:** For think_bridge description: what's the most important gap to fix?
**A:** List all 6 actions with their required params.

---

## Context

Two compounding problems: (1) tool descriptions don't expose enough to choose the right action without trial-and-error -- actions exist only in code, not docstrings; (2) SQL and graph tools require explicit session_create while think tools auto-create. A full docstring audit found 8 tools with description gaps. The plan fixes all of them and adds SQL/graph auto-create to match think-tool lifecycle behavior.

---

## Current State

### Session auto-create

| Group | Helper | Auto-create? |
|-------|--------|-------------|
| think_*, holon_*, score_* (most) | `_get_or_create_think_session()` think.py:227 | Yes |
| graph_* (most) | `_require_graph_session()` graph.py:28 | No -- raises ValueError |
| sql_* (most) | `_require_sql_session()` sql.py:32 | No -- raises ValueError |

`resolve_active_or_provided_session_id()` (__init__.py:113) is shared by all helpers and already handles the active-session shortcut. `create_session()` in session.py auto-activates the new session if no active session exists yet. Active session is process-wide -- existing architecture, not changed here.

### Tool description gaps (8 tools)

From user feedback + full docstring audit:

| Tool | File | Approx line | Gap |
|------|------|-------------|-----|
| `think_bridge` | think.py | ~3939 | Describes subsystems queried, not the 6 actions or their required params |
| `graph_analyze` | graph.py | ~679 | No mention of the 8 analysis_type values or what each computes |
| `graph_statistics` | graph.py | ~281 | Doesn't clarify what it does NOT compute |
| `knowledge_batch` | graph.py | ~1141 | No volume guidance, no inline parameter shape |
| `think_hypothesis` | think.py | ~3050 | 6 actions not enumerated; per-action params not shown |
| `think_constraint` | think.py | ~3264 | Actions implied but not listed; type and target_type enum values in code only |
| `think_topology` | think.py | ~3549 | 5 actions not enumerated; node role + edge type enums in code only |
| `holon_create` | holon.py | ~88 | Batch item schema shows only 3 required fields; 7 optional fields undocumented |

---

## Changes

### Description rewrites (8 docstrings)

All are docstring-only changes. MCP exposes the docstring directly as the tool description.
Each rewritten description follows the pattern: what it does + what it returns + actions/schema + session_id behavior.

#### 1. `think_bridge` -- think.py ~3939

```
[ELABORATE] Query think session state by entity, node, hypothesis, or topic.
Returns integrated context from the think graph and (if available) the graph backend.

Six actions -- each requires different params:
  full_context(target_id, target_type?)          - everything known about a specific record ID
  thoughts_for_entity(entity_name)               - all ThoughtNodes referencing an entity
  entities_for_thought(node_id)                  - entities referenced in a specific thought node
  hypotheses_for_entity(entity_name)             - hypotheses where entity appears
  evidence_for_hypothesis(hypothesis_id)         - evidence chain + computed strength score
  constraints_for_hypothesis(hypothesis_id)      - constraint validations on a hypothesis

Graph backend lookup is best-effort: if no graph backend, think-side result still returns.
session_id: think session; omit to auto-create or reuse active session
```

#### 2. `graph_analyze` -- graph.py ~679

```
[ELABORATE] Run pre-built graph analysis. Returns formatted text result per type.

analysis_type (required):
  orphans           - nodes with no relationships
  hubs              - top 10 most-connected nodes per type (degree leaders)
  bottlenecks       - same as hubs (highest-degree nodes)
  categories        - group nodes by property values (status, direction, etc.)
  cross_connections - nodes that participate in multiple relationship types
  feedback_loops    - 2-cycle detection: (a)-->(b)-->(a) patterns
  motifs            - recurring patterns: mutual pairs and feed-forward triads
  domain_bridges    - KnowledgeNode edges where r.domain IS NOT NULL

Use hubs/bottlenecks for degree centrality. Use feedback_loops for cycle detection.
Does NOT compute betweenness centrality or minimum vertex cut.
session_id: graph session; omit to auto-create in-memory session or reuse active session
```

#### 3. `graph_statistics` -- graph.py ~281

```
[ELABORATE] Graph overview in one call. Returns node counts by type, edge counts by
type, total nodes, total edges, and top 5 nodes by connection count (text format).
Use before graph_analyze to understand what types and volumes exist.
Does NOT compute centrality metrics -- use graph_analyze(analysis_type="hubs") for degree leaders.
session_id: graph session; omit to auto-create in-memory session or reuse active session
```

#### 4. `knowledge_batch` -- graph.py ~1141

```
[ELABORATE] Bulk-create knowledge graph nodes and relations in one call.
Returns: "Session: X | Nodes added: N | Relations added: R" plus any per-relation errors.

Use INSTEAD of sequential graph_knowledge_add / graph_knowledge_relate when adding 3+
items. No hard volume limit -- tested with 50+ nodes and 49+ edges in a single call.
Invalid items abort the entire batch (fail-fast).

Node schema:     {entity (required), entity_type?, confidence?, properties?, source?}
Relation schema: {from_name, to_name, relation (all required), weight?,
                  justification?, source?, domain?, directionality?, confidence_basis?}

Two-phase: nodes first (so relations can resolve them), then relations.
Single session lock for the full batch.
idempotency_key: optional stable string to deduplicate retried calls.
session_id: graph session; omit to auto-create in-memory session or reuse active session
```

#### 5. `think_hypothesis` -- think.py ~3050

Prepend behavior + session line; add actions block after existing items[] preference note:
```
[SCAFFOLD] Register, compare, update, and invalidate competing hypotheses.
Returns text summary of hypotheses, evidence rankings, or comparison matrix.
PREFER items=[...] (or hypothesis_ids=[...] for invalidate) for batch ops.

Actions:
  register(statement, confidence?, predictions?, prior_weight?, domain?, refs?)
      -- add hypothesis; items=[] for N at once
  evidence(hypothesis_id, evidence_text, direction)
      -- attach supporting or contradicting evidence
  compare()                              -- rank all by evidence strength
  discriminate(hypothesis_ids[>=2])      -- identify discriminating observations
  update(hypothesis_id, new_predictions?, revised_statement?)
  invalidate(hypothesis_id or hypothesis_ids[], reason?, invalidated_by?)

session_id: think session; omit to auto-create or reuse active session
```

#### 6. `think_constraint` -- think.py ~3264

Prepend behavior + session line; add type/target enums and actions block:
```
[ELABORATE] Register constraints and validate targets against them.
Returns validation matrix, compliance results, or constraint list (text format).
PREFER items=[...] (or constraint_ids=[...] for remove).

type:        "hard" (must not be violated) | "soft" (should not be violated)
target_type: hypothesis | thought | model | decision | holon | evaluation

Actions:
  register(constraint_id, domain, type, statement, check_description?, applies_to?)
  list()                                         -- all registered constraints
  remove(constraint_id or constraint_ids[])
  validate(constraint_id, target_type, target_id?, target_text?, status?, note?)
  check_all(target_type, target_id?)             -- sweep all applicable constraints

session_id: think session; omit to auto-create or reuse active session
```

#### 7. `think_topology` -- think.py ~3549

Prepend behavior + session line; add node/edge enums and actions block:
```
[ELABORATE] Define, abstract, compare, and translate domain-neutral structural topologies.
Returns topology definitions, similarity scores, or translated vocabulary (text format).
PREFER items=[...] for define and abstract when creating N topologies.

Node role values: SOURCE | SINK | SENSOR | EFFECTOR | BUFFER | SWITCH | GATE | JUNCTION
Edge type values: AMPLIFIES | SUPPRESSES | DELAYS | SATURATES | OSCILLATES | THRESHOLDS | COUPLES

Actions:
  define(topology_id, name, nodes[{role}], edges[{type}]?, source_description?, source_domain?)
  abstract(source_description, topology_id?, name?, source_domain?, edges?)
      -- infer topology from natural language
  compare(topology_a_id, topology_b_id)         -- structural similarity
  translate(topology_id, target_domain)          -- map into target domain's vocabulary
  search(pattern?)                               -- find matching topologies

session_id: think session; omit to auto-create or reuse active session
```

#### 8. `holon_create` -- holon.py ~88

Add behavior line + complete item schema + session line (keep existing batch-operation guidance):
```
Returns: created holon IDs, holarchy IDs, and parent-child edge summaries (text format).

holons item schema (all fields):
  ref (required)         - temp reference for resolving parent_ref within same batch
  name (required)        - human-readable label
  description (required) - what this holon IS
  parent_ref?            - ref or existing holon_id of parent
  holarchy_id?           - which holarchy; auto-created if this is root
  role_in_parent?        - what this holon DOES as a part
  context?               - working state/knowledge at this level
  rules?                 - internal constraints (list of strings)
  properties?            - observable properties (list of strings)
  projection?            - what this holon exposes upward in the holarchy

session_id: think session; omit to auto-create or reuse active session
```

---

### Session auto-create (2 new helpers + call-site updates)

#### Add `_get_or_create_graph_session()` -- graph.py, after `_require_graph_session()` ~line 42

Mirrors `_get_or_create_think_session()` in think.py:227 exactly:
- Calls `resolve_active_or_provided_session_id(session_id)`
- If resolved: calls `mgr.resolve_backend_session(session_id, "graph")`
- If None: calls `resolve_identity(ctx, None, None)` then `mgr.create_session("graph", user_id, project_id)`

Replace `_require_graph_session(session_id)` with `_get_or_create_graph_session(session_id)` in:
`graph_query`, `graph_import`, `graph_neighbors`, `graph_analyze`, `graph_statistics`,
`graph_schema`, `graph_cross_reference`, `graph_find_connections`, `graph_compare`,
`graph_focus_summary`, `graph_knowledge_add`, `graph_knowledge_relate`,
`graph_knowledge_infer`, `graph_knowledge_summary`, `knowledge_batch`,
`extract_findings_from_graph`

Keep `_require_graph_session` in: `graph_query_next` (needs existing cursor), `graph_destroy_session`.

#### Add `_get_or_create_sql_session()` -- sql.py, after `_require_sql_session()` ~line 49

Same pattern with `"sql"` backend.

Replace `_require_sql_session(session_id)` with `_get_or_create_sql_session(session_id)` in:
`sql_query`, `sql_import`, `sql_import_batch`, `sql_schema`

Keep `_require_sql_session` in: `sql_query_next` (needs existing cursor), `sql_destroy_session`.

---

## Active-Session Edge Case

- **Cold start (no active session):** first sql/graph call auto-creates and auto-activates -- subsequent calls without session_id reuse it (desired auto-persist/resume behavior).
- **Active think session + sql/graph call without session_id:** `resolve_active_or_provided_session_id()` returns the think session ID -- `resolve_backend_session(think_id, "sql")` fails with a clear "no sql backend" error. Not a regression. User must pass explicit session_id or use a unified session.

---

## Non-Goals

- Per-backend active session tracking in SessionManager
- Changing `holon_query` or `score_gate` (intentionally use `_require_think_session`)
- Adding `ctx: Context` parameter to SQL/graph tool signatures (`resolve_identity(None, None, None)` falls back to defaults; sufficient for auto-create)

---

## Verification

```bash
uv run pytest -v                       # no regressions
uv run pyright                         # type check passes
uv run ruff check src/ tests/          # lint clean

# Functional smoke tests:
# - call graph_analyze(analysis_type="hubs") without session_id -- auto-creates + returns
# - call sql_query("SELECT 1") without session_id -- auto-creates + returns
# - inspect 8 updated docstrings to confirm actions/schema visible
```

---

## TLDR

Eight docstring rewrites that add action enumerations, inline parameter schemas, enum values, return-value descriptions, and session_id behavior so tool selection requires no trial-and-error; plus two `_get_or_create_*` session helpers for SQL and graph tools (mirroring the existing think-tool pattern) that eliminate the mandatory `session_create` ceremony for the common in-memory workflow.
