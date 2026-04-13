# Plan: Implement Holonic Thinking Tools

## Verbatim Requirements

### Original Request
> Use clear-thought. I want to build a real practical and workable option to think in holons. [...] I want a full working practical implementation tested against that pathophysiology case.

### Clarifications
**Q:** Consolidate into tools with action parameters?
**A:** Yes, consolidated tools (Recommended)

**Q:** Include four drives analysis?
**A:** Include as optional extensible lenses. AI can define new ones.

**Q:** Naming prefix?
**A:** holon_* prefix (distinct from think_*)

**Q:** Plan review feedback (detailed):
**A:** (1) Replace parent_id+peers with memberships list for multi-holarchy. (2) Add projections dict per holarchy. (3) Add stale_projections tracking. (4) Add coherence and bridge actions. (5) Add holon_query as 5th tool. (6) Propagation must modify data model state. (7) Remove peers field (derivable from memberships). 5 tools total.

## Context

Holonic thinking models domains where every entity is simultaneously a whole and a part — and critically, can participate in MULTIPLE holarchies simultaneously. A mitochondrion is part of a cell (structural), part of energy metabolism (functional), and part of apoptosis signaling (regulatory). Single-parent trees can't represent this.

The tools let AI build multi-membership holarchies, navigate between levels with context preservation, detect emergent properties, propagate insights with structural traces, query from specific vantage points, and find bridges between distant holons.

---

## Design

### Data Model: HolonNode

```
HolonNode:
    id: str
    name: str
    description: str               # what this holon IS (as a whole)
    context: str                   # working state at this level
    rules: list[str]               # internal constraints
    properties: list[str]          # observable properties

    # Multi-holarchy participation (the key structural innovation)
    memberships: list[dict]        # [{holarchy_id, parent_id, role_in_parent, level}]

    # Per-holarchy projections (what the holon exposes upward)
    projections: dict[str, str]    # {holarchy_id: projected_state}
    stale_projections: list[str]   # holarchy_ids where projection may be outdated

    # Extensible analytical lenses
    analytical_lenses: list[dict]  # [{name, findings}]

    children_by_holarchy: dict[str, list[str]]  # {holarchy_id: [child_ids]}
    created_at: datetime
```

Key design decisions:
- **memberships replaces parent_id + peers**: A holon belongs to multiple holarchies with different parents and roles in each. Peers are derivable (holons sharing a parent in the same holarchy).
- **projections separate from description**: Description is identity ("autonomous self-replicating unit"). Projection is what the parent sees ("inflamed, metabolically compromised, Th1-dominant"). Distinct concepts.
- **stale_projections**: Propagation leaves structural traces. When a child propagates up, the parent's projection gets flagged as stale in all holarchies containing that child.
- **children_by_holarchy**: Computed/maintained per holarchy. When a holon joins a holarchy with a parent, the parent's children_by_holarchy[holarchy_id] gets the child's ID.
- **level is per-membership, not absolute**: A mitochondrion might be level 4 in the structural holarchy and level 2 in the metabolic holarchy.

### Memory Management

```
MAX_HOLONS = 1000
MAX_HOLARCHIES = 30  # holarchies within a workspace

holon_nodes: dict[str, HolonNode]        # all holons by ID
holon_holarchies: dict[str, str]         # holarchy_id → root_holon_id
```

No separate workspace concept needed — the holarchies dict serves as the grouping. A single session can contain multiple holarchies that share holons (which is the whole point of multi-membership).

### Tool 1: `holon_create`

```python
async def holon_create(
    name: str,
    description: str,
    session_id: str | None = None,
    holarchy_id: str | None = None,      # auto-create for root
    parent_id: str | None = None,        # None = root of new holarchy
    role_in_parent: str = "",
    context: str = "",
    rules: list[str] | None = None,
    properties: list[str] | None = None,
    projection: str = "",                # initial projection in this holarchy
) -> str:
```

Creates a holon. If parent_id=None, creates a new holarchy with this holon as root. If parent_id given, adds the holon as a child in the specified holarchy (joining that holarchy).

To add an EXISTING holon to a SECOND holarchy, use `holon_update` with `action="join_holarchy"`.

Output:
```
Session: {sid} | Holarchy: {hid} | Holon: {id}
Name: {name} | Level: {level} | Memberships: 1
Parent: {parent_name} | Role: {role}
Status: created
```

### Tool 2: `holon_update`

```python
async def holon_update(
    session_id: str,
    holon_id: str,
    action: str,
    # context/description/projection updates
    content: str | None = None,
    # rules/properties updates
    rules: list[str] | None = None,
    properties: list[str] | None = None,
    # join_holarchy params
    holarchy_id: str | None = None,
    parent_id: str | None = None,
    role_in_parent: str | None = None,
    projection: str | None = None,
    # add_lens params
    lens_name: str | None = None,
    lens_findings: str | None = None,
) -> str:
```

Actions:
- `context` — update working state
- `rules` — replace internal constraints
- `description` — update what the holon IS
- `properties` — update observable properties
- `projection` — update projected state in a specific holarchy (requires holarchy_id)
- `join_holarchy` — add this holon to another holarchy with a different parent/role (requires holarchy_id, parent_id, role_in_parent)
- `add_lens` — add an analytical lens result (extensible — any name)

### Tool 3: `holon_view`

```python
async def holon_view(
    session_id: str,
    holon_id: str,
    action: str = "cross_level",
    holarchy_id: str | None = None,      # which holarchy perspective
    levels_up: int = 1,
    levels_down: int = 1,
) -> str:
```

When holarchy_id is provided, navigation follows that holarchy's parent-child structure. When omitted and the holon has only one membership, that's used. When omitted with multiple memberships, returns a membership overview.

Actions:
- `zoom_in` — descend one level in the specified holarchy. Returns children with descriptions/roles PLUS parent context as constraint header. If any projections are stale, shows warning.
- `zoom_out` — ascend one level. Returns parent's full state, all siblings with context summaries, synthesis prompt: "Given what you learned at the child level, does the parent context need updating?"
- `sideways` — view peers (children of same parent in same holarchy). Shows each peer's description, role, projection. Parent context as shared frame. Detected tensions between peers.
- `cross_level` — three-level view: ancestry (up to levels_up), the holon, descendants (down to levels_down). Shows stale projections.
- `memberships` — show all holarchies this holon participates in, with role/level/parent in each. Useful when holon has multiple memberships.

### Tool 4: `holon_analyze`

```python
async def holon_analyze(
    session_id: str,
    action: str,
    holon_id: str | None = None,
    holarchy_id: str | None = None,
    # propagation params
    insight: str | None = None,
    propagation_type: str | None = None,
    # lens params
    lens_name: str | None = None,
    lens_prompt: str | None = None,
    # coherence params
    holon_a_id: str | None = None,
    holon_b_id: str | None = None,
    # bridge params
    from_id: str | None = None,
    to_id: str | None = None,
) -> str:
```

Actions:
- `tensions` — scan for pathological patterns: missing intermediate holons, cross-level rule violations, conflicting projections, circular containment, membership conflicts. Scope: when holon_id is None, scan all holons in all holarchies. When holon_id given but holarchy_id None, scan all memberships of that holon. When both given, scan that holon's participation in that holarchy.
- `emergence` — compare holon's properties to sum of children's properties. Gap = emergent properties.
- `propagate_up` — push insight upward. Modifies actual data:
  - `inform`: append to parent's context, flag parent's projections as stale in all holarchies
  - `constrain`: add to parent's RULES
  - `transform`: mark parent's description as potentially invalid (add `__description_stale` to stale_projections), surface warning in next holon_view
  Returns chain of affected holons with what changed.
- `propagate_down` — push directive downward. Modifies actual data:
  - `constrain`: add to ALL descendants' rules within scope
  - `enable`: add to descendants' properties
  - `restructure`: flag descendants' descriptions as potentially invalid
  Returns affected holons.
- `coherence` — given two holon IDs, assess what each implies about the other. Gathers both holons' projections, context, rules, and presents: "Given holon A's state and holon B's state, what must be true for both to be coherent? What can be verified or falsified?"
- `bridge` — find the shortest path between two holons. BFS across ALL holarchies, traversing parent and child links in every holarchy each holon participates in. Returns intermediate holons, potentially crossing holarchy boundaries through shared holons. Critical for pathophysiology: "How does psychological stress connect to mitochondrial complex I dysfunction?"
- `lens` — apply an analytical lens. Built-in suggestions: agency, communion, transcendence, dissolution. But any lens_name + lens_prompt works. Findings stored on the holon.

### Tool 5: `holon_query`

```python
async def holon_query(
    session_id: str,
    question: str,
    vantage_id: str,                     # from whose perspective
    holarchy_id: str | None = None,      # which holarchy
    resolution: str = "local",           # local | subtree | holarchy
) -> str:
```

Assembles context from the specified vantage point at the specified resolution:
- `local` — the holon's own state + parent context + immediate children
- `subtree` — the holon + all descendants in the specified holarchy
- `holarchy` — the entire holarchy, centered on the vantage holon

Returns a structured briefing with the question, all gathered context, and prompts the AI to reason over it. This is structured context assembly — the embryonic form of perspectival reconstruction. The interface is designed so that Layer 2 can make the implementation smarter without changing the tool contract.

Output:
```
Session: {sid} | Query from: {vantage_name} | Resolution: {resolution}
Question: {question}

## Vantage Point: {vantage_name}
{description}
Context: {context}
Projection: {projection}
Rules: {rules}

## Visible Context ({resolution}):
{gathered context from resolution scope}

## Stale Projections:
{any flagged stale projections in scope}
```

---

## Implementation Steps

### Files to create:
- `src/aismartbuddy/tools/holon.py` — 5 holonic tool functions + validation constants

### Files to modify:
- `src/aismartbuddy/engines/thinking_engine.py` — add HolonNode, engine methods
- `src/aismartbuddy/server.py` — register 5 new tools, update guide prompt
- `tests/test_think_tools.py` — add holonic test classes
- `CLAUDE.md` — update tool count, add holon_* prefix

### Step 1: HolonNode dataclass + engine methods (`engines/thinking_engine.py`)

Add HolonNode dataclass with multi-membership model.
Add MAX_HOLONS=1000, MAX_HOLARCHIES=30 constants.

Add to ThinkingEngine.__init__:
- `self.holon_nodes: dict[str, HolonNode] = {}`
- `self.holon_holarchies: dict[str, str] = {}` (holarchy_id → root_id)

Engine methods:
- `add_holon(node)` — store, update parent's children_by_holarchy, trigger cleanup
- `join_holarchy(holon_id, holarchy_id, parent_id, role, level)` — add membership + update parent's children
- `get_holon(id)` → HolonNode | None
- `get_holon_children(holon_id, holarchy_id)` → list[HolonNode]
- `get_holon_parent(holon_id, holarchy_id)` → HolonNode | None
- `get_holon_siblings(holon_id, holarchy_id)` → list[HolonNode]
- `get_holon_ancestry(holon_id, holarchy_id)` → list[HolonNode]
- `get_holon_subtree(holon_id, holarchy_id, max_depth=None)` → list[HolonNode]
- `find_bridge(from_id, to_id)` → list[HolonNode] (BFS across all holarchies)
- `get_holarchy_ids()`, `get_holon_count()`
- `_cleanup_holon_memory()` — evict oldest holarchies when limits exceeded
- `_evict_holarchy(holarchy_id)` — multi-membership-safe eviction: (1) remove holarchy from holon_holarchies, (2) for each holon in that holarchy, remove the membership entry and children_by_holarchy[holarchy_id] entry, (3) remove projections[holarchy_id] and stale_projections entries for that holarchy, (4) delete holons that have zero remaining memberships after cleanup

Update close(): add `self.holon_nodes.clear()` and `self.holon_holarchies.clear()`. Update get_summary(): add Holonic Workspaces section showing holarchy count, holon count, multi-membership holons count, stale projection count.

### Step 2: 5 tool functions (`tools/holon.py` — new file)

Add validation constants:
```python
_HOLON_UPDATE_ACTIONS = frozenset({
    "context", "rules", "description", "properties",
    "projection", "join_holarchy", "add_lens",
})
_HOLON_VIEW_ACTIONS = frozenset({
    "zoom_in", "zoom_out", "sideways", "cross_level", "memberships",
})
_HOLON_ANALYZE_ACTIONS = frozenset({
    "tensions", "emergence", "propagate_up", "propagate_down",
    "coherence", "bridge", "lens",
})
_HOLON_PROPAGATION_TYPES = frozenset({
    "inform", "constrain", "transform", "enable", "restructure",
})
_HOLON_QUERY_RESOLUTIONS = frozenset({
    "local", "subtree", "holarchy",
})
```

Create new file `src/aismartbuddy/tools/holon.py`. Import _get_or_create_think_session, _engine, _validate_enum from tools/think.py. Implement holon_create, holon_update, holon_view, holon_analyze, holon_query. Step 3 imports from this file.

### Step 3: Server registration + prompt

Register 5 tools. Update aismartbuddy-guide with Holonic Workspace section.

### Step 4: Update CLAUDE.md

Update tool count (37 + 5 = 42). Update naming convention to include `holon_*`. Document that holon tools model domains holonically.

### Step 5: Tests — pathophysiology case + unit tests

**TestHolonCreate**: create root, create children, auto-holarchy
**TestHolonUpdate**: context, rules, join_holarchy (multi-membership), projection, add_lens
**TestHolonView**: zoom_in (parent context preserved), zoom_out (synthesis prompt), sideways (peer tensions), cross_level, memberships (multi-holarchy view)
**TestHolonAnalyze**: tensions, emergence, propagate_up (modifies parent context + flags stale), propagate_down (modifies descendant rules), coherence (two-holon assessment), bridge (path finding), lens
**TestHolonQuery**: local/subtree/holarchy resolution, stale projections in output

**TestPathophysiologyCase** (integration test):
Build ME/CFS holarchy with multi-membership:
- Structural holarchy: Organism → Systems → Organs → Cells → Molecules
- Functional holarchy: Energy Metabolism → Mitochondria → Complex I/II/III/IV
- Regulatory holarchy: Stress Response → HPA Axis → Cortisol → GR Signaling
- Mitochondrion participates in ALL THREE holarchies

Test operations:
1. Create holarchies and holons with multi-membership
2. zoom_in("Immune System", holarchy_id="structural") → children with parent context
3. sideways("Immune System", holarchy_id="structural") → HPA Axis, Nervous System as peers
4. coherence("Cortisol Signaling", "Mitochondrial Complex I") → what must be true for both to cohere
5. bridge("Psychological Stress", "Mitochondrial Complex I") → trace causal chain through intermediaries
6. propagate_up from "Cortisol Signaling" with insight → verify parent context updated AND projection flagged stale
7. detect_tensions on workspace → verify cross-holarchy tensions detected
8. holon_query(question="How does stress reach the mitochondria?", vantage_id="Mitochondrion", resolution="holarchy") → comprehensive briefing
9. Apply custom lens "vulnerability" → verify stored

**Error tests**: invalid actions, nonexistent IDs, missing required params

---

## Verification

1. `uv run pytest tests/test_think_tools.py -v` — all tests pass
2. `uv run ruff check src/ tests/` — lint clean
3. `uv run pytest -v` — full suite passes
4. Manual: Build ME/CFS holarchy, navigate it, find bridges, detect emergence

---

## Non-Goals

- **Holographic database / perspectival reconstruction**: Layer 2 future work. holon_query establishes the interface pattern.
- **Quantified projections**: Projections are qualitative (AI-filled text). Transfer functions are future.
- **Auto-decomposition**: AI decides what holons to create. Tool stores and navigates.
- **Cross-session persistence**: Layer 1, in-memory.

---

## TLDR

Add 5 holonic tools (`holon_create`, `holon_update`, `holon_view`, `holon_analyze`, `holon_query`) with a multi-membership data model where holons participate in multiple holarchies simultaneously. Navigation preserves context during level transitions (zoom_in includes parent context, zoom_out includes synthesis prompt). Propagation leaves structural traces (stale projections, modified rules). Bridge finds causal paths between distant holons. Query assembles context from a vantage point at a resolution. Analytical lenses are extensible. Tested against ME/CFS pathophysiology with structural, functional, and regulatory holarchies sharing holons across all three.
