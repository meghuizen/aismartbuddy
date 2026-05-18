# Plan: Bundle assembly + authority tier + session density

## Verbatim Requirements

### Original Request
> Analyze the following youtube and see where aismartbuddy can improve knowing this.
> https://www.youtube.com/watch?v=lqiwQiDglGk

### Clarifications
**Q:** Which gap(s) to implement?
**A:** Bundle assembly, Authority tier + session density

---

## Context

Video: "Pinecone Just Demoted Vector Search" — about agent memory infrastructure.
Core problem: agents waste compute re-assembling context already processed (rediscovery).
Three of five identified AISmartBuddy gaps addressed here:

1. **Bundle assembly** — `think_bridge` does partial cross-backend assembly (think+graph) but
   SQL is excluded and no "task → assembled context" primitive exists. Agents make 3-4 calls
   to assemble what should be one.

2. **Authority tier** — `auto_graph=True` stamps model-inferred conclusions and user-confirmed
   facts identically (`source="ai"`). No machine-readable way to distinguish inference from
   ground truth; inference pollution is undetectable.

3. **Session density** — `think_monitor` tracks certainty at the claim level but gives no
   signal about session-level load. No proactive indicator before context rot sets in.

---

## Current State

### think_bridge (think.py ~3968)

Six action branches dispatched via conditionals after validating against `_BRIDGE_ACTIONS`
frozenset (think.py:212-221 via `_validate_enum`). Each branch calls
`_safe_graph_context_lines(think_session_id, entity_names=[...], target_name=...)` (~line 4007).
Companion resolution: `get_session_manager().find_companion_session(think_session_id, "graph")`
(think.py:343). `find_companion_session` already handles any backend string (session.py:540).

### knowledge nodes (graph.py ~946, ~1150; __init__.py ~246)

KnowledgeNode NODE TABLE is declared with a fixed column list in **three places**:
- `graph_knowledge_add` (~line 1011)
- `knowledge_batch` (~line 1206)
- `materialize_auto_graph` in tools/__init__.py (~line 246)

CREATE Cypher: `{name, description, entity_type, confidence, source, created_at}` — no
`authority` column. **Both the TABLE DDL and the CREATE Cypher must be extended in all 3 places.**

`materialize_auto_graph` issues inline Cypher directly (NOT via `graph_knowledge_add`);
the authority stamp must target the inline CREATE at `tools/__init__.py:273-278`.

All Cypher in the codebase uses **f-string interpolation + `_escape_cypher_string`** for user
values — NOT `$param` binding.

### think_monitor (think.py ~2268)

Dispatches on `stage` field (validated against `_MONITOR_STAGES`) and on `items=[]` presence.
No `action` parameter exists. Adding a meta-operation like "density" requires introducing an
`action` short-circuit before the items/stage dispatch.

Engine methods accessible: `engine.thought_nodes` dict, `engine.get_node_count()` (line ~855),
`ThoughtNode.depth`, `engine.thought_trees` dict.

---

## Changes

### 1. Bundle assembly — new `bundle` action on `think_bridge`

**File:** `tools/think.py`

**a) Add to `_BRIDGE_ACTIONS` frozenset** (think.py:212-221):
Add `"bundle"` and `"authoritative_source"` to the frozenset so `_validate_enum` accepts them.

**b) Add three optional params to `think_bridge` signature**:
```
entity_ids: list[str] | None = None
confidence_min: float | None = None
include_sql_tables: list[str] | None = None
```

**c) Add `bundle` action branch** (after existing six branches):
- Require `entity_ids` non-empty; raise ValueError if missing
- For each entity in `entity_ids`:
  - Collect think nodes referencing the entity (reuse `thoughts_for_entity` logic)
  - Call `_safe_graph_context_lines(think_session_id, entity_names=[entity])`
  - If `confidence_min` is set: issue a separate Cypher against the graph companion:
    `f"MATCH (n:KnowledgeNode) WHERE n.name = '{_escape_cypher_string(entity)}' AND n.confidence >= {confidence_min} RETURN n.name, n.confidence, n.source LIMIT 10"`
    (bypasses _safe_graph_context_lines for the confidence-filtered path)
- If `include_sql_tables` non-empty:
  - Resolve SQL companion: `get_session_manager().find_companion_session(think_session_id, "sql")`
    returns `str | None` (session.py:540). If found, resolve to SessionInfo via `mgr.get_session(sql_session_id)`.
  - If found, for each table (validated against `^[A-Za-z0-9_]+$` — same pattern as user_id
    validation in identity.py):
    - Call module-level `await execute_and_format(sql_info, mgr, f"SELECT * FROM {table} LIMIT 20")`
      (`execute_and_format` is a free function in tools/__init__.py:337, not an engine method;
      it already acquires the session lock internally — no additional `run_with_lock` wrapper)
    - Collect as CSV block
  - If companion not found: skip silently (same fail-safe pattern as graph companion)
- Assemble output in sections: `## Think`, `## Graph`, `## SQL`
- Return `"\n".join(lines)` string

**d) Update `think_bridge` docstring**: add `bundle` and `authoritative_source` to the
8-action list (currently says "Six actions"). Document new params.

---

### 2. Authority tier — `authority` field on knowledge nodes

**File:** `tools/graph.py`

**a) `graph_knowledge_add` — TWO changes at ~line 1006-1030**:

1. Add `authority: str | None = None` param. Validate with a None-guard:
   `if authority is not None: _validate_enum(authority, {"ground_truth", "primary", "inferred", "external"}, "authority")`
   (graph.py has its own `_validate_enum` import from think.py — verify the import before use,
   or inline the validation as a simple `if authority not in {...}: raise ValueError(...)`)

2. NODE TABLE DDL (line ~1011): add `authority STRING` to the existing column list.
   The current schema uses `id SERIAL PRIMARY KEY` — only add the new column, do not restructure.
   Note: `IF NOT EXISTS` does NOT alter existing tables. This only applies to fresh sessions.
   No migration of existing data is in scope; existing nodes will have `authority = ""`.

3. CREATE Cypher (line ~1023): add `authority: '{_escape_cypher_string(authority or "")}'`

**b) `knowledge_batch` — same two changes at ~line 1202-1212**:
1. NODE TABLE DDL (line ~1206): add `authority STRING` column (same as above)
2. Node schema parsing: `authority = n.get("authority", "")` then add to the CREATE Cypher
3. Update docstring node schema block to list `authority?` with four enum values

**c) `materialize_auto_graph` in `tools/__init__.py` — TWO changes at ~line 246-278**:
1. NODE TABLE DDL (line ~246): add `authority STRING` column
2. Inline CREATE Cypher (line ~273-278): add `authority: 'inferred'` — hardcoded since all
   auto_graph-materialised nodes originate from model reasoning

**d) New `authoritative_source` action on `think_bridge` in `tools/think.py`**:
Add branch: requires `entity_name`.
Resolve graph companion. If found, run:
```python
q = (
    f"MATCH (n:KnowledgeNode) WHERE n.name = '{_escape_cypher_string(entity_name)}' "
    f"RETURN n.name, n.authority, n.source, n.confidence"
)
```
Fetch results, sort in Python by authority rank
(`ground_truth=0, primary=1, external=2, inferred=3, ""=4`).
Also include think-side hypotheses referencing the entity (reuse `hypotheses_for_entity` logic).
Return ranked list: authority tier, confidence, source, for each result.

---

### 3. Session density — `density` action on `think_monitor`

**File:** `engines/thinking_engine.py`

Add `get_session_stats() -> dict` as an undecorated read method (consistent with
existing read methods `get_node_count`, `get_tree_ids`, `get_node`):
```python
def get_session_stats(self) -> dict:
    nodes = list(self.thought_nodes.values())
    all_refs = {r for n in nodes for r in n.refs}
    return {
        "node_count": len(nodes),
        "tree_count": len(self.thought_trees),
        "max_depth": max((n.depth for n in nodes), default=0),
        "entity_count": len(all_refs),
        "revision_count": sum(len(n.revision_history) for n in nodes),
        "export_token_estimate": sum(len(n.content) for n in nodes) // 4,
    }
```
Note: token estimate covers thought content only — sessions heavy in hypotheses/evidence will
read lower than actual. Document this limitation in the output.

**File:** `tools/think.py`

Add `action: str | None = None` param to `think_monitor` signature.
At the top of the function body (before the items/stage dispatch), add an `action` short-circuit:
```python
if action == "density":
    stats = await anyio.to_thread.run_sync(engine.get_session_stats)
    # recommendation logic
    if stats["node_count"] > 80 or stats["export_token_estimate"] > 6000:
        rec = "summarize"
    elif stats["tree_count"] > 4 and stats["node_count"] > 40:
        rec = "delegate"
    else:
        rec = "continue"
    # format as text block + return
```
Return a single text block with all stats, the note about estimate scope, and `recommendation: {rec}`.

Update `think_monitor` docstring: document `action="density"` before the existing items/stage
documentation.

---

### 4. Documentation update

**File:** `CLAUDE.md`

Update:
- think_bridge description: "Six actions" → "Eight actions"; add `bundle` and `authoritative_source`
- Add authority field description to the knowledge graph tools section
- Add density action to think_monitor description
- Note that auto_graph-materialised nodes carry `authority="inferred"`

---

## File Change Summary

| File | Change |
|------|--------|
| `tools/think.py` | think_bridge: `_BRIDGE_ACTIONS` + 3 new params + `bundle` + `authoritative_source` actions; think_monitor: `action` param + `density` short-circuit; docstrings |
| `tools/graph.py` | graph_knowledge_add: `authority` param + DDL column + CREATE field; knowledge_batch: same |
| `tools/__init__.py` | materialize_auto_graph: DDL column + `authority: 'inferred'` in inline CREATE |
| `engines/thinking_engine.py` | Add `get_session_stats()` method |
| `CLAUDE.md` | Update tool descriptions for new actions and authority field |

`session.py` — no change needed; `find_companion_session` already exists at line 540.

---

## Edge Cases

- **bundle with no entity_ids**: raise ValueError("entity_ids required for bundle action")
- **bundle, no SQL companion**: skip SQL section silently, no error
- **authority=None**: stored as empty string; `authoritative_source` treats `""` as rank 4
- **authority=None in knowledge_batch items**: same — `n.get("authority", "")` defaults to `""`
- **density on empty session**: all zeros, recommendation="continue"
- **confidence_min with no graph companion**: skip confidence-filtered Cypher, include think-only context
- **table name injection**: validate each table against `^[A-Za-z0-9_]+$` before SQL interpolation
- **IF NOT EXISTS DDL on existing sessions**: authority column missing on existing KnowledgeNode
  tables — authority-aware queries will return empty string, not an error (LadybugDB returns
  default for missing string properties). Acceptable for now; no migration in scope.

---

## Tests to add

- `tests/test_think_tools.py`: bundle action returns think context when no companion; no error when include_sql_tables=[] and no SQL companion; entity_ids=None raises ValueError
- `tests/test_graph_tools.py`: graph_knowledge_add with authority="ground_truth" stores field; knowledge_batch with authority on one node stores it; authority="" on nodes without it
- `tests/test_think_tools.py`: think_monitor(action="density") returns stats dict shape; recommendation="summarize" when node_count > 80
- `tests/test_think_tools.py`: think_bridge authoritative_source returns ranked list; returns think-side hypotheses when no graph companion

---

## Non-Goals

- Session resume / cross-session seed (separate, large effort)
- Document tree ingest (separate quick win)
- Migrating existing knowledge nodes to add authority values
- Per-backend active session tracking
- confidence_min post-fetch text filtering (fragile; Cypher-based path used instead)

---

## Verification

```bash
uv run pytest -v                    # no regressions (473 tests + new)
uv run pyright                      # type check
uv run ruff check src/ tests/       # lint

# Functional smoke tests:
# 1. knowledge_batch(nodes=[{entity="x", authority="ground_truth"}, {entity="y"}])
#    graph_query: MATCH (n:KnowledgeNode) RETURN n.name, n.authority
#    → x has "ground_truth", y has ""
# 2. think_model(items=[...], auto_graph=True)
#    graph_query: MATCH (n:KnowledgeNode) WHERE n.source='ai' RETURN n.authority
#    → all rows have "inferred"
# 3. think_monitor(action="density") without session_id
#    → auto-creates, returns stats block with recommendation="continue"
# 4. think_bridge(action="bundle", entity_ids=["x"]) with graph companion
#    → returns "## Think" + "## Graph" sections, no errors
# 5. think_bridge(action="authoritative_source", entity_name="x")
#    with ground_truth + inferred node for same entity
#    → ground_truth node ranked first
```

---

## TLDR

Three targeted additions addressing agent memory failure modes from the video: a `bundle` action
on `think_bridge` that assembles think+graph+SQL context in one call; an `authority` field on
knowledge nodes (added to all three DDL sites + auto-stamped `"inferred"` via auto_graph) making
inference pollution detectable; and a `density` action on `think_monitor` that reports session
load and emits a summarize/delegate/continue recommendation. The critical reviewer findings were
all addressed: NODE TABLE DDL updated in all three locations, inline Cypher target corrected in
materialize_auto_graph, think_monitor dispatch approach clarified, Cypher uses f-string pattern,
and SQL execution uses run_with_lock + validated identifiers.
