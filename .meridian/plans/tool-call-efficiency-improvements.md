# AISmartBuddy — Tactical Tool-Call Efficiency Improvements

## Verbatim Requirements

### Original Request
> Analyze this current MCP server for your help to think and also the ability to think through high complex problems without reaching tool usage limits. Come up with possible improvements

### Clarifications
**Q:** What's the primary pain you're hitting today when thinking through complex problems? (multi-select)
**A:** Too many tool calls per workflow

**Q:** How aggressive should the change set be?
**A:** Tactical, additive only. Selected preview:
> + auto_graph=True on think_graph/think_decide/holon_create/think_argue/think_validate
> + items=[] on think_hypothesis/think_constraint/think_evidence/think_topology
> + Trim ceremony in score_evaluate response, drop redundant Session: echo
> + Phase tags + auto_graph mention on ~30 docstrings
> + Fix README stale tool list
> - No new tools, no signature changes
> - Single-form paths preserved

**Q:** What kind of complex problems do you actually try to think through? (multi-select)
**A:** Software design / architecture decisions; Strategic / business analysis; Debugging / root-cause investigation; Knowledge synthesis from data — all four.

**Q:** Are breaking changes to existing tool signatures OK?
**A:** Strictly additive — no breaks (Recommended)

**Q:** score_evaluate needs 3 sequential calls today. Cheapest additive fix?
**A:** Add auto_finalize flag to batch_findings (Recommended). Selected preview:
> score_evaluate(action="batch_findings", evaluation_id=eid, findings=[...],
>   auto_finalize=True, summary="...", dimensions_reviewed=[...])

**Q:** auto_graph default behavior when adding to more tools?
**A:** Default False, opt-in. Same convention as existing think_model/think_science/think_monitor.

---

## Context

The aismartbuddy MCP server has *good bones* for assisted thinking — strict items[] forcing function, auto_graph KG materialisation, runtime `Suggested next:` hints, parent-session multi-backend facade — but coverage is uneven. Half the batch-capable tools never had the items[] retrofit applied. auto_graph exists on 3 of the 6 SCAFFOLD/ASSESS tools that have items[]. `score_evaluate` forces a strictly-3-call sequence even when the agent has all the findings ready up front. The result: a complex-reasoning workflow that should take ~5-8 calls today takes ~25-35 calls in practice when every single-record-action tool is involved.

This change set is strictly additive. New optional parameters with safe defaults, new batch actions on action-dispatch tools, new auto_graph plumbing using the **already-existing** `materialize_auto_graph` helper. Single-form and current-action call shapes keep working unchanged. The win is concentrated where the agents already do the most work: framing → hypothesising → elaborating → scoring → deciding.

**Estimated impact** (typical "frame + hypothesise + branch + score + decide" run, ALL four problem types):

| Phase | Today | After |
|---|---|---|
| Setup | session_create + auto-create overhead | 1 call |
| Framing (3 mental models) | 3 × `think_model` | 1 × `think_model(items=[3])` (already supported) |
| Hypotheses (5 competing) | 5 × `think_hypothesis(action="register")` | 1 × `think_hypothesis(action="register", items=[5])` ⭐ list-form |
| Constraints (3 to register) | 3 × `think_constraint(action="register")` | 1 × `think_constraint(action="register", items=[3])` ⭐ list-form |
| Evidence (4 pieces) | 4 × `think_evidence(action="register")` | 1 × `think_evidence(action="register", items=[4])` ⭐ list-form |
| Branch tree (8 thoughts) | 1 × `think_graph(thoughts=[8])` + 8 × `graph_knowledge_add` | 1 × `think_graph(thoughts=[8], auto_graph=True)` ⭐ NEW |
| Score (1 rubric, 6 findings) | start + batch_findings + finalize = 3 calls | 1 × `score_evaluate(action="batch_findings", auto_finalize=True)` ⭐ NEW |
| Decide | 1 × `think_decide(items=[1])` | 1 × `think_decide(items=[1], auto_graph=True)` ⭐ NEW |

**~30 calls → ~8 calls**, and every artifact ends up in the KG without manual `graph_knowledge_*` orchestration.

---

## Current State

### Helpers that get reused
- `tools/__init__.py:123 validate_items(items, required, *, tool, item_validators)` — strict per-item validator. Already used by 8 tools. Universally reusable for new items[] retrofits.
- `tools/__init__.py:175 collect_item_refs(item)` — dedupes `connects_to` + `refs` into one list.
- `tools/__init__.py:191 materialize_auto_graph(parent_session_id, items, *, source_tag, entity_type, description_field, edge_label)` — generic KG materialiser. Currently hardcodes `connects_to` as the source-of-edges field at line 274. Needs ONE small change (new `ref_field` parameter) before it can power `think_graph` (parent_ref) and `think_argue` (responds_to_index).
- `tools/__init__.py:213-222` — auto_graph pre-condition error message is the gold standard ("requires a graph backend... session_create(backends=['think','graph'])"). Reuse for the new tools.

### Engine helpers already atomic / locked
- `engines/thinking_engine.py:752 add_nodes_batch(specs)` — full forest under one lock. Powers `think_graph(thoughts=[...])`.
- `engines/thinking_engine.py:1051 add_holons_batch(specs)` — same for holons. Powers `holon_create(holons=[...])`.
- `engines/thinking_engine.py:1683 validate_subject(...)` — atomic per-call. Bulk = loop.
- `engines/thinking_engine.py:2127 apply_finding(...)` and `:2222 finalize_evaluation(...)` — both `@_synchronized`. Composable into auto_finalize.
- `engines/thinking_engine.py:973 add_model`, `:985 upsert_decision` — single-record helpers fine to loop under one items[] handler.

### Where the items[] pattern is missing today
- `think_hypothesis` (`tools/think.py:2811`) — actions register / evidence / compare / discriminate / update / invalidate, ONE record per call.
- `think_constraint` (`tools/think.py:2939`) — actions register / validate / list / remove / check_all.
- `think_evidence` (`tools/think.py:3276`) — actions register / chain / trace / strength / list.
- `think_topology` (`tools/think.py:3139`) — actions define / abstract / compare / translate / search.

### Where auto_graph is missing today
- `think_graph(thoughts=[...])` (`tools/think.py:728`, batch path 883) — biggest leverage; parent_ref → `BranchOf` edge.
- `think_decide(items=[...])` (`tools/think.py:1157`).
- `think_argue(chain=[...])` (`tools/think.py:1705`) — responds_to_index → `RespondsTo` edge.
- `think_validate(items=[...])` (`tools/think.py:2487`) — subject_id → `Validates` edge.
- `holon_create(holons=[...])` (`tools/holon.py:153`) — parent_ref → `PartOf` edge.

### score_evaluate today
- `tools/score.py:436` entry point. `batch_findings` action at `:653`. `finalize` action at `:786`.
- Engine path is already `upsert_evaluation → loop apply_finding → finalize_evaluation` (all atomic). Adding `auto_finalize=True` is plumbing, not new logic.
- Response ceremony per call: `Session:` header, `evaluation_id:` echo, `Results:` JSON list, `Running scores:` arrow chain, `Final:` line, `Finding IDs:` line. The `Running scores:` arrow chain duplicates per-finding running_score that's already in `Results` JSON.

### Documentation state
- `README.md:522-528` lists `think_collaborate` and `think_visualize` — both **removed** per CLAUDE.md "Removed tools" section. Stale.
- ~30 reasoning tool docstrings missing the `[SCAFFOLD] / [ELABORATE] / [ASSESS] / [INFRA]` phase tag.
- `_compose_next_hint` runtime feature is genuinely useful but documented in zero places agents read.

---

## Changes

### 1. `tools/__init__.py` — extend `materialize_auto_graph`

Add two optional parameters:

- `ref_field: str = "connects_to"` — name of the per-item field holding outgoing-edge targets. Replace the hard-coded `item.get("connects_to") or []` at line 274 with `item.get(ref_field) or []`.
- `ref_resolver: Callable[[Any], str | None] | None = None` — generic resolver applied to every ref value. Returns the final node-name string the edge should point to, or `None` to mean "use the value as-is". This single resolver handles:
  - **think_argue** — int chain-index → assigned argument id.
  - **think_graph** — `parent_ref` may be int (batch index) OR str (existing node_id) OR None (root); resolver maps int → batch-id, returns None for str (passes through), and for None the empty list short-circuits the edge loop entirely.
  - **holon_create** — `parent_ref` may be a batch-ref-string OR an existing-holon-id-string; resolver looks up batch-ref in `ref_to_id` map (returned by `add_holons_batch`), returns None for unknown values to let them pass through as existing ids.

The single resolver design replaces the earlier proposal of an int-only resolver, which couldn't cover the holon string-ref case.

### 2. `tools/think.py` — extend existing actions to accept list-form input on 4 single-record tools

**Design choice:** do NOT add new `*_batch` actions. Instead, extend the EXISTING action handlers (`register`, `invalidate`, `remove`, `chain`, `define`) to accept a list-form input alongside the current single-record arguments. The agent learns one rule — "if you have multiple, pass items=[...] (or `*_ids=[...]` for id-only actions); otherwise keep using the single args" — and no new action names enter the surface area. Single-form remains the backward-compat default; items[] enables 1-or-more in one call.

| Tool | Action | List-form parameter | Per-item / per-id schema | Reuses |
|---|---|---|---|---|
| `think_hypothesis` | `register` | `items: list[dict]` | id, statement, kind, confidence (defaults applied) | `validate_items` + loop `engine.upsert_hypothesis` |
| `think_hypothesis` | `invalidate` | `hypothesis_ids: list[str]` | id strings | loop `engine.invalidate_hypothesis` |
| `think_constraint` | `register` | `items: list[dict]` | id, domain, type, statement | loop `engine.upsert_constraint` |
| `think_constraint` | `remove` | `constraint_ids: list[str]` | id strings | loop `engine.remove_constraint` |
| `think_evidence` | `register` | `items: list[dict]` | id, claim_id, content, source, direction | loop `engine.upsert_evidence` |
| `think_evidence` | `chain` | `items: list[dict]` | id, from_id, to_id, justification | loop `engine.add_evidence_chain` |
| `think_topology` | `define` | `items: list[dict]` | id, domain, nodes[], relations[] | loop `engine.upsert_topology` |

**Dispatch rule per action:**
1. If the list-form parameter (`items` or `*_ids`) is non-empty → list-form path: validate via `validate_items` (or simple `isinstance(x, str) and x` for id lists), loop the engine helper under one `state_lock`, return aggregated response.
2. Else if the single-record arguments are populated → existing single-record path (untouched).
3. Else → existing single-record error path (also untouched).

**Items[] of size 1 is allowed and explicitly encouraged in the docstring** — the agent should default to items[] even for one record because it makes scaling to N trivial later. The existing `validate_items` helper already accepts N≥1 (rejects only empty lists), so no change there.

**Mutual exclusion**: if a caller passes BOTH list-form AND single-record args in the same call, raise `ValueError("<tool>.<action>: pass either items=[...] (preferred) or single-record args, not both.")`. This prevents ambiguous semantics.

**Docstring pattern** for each action: phase tag, "Use when / Do NOT use when", "PREFER items=[...] (or *_ids=[...]) for one-or-many — the list form scales without added round-trips. Single-record args remain supported for backward-compat." Error messages reuse `validate_items` so wording matches the existing high-quality tools.

### 3. `tools/think.py` — add `auto_graph` to existing batch tools

Wire `auto_graph: bool = False` parameter into:

- `think_graph(thoughts=[...], auto_graph=False)` (`tools/think.py:728`). When True, calls `materialize_auto_graph(... ref_field="parent_ref", edge_label="BranchOf", entity_type="thought", description_field="thought", ref_resolver=<int → batch-id, str passes through, None → no edge>)`. Skip nodes whose `parent_ref` is None (root thoughts).
- `think_decide(items=[...], auto_graph=False)` (`:1157`). `entity_type="decision"`, `description_field="recommendation"`, `edge_label="DerivedFrom"`. Same pattern as existing think_model items[] path.
- `think_argue(chain=[...], auto_graph=False)` (`:1705`). `ref_field="responds_to_index"`, `edge_label="RespondsTo"`, `entity_type="argument"`, `description_field="claim"`. ref_resolver maps int chain-index → argument id.
- `think_validate(items=[...], auto_graph=False)` (`:2487`). `ref_field="subject_id"`, `edge_label="Validates"`, `entity_type="validation"`, `description_field="rationale"`. Note: `subject_id` is a string, not a list — small adapter wraps it as `[subject_id]` for materialize_auto_graph. **Caveat**: the Validates edge target is only a real node if the subject was previously materialised as a KnowledgeNode (e.g., via auto_graph on `think_decide`/`think_model` earlier in the session). Otherwise the edge silently skips (existing behaviour at `tools/__init__.py:285-289`). Document this in the docstring so callers understand: "Validates edges require the subject_id to already be a KnowledgeNode — chain auto_graph from your scaffold/decision tools or expect the edge to be skipped."

For each tool, the auto_graph pre-condition error message is the existing canonical: `"auto_graph requires a graph backend in this session. Create the session via session_create(backends=['think','graph'])."` Reuse the existing wrapping in `materialize_auto_graph`.

### 4. `tools/think.py` — verbosity trims (additive opt-in via existing path)

These are surgical removals of pure-redundancy lines, not signature changes:

- **think_model single-form** (`:1583-1599`): `_MODEL_GUIDANCE` framework block currently emits whenever `steps and conclusion` are absent. The intent is "tutorial on first encounter, skip on repeat". The correct gate is a **session-level model-count check**: only emit when `len(engine.get_models()) == 0` (or equivalent — confirm the engine accessor name during implementation; it's part of `engines/thinking_engine.py` ModelRecord storage). The local `record_id` is NOT a session-level counter (it's only set when `rule_profile_ids` is passed), so do not gate on `record_id`. Saves ~5 lines on every think_model call after the first in a session.
- **Long-thought warnings** (`_long_thought_warnings`, `:688`): emit a single-line summary `"Note: 2 thoughts >120 chars (use action='branch' to split)"` instead of one line per long thought. Detail re-enabled via existing `verbose=True` parameter (already accepted by the tool).
- **`Session:` header line** in items[] response builders: keep when single-form (agent may have just auto-created the session and needs the id), drop when items[]/batch path AND `session_id` was explicitly passed (agent already has it). This is ~50-80 bytes per items[] call. Enumerated builders to edit (each retains its single-form sibling untouched):
  - `tools/think.py:1257-1263` — `think_decide` items[] response
  - `tools/think.py:1551-1561` — `think_model` items[] response
  - `tools/think.py:1673-1677` — `think_debug` items[] response
  - `tools/think.py:~1820` — `think_argue` chain[] response (verify exact line during implementation)
  - `tools/think.py:~1990` — `think_science` items[] response
  - `tools/think.py:~2195` — `think_monitor` items[] response
  - `tools/think.py:2547-2551` — `think_validate` items[] response
  - The 4 NEW `*_batch` action response builders being added in Section 2 (`think_hypothesis.register_batch`/`invalidate_batch`, `think_constraint.register_batch`/`remove_batch`, `think_evidence.register_batch`/`chain_batch`, `think_topology.define_batch`) — design with the trim baked in from the start.

  Single-form sibling response paths in each tool are NOT touched. Verify with a targeted unit test per tool: capture the exact bytes of a single-form response before and after the change; assert no diff.

### 5. `tools/holon.py` — add `auto_graph` to `holon_create`

Wire `auto_graph: bool = False` into `holon_create(holons=[...])` (`tools/holon.py:153`). For each holon item: KnowledgeNode with `entity_type="holon"`, `description_field="description"`. For each `parent_ref` (which may be a batch-ref or existing id): `PartOf` edge from this holon's id → parent.

**Adapter step** (load-bearing detail): `holon_create` items use `ref` as a temp identifier and `add_holons_batch` returns a `ref_to_id: dict[str, str]` mapping ref → assigned holon-id. Before calling `materialize_auto_graph`, build a synthetic items list:

```
synthetic = [
    {"id": ref_to_id[h["ref"]],
     "description": h.get("description", ""),
     "parent_ref": [ref_to_id.get(h["parent_ref"], h["parent_ref"])] if h.get("parent_ref") else []}
    for h in holons
]
```

This (a) keys KnowledgeNode rows on the FINAL assigned id (matching how downstream tools reference holons), (b) maps batch-ref parent values through the same lookup, (c) lets existing-id parents pass through unchanged via `dict.get`'s fallback. Pass `synthetic` to `materialize_auto_graph(ref_field="parent_ref", ref_resolver=None, edge_label="PartOf", entity_type="holon", description_field="description")`.

Existing `_materialize_subject_rule_bindings` (think.py:563) — leave alone; that's a different best-effort path.

### 6. `tools/score.py` — `auto_finalize` on `batch_findings`

`score_evaluate(action="batch_findings", ...)` at `tools/score.py:654`. Add **one** new optional parameter:

- `auto_finalize: bool = False`

The existing `summary` and `dimensions_reviewed` parameters (already on the function signature, used by `action="finalize"`) are reused when `auto_finalize=True`. No new parameters for them.

When `auto_finalize=True`: after the existing `apply_finding` loop completes, call `engine.finalize_evaluation(eval_id, summary, dimensions_reviewed)` under the same lock. Append the finalize block (final score + dimension table) to the same response. Net effect: 3 round-trips collapse to 1 for the common end-of-analysis case.

Validation: when `auto_finalize=True`, require `summary` to be non-empty. Error message: `"auto_finalize=True requires a 'summary' parameter — finalize records the evaluation conclusion. Without a summary, use action='finalize' separately."`

### 7. `tools/score.py` — verbosity trim on batch_findings

- Drop the `Running scores: 9.5 -> 9.0 -> 8.5 -> ...` arrow chain at `score.py:733-742`. The same per-finding running_score is already present in the `Results: [{...}]` JSON. Roughly 15-30 bytes saved per finding.
- Drop the `evaluation_id: <hex>` echo line at `:546, :644, :766, :798, :840`. Agent passed it in.
- Keep `Final: <score>/<max> (threshold X) | <verdict>` — load-bearing.
- Keep `Finding IDs: ...` — load-bearing for downstream `analysis_refs`.

### 8. Docstring sweep (~30 tools) — phase tags + auto_graph + Suggested-next

**Implementation note:** several tools listed in earlier audits already carry phase tags (`think_decide` at `:1173` has `[SCAFFOLD]`, `think_debug` at `:1618` has `[ELABORATE]`, `think_validate` at `:2500` has `[ASSESS]`). The implementer must **enumerate the actually-missing set first** before editing — run a grep over docstrings for the existing tag pattern and skip tools that already have one. Do not double-tag.

For each reasoning tool currently missing a `[SCAFFOLD] / [ELABORATE] / [ASSESS] / [INFRA]` first-token tag, add it. Candidate tools (verify each is truly missing before editing):

- ELABORATE: `think_graph`, `think_argue`, `think_constraint`, `think_topology`, `think_evidence`, `think_bridge`, `think_summarize` (call it `[RESUME]` or `[ASSESS]` per recommendation), `think_get_subtree`, `think_get_path`, `think_export_session`, `think_link_sessions`, `think_get_session_links`, `think_set_active_session`, `think_graph_validate`, `think_interfere`, `holon_create`, `holon_update`, `holon_view`, `holon_analyze`, `holon_query`, `iterate`, `brainstorm`, `knowledge_batch`.
- ASSESS: `score_rubric`, `score_evaluate`, `score_gate`, `rubric_templates`.
- SCAFFOLD: `think_hypothesis` (it's a SCAFFOLD-family record; older API shape).

For tools that gain `auto_graph` (think_graph, think_decide, think_argue, think_validate, holon_create), add to docstring: `"Pass auto_graph=True (requires session_create(backends=['think','graph'])) to materialise each item as a KnowledgeNode + edges in one round-trip."`

For tools that emit `_compose_next_hint` (think_model, think_science, think_monitor, think_decide, think_argue, think_graph synthesise, plus all NEW auto_graph tools): add `"Returns a 'Suggested next:' line at end of response with canonical follow-up call pre-filled. Read it before deciding the next step."`

For the 4 single-record tools that gain list-form input on existing actions: add `[SCAFFOLD]` or `[ELABORATE]` tag plus `"PREFER items=[...] (or *_ids=[...] for invalidate/remove) on every action when handling one-or-more records — list-form scales without added round-trips. Single-record args remain supported for backward-compat."`

### 9. Single-form error redirects to items[]

For each tool with both single-form and items[] paths, the `"X is required for single-form"` error path should suggest the items[] alternative. Concretely (file:line):

- `tools/think.py:1268-1269` (think_decide): `"single-form requires decision_statement, options, decision_id. PREFER items=[{id, decision_statement, options, criteria, recommendation}, ...] for batch decisions."`
- `tools/think.py:960` (think_graph): `"thought is required in single-node mode. PREFER thoughts=[{thought, parent_ref, ...}, ...] for batch creation — same lock, fewer round-trips."`
- `tools/think.py:1764` (think_argue): `"chain must be non-empty. Use chain=[...] (PREFERRED) or single-mode with claim+premises+conclusion."`
- `tools/think.py:2008` (think_science): `"inquiry_id required for single-stage form. PREFER items=[{id, observation, question, hypothesis:{...}}, ...] for batch hypotheses."`
- `tools/think.py:2211` (think_monitor): `"monitoring_id required for single-form. PREFER items=[{id, task, knowledge:{...}, claims:[...]}, ...] for batch self-assessment."`

These are pure error-message edits — no behavioural change.

### 10. `README.md` — remove stale tool list entries

`README.md:522-528` currently lists `think_collaborate` and `think_visualize`. Both are documented as removed in CLAUDE.md's "Removed tools" section. Delete the two lines. Also add a brief mention of items[] / auto_graph for parity with the in-tree CLAUDE.md.

---

## Files Modified

```
src/aismartbuddy/tools/__init__.py        — materialize_auto_graph: ref_field, int_ref_resolver
src/aismartbuddy/tools/think.py           — 4 new batch actions, 4 auto_graph wirings,
                                              verbosity trims, error redirects, docstrings
src/aismartbuddy/tools/holon.py           — auto_graph on holon_create, docstring sweep
src/aismartbuddy/tools/score.py           — auto_finalize on batch_findings, verbosity trim,
                                              docstring sweep
README.md                                 — remove stale tool list entries
tests/                                    — new tests for each change (see verification)
```

CLAUDE.md update: add a one-paragraph note that auto_graph now also covers think_graph / think_decide / think_argue / think_validate / holon_create. The existing CLAUDE.md "auto-graph pipeline" subsection is the natural home — extend the bullet list.

---

## Test Plan

New unit tests (one per change point):

- `tests/test_think_tools.py` — for each extended action (`think_hypothesis.register` with `items=[]`, `.invalidate` with `hypothesis_ids=[]`; `think_constraint.register` with `items=[]`, `.remove` with `constraint_ids=[]`; `think_evidence.register` with `items=[]`, `.chain` with `items=[]`; `think_topology.define` with `items=[]`): verify list-form forcing function — empty list rejected, missing field rejected with index+id+field, duplicate id rejected, list of N=1 succeeds (single-item-in-list is the encouraged shape), list of N=K creates K records under one lock. Verify mutual-exclusion error when BOTH list-form and single-record args are passed. Verify backward-compat — single-record-args path still works byte-for-byte.
- `tests/test_think_tools.py` — for each `auto_graph` retrofit (think_graph, think_decide, think_argue, think_validate): create a parent session with both backends, run the batch tool with `auto_graph=True`, verify N KnowledgeNode rows created with the expected `entity_type`, expected number of edges with the expected `edge_label`, and that calling auto_graph=True on a think-only session raises the canonical "requires graph backend" error.
- `tests/test_holon_tools.py` — same pattern for `holon_create(holons=[...], auto_graph=True)`. Verify `PartOf` edges from parent_ref-as-batch-ref AND parent_ref-as-existing-id.
- `tests/test_score_tools.py` — `score_evaluate(action="batch_findings", auto_finalize=True, summary="...", dimensions_reviewed=[...])` produces the same final score + dimension table as the equivalent two-call sequence (start → batch_findings → finalize). Test missing `summary` raises the new error. Test `auto_finalize=False` (default) preserves current behaviour byte-for-byte.
- `tests/test_score_tools.py` — assert the redundant `Running scores:` arrow chain is GONE from the response, and `evaluation_id:` echo is GONE. Assert `Final:` and `Finding IDs:` are still present.
- `tests/test_think_tools.py` — assert error messages on `think_decide(action default)`, `think_graph(thought=None)`, `think_science(stage_call default)`, `think_monitor(default)` mention `items=[...]` / `thoughts=[...]` / `chain=[...]`.

End-to-end manual verification:

1. `uv run pytest -v` — all green (existing + new).
2. `uv run pyright` — no new type errors.
3. `uv run ruff check src/ tests/` — clean.
4. Spin up the server (`uv run python -m aismartbuddy --transport sse --port 8000`) and run a complex-reasoning workflow against it via MCP Inspector or a test client:
   - `session_create(backends=["think","graph"], mode="analyze")` → parent_id
   - `think_model(model_name="first_principles", items=[3 items with connects_to], auto_graph=True, session_id=parent_id)`
   - `think_hypothesis(action="register", items=[5], session_id=parent_id)` ← NEW list-form on existing action
   - `think_constraint(action="register", items=[3], session_id=parent_id)` ← NEW list-form on existing action
   - `think_evidence(action="register", items=[4], session_id=parent_id)` ← NEW list-form on existing action
   - `think_graph(thoughts=[8 with parent_ref], auto_graph=True, session_id=parent_id)` ← NEW auto_graph
   - `score_evaluate(action="start_with_rubric", rubric_id="design_review", dimensions=[...], session_id=parent_id)` → eval_id
   - `score_evaluate(action="batch_findings", evaluation_id=eval_id, findings=[6], auto_finalize=True, summary="...", dimensions_reviewed=[...], session_id=parent_id)` ← NEW auto_finalize
   - `think_decide(items=[1 with connects_to=[eval_id, hypothesis_ids]], auto_graph=True, session_id=parent_id)`
   - Confirm: 8 round-trips total, zero manual `graph_knowledge_*` calls, KG fully populated.

---

## Non-Goals

- **No new "macro" tools.** No `think_decide_and_score`, no `think_frame`, no `think_hypothesis_tree`, no `reasoning_session`. Single-tool changes only.
- **No breaking changes to any existing call shape.** Every current parameter, action value, and return shape keeps working byte-for-byte (except for the verbosity-trim removals that are the documented intent).
- **No deletion of the `reasoning_v2.py` legacy / dead code.** That cleanup is a separate task.
- **No unification of `refs` vs `connects_to` semantics.** They keep their current behavioural asymmetry (only `connects_to` produces auto_graph edges). DOCUMENT the asymmetry in CLAUDE.md but don't change the dispatch in `materialize_auto_graph`.
- **No removal of the `score_evaluate(action="finding")` single-finding path** or the `finding_batch` alias warning. Both stay.
- **No changes to `think_interfere`'s 11-action state machine.** The high call count is by design (saturation enforcement). Out of scope.
- **No changes to `think_summarize`'s always-on cross-backend graph queries.** The 1-2 hidden round-trips are noted but stay; making opt-in would change return shape for existing callers in subtle ways.
- **No new MCP prompts.** The `aismartbuddy-guide` prompt update is in scope; adding `items-batch-form-guide` as a separate prompt is not.
- **No changes to annotation presets** (`_DEFAULT` / `_READONLY` / `_READONLY_OPEN` / `_DESTRUCTIVE`).
- **No `next_actions: [{tool, args}]` structured-hint field.** Today's text-form `Suggested next:` line stays.

---

## Acceptance Criteria

- All existing tests in `tests/` pass with no modifications.
- All new tests pass.
- `uv run pyright` and `uv run ruff check` clean.
- Calling any of the 4 extended actions with malformed `items=[...]` returns an error message matching the existing `validate_items` template (`"<tool>.items[<i>] (<id>) missing required '<field>' — strict items[] form rejects lazy submissions."`). Calling them with both `items=[...]` AND single-record args raises the new mutual-exclusion error.
- Calling any of the 5 new `auto_graph=True` paths against a session WITHOUT a graph backend returns the canonical `"auto_graph requires a graph backend in this session. Create the session via session_create(backends=['think','graph'])."` error.
- Calling `score_evaluate(action="batch_findings", auto_finalize=True)` without `summary` returns the new explicit error.
- Calling `score_evaluate(action="batch_findings", auto_finalize=True, summary=..., dimensions_reviewed=...)` produces a response that contains, in order: per-finding `Results:` JSON list, `Final:` line, dimension table — and DOES NOT contain `Running scores:` arrow chain or `evaluation_id:` echo.
- README.md no longer lists `think_collaborate` or `think_visualize`.

---

## TLDR

Cut tool-call count for a typical complex-reasoning workflow from ~30 round-trips to ~8 by extending four older single-record-action tools (`think_hypothesis` / `think_constraint` / `think_evidence` / `think_topology`) with optional `items=[...]` (or `*_ids=[...]`) list-form inputs on their **existing** actions — no new action names, single-record args still work — extending `auto_graph` to five more batch tools (`think_graph` / `think_decide` / `think_argue` / `think_validate` / `holon_create`) using a small generalisation of the already-shipping `materialize_auto_graph` helper, and adding `auto_finalize=True` to `score_evaluate.batch_findings` so the start→findings→finalize triple collapses into a single call. All strictly additive — every existing call shape keeps working — plus a docstring sweep and a stale-README-tool-list fix to stop the agent from wasting calls discovering the right form.
