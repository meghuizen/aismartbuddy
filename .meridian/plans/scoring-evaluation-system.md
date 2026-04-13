# Plan: Implement General Scoring/Evaluation System

## Verbatim Requirements

### Original Request
> Think like an architect and use clear-thought to think through in designing a general scoring capability which AI can use when using this MCP server. [...] This is modeled to the meridian plan reviewer scoring mechanism [detailed 5-tool design with rubrics, findings, finalization, gate checking, and evaluation history]

### Clarifications
**Q:** 3 consolidated tools or 5 separate?
**A:** 3 consolidated tools (Recommended)

## Context

The core problem: AI-driven evaluations (plan review, code review, security review) currently rely on prompt-enforced scoring. The AI both finds issues AND assigns the score, with nothing preventing contradiction (5 critical findings but still "9/10"). This system separates judgment from scoring: the AI decides what findings exist, the server decides what those findings mean for the score.

The key innovation: **incremental finding submission with running score feedback.** Each finding adjusts the score mechanically. The AI sees the score drop in real-time, preventing post-hoc rationalization. Required dimensions must be reviewed or finalization fails.

---

## Design

### Data Model

**RubricRecord:**
```
id: str
description: str
dimensions: list[dict]         # [{id, description, weight, required}]
severity_levels: list[str]     # ["critical", "high", "moderate", "low"]
severity_deductions: dict[str, float]  # {critical: 3.0, high: 2.0, ...}
pass_threshold: float          # e.g., 9.0
scale: tuple[int, int]         # (1, 10)
scoring_strategy: str          # weighted_deduction | weighted_average | minimum_floor
created_at: datetime
```

**EvaluationRecord:**
```
id: str
rubric_id: str
context: str                   # what's being evaluated
status: str                    # active | finalized
findings: list[FindingRecord]
dimension_scores: dict[str, float]  # {dimension_id: current_score}
dimensions_reviewed: set[str]  # tracked automatically
running_score: float
final_score: float | None
passed: bool | None
has_blocking: bool
auto_fail: bool
summary: str
created_at: datetime
finalized_at: datetime | None
```

**FindingRecord:**
```
id: str
dimension: str
severity: str
blocking: bool
description: str
evidence: list[str]
recommendation: str
created_at: datetime
```

### Scoring Mechanics

**On each finding submission:**
```
1. Look up dimension in rubric
2. Apply severity deduction to dimension score:
   dimension_score -= severity_deductions[severity]
   dimension_score = max(dimension_score, scale_min)
3. If finding.blocking → evaluation.has_blocking = True
4. If severity == "critical" AND dimension.required → evaluation.auto_fail = True
5. Mark dimension as reviewed
6. Recompute running_score based on strategy
```

**Scoring strategies:**
- `weighted_deduction`: start all dimensions at scale_max, deduct per finding. Final = weighted average of dimension scores.
- `weighted_average`: same formula (they're equivalent when starting at max).
- `minimum_floor`: weighted average BUT capped by lowest required dimension score.

**On finalization:**
```
1. Merge: dimensions_reviewed = auto-tracked (from findings) ∪ explicitly passed dimensions
   (This allows marking "I reviewed this dimension, no issues found")
2. Check all required dimensions are in merged dimensions_reviewed → fail if not
3. If auto_fail → pass = False
4. If has_blocking → pass = False
5. Else → pass = (running_score >= pass_threshold)
6. Set final_score, status = "finalized"
```

### 3 Tools

#### Tool 1: `score_rubric`

```python
async def score_rubric(
    action: str,                         # create | list
    session_id: str | None = None,
    # create params:
    rubric_id: str | None = None,
    description: str | None = None,
    dimensions: list[dict] | None = None,
    severity_levels: list[str] | None = None,
    severity_deductions: dict[str, float] | None = None,
    pass_threshold: float = 9.0,
    scale_min: int = 1,
    scale_max: int = 10,
    scoring_strategy: str = "weighted_deduction",
) -> str:
```

**create:** Validates dimensions have id/description/weight/required. Stores rubric. Default severity_deductions: {critical: 3.0, high: 2.0, moderate: 1.0, low: 0.5}. Default severity_levels: ["critical", "high", "moderate", "low"].

**list:** Returns all rubrics in the session with their dimension counts and thresholds.

Output (create):
```
Session: {sid} | Rubric: {rubric_id}
Dimensions: 4 (2 required) | Threshold: 9.0/10
Strategy: weighted_deduction
Status: created
```

#### Tool 2: `score_evaluate`

```python
async def score_evaluate(
    action: str,                         # start | finding | finalize
    session_id: str,
    # start params:
    rubric_id: str | None = None,
    context: str | None = None,
    evaluation_id: str | None = None,    # auto-generated on start
    # finding params:
    dimension: str | None = None,
    severity: str | None = None,
    blocking: bool = False,
    description: str | None = None,
    evidence: list[str] | None = None,
    recommendation: str | None = None,
    # finalize params:
    summary: str | None = None,
    dimensions_reviewed: list[str] | None = None,
) -> str:
```

**start:** Creates a new evaluation against a rubric. Initializes all dimension scores at scale_max. Returns evaluation_id.

**finding:** Submits a single finding. Computes and returns running_score + dimension_scores. This is the workhorse action — called many times per evaluation.

Output (finding):
```
Session: {sid} | Eval: {eval_id} | Finding: {finding_id}
Dimension: {dim} ({severity}) | Blocking: {blocking}
Running score: {running_score}/{scale_max} | Status: {above/below}_threshold
Dimension scores: feasibility=10, completeness=6, correctness=10, integration=?
```

**finalize:** Closes the evaluation. Checks required dimension coverage. Computes final verdict.

Output (finalize):
```
Session: {sid} | Eval: {eval_id}
Final score: {score}/{scale_max} | Pass: {true/false}
Threshold: {threshold} | Strategy: {strategy}
Findings: {n} (critical={c}, high={h}, moderate={m}, low={l})
Dimension scores:
  feasibility: 10/10 (0 findings)
  completeness: 6/10 (2 findings)
  correctness: 9/10 (1 finding)
  integration: 8/10 (1 finding)
```

#### Tool 3: `score_gate`

```python
async def score_gate(
    action: str,                         # gate | list
    session_id: str,
    evaluation_id: str | None = None,    # for gate
    rubric_id: str | None = None,        # for list (filter)
    limit: int = 10,                     # for list
) -> str:
```

**gate:** Lightweight pass/fail check. Returns pass boolean, score, threshold, blocking status. Designed for hooks. If evaluation is not finalized, returns pass=None (indeterminate) with status=active and the running_score, so consumers know the evaluation is incomplete.

Output (gate — finalized):
```
Session: {sid} | Eval: {eval_id}
Pass: false | Score: 7.5/10 | Threshold: 9.0
Blocking: 0 | Status: finalized
```

Output (gate — active):
```
Session: {sid} | Eval: {eval_id}
Pass: ? | Score: 8.0/10 (running) | Threshold: 9.0
Status: active (not finalized)
```

**list:** Returns evaluation history, optionally filtered by rubric_id. Shows scores and pass/fail for trend tracking.

Output (list):
```
Session: {sid} | Rubric: {rubric_id or "all"}
Evaluations (3):
  eval-abc: 7.5/10 FAIL (3 findings) — 2026-04-12
  eval-def: 9.2/10 PASS (1 finding) — 2026-04-11
  eval-ghi: 9.5/10 PASS (2 findings) — 2026-04-10
```

---

## Implementation Steps

### Files to create:
- `src/aismartbuddy/tools/score.py` — 3 scoring tool functions + validation constants

### Files to modify:
- `src/aismartbuddy/engines/thinking_engine.py` — RubricRecord, EvaluationRecord, FindingRecord dataclasses + engine methods
- `src/aismartbuddy/server.py` — register 3 tools, update guide prompt
- `tests/test_score_tools.py` — NEW test file
- `CLAUDE.md` — update tool count

### Step 1: Add dataclasses and engine methods (`engines/thinking_engine.py`)

Add RubricRecord, EvaluationRecord, FindingRecord dataclasses after HolonNode.

Add constants: `MAX_RUBRICS = 100`, `MAX_EVALUATIONS = 100`.

Add to ThinkingEngine.__init__:
- `self.rubrics: dict[str, RubricRecord] = {}`
- `self.evaluations: dict[str, EvaluationRecord] = {}`

Engine methods:
- `upsert_rubric(record)` / `get_rubric(id)` / `get_rubrics()` — standard dict ops
- `upsert_evaluation(record)` / `get_evaluation(id)` / `get_evaluations(rubric_id=None)` — with optional filter
- `compute_running_score(eval_id)` — applies scoring strategy, returns float
- Private: `_apply_deduction(eval, finding)` — modifies dimension score for a finding
- Private: `_check_finalization(eval)` — validates required dimensions reviewed

Update close() to clear rubrics and evaluations.
Update get_summary() with Scoring section: rubric count, evaluation count, active/finalized.

### Step 2: Create tools/score.py (3 tools)

Follow holon.py pattern: import helpers from think.py.

Validation constants:
```python
_SCORE_RUBRIC_ACTIONS = frozenset({"create", "list"})
_SCORE_EVALUATE_ACTIONS = frozenset({"start", "finding", "finalize"})
_SCORE_GATE_ACTIONS = frozenset({"gate", "list"})
_SCORING_STRATEGIES = frozenset({
    "weighted_deduction", "weighted_average", "minimum_floor",
})
_DEFAULT_SEVERITY_LEVELS = ["critical", "high", "moderate", "low"]
_DEFAULT_SEVERITY_DEDUCTIONS = {
    "critical": 3.0, "high": 2.0, "moderate": 1.0, "low": 0.5,
}
```

Implement score_rubric, score_evaluate, score_gate.

Key implementation detail for `score_evaluate(action="finding")`:
1. Look up evaluation → look up rubric
2. Validate dimension is in rubric's dimensions
3. Validate severity is in rubric's severity_levels
4. Create FindingRecord, append to evaluation.findings
5. Call engine.compute_running_score(eval_id) → returns running_score
6. Return compact text with running score + dimension scores

### Step 3: Register tools + update guide prompt (`server.py`)

Import from tools/score.py. Add 3 entries to _TOOLS:
- `(score_rubric, "score_rubric", "Scoring Rubric", _DEFAULT)`
- `(score_evaluate, "score_evaluate", "Evaluate with Score", _DEFAULT)`
- `(score_gate, "score_gate", "Scoring Gate Check", _READONLY)`

Add Scoring section to aismartbuddy-guide prompt.

### Step 4: Update CLAUDE.md

Update tool count: 42 + 3 = 45. Add score_* prefix to naming convention. Document scoring capability.

### Step 5: Tests (`tests/test_score_tools.py`)

**TestScoreRubric:**
- Create rubric with 4 dimensions → verify stored
- List rubrics → verify returned
- Invalid scoring strategy → ValueError

**TestScoreEvaluate:**
- Start evaluation → verify active, all dimensions at max
- Submit finding → verify running score drops correctly
- Submit critical finding on required dimension → verify auto_fail
- Submit blocking finding → verify has_blocking
- Finalize with all required dimensions → verify pass/fail
- Finalize missing required dimension → verify failure
- Submit finding to finalized evaluation → verify rejection

**TestScoreGate:**
- Gate check on passing evaluation → pass=true
- Gate check on failing evaluation → pass=false
- List evaluations → verify history

**TestScoringStrategies:**
- weighted_deduction: 2 findings → verify score computation
- minimum_floor: required dimension tanked → verify floor caps total

**TestEndToEnd:**
- Full flow: create rubric → start eval → 3 findings → finalize → gate check
- Verify running_score changed after each finding
- Verify final score matches mechanical computation
- Verify pass=false when below threshold

---

## Verification

1. `uv run pytest tests/test_score_tools.py -v` — all scoring tests pass
2. `uv run ruff check src/ tests/` — lint clean
3. `uv run pytest -v` — full suite passes
4. Manual: Create plan-review rubric, start evaluation, submit 3 findings, finalize, check gate

---

## Non-Goals

- **Persistence across sessions**: Layer 1, in-memory. Rubrics must be recreated per session. (Layer 2 with DuckDB backing is future work.)
- **Hook integration**: The gate tool ENABLES hook integration but we don't modify any hooks. Hook authors use score_gate.
- **Prompt-level rubric definitions**: Rubrics are defined via the tool, not in prompt text.
- **Cross-session trend analysis**: list shows history within a session only.

---

## TLDR

Add 3 scoring tools (`score_rubric`, `score_evaluate`, `score_gate`) that separate AI judgment from mechanical scoring. The AI submits findings one at a time; the server computes running scores after each, preventing post-hoc rationalization. Required dimensions must be reviewed or finalization fails. Three scoring strategies (weighted_deduction, weighted_average, minimum_floor). Gate check returns a boolean for hooks to enforce. Rubrics are reusable — define plan-review, code-review, security-review once and score against them. Tool count: 42 + 3 = 45.
