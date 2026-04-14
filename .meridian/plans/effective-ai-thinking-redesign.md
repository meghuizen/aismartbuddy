# AISmartBuddy — Effective AI-Thinking Redesign

## Verbatim Requirements

### Original Request (current round)

> analyze the mcp server like the analysis from the AI thinking to problems deeply. AI needs structured thinking. Also analyze from your full chat history and it's tool usage, especially on clear-thought and see how this server can help you think better and more structured and give you a higher quality then current clear-thought. Also make sure that MCP tool description can really help structure thoughts and tool use but also instruct AI to really structure it's thoughts and put only needed thoughts and content in the MCP tools. then analyze from an architect point of view. use clear-thought

### Critical follow-up (user-provided insights from prior analytical chat)

> A tool's value = f(schema structure × sequence position). Structured schemas called EARLY = forcing function. Structured schemas called LATE = log. … fat nodes destroy the forcing function … The root cause: think_graph has one text field. … The real abstraction should be: 1 tool call = 1 analytical move, which produces 1 or N structured outputs.

> We might want to be able to create batched calls where you can structure multiple thought trees or graphs in 1 call and not put full text of multiple thoughts in a unstructured way.

### Clarifications so far

| # | Question | Answer |
|---|---|---|
| 1 | Flexible family (think_model / think_science / think_monitor) — remove or keep? | **Keep, tighten descriptions.** |
| 2 | Which of think_collaborate / think_visualize / think_graph_validate / brainstorm / iterate / workflow are worth keeping? | **brainstorm + iterate.** Implicit: collaborate/visualize/validate/workflow = ceremony. |
| 3 | Infra tools (session_create, bridge, session_export, session_snapshot) — keep? | OPEN — to be answered in review pass. |
| 4 | Description rewrite sweep to 20-line convention? | OPEN — to be answered in review pass. |

Multi-backend reality: DuckDB (SQL sessions) + LadybugDB (graph sessions) + in-memory ThinkingEngine dicts, bound to (user_id, project_id). Engines stay isolated — this plan preserves that. No single storage layer.

---

## TLDR

Redesign the thinking-tool surface around ONE organising insight: **tool value = schema structure × sequence position**. Upgrade existing think_model / think_science / think_monitor with an `items[]` batch parameter that enforces per-item required fields (problem, steps, reasoning, conclusion — whichever applies to that tool), so the forcing-function discipline that made clear-thought's mentalmodel high-value is preserved PER ITEM in one round trip. Remove the redundant scaffold / hypothesize / self_assess tools I added — they're already what think_model/science/monitor become when called with `items=[...]`. Add auto-graph: when items[] is submitted in a unified session with a graph backend, each item auto-becomes a KnowledgeNode and `connects_to` fields auto-become edges. Sweep tool descriptions to a uniform 20-line convention that names the phase (SCAFFOLD / ELABORATE / ASSESS) and the rejection rules. Drop feature bloat (workflow, session_export/snapshot, think_collaborate-as-strict). Target tool count: 65+ → ~40.

---

## Context — The Core Insight

Deep AI thinking is not reasoning-recorded-post-hoc. It is reasoning-forced-by-schema-at-the-right-moment.

### Three things that matter for an AI to think well (empirical, from this session):

1. **Sequence position.** A structured-schema tool called BEFORE reasoning has happened forces the reasoning to be structured as it's written. Called AFTER, it's a post-hoc log that wastes tokens. `think_model(first_principles)` was "the single most important call" in the RNA analysis because it was the FIRST call — the schema structured thinking that had not yet happened.

2. **Per-item validation under batching.** Real analytical work produces N related items (7 pathways, 5 tensions, 3 arguments). If the tool forces N calls, round-trips dominate. If the tool takes a fat text blob, the forcing function vanishes ("all 7 analyses" becomes one paragraph). The answer is `items=[...]` where each item is validated against the same per-item schema. One call, N forcing functions, N addressable outputs.

3. **Structural cross-reference, not text search.** Thoughts become queryable when they have IDs and typed links. `connects_to: ["pathway_3"]` inside a scaffold item is more valuable than prose mentioning pathway 3, because the server can later compute "what other items depend on pathway_3?" without NLP.

### Why this server can beat clear-thought

clear-thought is stateless and per-call. Each mentalmodel call is isolated; no cross-tool structure. Good forcing functions, no memory.

aismartbuddy is stateful per session. The engines persist for the session's lifetime. A scaffold item produced in call 3 can be referenced by a score finding in call 27 via its ID. Holons, thoughts, hypotheses, and findings can reference each other. An analysis becomes a queryable graph, not a chat transcript.

That composition + persistence is the server's real competitive advantage. Replicating clear-thought's strict schemas was necessary but not sufficient. The items[] pattern + auto-graph pipeline turn the persistent session into a structurally-navigable reasoning workspace that clear-thought fundamentally cannot offer.

---

## Current State Audit

### What exists today

- 49 original tools + ~15 I added = ~65 registered. See `server.py::_TOOLS` (current lines 236-320).
- 3 engines, isolated: DuckDB (sql), LadybugDB (graph), ThinkingEngine (think/holon/score in-memory).
- Sessions bound to (user_id, project_id); per-session `threading.Lock`; Bearer-auth optional.
- 356 tests green.

### What I got wrong in M0-M5

- **scaffold / hypothesize / self_assess** are redundant. The RIGHT move was to upgrade `think_model` / `think_science` / `think_monitor` with `items[]` batch + per-item schema enforcement. Dual families are a symptom of not recognising the sequence-position insight.
- **workflow** is admitted ceremony (soft-advisory, never blocks). Remove.
- **session_create + bridge + session_export + session_snapshot** solve problems the AI doesn't actually have in practice. Remove or defer.
- **brainstorm** is `think_graph(action="branch", children=[...], min_children=N)` with a fancy name. Could remove; user has chosen to keep.
- **iterate** is a narrow but real tool for coding build-test-learn loops. Keep.
- **data_profile / data_anomalies** are useful shortcuts over DuckDB's SUMMARIZE/window functions. Keep.

### What I got right

- M0 performance fixes (truncation config, timeouts, max_depth, size_guarded, summarize cap) — keep all.
- M1 batch operations on `think_graph`, `holon_create`, `think_argue`, `score_evaluate.finding_batch`, `knowledge_batch` — keep all. These ARE the unit-of-thought pattern.
- Bug fixes from the reviewer pass — keep all.

---

## The Unified Framework: SCAFFOLD → ELABORATE → ASSESS

Every analytical workflow has three phases. A tool is high-value ONLY when called in its native phase.

| Phase | When | Value comes from | Tools (final) |
|---|---|---|---|
| **SCAFFOLD** | First calls in a new analysis. Reasoning NOT yet done. | Required schema forces decomposition that hasn't happened. | `think_model`, `think_science`, `think_decide`, `think_interfere` — **all with items[]** |
| **ELABORATE** | Middle of analysis. Building, branching, connecting. | Flexible storage for evolving ideas, cross-links, navigation. | `think_graph` (already has children[]), `holon_*`, `think_argue` (already has chain[]), `brainstorm`, `iterate`, `think_debug` |
| **ASSESS** | Last. Evaluating what was produced. | Required schema forces honest self-critique. | `score_rubric`, `score_evaluate` (+ finding_batch), `think_monitor` (upgraded with items[]), `rubric_templates` |

### Tool descriptions must NAME the phase

First line of every tool description begins with its phase tag: `[SCAFFOLD]`, `[ELABORATE]`, or `[ASSESS]`. Plus `[DATA]` for SQL/graph data tools that aren't thinking tools.

---

## The Unit-of-Thought Pattern

### The abstraction

```
1 tool call = 1 analytical move that produces 1..N structured outputs.
Each output is an independently addressable item with its own ID.
Each output passed the SAME per-item schema validation.
Cross-references between items are DECLARED structurally (connects_to, responds_to_index),
not buried in prose.
```

### The items[] contract (universal across SCAFFOLD and ASSESS families)

```python
tool_name(
    # tool-specific control fields (model_name, analysis_type, etc.)
    items=[
        {
            "id": str,             # REQUIRED — unique within batch
            # ... per-tool required fields (enforced server-side with REJECTION on missing)
            "connects_to": [id],   # OPTIONAL — cross-refs; auto-graph uses these
            "metadata": dict,      # OPTIONAL
        },
        ...
    ],
    session_id: str,
    auto_graph: bool = False,     # if True + session has graph backend, materialize
)
```

Per-item rejection logic:
- Any missing required field → `ValueError` with item index + missing field name. Whole batch aborts (fail-fast, no partial state).
- Any empty list where ≥1 required → same.
- Any field too short (falsifiability ≥ 20 chars, limitations ≥ 1 entry, etc.) → same.

Return shape:
```
Session: {sid} | Tool: {name} | Items: {N}
Item IDs: id_1, id_2, ..., id_N
Graph nodes created: {M}  (if auto_graph)
Status: scaffolded | hypothesized | monitored | ...
```

### The children[] contract (ELABORATE — think_graph)

Same shape, different name because think_graph's unit is thought-node not forcing-function-item:

```python
think_graph(
    thought: str,        # parent content
    action: str = "branch",
    children: [{"thought": str, "metadata": dict}],
    expected_children: int | None,  # planning horizon; warns at synthesize
    session_id: str,
)
```

Already implemented; preserved as-is.

### The chain[] contract (ELABORATE — think_argue)

Already implemented. Preserved.

---

## Tool Redesign Spec

### SCAFFOLD family — upgrade with items[]

#### `think_model` (UPGRADE, don't replace)

Target description (~18 lines):

```
[SCAFFOLD] Apply a named mental model to 1..N problems. Call FIRST — before
reasoning is done — so the schema forces structure. Called after reasoning is
post-hoc logging (ceremony — skip).

Use when: starting a deep analysis; you have N sub-problems to decompose;
the problem is complex enough that first-principles (or similar) matters.
Do NOT use when: mid-elaboration (use think_graph); you already know the
answer and are just recording it.

Rejects: single-item mode with all fields empty; items[] where any item
lacks problem/steps/reasoning/conclusion; empty items list; unknown model.

Args:
  model_name: one of first_principles, design_review, root_cause, pre_mortem,
    assumptions_xray, error_propagation, complexity, swot, fishbone, pareto,
    opportunity_cost, value_of_info, rubber_duck.
  items: [{id, problem, steps[], reasoning, conclusion, connects_to?, metadata?}]
    — strict per-item; all listed fields required per item.
  problem, steps, reasoning, conclusion: single-item mode (backward compat; lax).
  auto_graph: when True + session has graph backend, auto-create KG nodes.
  session_id: omit to auto-create think session.

Returns: item_ids[] + graph_node_ids[] if auto_graph.
```

Semantics:
- If `items` provided: strict — each item validated, atomic apply under engine lock, returns all item_ids.
- If `items` omitted and single-item fields provided: current behaviour preserved (flexible mid-analysis use — the description now explicitly warns this is log-style).
- If both provided: `items` wins; single-item fields ignored with warning.

Rationale: this IS what scaffold does. Merging eliminates the dual family.

#### `think_science` (UPGRADE)

Same pattern. items shape: `[{id, observation, question, hypothesis: {statement, variables[{name, role}], assumptions[], confidence, falsifiability (≥20 chars)}, connects_to?}]`. Single-item mode preserved for iterative staged use.

Rejects lax submissions in items[] mode — falsifiability < 20 chars, missing variables, empty assumptions.

Rationale: this IS what hypothesize does.

#### `think_monitor` (UPGRADE — ASSESS)

items shape: `[{id, task, knowledge: {domain, level, confidence, limitations[≥1]}, claims[≥1]: [{claim, status, confidence, evidence}]}]`.

Rejects empty limitations. Phase: ASSESS (called LAST for honest self-critique of what was produced).

Rationale: this IS what self_assess does.

#### `think_decide` (UPGRADE)

items shape: `[{id, decision_statement, options[], criteria[{name, weight}], evaluations[], recommendation}]`.

Unblocks multi-decision analyses in one call.

#### `think_interfere` (UNCHANGED)

Already phase-gated. Already forcing. Description rewrite only.

### REMOVE (these become redundant with upgraded SCAFFOLD/ASSESS family)

- `scaffold` → superseded by `think_model(items=[...])`
- `hypothesize` → superseded by `think_science(items=[...])`
- `self_assess` → superseded by `think_monitor(items=[...])`

Unregister from `_TOOLS` list. Delete tool files and tests. Migration: if any existing caller imports these, change to the equivalent `think_*(items=[...])` form.

### ELABORATE family

- `think_graph` — already has children[]. Description rewrite to [ELABORATE] tag + "short thoughts, 1-3 sentences, branch if longer" (already added by me).
- `holon_create`, `holon_update`, `holon_view`, `holon_analyze`, `holon_query` — already work. Description sweep.
- `think_argue` — already has chain[]. Description rewrite.
- `think_debug` — add items[] for batch debugging of N issues.
- `brainstorm` — keep (user choice). Describe as: `[ELABORATE] Generate quantity before quality. Call when DIVERGING. Do NOT use at SCAFFOLD or ASSESS.`
- `iterate` — keep (user choice). Describe as: `[ELABORATE] Lightweight build-test-learn tracker. Use for coding loops where think_graph's tree is overhead.`

### REMOVE (feature bloat)

- `think_collaborate` — single-LLM personas are theatrical. Drop.
- `think_visualize` — stores metadata that never renders. Drop; think_graph metadata covers diagrams.
- `think_graph_validate` — records self-assessment; duplicate of think_graph metadata. Drop.
- `workflow` — admitted soft-advisory (= ceremony). Drop.
- `session_create` + `bridge` + `session_export` + `session_snapshot` — **CONDITIONAL drop**, see the pending Q3 in Clarifications. Default recommendation: drop. The individual backend sessions (`sql_create_session`, `graph_create_session`, `think_create_session`) work fine; unified facade adds a layer without solving a demonstrated pain.

### DATA family (keep as-is)

- `sql_*` tools, `graph_*` tools, `graph_knowledge_*` tools, `knowledge_batch`, `data_profile`, `data_anomalies`, `suggest_database`, `get_youtube_information`, `rubric_templates`, `score_rubric`, `score_evaluate`, `score_gate`. Description sweep only.

### New tool count

- Start: 65+
- Remove 10: scaffold, hypothesize, self_assess, think_collaborate, think_visualize, think_graph_validate, workflow, session_create, bridge, session_export, session_snapshot (11 if snapshot drops too)
- Upgrade with items[]: think_model, think_science, think_monitor, think_decide, think_debug
- **Target: ~40 tools**, all with phase-tagged descriptions ≤ 20 lines.

---

## Auto-Graph Pipeline

Single server-side capability that dramatically multiplies the value of SCAFFOLD tools:

```
think_model(
    model_name="first_principles",
    items=[{id: "p1", ..., connects_to: ["p3"]}, ...],
    auto_graph=True,
    session_id=<parent_session_with_graph_backend>,
)
```

Server actions:
1. Validate and insert N items as ModelRecord (ThinkingEngine).
2. If `auto_graph=True`:
   a. Require parent session with graph backend — else `ValueError`.
   b. For each item, upsert a KnowledgeNode: `name=id`, `description=conclusion[:200]`, `entity_type="concept"`, `source=f"{tool_name}:{model_name}"`.
   c. For each item's `connects_to`, CREATE DerivedFrom edge.
3. Return combined: item_ids[] + graph_node_ids[].

Applied to: `think_model`, `think_science`, `think_monitor`, `think_decide` (when items[] present). Skipped for `think_argue` (chain has sequential dependency, not declared refs) and `think_debug` (rarely cross-references anything).

Impact: Eliminates the manual KG-construction phase. A 7-item scaffold call produces 7 structured records AND 7 KG nodes AND all declared edges, in one round trip.

Because this requires a unified session with both `think` and `graph` backends, this is the ONE infra tool that earns its keep: `session_create(backends=[...])`. Keep it; drop bridge/export/snapshot.

### Reconciliation with Q3

Given auto_graph needs unified sessions:
- **Keep** `session_create` + `session_destroy` (unified multi-backend).
- **Drop** `bridge` (explicit data movement rarely needed once auto_graph exists).
- **Drop** `session_export`, `session_snapshot` (not core to AI-thinking).

---

## Description Convention

Every registered tool's description conforms to this shape, max 20 lines:

```
[<PHASE>] <one-line purpose + who-should-call-it>

Use when: <2-3 specific bullets>
Do NOT use when: <1-2 specific bullets>
Rejects: <server-side rejection rules>

Args:
  <name>: <type> — <one clause, no paragraphs>
  ...

Returns: <one-line output shape>
```

Where `<PHASE>` ∈ `SCAFFOLD`, `ELABORATE`, `ASSESS`, `DATA`, `INFRA`.

No examples in the description (they bloat). Examples go in `.meridian/docs/`. No philosophical framing, no "this tool supports...". Lead with the verb.

Token impact: current descriptions average ~35 lines × 65 tools = ~2275 lines of description payload. Target ~18 lines × 40 tools = ~720. Every AI call loads this payload. **~70% reduction in description tokens.**

---

## Multi-Tenant & Engine Isolation — Unchanged

- 3 engines remain isolated. DuckDB files + LadybugDB files + in-memory ThinkingEngine instances.
- Sessions remain bound to (user_id, project_id). `identity.py::resolve_identity` preserved.
- Per-session `threading.Lock` preserved. Unified session = facade over single-backend children (already implemented in M2-1).
- `items[]` batches execute under one engine-lock acquisition — atomic per batch. Same isolation guarantees; N validations in one round trip.
- The auto_graph path acquires `think_info.lock` and `graph_info.lock` in consistent order (already implemented correctly in M2-4 bridge pattern).

No change to existing auth (Entra / Bearer optional), temp-dir layout, or cleanup lifecycle. No change to max_holons / max_nodes engine limits.

---

## What's Missing (Gap Analysis)

### Genuinely missing (add)

1. **items[] on think_model / think_science / think_monitor / think_decide / think_debug** — this plan's central change.
2. **auto_graph** on the SCAFFOLD/ASSESS family (requires session_create with graph backend).
3. **Phase tags in descriptions** — lightweight metadata that helps the AI pick tools faster.
4. **`min_children` on `think_graph(action="branch", children=[...])`** — subsumes brainstorm's min_ideas discipline; lets us eventually retire brainstorm if desired.
5. **Cross-tool ID references exposed via queries** — today, `refs: list[str]` exists on records but there's no query surface to ask "which findings reference scaffold item X?" Add a `think_refs_query(entity_id)` tool that returns all records mentioning an ID. Small, unique, completes the structural-persistence pitch.

### Not missing (don't add)

- A workflow state machine. The AI knows the phase from the description tags.
- An event bus / side-effect routing. Auto_graph is the ONE side-effect path worth formalising; the rest would be magic.
- Memory palace / cross-session persistence. Out of scope; Claude's own memory + CLAUDE.md handle this.

---

## Migration / Execution Plan

### Step 1 — Audit + Plan Reviewer

Run plan-reviewer. Target 9+. Address findings.

### Step 2 — SCAFFOLD/ASSESS upgrade (highest value)

1. Add items[] parameter + `_validate_items` helper to: `think_model`, `think_science`, `think_monitor`, `think_decide`, `think_debug`. Preserve single-item form for backward compat. Engine helpers `add_model_batch`, `add_inquiry_batch`, `add_monitor_batch`, `add_decision_batch`, `add_debug_batch` (each `@_synchronized`).
2. Add auto_graph parameter + shared helper `_materialize_auto_graph(graph_info, items, source_tag)` in `tools/__init__.py`. Reuse scaffold.py's existing auto_graph logic.
3. Update tests in `test_think_tools.py` to cover items[] paths + rejections.

### Step 3 — Remove redundant tools

Unregister from `_TOOLS`: `scaffold`, `hypothesize`, `self_assess`, `think_collaborate`, `think_visualize`, `think_graph_validate`, `workflow`, `bridge`, `session_export`, `session_snapshot`. Delete their source files and tests. Keep `session_create` and `session_destroy`.

### Step 4 — Description sweep

Rewrite every registered tool's docstring to the 20-line convention above. Affected: ~40 tools. Mechanical; one pass.

### Step 5 — Add `think_refs_query`

New tool, small (~50 LoC): returns all records that include `entity_id` in their `refs` list. One of: ThoughtNode, ModelRecord, InquiryRecord, MonitorRecord, FindingRecord, HolonNode, DecisionRecord. Returns IDs + types, compact.

### Step 6 — `min_children` on think_graph

Add `min_children: int | None = None` to think_graph. When `action="branch"` and `children=[...]` and `len(children) < min_children` → reject. Unit test.

### Step 7 — CLAUDE.md update

Update the "Key patterns" section with:
- New tool count and phase taxonomy
- items[] pattern examples
- Auto-graph behaviour
- Removed tools list (for any cached agent contexts)

### Step 8 — Test suite green check

Run full test suite. Expected ~320 tests post-cleanup (down from 356 because deleted tools take their tests). All must pass. Lint clean. pyright clean.

---

## Files to Create / Modify / Delete

### Modify
- `src/aismartbuddy/tools/think.py` — upgrade think_model, think_science, think_monitor, think_decide, think_debug. Rewrite descriptions.
- `src/aismartbuddy/tools/graph.py`, `tools/holon.py`, `tools/score.py`, `tools/sql.py`, `tools/meta.py`, `tools/youtube.py` — description sweep only (≤ 20 lines each).
- `src/aismartbuddy/tools/__init__.py` — add `_materialize_auto_graph` shared helper.
- `src/aismartbuddy/engines/thinking_engine.py` — add `add_*_batch` helpers analogous to existing `add_node_with_children`.
- `src/aismartbuddy/server.py` — drop removed tools from `_TOOLS`, drop imports for deleted files.
- `CLAUDE.md` — architecture section, tool count, patterns.

### Create
- `src/aismartbuddy/tools/refs.py` — one small tool `think_refs_query`.
- `.meridian/docs/phases.md` — the SCAFFOLD→ELABORATE→ASSESS framework (for AI contexts).
- `.meridian/docs/items-batch.md` — the items[] pattern spec.
- `.meridian/docs/auto-graph.md` — auto_graph semantics + when to opt in.

### Delete
- `src/aismartbuddy/tools/scaffold.py` + its tests in `test_new_modes.py`.
- `src/aismartbuddy/tools/hypothesize.py` + its tests.
- `src/aismartbuddy/tools/self_assess.py` + its tests.
- `src/aismartbuddy/tools/infra.py::bridge`, `::session_export`, `::session_snapshot`, `::workflow` + their tests.
- Portions of `test_batch_ops.py` that exercise bridge.
- `think_collaborate`, `think_visualize`, `think_graph_validate` handlers in `tools/think.py` + their tests (or leave functions un-registered; removing code is cleaner).

---

## Verification

Acceptance criteria:

1. `uv run pytest tests/ -v` → all green (~320 tests after deletions).
2. `uv run ruff check src/ tests/` → clean.
3. `uv run pyright` → clean.
4. `uv run python -c "from aismartbuddy.server import _TOOLS; print(len(_TOOLS))"` → 40 ± 3.
5. Tool-list payload token-count (sum of all tool descriptions) → measure before + after; expect ≥ 50% reduction.
6. Manual smoke test: call `think_model(model_name="first_principles", items=[...7 items...], auto_graph=True)` in a session created with `session_create(backends=["think", "graph"])`. Verify: 7 ModelRecords exist, 7 KnowledgeNodes exist, declared connects_to edges exist. One round trip.
7. Manual rejection test: submit `think_model(items=[{id: "x", problem: "p"}])` — missing steps/reasoning/conclusion. Server returns ValueError naming the missing fields and the item index. No partial state.

Observability check (post-deploy, not a blocker):
- Log response sizes via existing `@size_guarded`. Descriptions alone should drop by ~70%.
- Log forced-rejection rate on SCAFFOLD/ASSESS tools. High rate initially = AI learning the new strictness; should stabilise near zero.

---

## Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | Upgrading think_model/etc. with items[] accidentally tightens the single-item form and breaks existing callers. | Med | items[] param is OPTIONAL. Single-item form's validation is unchanged. Existing tests for single-item paths must stay green. |
| 2 | Auto_graph produces stale KG nodes when items are revised. | Low | Scope: revision is Phase 2 work; auto_graph runs once per items[] call; revisions use explicit graph_knowledge_* if needed. Document this. |
| 3 | AI ignores phase tags and uses tools in wrong phase. | Med | Phase tag + "Use when / Do not use when" in description is strongest we can do without enforcement. If needed, add soft-advisory warnings in tool output, not rejections. |
| 4 | Description sweep introduces prose regressions (too terse, agent can't tell tool apart). | Med | Sweep done tool-by-tool, review diff before commit. Coexistence tests exercise: given two similar tools, does the AI pick the right one? |
| 5 | Removing scaffold/hypothesize/self_assess breaks external MCP callers if any exist. | Low (just us) | No external callers today. Internal tests rewritten to use think_* with items[]. |
| 6 | Auto_graph conflicts with parent session having only think backend (no graph). | High if users forget | Fail-fast with actionable message: `"auto_graph requires graph backend. Create session via session_create(backends=['think','graph'])."` |

---

## Non-Goals (do not implement)

- Temporal knowledge graph (valid_from / valid_to / invalidate / as_of). Already reverted.
- Event bus / automatic cross-tool side effects. Auto_graph is the ONE exception, scoped to SCAFFOLD/ASSESS.
- Memory palace / cross-session persistence. Out of scope.
- think_interfere ban list. User declined.
- Workflow state machine. Removed from plan.
- Bridge tool (explicit data movement). Removed — auto_graph covers the common case.
- Session export / snapshot. Removed.

---

## Plan Review

Before exiting plan mode: run `meridian:plan-reviewer` with this plan path + the verbatim user chat above. Target score 9+. Address findings, re-run until passing.

Key review questions:
- Does the items[] pattern preserve backward compat for every affected tool?
- Is auto_graph's error message actionable when graph backend is missing?
- Are the 11 tools slated for removal actually dead (no other tool imports them)?
- Is the description convention implementable without dropping information agents actually need?

---

## TLDR (again, revised)

Upgrade think_model / think_science / think_monitor / think_decide / think_debug with an `items[]` batch parameter that enforces per-item required fields — this turns them into proper forcing functions when called EARLY, which is the actual insight that made clear-thought's mentalmodel valuable. Add `auto_graph` so items with declared `connects_to` materialise as KnowledgeNode + DerivedFrom edges in one round trip. Remove the redundant scaffold / hypothesize / self_assess tools I added, plus feature bloat (workflow, bridge, session_export/snapshot, think_collaborate / visualize / graph_validate). Sweep every remaining tool's description to a 20-line convention with `[PHASE]` tag. Net: 65 → ~40 tools, descriptions cut ~70%, AI gets strong forcing-function discipline without paying ceremony overhead.
