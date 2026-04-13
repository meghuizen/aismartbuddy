# Plan: Adopt Clear-Thought Frameworks into Existing Tools

## Verbatim Requirements

### Original Request
> Now analyze the clear-thought tool [...] and look at what tools we can adopt in our tool. Like metacognitive thinking, scientific method, assumptions xray, etc. Go through each tool separately using the todolist and validate if the tool is useful to the intent of the mcp server and think like an architect on how you would embed those in this MCP server without overwhelming the amount of tools [...]

### Clarifications
**Q:** Extend existing tools (0 new) or add standalone tools?
**A:** Extend existing tools (Recommended)

**Q:** Socratic method as pattern or tool?
**A:** Document as pattern (Recommended)

## Context

Clear-thought has 27 tools. We already cover 11 of them. Of the remaining 16, 5 are placeholders and 4 are achievable with existing tools. That leaves 7 high-value frameworks. The architectural decision: implement these as extensions to existing tools (4 new mental models + 2 new holon_analyze actions) rather than adding new tools. This keeps the tool count at 42.

## Analysis Summary: All 27 Clear-Thought Tools

| Tool | Verdict | Integration |
|------|---------|-------------|
| sequential-thinking | COVERED | think_graph (superior) |
| mental-model | COVERED | think_model |
| debugging-approach | COVERED | think_debug |
| decision-framework | COVERED | think_decide |
| metacognitive | COVERED | think_monitor |
| scientific-method | COVERED | think_science |
| collaborative-reasoning | COVERED | think_collaborate |
| structured-argumentation | COVERED | think_argue |
| visual-reasoning | COVERED | think_visualize |
| concept-map | COVERED | think_visualize (conceptMap) |
| session-management | COVERED | think_summarize + destroy |
| **assumption-xray** | **ADOPT** | think_model: "assumptions_xray" |
| **systems-thinking** | **ADOPT** | holon_analyze: "feedback_loops" + "leverage_points" |
| **fishbone-diagram** | **ADOPT** | think_model: "fishbone" |
| **value-of-information** | **ADOPT** | think_model: "value_of_info" |
| **swot-analysis** | **ADOPT** | think_model: "swot" |
| **socratic-method** | **PATTERN** | Documented think_graph usage pattern |
| analogical-mapper | SKIP | think_interfere does this better |
| creative-thinking | SKIP | think_graph branching covers this |
| mind-map | SKIP | think_graph covers this |
| issue-tree | SKIP | think_graph with branch covers this |
| comparative-advantage | SKIP | Not a thinking tool |
| drag-point-audit | SKIP | Narrow use case |
| safe-struggle-designer | SKIP | Skill development, not thinking |
| seven-seekers-orchestrator | SKIP | Placeholder implementation |
| existing-tool-example | SKIP | Template file |
| design-patterns | SKIP | Software-specific |

---

## Changes

### Change 1: Add 4 new mental models to think_model

**File:** `src/aismartbuddy/tools/think.py`

Add to `_MODEL_NAMES` frozenset:
- `"assumptions_xray"` — Surface hidden assumptions in claims
- `"fishbone"` — Categorize causes using Ishikawa diagram structure
- `"value_of_info"` — Assess whether gathering info is worth the cost
- `"swot"` — Analyze strengths, weaknesses, opportunities, threats

Add to `_MODEL_GUIDANCE` dict:

```
"assumptions_xray": (
    "Framework: Assumption X-Ray\n"
    "1. Surface hidden assumptions — what must be true for this claim to hold?\n"
    "2. Rate confidence in each assumption (0.0-1.0)\n"
    "3. Propose falsification tests — how could each assumption be disproven?"
)

"fishbone": (
    "Framework: Fishbone Diagram (Ishikawa)\n"
    "1. State the problem/effect clearly\n"
    "2. Identify cause categories: methods, materials, people, environment,\n"
    "   measurement, machines (customize for domain)\n"
    "3. For each category, list specific potential causes\n"
    "4. Identify which causes are most likely and testable"
)

"value_of_info": (
    "Framework: Value of Information\n"
    "1. List decision options and their expected outcomes\n"
    "2. Identify key uncertainties that affect the decision\n"
    "3. For each uncertainty: what would perfect information change?\n"
    "4. Prioritize: investigate uncertainties where info changes the decision"
)

"swot": (
    "Framework: SWOT Analysis\n"
    "1. Strengths — internal advantages and capabilities\n"
    "2. Weaknesses — internal limitations and gaps\n"
    "3. Opportunities — external favorable conditions\n"
    "4. Threats — external risks and challenges"
)
```

Update the think_model docstring to list the new models.

Total models: 5 existing + 4 new = 9 models.

### Change 2: Add 2 new actions to holon_analyze

**File:** `src/aismartbuddy/tools/holon.py`

Add to `_HOLON_ANALYZE_ACTIONS` frozenset:
- `"feedback_loops"` — Detect feedback loops between holons
- `"leverage_points"` — Find high-impact intervention points

**feedback_loops action:**
Given a holarchy_id (or scan all), identify pairs of holons where A's projection/context references B AND B's projection/context references A (bidirectional causal chains). Classify as positive (reinforcing) or negative (balancing) based on whether the loop amplifies or dampens. Return the loop chain and type.

Implementation: For each holon, check if any of its context/rules mention names of its siblings or parent's children. This is a text-based heuristic (searching for holon names in context strings). Not perfect, but useful as a structured prompt: the AI can verify each detected loop.

**leverage_points action:**
Find holons that participate in the most holarchies (multi-membership count), have the most connections (children across holarchies), or sit on the most bridge paths between distant holons. These are structurally important nodes where intervention has maximum impact.

Implementation: Score each holon by: (a) number of memberships, (b) total children across all holarchies, (c) number of times the holon appears in bridge paths between other holons. Return ranked list.

Add implementations for both actions in the holon_analyze function's action dispatch.

Update holon_analyze docstring to include the new actions.

### Change 3: Document Socratic method as think_graph pattern

**File:** `src/aismartbuddy/server.py` (aismartbuddy-guide prompt)

Add to the Thought Graph section of the guide prompt:

```
### Socratic Method (think_graph pattern)
Use think_graph to do Socratic inquiry:
  1. think_graph(thought="Claim: ...", action="branch") → root
  2. think_graph(thought="CLARIFICATION: What exactly do we mean?", parent_id=root)
  3. think_graph(thought="ASSUMPTIONS: What must be true?", parent_id=root)
  4. think_graph(thought="EVIDENCE: What supports/contradicts?", parent_id=root)
  5. think_graph(thought="PERSPECTIVES: What other viewpoints?", parent_id=root)
  6. think_graph(thought="IMPLICATIONS: What follows if true?", parent_id=root)
  7. think_graph(thought="Synthesis", action="synthesize", parent_id=root)
```

### Change 4: Update CLAUDE.md

Update think_model description to mention 9 models including the 4 new ones. Update holon_analyze description to mention feedback_loops and leverage_points actions.

---

## Implementation Steps

### Step 1: Add 4 models to think_model (`tools/think.py`)

- Add "assumptions_xray", "fishbone", "value_of_info", "swot" to `_MODEL_NAMES`
- Add 4 entries to `_MODEL_GUIDANCE` with framework-specific guidance text
- Update think_model docstring

### Step 2: Add 2 actions to holon_analyze (`tools/holon.py`)

- Add "feedback_loops" and "leverage_points" to `_HOLON_ANALYZE_ACTIONS`
- Implement feedback_loops: scan holons for bidirectional references in context, return detected loops
- Implement leverage_points: score holons by membership count + connection count, return ranked list
- Update holon_analyze docstring

### Step 3: Document Socratic pattern + update model list in server.py guide prompt

- Add Socratic Method section to the Thought Graph guide
- Update the think_model line in the guide to list new models: "think_model(model_name, problem) → mental models (first_principles, pareto_principle, assumptions_xray, fishbone, value_of_info, swot, ...)"

### Step 4: Update CLAUDE.md

- Update model count (5→9) and holon_analyze action list

### Step 5: Tests

- Test each new model in think_model: call without steps → verify guidance returned
- Test feedback_loops action on holarchy with bidirectional context references. Parameters: holarchy_id scopes to one holarchy, holon_id scopes to subtree. Both optional (None = scan all).
- Test leverage_points action on holarchy with multi-membership holons. Scans all holons globally (no scoping parameters).

---

## Verification

1. `uv run pytest tests/test_think_tools.py -v` — new model tests pass
2. `uv run pytest tests/test_holon_tools.py -v` — new action tests pass
3. `uv run ruff check src/ tests/` — lint clean
4. `uv run pytest -v` — full suite passes, no regressions

---

## Non-Goals

- **New standalone tools**: Zero new tools added. All capabilities extend existing tools.
- **Reimplementing clear-thought placeholder logic**: Their fishbone/SWOT/etc. are placeholder implementations. We provide structured guidance frameworks, not fake computed outputs.
- **Socratic tool**: Documented as pattern, not a tool.
- **analogical-mapper**: Interference protocol already does cross-domain thinking more rigorously.

---

## Self-Validation: Would I (Claude) actually use these?

**assumptions_xray**: YES. Every time I accept a claim during investigation, I should challenge it. "Chronic cortisol causes mitochondrial dysfunction" — what assumptions hide in that? This model forces me to make them explicit.

**fishbone**: YES. When investigating root causes in pathophysiology, forced categorization prevents tunnel vision. "Why is Complex I activity reduced?" Categories: molecular mechanisms, environmental factors, upstream signaling, measurement artifacts.

**value_of_info**: YES. During research, I constantly decide what to investigate next. "Should I look at the GR receptor density data or the NF-kB pathway first?" Value-of-info structures that decision.

**swot**: SOMETIMES. More useful for strategic analysis than investigation. But applicable when comparing treatment approaches or research directions.

**feedback_loops**: YES. Biological systems are full of feedback loops. The stress→cortisol→inflammation→neuroinflammation→stress cycle IS a positive feedback loop. Detecting these structurally in the holarchy is critical.

**leverage_points**: YES. "Where should we intervene in the ME/CFS cascade?" The holon with the most cross-holarchy connections is the leverage point. This is exactly the question that matters.

**Socratic pattern**: YES. Before accepting any claim during investigation, running it through clarification→assumptions→evidence→perspectives→implications is good practice. The think_graph structure makes this natural.

---

## TLDR

Adopt 7 clear-thought frameworks by extending existing tools: 4 new mental models in think_model (assumptions_xray, fishbone, value_of_info, swot) + 2 new actions in holon_analyze (feedback_loops, leverage_points) + Socratic method documented as think_graph pattern. Zero new tools. Tool count stays at 42. Each framework is validated against the pathophysiology investigation use case.
