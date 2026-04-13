# Plan: Implement Interference Protocol Thinking Framework

## Verbatim Requirements

### Original Request
> Use clear-thought to think the following thought framework through and also how it fits in the architecture and structure of this mcp server. It's especially for opportunities when you want to think, like Elon Musk, beyond industry framing and assumptions. Think also on the partical implications and come up with an effective plan to integrate this thinking framework in the mcp server. feel free to change the thinking framework when you have better ideas: [Full Interference Protocol specification]

## Context

The Interference Protocol is a structured thinking framework that produces novel concepts by holding unrelated structural laws in superposition until interference patterns produce emergent concepts. It has 6 phases with strict ordering, rich internal state, frame detection, and collapse detection. This needs to become a tool in AISmartBuddy's existing Layer 1 thinking toolkit.

The key challenge: the IP is a **stateful workflow with phase gates** — fundamentally different from our existing tools which are either stateless (think_model) or lightly stateful (think_decide with stages). The IP has strict phase ordering, minimum-count prerequisites (2+ sources, 5+ fragments), and an emergence test that mechanically validates novelty.

---

## Design Decisions

### 1. Tool surface: 2 tools (not 8)
One `think_interfere` tool with an `action` parameter that selects phase-specific behavior, plus `think_interfere_state` for read-only queries. Matches the `think_visualize` pattern (operation param). Keeps total tool count at 35 (33 + 2).

### 2. Frame detection stays with the AI
The tool cannot do NLP-level semantic analysis of "is this input framed?" — that requires LLM reasoning. Instead, the tool **returns the suspended frames list and detection guidance in every response**, so the AI applies frame detection to its own reasoning. The tool enforces **structural gates** (phase ordering, minimum counts, emergence test). The AI enforces **semantic gates** (frame detection, collapse detection).

### 3. Emergence test IS mechanical — the tool does it
When crystallizing, each property has a `source_laws` field listing which source laws it derives from. The tool checks: properties marked `novel=True` must reference 2+ source laws. If all "novel" properties trace to a single source → reject as "mashup, not emergence."

### 4. Recursion creates a new protocol record, not a new session
Multiple InterferenceRecords can exist in one ThinkingEngine session. Recursion creates a new record with `iteration+1`, pre-loaded with the emergent concept as source #1.

---

## Implementation Plan

### Files to create: None (all additions go in existing files)

### Files to modify:
- `src/aismartbuddy/engines/thinking_engine.py` — add InterferenceRecord, engine methods
- `src/aismartbuddy/tools/think.py` — add 2 tool functions, validation constants
- `src/aismartbuddy/server.py` — register 2 new tools
- `tests/test_think_tools.py` — add test class
- `CLAUDE.md` — update tool count

---

### Step 1: InterferenceRecord dataclass (`engines/thinking_engine.py`)

Add after DiagramRecord:

```
InterferenceRecord:
    protocol_id: str
    phase: str          # uninitiated|domain_set|sources_ready|interfering|
                        # saturated|crystallized|necessities_derived|stress_tested
    iteration: int = 1
    target_domain: str = ""
    suspended_frames: list[str]        # structural assumptions identified
    source_laws: list[dict]            # [{domain, law, isomorphism}]
    fragments: list[str]               # interference observations
    tensions: list[dict]               # [{between: [idx, idx], description}]
    emergent_name: str = ""
    emergent_properties: list[dict]    # [{text, novel: bool, source_laws: [idx]}]
    necessity_chains: list[dict]       # [{conclusion, prerequisites: [{claim, status}]}]
    audit_results: dict                # {type: result_text, ...}
    verdict: str = ""                  # "survives"|"dies"|"wounded"
    timestamp: datetime
```

### Step 2: ThinkingEngine additions (`engines/thinking_engine.py`)

- Add `self.interferences: dict[str, InterferenceRecord] = {}` in `__init__`
- Add `upsert_interference(record)` — standard dict set by protocol_id
- Add `get_interference(protocol_id)` — standard dict get
- Update `close()` — add `self.interferences.clear()`
- Update `get_summary()` — add Interference Protocols section showing: protocol_id, phase, iteration, domain, source count, fragment count, emergent name if crystallized

### Step 3: Validation constants (`tools/think.py`)

Add module-level frozensets:

```python
_IP_PHASES = frozenset({
    "uninitiated", "domain_set", "sources_ready", "interfering",
    "saturated", "crystallized", "necessities_derived", "stress_tested",
})

_IP_ACTIONS = frozenset({
    "set_domain", "add_frame", "add_source", "add_fragment",
    "add_tension", "crystallize", "add_necessity", "update_necessity",
    "stress_test", "finalize", "recurse",
})

_IP_AUDIT_TYPES = frozenset({
    "first_principles", "ecosystem", "contingency", "failure_modes",
})

_IP_NECESSITY_STATUSES = frozenset({
    "untested", "holds", "fails",
})

_IP_VERDICTS = frozenset({
    "survives", "dies", "wounded",
})
```

### Step 4: `think_interfere` tool function (`tools/think.py`)

Single async function with `action` parameter dispatching to phase-specific logic.

**Signature:**
```python
async def think_interfere(
    action: str,                        # required — which operation
    session_id: str | None = None,      # auto-create think session
    protocol_id: str | None = None,     # auto-create on set_domain
    target_domain: str | None = None,   # for set_domain
    frame: str | None = None,           # for add_frame
    source_domain: str | None = None,   # for add_source
    law: str | None = None,             # for add_source
    isomorphism: str | None = None,     # for add_source
    fragment: str | None = None,        # for add_fragment
    tension_laws: list[int] | None = None,  # for add_tension (source indices)
    tension_description: str | None = None, # for add_tension
    name: str | None = None,            # for crystallize
    properties: list[dict] | None = None,   # for crystallize [{text, novel, source_laws}]
    conclusion: str | None = None,      # for add_necessity
    prerequisites: list[dict] | None = None, # for add_necessity [{claim, status}]
    chain_index: int | None = None,     # for update_necessity
    prereq_index: int | None = None,    # for update_necessity
    new_status: str | None = None,      # for update_necessity
    audit_type: str | None = None,      # for stress_test
    audit_result: str | None = None,    # for stress_test
    verdict: str | None = None,         # for finalize
    new_domain: str | None = None,      # for recurse
    concept_as_law: str | None = None,  # for recurse
) -> str:
```

**Phase gate enforcement (in-tool logic):**

| Action | Required phase | Transitions to | Prerequisites |
|--------|---------------|----------------|---------------|
| set_domain | (creates new) | domain_set | target_domain required |
| add_frame | domain_set | domain_set | frame required |
| add_source | domain_set or sources_ready | sources_ready (after 2+) | source_domain, law, isomorphism required |
| add_fragment | sources_ready or interfering | interfering (then saturated after 5+) | fragment required |
| add_tension | interfering or saturated | (stays) | tension_laws, tension_description required |
| crystallize | saturated | crystallized (if passes) | name, properties required. Emergence test: 2+ novel properties must reference 2+ sources |
| add_necessity | crystallized or necessities_derived | necessities_derived | conclusion, prerequisites required |
| update_necessity | necessities_derived | (stays) | chain_index, prereq_index, new_status required |
| stress_test | crystallized or necessities_derived or stress_tested | (stays) | audit_type, audit_result required |
| finalize | necessities_derived or stress_tested | stress_tested | verdict required |
| recurse | stress_tested | (creates new record) | new_domain, concept_as_law required |

**Rejection on wrong phase:** Return compact text with reason, current phase, and what actions are valid.

**Output format (compact text, every response):**
```
Session: {id} | Protocol: {protocol_id}
Phase: {phase} | Iter: {iteration} | Domain: {target_domain}
Sources: {n} | Fragments: {n}/5 | Frames: {n}
Status: {what happened — accepted/rejected + reason}
Next: {valid actions and guidance}
Suspended frames: {list if phase < stress_tested}
```

The suspended frames are included in output (phases 0-3.5) so the AI can apply frame detection. In Phase 4 (stress_test/finalize), they are omitted (frame detection lifted).

**Emergence test logic (in crystallize action):**
```
For each property where novel=True:
    for idx in property["source_laws"]:
        if idx not in range(len(record.source_laws)):
            reject: "Property '{text}' references nonexistent source index {idx}"
    if len(property["source_laws"]) < 2:
        reject: "Property '{text}' traces to single source — not emergent"
If no property has novel=True:
    reject: "No properties marked as novel — need at least 2"
If count of novel properties < 2:
    reject: "Need at least 2 novel properties for emergence"
```

**Necessity chain health check (in update_necessity):**
After updating a prerequisite status, check if any chain has all prerequisites as "fails" → report "chain broken."

### Step 5: `think_interfere_state` tool function (`tools/think.py`)

Read-only query tool:

```python
async def think_interfere_state(
    session_id: str,
    protocol_id: str,
) -> str:
```

Returns full state dump in compact text:
- Phase, iteration, domain
- All suspended frames
- All sources with domain, law, isomorphism
- All fragments and tensions
- Emergent name + properties (if crystallized)
- Necessity chains with statuses (if derived)
- Audit results + verdict (if tested)

### Step 6: Server registration (`server.py`)

Add to imports and `_TOOLS` list:
- `(think_interfere, "think_interfere", "Interference Protocol", _DEFAULT)`
- `(think_interfere_state, "think_interfere_state", "Interference Protocol State", _READONLY)`

Total tools: 33 + 2 = 35

### Step 7: Update server.py prompt and CLAUDE.md

**server.py `aismartbuddy-guide` prompt** (around line 211-231): Add to the Thinking Sessions section:
```
### Interference Protocol (Structured Novelty Generation)
- think_interfere(action="set_domain", target_domain="...") → start protocol
- think_interfere(action="add_source", protocol_id, source_domain, law, isomorphism)
- think_interfere(action="add_fragment", protocol_id, fragment)
- think_interfere(action="crystallize", protocol_id, name, properties)
- think_interfere(action="stress_test", protocol_id, audit_type, audit_result)
- think_interfere_state(session_id, protocol_id) → full state query
```

**CLAUDE.md**: Update tool count to "35 total tools: 6 SQL, 15 graph, 1 meta, 13 thinking". Add Interference Protocol to key patterns.

### Step 8: Tests (`tests/test_think_tools.py`)

Add `TestInterferenceProtocol` class with tests:

**Phase progression (happy path):**
1. set_domain → verify phase=domain_set, suspended frames returned
2. add_frame → verify frame stored
3. add_source (x3) → verify phase transitions to sources_ready after 2nd
4. add_fragment (x5) → verify phase transitions to interfering then saturated
5. add_tension → verify tension stored with source references
6. crystallize with emergence test passing → verify phase=crystallized
7. add_necessity → verify chain stored, phase=necessities_derived
8. update_necessity → verify prerequisite status updated
9. stress_test → verify audit stored
10. finalize → verify verdict stored, phase=stress_tested
11. recurse → verify new protocol created with iteration=2, old concept as source

**Rejection tests:**
- Try add_source before set_domain → rejected
- Try add_fragment before 2 sources → rejected
- Try crystallize with <5 fragments → rejected
- Crystallize with all novel=False → rejected (no novel properties)
- Crystallize with novel property tracing to 1 source → rejected (mashup)
- Try stress_test before crystallize → rejected
- Invalid action → rejected

**Necessity chain health test:**
- Create chain with 3 prerequisites, update all to "fails" → verify response indicates "chain broken"

**State query test:**
- Create protocol through multiple phases, query state, verify all data present

**Multi-protocol isolation:**
- Create 2 protocols in same session, verify independent state

---

## Verification

1. `uv run pytest tests/test_think_tools.py -v` — all tests pass including new interference tests
2. `uv run ruff check src/ tests/` — lint clean
3. `uv run pytest -v` — full suite passes, no regressions
4. Manual test: Start server, run through a complete 6-phase interference protocol, verify output format at each phase

---

## Non-Goals

- **NLP-level frame detection in the tool**: The tool enforces structural gates. The AI (which is an LLM) does semantic frame detection using the suspended frames the tool provides.
- **Persistent storage**: InterferenceRecord is in-memory like all Layer 1 thinking state. Layer 2 persistence is a future enhancement.
- **Visualization/export**: No Mermaid rendering of the interference state. Just compact text.

---

## TLDR

Add 2 MCP tools (`think_interfere` + `think_interfere_state`) implementing the Interference Protocol — an 8-state structured thinking framework for producing novel concepts through cross-domain interference patterns. Uses a single tool with `action` parameter for phase-specific operations, strict phase gates, mechanical emergence testing, and necessity chain tracking. Fits into existing ThinkingEngine as a new InterferenceRecord with upsert pattern. Tool provides structural enforcement while returning suspended frames so the AI applies semantic frame detection. Total: 35 tools.
