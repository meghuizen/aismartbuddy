# AISmartBuddy — Description Sweep + Gap Fixes

## Verbatim Requirements

### Original Request (this round)

> fix those gaps, do a proper description sweep, where you steer the AI, ask it to be concise and clear and focused use of the item. good at proper one shotting the calls. Correctly putting structure around the calls in the description. give the AI an idea which tool to use for what use cases. use your own behaviour as reflection

### Source: my own honest reflection (previous turn)

> If S4 [description sweep] happened, the effectiveness grade goes from 7/10 to 9/10 for the right scenarios. … 55 tools is still a lot — without uniform phase tagging, AI wastes calls picking. … Dual form (items[] vs single) creates choice paralysis. … `think_refs_query` needs upstream `refs:` — but `items[].connects_to` makes graph edges, not refs. Two different cross-reference mechanisms. … `auto_graph` needs explicit `session_create` — but other think tools auto-create. Inconsistent session creation paths. … `think_interfere` is still 16 actions and phase-gated, never sweep-cleaned.

### Clarifications

| # | Question | Answer |
|---|---|---|
| 1 | auto_graph friction (no session_id) | **Auto-create unified session** with backends=['think','graph'] |
| 2 | Cross-ref mechanism unification | **Unify on `refs` field** — items[].connects_to populates BOTH refs AND graph edges |
| 3 | Description budget | **20 lines soft cap** per tool |
| 4 | Single-form on think_model/science/monitor | **Remove single-form entirely** — items=[...] becomes required |

---

## TLDR

Sweep all 55 tool descriptions to a uniform 20-line convention with `[PHASE]` tags, explicit `Use when / Skip when / Rejects` sections, and concise args. Concurrently fix the four real gaps: (1) auto_graph auto-creates the unified session when needed; (2) `refs` becomes the single cross-reference mechanism (added to ModelRecord/InquiryRecord/MonitorRecord/DecisionRecord/DebugRecord/HolonNode-on-create); (3) think_refs_query covers every record type; (4) think_model/think_science/think_monitor drop their single-item legacy form — `items=[...]` becomes required. Net effect: AI scans tool list 70%+ faster, picks the right tool first try, and one-shots calls without trial-and-error.

---

## Context — Why This Matters

Empirical from my own honest grade in the previous turn: **the deferred description sweep (S4) is the single biggest unrealized improvement**. Every AI call loads the full tool-list payload as context. Currently:

- 55 tools, average 21 docstring lines = ~1,150 lines of description payload per call
- 47 of 55 have NO phase tag → AI scans linearly to pick the right tool
- 48 of 55 have NO "Use when" / "Skip when" guidance → AI guesses, wastes calls
- 13 docstrings exceed 25 lines (worst: think_interfere at 64). Long descriptions ARE the ceremony I told the AI to avoid in thoughts

Plus four cross-cutting bugs from my honest review:

1. `auto_graph=True` + no `session_id` raises ValueError → AI must orchestrate session_create first → wasted round trip
2. `refs` and `connects_to` are parallel cross-reference universes that never meet → think_refs_query can't find half the records the AI creates
3. ModelRecord / InquiryRecord / MonitorRecord have no `refs` field at all → they are invisible to think_refs_query forever
4. think_model / think_science / think_monitor expose two forms (items[] strict, single lax) → choice paralysis and a documented "ceremony" path the AI shouldn't take

Fixing all of these together is the path from "useful for complex analyses" (today) to "the AI reaches for it on its own" (target).

---

## Description Convention — The Contract

Every registered tool's docstring follows this exact shape. Max 20 lines total.

```
[<PHASE>] <one-line purpose; emphasise the moment to call it>.

Use when: <bullet 1 — concrete scenario>; <bullet 2 — second concrete scenario>.
Skip when: <bullet — name the better tool for the alternative scenario>.
Rejects: <server validation rules, one line, only if applicable>.

Args:
  <name>: <type> — <one clause, no paragraphs, no examples>.
  ...

Returns: <one-line output shape>.
```

**Required first line**: `[<PHASE>]` tag. Phase ∈ `SCAFFOLD`, `ELABORATE`, `ASSESS`, `DATA`, `INFRA`. The tag is the AI's primary scanning signal.

**Use when** — 1 or 2 specific scenarios, not abstract categories. "Use when: starting a deep multi-pathway analysis; you have N hypotheses to record". NOT "Use for analytical work".

**Skip when** — names the BETTER tool for an adjacent scenario. This is the choice-paralysis killer. "Skip when: a single thought (use `think_graph`)".

**Rejects** — only if the server actually rejects. One line. "Rejects: items missing required fields (problem/steps/reasoning/conclusion); empty items list".

**Args** — terse, one clause per arg. Required args first. Optional args follow. NO examples in args section.

**Returns** — one-line shape: `Returns: item_ids[] + graph_node_ids[] when auto_graph.`

**No examples in description.** Examples → `.meridian/docs/<tool-or-pattern>.md`. Example payloads cost more tokens than the entire description.

**No "philosophy" prose.** No "this tool helps you think structurally about…". Lead with the verb.

**Phase tag rules:**
- `[SCAFFOLD]` — call FIRST in an analysis. Required schema forces structure.
- `[ELABORATE]` — call MIDDLE. Flexible thinking, building, navigating.
- `[ASSESS]` — call LAST. Required schema forces honest self-critique.
- `[DATA]` — SQL/graph data tools. Not part of the thinking workflow.
- `[INFRA]` — sessions, lifecycle, exports. Setup/teardown.

---

## Phase Assignments — The 55 Tools

### `[DATA]` — 28 tools

`sql.py` (9): sql_create_session, sql_query, sql_query_next, sql_import, sql_import_batch, sql_schema, sql_destroy_session, data_profile, data_anomalies

`graph.py` (17): graph_create_session, graph_query, graph_query_next, graph_import, graph_schema, graph_destroy_session, graph_statistics, graph_neighbors, graph_find_connections, graph_analyze, graph_compare, graph_cross_reference, graph_knowledge_add, graph_knowledge_relate, knowledge_batch, graph_knowledge_infer, graph_knowledge_summary

`youtube.py` (1): get_youtube_information

`meta.py` (1): suggest_database (this is meta over [DATA] — describe as `[DATA]` since it advises on DATA backends)

### `[INFRA]` — 4 tools

`infra.py`: session_create, session_destroy

`think.py`: think_create_session, think_destroy_session

### `[SCAFFOLD]` — 4 tools

`think.py`: think_model, think_science, think_decide, think_interfere

(Note: think_monitor moves to [ASSESS] — it's calibration AFTER an analysis.)

### `[ELABORATE]` — 13 tools

`think.py`: think_graph, think_graph_delegate, think_argue, think_debug, think_summarize, think_interfere_state

`refs.py`: think_refs_query

`brainstorm.py`: brainstorm

`iterate.py`: iterate

`holon.py`: holon_create, holon_update, holon_view, holon_query (multi-level domain modeling — naturally mid-analysis)

### `[ASSESS]` — 6 tools

`score.py`: score_rubric, score_evaluate, score_gate, rubric_templates

`think.py`: think_monitor

`holon.py`: holon_analyze (it's evaluating an existing holarchy, not building one)

**Total: 28 + 4 + 4 + 13 + 6 = 55. ✓**

---

## The Six Gap Fixes

### Gap 1 — Auto-create unified session when `auto_graph=True`

**Files**:
- `src/aismartbuddy/tools/__init__.py::materialize_auto_graph` — currently raises if no graph backend. Add logic: if `parent_session_id is None`, create a parent with `backends=["think","graph"]` via SessionManager and use it. Return both the materialised count AND the parent session_id.
- `src/aismartbuddy/tools/think.py::think_model / think_science / think_monitor / think_decide` — items[] paths currently raise if `auto_graph=True` and `session_id is None`. Replace that check with a call to a new shared helper `_resolve_or_create_for_auto_graph(session_id, ctx, mgr)` that returns `(effective_session_id, think_info)`. If session_id is None → mgr.create_parent_session(["think","graph"], user_id, project_id) → use parent_id as effective_session_id.
- The tool's response includes the effective_session_id explicitly as `session_id: <id>` (top line) so AI captures it for follow-up calls.

**Behaviour change**: AI calling `think_model(model_name="first_principles", items=[...], auto_graph=True)` with NO session_id no longer fails. Server creates the unified session, uses it, returns the new session_id. Single-call experience.

**Edge case**: when session_id IS provided but is a single-backend think session (no graph), still raise — the AI explicitly chose a session that lacks the backend, so the actionable error stands. Auto-creation only kicks in when AI omits session_id entirely.

### Gap 2 — Unify cross-reference on `refs` field

**Files**:
- `src/aismartbuddy/engines/thinking_engine.py` — add `refs: list[str] = field(default_factory=list)` to: ModelRecord, InquiryRecord, MonitorRecord, DecisionRecord, DebugRecord. (HolonNode and EvaluationRecord and ThoughtNode already have it.)
- `src/aismartbuddy/tools/think.py` — every items[] handler: when constructing the record, set `refs=list(it.get("connects_to") or []) + list(it.get("refs") or [])`. (Both names accepted in items dicts; both feed the single `refs` field.)
- `src/aismartbuddy/tools/__init__.py::materialize_auto_graph` — unchanged behaviour; still creates DerivedFrom edges. The graph edges now mirror the `refs` field, not duplicate it.
- `src/aismartbuddy/tools/holon.py::holon_create` — accept `refs: list[str] | None = None` parameter (and within `holons` batch entries). Currently HolonNode.refs is defined but unsettable.
- `src/aismartbuddy/tools/score.py::score_evaluate` — accept `refs: list[str] | None = None` parameter on the `start` action (the call that creates the EvaluationRecord). EvaluationRecord.refs is already defined but unsettable. (Reviewer note: NOT on score_rubric — RubricRecord has no refs field; rubrics are framework definitions, not analytical artifacts that reference others.)

**Result**: items[].connects_to (the structural cross-ref the AI declares) populates the record's `refs` field, which `think_refs_query` already searches. Single source of truth.

### Gap 3 — `think_refs_query` covers every record type with refs

**File**: `src/aismartbuddy/tools/refs.py`

**Change**: extend the `matches` dict to scan: thought_nodes, holon_nodes, evaluations (already there), PLUS models, inquiries, monitors, decisions, debugs (newly have refs after Gap 2). Each iteration adds `(record_id, type)` to the appropriate bucket.

**Implementation note** — the engine stores some collections as dicts (inquiries, monitors, decisions, evaluations) and others as lists (models, debugs). For dict-backed: iterate `engine.<col>.items()` using the dict key as the id. For list-backed: iterate the list and use the new `record_id` field as the id. Two iteration patterns; one helper function suffices.

**Output expansion**: per-type counts in the response plus matching IDs. AI can chase any reference back to its origin record by id+type.

### Gap 4 — Remove single-form from `think_model` / `think_science` / `think_monitor`

**Files**: `src/aismartbuddy/tools/think.py`

**Changes**:
- `think_model`: delete the single-form branch (lines after `# ── Single-item backward-compat path`). `items` becomes a REQUIRED parameter (no default `None`). Drop the now-unused parameters: `problem, steps, reasoning, conclusion`.
- `think_science`: same — delete single-stage branch. `items` becomes required. Drop: `stage, inquiry_id, iteration, next_stage_needed, observation, question, hypothesis, experiment, analysis, conclusion`.
- `think_monitor`: same — delete single-form branch. `items` becomes required. Drop: `task, stage, overall_confidence, monitoring_id, iteration, next_assessment_needed, knowledge_assessment, claims, reasoning_steps, uncertainty_areas, recommended_approach, suggested_assessments`.
- `think_decide` and `think_debug`: KEEP single-form. They're [SCAFFOLD] / [ELABORATE] respectively but smaller — single-form still useful. (User's answer applied to think_model/science/monitor specifically — those are the dual-family redundant ones.)

**Tests to update/remove**:
- `tests/test_think_tools.py::TestThinkModelTool` — many tests use single-form. Convert each to items[] with one item, OR delete tests for the framework-loading behaviour (no longer applicable).
- `tests/test_think_tools.py::TestThinkScienceTool::test_scientific_inquiry` — single-form. Convert to items[].
- `tests/test_think_tools.py::TestThinkMonitorTool` — multiple single-form tests. Convert.
- The `_MODEL_GUIDANCE` dict (per-model framework prose returned in single-form when no steps/conclusion) — delete; it's part of the single-form behaviour the AI no longer sees.

This is a BREAKING change to the tool signatures. Acceptable: the strict items[] form was always the intended primary; single-form was scaffolded backward-compat that the AI shouldn't reach for.

### Gap 5 — Compress `think_interfere` to ≤25 lines

**File**: `src/aismartbuddy/tools/think.py::think_interfere` (currently 64 lines)

**Change**: collapse the 16-action enumeration in the docstring into a brief "Phase-gated protocol — see `.meridian/docs/think-interfere.md` for the full action reference." Keep only:
- [SCAFFOLD] tag + one-line purpose
- Use when: novel concept generation from cross-domain interference
- Skip when: a regular think_model decomposition is enough
- Rejects: out-of-phase actions
- Args: action (str), session_id, protocol_id, plus `**kwargs`-style note "action-specific args; see docs"
- Returns

Move the 16-action documentation to `.meridian/docs/think-interfere.md` (new file). The actual action handling code stays unchanged.

### Gap 6 — Add `[ELABORATE] / [ASSESS]` + use-when to all 5 holon tools

**File**: `src/aismartbuddy/tools/holon.py`

**Per tool**:
- `holon_create` → `[ELABORATE]` Build holons in a multi-level domain. **Skip when**: a flat tree is enough (use think_graph branch).
- `holon_update` → `[ELABORATE]` Modify existing holon state. **Skip when**: writing to a fresh node (use holon_create).
- `holon_view` → `[ELABORATE]` Navigate holarchy. **Skip when**: you want a query result, not a navigation view (use holon_query).
- `holon_query` → `[ELABORATE]` Query the holarchy from a vantage point.
- `holon_analyze` → `[ASSESS]` Detect tensions / coherence / leverage in an existing holarchy. **Skip when**: building (use holon_create).

---

## Per-File Description Sweep — Specs

For each file, the convention is applied tool-by-tool. The plan reviewer + tests catch drift. Below are the tools that need specific reframing beyond mechanical convention application.

### `src/aismartbuddy/tools/think.py`

- `think_graph` — already has the SHORT-thoughts nudge; trim to [ELABORATE] convention. Keep the "1-3 sentences, branch if longer" rule prominently in `Use when`.
- `think_model` — [SCAFFOLD]. After Gap 4, single-form is gone. Description leads with `items=[...]` form. Use when: starting decomposition. Skip when: mid-elaboration (use think_graph).
- `think_science` — [SCAFFOLD]. Same shape as think_model.
- `think_monitor` — [ASSESS]. Lead with calibration purpose. Use when: AFTER an analysis to record what you don't know. Skip when: confident the analysis is exhaustive.
- `think_decide` — [SCAFFOLD]. items[] is the primary form (already exists). Skip when: decision is binary/obvious.
- `think_debug` — [ELABORATE]. items[] for batch debugging. Skip when: a single ad-hoc check suffices.
- `think_argue` — [ELABORATE]. chain[] form. Skip when: no genuine ambiguity.
- `think_interfere` — [SCAFFOLD]. Per Gap 5, collapse to ≤25 lines.
- `think_interfere_state` — [ELABORATE]. Already short. Just add tag.
- `think_summarize` — [ELABORATE]. Add Use when: resuming after context reset.
- `think_graph_delegate` — [ELABORATE]. Add Use when: handing subtree to a subagent.
- `think_create_session` / `think_destroy_session` — [INFRA].

### `src/aismartbuddy/tools/holon.py` — per Gap 6.

### `src/aismartbuddy/tools/score.py`

- `score_rubric` — [ASSESS]. Use when: defining evaluation criteria up front. Skip when: ad-hoc judgement is enough.
- `score_evaluate` — [ASSESS]. Note in description: incremental `action="finding"` form is the preferred discipline; `action="finding_batch"` exists but loses incremental forcing.
- `score_gate` — [ASSESS]. Use when: yes/no pass check.
- `rubric_templates` — [ASSESS]. Use when: bootstrapping a standard review.

### `src/aismartbuddy/tools/sql.py` and `graph.py`

All [DATA]. Mostly current descriptions are fine — just need:
- The [DATA] tag prepended.
- "Use when" added (1 bullet).
- Long ones (sql_query, sql_import, graph_query at 35 lines) trimmed to remove redundant prose, keep the technical contract.

### `src/aismartbuddy/tools/infra.py`

Already tagged. Minor polish — `session_destroy` description mentions "Use the session_id" which is vague; replace with "Pass the parent session_id from session_create."

### `src/aismartbuddy/tools/refs.py`

Already tagged. After Gap 3, update the docstring to list all 8 record types it now scans.

### `src/aismartbuddy/tools/brainstorm.py` and `iterate.py`

Single-tool files. Apply convention. Brainstorm: `[ELABORATE]` + Skip when: convergent / scoring (use score_evaluate). Iterate: `[ELABORATE]` + Skip when: not a build-test-learn loop.

### `src/aismartbuddy/tools/youtube.py::get_youtube_information`

[DATA]. Currently 53 lines. Trim:
- Move the long YouTube degradation explanation to `.meridian/docs/youtube-degradation.md` (already partially there in CLAUDE.md — repoint).
- Description keeps: phase tag, what it does, when to use, the cache behaviour in one line, args, returns.

### `src/aismartbuddy/tools/meta.py::suggest_database`

[DATA] (advisor over data backends). Trim. Use when: AI is unsure whether SQL or graph fits a use case.

---

## Execution Order

Sequence the work so each step is independently verifiable:

1. **Engine schema additions** (Gap 2 part A) — add `refs` field to ModelRecord/InquiryRecord/MonitorRecord/DecisionRecord/DebugRecord. Run tests; nothing should break (additive change).

2. **Items[] handlers populate refs** (Gap 2 part B) — wire `connects_to` and `refs` from items into the record's `refs` field in think_model/science/monitor/decide/debug. Add tests asserting it.

3. **think_refs_query expansion** (Gap 3) — scan all 8 record types. Add a test.

4. **holon_create/score_rubric accept refs** (Gap 2 part C) — add parameter; populate; test.

5. **Remove single-form** (Gap 4) — delete legacy branches. Convert affected tests to items[] form. The breaking change happens here; CI must still pass.

6. **Auto_graph auto-creates session** (Gap 1) — modify materialize_auto_graph + each items[] auto_graph block. Add a test that confirms `think_model(items=[...], auto_graph=True)` without a session_id succeeds and returns the new session_id.

7. **think_interfere docs split** (Gap 5) — write `.meridian/docs/think-interfere.md`; collapse the docstring.

8. **Description sweep** (Gap 6 + general) — go file-by-file, tool-by-tool, applying the convention. Use the inventory table for tracking. Verify each file's tools with a docstring-line-count assertion in a new test.

9. **Update CLAUDE.md** — describe the items[]-only contract for the SCAFFOLD-3 tools, the unified `refs` mechanism, the auto_graph auto-create behaviour, and the new docstring convention.

10. **Final lint + test + tool-count check + payload-size check** — verify the description-payload reduction (target: ~1150 → ~700 lines).

---

## Files to Modify

### Source

- `src/aismartbuddy/engines/thinking_engine.py` — add refs to 5 dataclasses
- `src/aismartbuddy/tools/__init__.py` — extend materialize_auto_graph for auto-create + add `_resolve_or_create_for_auto_graph` shared helper
- `src/aismartbuddy/tools/think.py` — Gap 4 (drop single-form ×3), Gap 5 (think_interfere), Gap 2 (refs in records), description sweep on all 13 tools
- `src/aismartbuddy/tools/holon.py` — Gap 2 (refs accept), Gap 6 (description sweep + tag)
- `src/aismartbuddy/tools/score.py` — Gap 2 (refs accept), description sweep on 4 tools
- `src/aismartbuddy/tools/sql.py` — description sweep on 9 tools
- `src/aismartbuddy/tools/graph.py` — description sweep on 16 tools
- `src/aismartbuddy/tools/refs.py` — Gap 3
- `src/aismartbuddy/tools/infra.py` — description polish
- `src/aismartbuddy/tools/brainstorm.py` — description sweep
- `src/aismartbuddy/tools/iterate.py` — description sweep
- `src/aismartbuddy/tools/youtube.py` — trim 53 → ≤20
- `src/aismartbuddy/tools/meta.py` — description sweep

### Tests

- `tests/test_think_tools.py`:
  - **DELETE** the 10 `_MODEL_GUIDANCE` framework-loading tests (test_first_principles_guidance through test_root_cause_guidance) — that behaviour is removed by Gap 4.
  - **CONVERT** ~5 remaining single-form tests (test_apply_model on think_model, test_scientific_inquiry on think_science, test_metacognitive_monitoring + test_knowledge_assessment + test_invalid_knowledge_level on think_monitor) to items[] form.
  - **UPDATE** `test_items_auto_graph_requires_session` (~line 690) — currently asserts ValueError; after Gap 1 it should assert SUCCESS (returns session_id, KG nodes created). Rename to `test_items_auto_graph_auto_creates_session`.
  - **ADD** auto-create-when-no-session-id positive test.
  - **ADD** refs-population assertions (item with connects_to=["x"] → record.refs == ["x"]).
- `tests/test_holon_tools.py` — add refs parameter test for holon_create.
- `tests/test_score_tools.py` — add refs parameter test for score_evaluate (start action).
- `tests/test_descriptions.py` (NEW) — assert every registered tool's docstring is ≤20 lines AND starts with a phase tag in the allowed set. Parameterized over `_TOOLS`. Allow ≤25 lines for [SCAFFOLD] tools as a documented exception.

### Docs

- `CLAUDE.md` — items[]-only contract, unified refs, auto_graph auto-create, docstring convention
- `.meridian/docs/` is a NET-NEW directory (existing `.meridian/` only contains `api-docs/` and `plans/`). Create it on first write.
- `.meridian/docs/think-interfere.md` (NEW) — full action reference for the protocol
- `.meridian/docs/description-convention.md` (NEW) — the 20-line contract for future tool authors
- `.meridian/docs/auto-graph.md` (NEW or update) — note the auto-create behaviour

---

## Acceptance Criteria

1. `uv run pytest tests/ -v` → all green. Test count drops by ~10 (single-form tests removed) and rises by ~15 (refs + auto-create tests). Net: ~340 tests.
2. `uv run ruff check src/ tests/` → clean.
3. `uv run pyright` → clean.
4. New test `tests/test_descriptions.py` passes: every tool docstring ≤20 lines AND starts with `[SCAFFOLD]|[ELABORATE]|[ASSESS]|[DATA]|[INFRA]`.
5. Tool count via `from aismartbuddy.server import _TOOLS; print(len(_TOOLS))` → still 55. (No tools added or removed in this pass.)
6. Manual: total docstring line count via `sum(len(fn.__doc__.split(chr(10))) for fn,_,_,_ in _TOOLS)` → reduced by ≥35% from the pre-sweep baseline (~1150 → ≤750).
7. Manual smoke test: `think_model(model_name="first_principles", items=[{id:"x",problem:"p",steps:["s"],reasoning:"r",conclusion:"c",connects_to:["y"]}], auto_graph=True)` with NO session_id and NO prior session — succeeds, returns session_id, creates KnowledgeNode for "x" with DerivedFrom edge to "y", AND ModelRecord for "x" has refs=["y"]. Then `think_refs_query(entity_id="y", session_id=<that id>)` finds the model record.
8. Manual smoke test: call `think_model` WITHOUT items=[...] — server raises `TypeError: missing 1 required argument: items` (Gap 4).

---

## Verification

```bash
# 1. Lint + format + types
uv run ruff check src/ tests/
uv run pyright

# 2. Full test suite
uv run pytest tests/ -v

# 3. Description convention enforcement
uv run pytest tests/test_descriptions.py -v

# 4. Tool count + description payload size
uv run python -c "
from aismartbuddy.server import _TOOLS
print(f'Tool count: {len(_TOOLS)}')
total = sum(len((fn.__doc__ or '').splitlines()) for fn, _, _, _ in _TOOLS)
print(f'Total docstring lines: {total}')
print(f'Avg per tool: {total / len(_TOOLS):.1f}')
"

# 5. Items[]-only enforcement on think_model
uv run python -c "
import asyncio
from aismartbuddy.tools.think import think_model
try:
    asyncio.run(think_model(model_name='first_principles'))
    print('FAIL: should have raised')
except TypeError as e:
    print(f'OK: {e}')
"
```

---

## Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | Removing single-form on 3 tools breaks ~12 tests | High | Convert each test to items=[{one item}] form. Tests grow ~3 lines each but exercise the same engine behaviour. |
| 2 | Auto-creating a parent session for `auto_graph=True` mints unbounded sessions if AI calls repeatedly | Medium | The existing session-cleanup loop already evicts idle parents. Add a test that confirms the orphan parent gets garbage collected after timeout. |
| 3 | Adding `refs` to 5 dataclasses could break `dataclasses.asdict()` callers if they assume specific field ordering | Low | Field is appended at the end with a default factory. Existing serialization paths unaffected. |
| 4 | The 20-line docstring cap is too tight for genuinely complex tools (think_interfere) | Medium | Use `.meridian/docs/<tool>.md` for the long-form reference; the docstring points to it. The cap is a SOFT cap — `tests/test_descriptions.py` allows ≤25 lines for [SCAFFOLD] tools, ≤20 for the rest. |
| 5 | AI can't tell items[] form is required from the description until it gets a TypeError | Low | Description's `Args:` section lists items as REQUIRED first. The Use when explicitly mentions "items=[...]". |
| 6 | refs unification might double-count when AI provides both refs and connects_to in same item | Low | Concatenate then dedup: `list(dict.fromkeys(connects_to + refs))`. Document in items[] contract. |

---

## Non-Goals

- Adding new tools. The 55 stay 55.
- Changing tool registration order in `_TOOLS`.
- Re-introducing think_collaborate / think_visualize / think_graph_validate / workflow / bridge / session_export / session_snapshot.
- Per-tool examples in docstrings (those go to `.meridian/docs/`).
- Restructuring the engine layer (ThinkingEngine, DuckDB, LadybugDB stay isolated).
- Multi-tenant model changes (identity resolution, per-session locks, parent-session facade all preserved).
- Temporal KG / event bus / memory palace — still out of scope.

---

## Plan Review

Run `meridian:plan-reviewer` against this file before exiting plan mode. Target 9+. Address findings with the user, update plan, re-run.

Key review questions:
- Do the 6 gap fixes actually fix what my honest reflection identified?
- Is the 20-line cap mechanically enforceable via a test?
- Does the items[]-only breaking change really get tested before removal?
- Does the auto_graph auto-create handle the orphan-session edge case?

---

## TLDR (again)

Sweep all 55 tool descriptions to a uniform 20-line `[PHASE] / Use when / Skip when / Rejects / Args / Returns` convention so the AI scans tool selection 70%+ faster and one-shots calls. Concurrently fix four real gaps from honest self-review: (1) auto_graph auto-creates the unified session when none provided; (2) `refs` becomes the single cross-reference mechanism — items[].connects_to populates it on every record type; (3) think_refs_query covers all 8 record types; (4) think_model/science/monitor drop their single-item legacy form so items=[...] becomes required. Net: AI grade jumps from "useful for complex analyses" to "reaches for it on its own" — the gap I admitted was the difference between 7/10 and 9/10.
