# Plan: Domain grouping + entity registration gap

## Verbatim Requirements

### Original Request
> Now this aismartbuddy is a general mcp tool to extend AI thinking and give AI a problem
> knowledge and mapping service, so it's not only for omics and omics specific tasks should
> probably on a specific omics mcp server. However analyze the feedback on the aismartbuddy
> tool usage and see where the server can actually be improved for general thinking which help
> for this situation, but also for software development, working with multiple "groups" /
> domains of knowledge (like inflammation, microbiology, RNA gene expression, DNA). Or for
> software development: front-end, backend, database, background jobs, user interface side,
> database side and connecting links between domains. Also the entity registration gap.

---

## Context

From the medical research meta-analysis two structural gaps surfaced that limit AISmartBuddy's
usefulness across ALL multi-domain reasoning tasks (biology, software architecture, business
analysis, etc.):

1. **Entity registration gap** — `think_bridge(action="thoughts_for_entity", entity_name="NLRX1")`
   returns nothing because `metadata["knowledge_refs"]` is never set automatically. The bridge
   query strategy is also inconsistent: `thoughts_for_entity` uses metadata lookup while
   `hypotheses_for_entity` uses full-text search on the statement.

2. **No domain grouping** — domain fields exist on 6 record types (HypothesisRecord.domain,
   ConstraintRecord.domain, EvidenceRecord.domain, ArtifactRecord.domain_tags, etc.) but:
   - Most batch tools (`think_model`, `think_graph`, `think_decide`) don't expose a `domain`
     param on their items[]
   - No tool queries by domain ("give me everything about the metabolism domain")
   - KnowledgeNode graph lacks a `domain` column — `entity_type` is the only categorical field
   - No cross-domain connection query ("what links frontend to backend in the graph?")
   - `knowledge_batch properties` dict is stored as a string blob in `description`, not as
     queryable columns

The fix makes domain a first-class attribute across the think + graph layers and adds a
`entity_refs` convention that closes the bridge lookup gap.

---

## Current State

### Entity registration (think.py)

`thoughts_for_entity` (think.py ~line 4009):
- Searches `node.metadata.get("knowledge_refs", [])` — a list of entity names
- This list is **never auto-populated** by any tool; caller must manually set it
- Results: always empty unless the calling agent explicitly populated `knowledge_refs` in metadata

`hypotheses_for_entity` (think.py ~line 4060):
- Full-text search on `hypothesis.statement.lower()`
- Works without any manual registration
- Inconsistency with `thoughts_for_entity` — same action family, different lookup strategy

`collect_item_refs()` (__init__.py:175-188):
- Merges `item["connects_to"]` and `item["refs"]` into a deduplicated list
- Used by think_graph, think_model, think_decide — NOT by think_science

`think_science items[]` processing (think.py ~2085):
- Creates `InquiryRecord` — does NOT call `collect_item_refs()`
- No `entity_refs` extraction, no `knowledge_refs` population

### Domain fields (thinking_engine.py)

Record types WITH domain fields (but not exposed to batch tools):

| Record type | Field | Default |
|-------------|-------|---------|
| HypothesisRecord | domain: str | "" |
| ConstraintRecord | domain: str | (required) |
| EvidenceRecord | domain: str | "" |
| TopologyRecord | source_domain: str | "" |
| InterferenceRecord | target_domain: str | "" |
| ArtifactRecord | domain_tags: list[str] | [] |

Record types WITHOUT domain fields (confirmed by code inspection):
- ThoughtNode (line ~75): has `metadata: dict = field(default_factory=dict)` — domain stored in `metadata["domain"]`
- ModelRecord (line ~84): NO metadata dict — only model_name/problem/steps/reasoning/conclusion/record_id/refs/rule_bindings/timestamp
- DecisionRecord (line ~107): NO metadata dict — only decision_id/statement/options/.../refs/rule_bindings/timestamp
- InquiryRecord (line ~165): NO metadata dict — only inquiry_id/stage/observation/question/hypothesis/experiment/analysis/conclusion/refs/rule_bindings/timestamp
- MonitorRecord (line ~186): NO metadata dict — only monitoring_id/task/stage/.../refs/rule_bindings/timestamp

**Implication:** storing domain in `metadata["domain"]` is only possible for ThoughtNode. ModelRecord, DecisionRecord, InquiryRecord, and MonitorRecord require a new `domain: str = ""` field to be added to their dataclasses — consistent with the HypothesisRecord.domain pattern (line ~443). This requires `engines/thinking_engine.py` changes.

### KnowledgeNode graph (graph.py)

Current DDL columns: `id, name, description, entity_type, confidence, source, created_at, authority`
Domain: NOT present.
`entity_type` is the closest proxy and is already used for Cypher WHERE filtering
(e.g., `WHERE a.entity_type = 'question'` in graph_knowledge_infer).

`knowledge_batch properties` field: stored as a stringified dict in the `description` column —
completely non-queryable as structured data.

### _BRIDGE_ACTIONS frozenset (think.py:~212-227)

Current 8 actions: thoughts_for_entity, entities_for_thought, hypotheses_for_entity,
evidence_for_hypothesis, constraints_for_hypothesis, full_context, bundle, authoritative_source.

`domain_context` and `domain_connections` are NOT present.

### think_bridge signature (think.py:~3972)

Current params: action, session_id, entity_name, node_id, hypothesis_id, target_id,
target_type, entity_ids, confidence_min, include_sql_tables.
`domain` and `domain_b` are NOT present.

---

## Changes

### 1. Entity registration — `entity_refs` field + `thoughts_for_entity` text fallback

**Goal:** Close the gap so bridge queries find nodes regardless of whether the caller
populated knowledge_refs manually.

#### 1a. `thoughts_for_entity` text fallback (think.py ~line 4009-4027)

After the existing knowledge_refs lookup, if `matches` is empty, fall back to
case-insensitive substring search on `node.content` — matching the behaviour of
`hypotheses_for_entity`. Prepend `"(text match)"` to the match string so callers
can distinguish the two lookup paths in the output.

Pattern: look at `hypotheses_for_entity`'s statement search as the reference implementation.

#### 1b. `entity_refs` as a recognized field in batch items[] processing — ThoughtNode only

**Scope:** `entity_refs` registration is scoped to `think_graph (thoughts=[])` only, because
`thoughts_for_entity` exclusively scans `engine.thought_nodes`. Registering entity_refs on
ModelRecord/DecisionRecord/InquiryRecord metadata would be silently useless — `thoughts_for_entity`
would never find them even if storage existed.

When an item in `thoughts=[]` contains `entity_refs: list[str]`:
1. After `add_thought` / `add_node`, call `engine.get_node(new_id)` and set
   `node.metadata["knowledge_refs"] = entity_refs_val` (merge with existing if present)
2. Do NOT add to structural refs — entity_refs name external concepts, not record IDs;
   they must not create DerivedFrom graph edges

Change location: think.py thoughts[] handler (~line 911, not ~744 which is the function def).

**think_model, think_decide, think_science**: do NOT support `entity_refs`. These record types
have no pathway to thoughts_for_entity. If future work extends bridge actions to scan other
record types, entity_refs can be added then. Document this limitation in the docstring updates.

#### 1c. Update `think_science` items[] to call `collect_item_refs()`

`think_science` is the only batch tool that skips `collect_item_refs()`. Fix: pass
`refs=collect_item_refs(it)` in the InquiryRecord constructor at think.py ~line 2151.
This mirrors the HypothesisRecord pattern at think.py:3151 (`refs=_collect_refs(it)`).
InquiryRecord already has a `refs: list[str]` field (confirmed at line 181).

#### 1d. Documentation update in think_bridge docstring

Add `entity_refs: list[str]` as a recognized optional field in the items[] description for
the tools that accept it. Explain the distinction from `refs` (structural IDs) and
`entity_refs` (external entity names).

---

### 2. Domain tagging — `domain` param on batch items[] + KnowledgeNode column

**Goal:** Make domain a first-class taggable attribute on all batch-created records and
graph nodes, queryable without parsing string blobs.

#### 2a. `domain` param on batch items[] + dataclass additions

ModelRecord, DecisionRecord, InquiryRecord, and MonitorRecord have no `metadata: dict` field.
Domain storage requires adding `domain: str = ""` to each dataclass — consistent with the
existing `HypothesisRecord.domain` pattern (engines/thinking_engine.py ~line 443).

**Dataclass changes (engines/thinking_engine.py):**

Add `domain: str = ""` after `refs: list[str]` in:
- `ModelRecord` (line ~84)
- `DecisionRecord` (line ~107)
- `InquiryRecord` (line ~165)
- `MonitorRecord` (line ~186)

ThoughtNode already stores domain in `metadata["domain"]` — no dataclass change needed.

**Storage per tool:**

| Tool | How to store |
|------|-------------|
| `think_graph (thoughts=[])` | `node.metadata["domain"] = domain_val` after add_thought (ThoughtNode uses metadata) |
| `think_model (items=[])` | Pass `domain=domain_val` to ModelRecord constructor (new field) |
| `think_decide (items=[])` | Pass `domain=domain_val` to DecisionRecord constructor (new field) |
| `think_science (items=[])` | Pass `domain=domain_val` to InquiryRecord constructor (new field) |
| `think_monitor (items[])` | Pass `domain=domain_val` to MonitorRecord constructor (new field) |
| `think_hypothesis (items=[])` | Already sets `HypothesisRecord.domain` from `it.get("domain")` at line 3147 — no change needed |

**domain_context bridge queries** use the SAME access pattern per type:
- ThoughtNode: `node.metadata.get("domain") == domain`
- ModelRecord/DecisionRecord/InquiryRecord/MonitorRecord: `record.domain == domain`
- HypothesisRecord: `record.domain == domain` (already has domain field)

#### 2b. `domain` on KnowledgeNode in the graph — 4 DDL sites

Add `domain STRING` to KnowledgeNode DDL at all four sites (follow the `authority` column pattern
that was added in the previous feature):
- `tools/graph.py:~1020-1023` (`graph_knowledge_add`)
- `tools/graph.py:~1239-1242` (`knowledge_batch` `_insert_nodes`)
- `tools/__init__.py:~246-249` (`materialize_auto_graph`)
- `tools/reasoning_v2.py:~302-306` (`_do` helper for reasoning tools)

**Column order:** Insert before `authority STRING` so the canonical order becomes:
`... source STRING, created_at STRING, domain STRING, authority STRING`.

#### 2c. `domain` param on `graph_knowledge_add`

Add `domain: str | None = None` parameter. Validate: no enum needed (domain is free-form
unlike authority). Add `domain: '{_escape_cypher_string(domain or "")}'` to CREATE Cypher.
Follow the `authority` parameter's implementation as the reference pattern.

#### 2d. `domain?` in `knowledge_batch` node schema

Add `domain_val = n.get("domain", "")` per-node extraction. Add to CREATE Cypher.
Update docstring node schema block to list `domain?` as a free-form string.

#### 2e. `domain` in `materialize_auto_graph`

Read `domain_val = _escape_cypher_string(str(item.get("domain", "")))` for each item.
Add `domain: '{domain_val}'` to the inline CREATE Cypher. This auto-propagates the
item-level domain into the knowledge graph node when `auto_graph=True`.

---

### 3. Domain retrieval — `domain_context` and `domain_connections` bridge actions

**Goal:** Answer "what does the session know about domain X?" and "what connects domain
X to domain Y?"

#### 3a. Add params to think_bridge signature

Add two optional params:
- `domain: str | None = None` — used by domain_context, domain_connections
- `domain_b: str | None = None` — second domain for domain_connections

Add `"domain_context"` and `"domain_connections"` to `_BRIDGE_ACTIONS` frozenset.

#### 3b. `domain_context` action

Requires `domain` (non-empty). Searches the think session:
- ThoughtNodes where `node.metadata.get("domain") == domain` (metadata dict)
- HypothesisRecords where `record.domain == domain` (dedicated field)
- ModelRecords where `record.domain == domain` (new field from Section 2a)
- DecisionRecords where `record.domain == domain` (new field from Section 2a)
- InquiryRecords where `record.domain == domain` (new field from Section 2a)
- MonitorRecords where `record.domain == domain` (new field from Section 2a)

Also queries graph companion (if present):
```
MATCH (n:KnowledgeNode) WHERE n.domain = '{escaped_domain}'
RETURN n.name, n.entity_type, n.confidence, n.authority LIMIT 30
```

Output structure: one section per record type with matching records. Sections only emitted
when non-empty. Include total counts at top:
`domain: X | thoughts: N, hypotheses: M, models: P, decisions: Q, inquiries: R, monitors: S`.

#### 3c. `domain_connections` action

Requires BOTH `domain` and `domain_b` (non-empty). If either is missing or empty, raise
`ValueError("domain_connections requires both domain and domain_b")`. If they are equal,
return empty output with note "same domain — use domain_context instead".

Two lookup modes:

**Graph mode** (when companion exists):
```
MATCH (a:KnowledgeNode)-[r]-(b:KnowledgeNode)
WHERE a.domain = '{domain_a}' AND b.domain = '{domain_b}'
RETURN a.name, type(r), b.name, r.weight LIMIT 20
```

**Think-side mode** (always run):
- Collect entity_refs (knowledge_refs) from ThoughtNodes with `metadata["domain"] == domain_a` → set A
- Collect entity_refs (knowledge_refs) from ThoughtNodes with `metadata["domain"] == domain_b` → set B
- Return intersection (entity names present in both sets) with the ThoughtNode IDs per domain

Note: entity_refs is ThoughtNode-only (Section 1b), so the think-side intersection only surfaces
entities explicitly registered via think_graph. This is expected behavior — it shows the explicit
conceptual overlap declared by the caller.

**Relationship with edge-level domain:** The graph already has edge-level domain on relations
(used by `_analyze_domain_bridges` in `graph_analyze`). `domain_connections` uses NODE-level
domain (the new `domain` column) — it finds connections between nodes tagged to different domains.
The two features are orthogonal and complementary: edge-domain describes the nature of a relation,
node-domain describes which conceptual area a node belongs to.

Output: `## Graph connections` (if companion) + `## Shared entities` (think-side intersection).
If both domains are the same, return empty with a note ("same domain — use domain_context instead").

---

### 4. Docstring and CLAUDE.md updates

**think_bridge docstring:**
- Add `domain_context(domain)` and `domain_connections(domain, domain_b?)` to the 8-action list
  (now 10 actions total)
- Document `domain` and `domain_b` params
- Document `entity_refs` as a recognized field in batch items[]
- Clarify `thoughts_for_entity` now also falls back to text search when knowledge_refs is absent

**CLAUDE.md:**
- Update think_bridge description to mention 10 actions, domain_context, domain_connections
- Add note that items[] accept optional `domain: str` and `entity_refs: list[str]`
- Add `domain` field to knowledge graph tools (graph_knowledge_add, knowledge_batch)
- Note that auto_graph=True auto-propagates item domain to KnowledgeNode

---

## File Change Summary

| File | Change |
|------|--------|
| `tools/think.py` | `thoughts_for_entity`: text fallback; `think_graph/thoughts[]`: entity_refs+domain to metadata; `think_model/items[]`: same; `think_decide/items[]`: same; `think_science/items[]`: collect_item_refs call + entity_refs+domain; `think_bridge`: 2 new params (domain, domain_b), 2 new actions (domain_context, domain_connections), `_BRIDGE_ACTIONS` extended; docstrings |
| `tools/graph.py` | `graph_knowledge_add`: `domain` param + DDL + CREATE Cypher; `knowledge_batch`: DDL + per-item domain extraction + CREATE Cypher |
| `tools/__init__.py` | `materialize_auto_graph`: DDL + domain from item in inline CREATE |
| `tools/reasoning_v2.py` | DDL: add `domain STRING` column |
| `engines/thinking_engine.py` | Add `domain: str = ""` field to ModelRecord, DecisionRecord, InquiryRecord, MonitorRecord |
| `CLAUDE.md` | Update think_bridge, think_graph, think_model, think_decide, think_science, knowledge_batch, graph_knowledge_add descriptions |

`session.py` — no change.
`tools/refs.py` — no change (think_refs_query already searches `refs` field universally).

---

## Edge Cases

- **entity_refs = []**: treat as absent; do not overwrite existing knowledge_refs
- **entity_refs contains non-string values**: stringify before storing
- **entity_refs on think_model/think_decide/think_science items[]**: silently ignored — these record types have no metadata dict and thoughts_for_entity wouldn't find them anyway
- **domain = "" in items[]**: treat as absent; leave field at default ""
- **domain_context with empty session**: return counts of 0, emit "(no records found)" line
- **domain_connections with same domain for both params**: return empty + note
- **domain_connections with no graph companion**: skip graph section, return think-only intersection
- **KnowledgeNode DDL on pre-existing sessions**: `CREATE NODE TABLE IF NOT EXISTS` skips DDL when the table already exists. Any subsequent `CREATE (n:KnowledgeNode {domain: '...'})` against an old-schema table (without the `domain` column) will fail at insert time. **No migration in scope** — this feature works only on sessions created after this change. This is explicit and acceptable: callers with old sessions must create a new session. Add a note to Non-Goals.
- **domain on materialize_auto_graph**: domain="" for items that don't set it — consistent with
  existing behavior for authority (stored as empty string)
- **thoughts_for_entity text fallback**: only triggers when knowledge_refs lookup returns empty;
  mark results with "(text match)" prefix so callers can distinguish precision
- **domain_b absent or empty in domain_connections**: raise ValueError("domain_connections requires both domain and domain_b")

---

## Tests to add

**tests/test_think_tools.py:**
- `thoughts_for_entity` returns nothing for unknown entity (entity_refs path)
- `thoughts_for_entity` falls back to text search when node has no knowledge_refs
- `thoughts_for_entity` prefers knowledge_refs over text when both present
- `think_graph(thoughts=[{thought: "NLRX1 is elevated", entity_refs: ["NLRX1"]}])` → bridge query `thoughts_for_entity("NLRX1")` returns the node
- `think_model(items=[{..., domain: "metabolism"}])` → bridge `domain_context("metabolism")` returns the item (uses new ModelRecord.domain field)
- `think_science(items=[{..., domain: "inflammation"}])` → bridge `domain_context("inflammation")` returns the item (uses new InquiryRecord.domain field)
- `domain_context` returns "(no records found)" for domains with no records
- `domain_connections` missing domain_b raises ValueError
- `domain_connections` with same domain for both returns empty + note
- `domain_connections` with no graph companion returns think-side only (ThoughtNode entity_refs intersection)
- `think_science(items=[{..., connects_to: ["existing_id"]}])` → record has refs populated (via InquiryRecord constructor)

**tests/test_graph_tools.py:**
- `graph_knowledge_add(entity="X", domain="metabolism")` stores domain field
- `knowledge_batch(nodes=[{entity: "X", domain: "frontend"}, {entity: "Y"}])` → X has domain, Y has ""
- Graph query `WHERE n.domain = 'metabolism'` returns only nodes with that domain
- `materialize_auto_graph` with item containing domain="metabolism" → graph node has domain

---

## Non-Goals

- Cross-session graph traversal (architectural change, separate effort)
- Pathway enrichment / MSigDB integration (domain-specific, belongs in an omics extension)
- Gene symbol normalization (domain-specific)
- Auto-extraction of entity names from free text (requires NLP; caller responsibility)
- Live literature retrieval (external API, separate MCP server)
- `domain_tags: list[str]` on ThoughtNode (single string domain is sufficient; multi-tag adds complexity without clear use case)
- Migrating existing KnowledgeNode rows to populate domain (no migration in scope — sessions created before this change have an incompatible KnowledgeNode schema; callers must create new sessions)
- entity_refs on think_model/think_decide/think_science items[] — thoughts_for_entity doesn't scan those record types; implement as a separate bridge action if needed later

---

## Verification

```bash
uv run pytest -v                    # no regressions + new tests
uv run ruff check src/ tests/       # lint
uv run pyright src/                 # type check on source

# Functional smoke tests (manual via MCP):
# 1. entity_refs registration:
#    think_graph(thoughts=[{thought: "NLRX1 inhibits MAVS", entity_refs: ["NLRX1", "MAVS"]}])
#    think_bridge(action="thoughts_for_entity", entity_name="NLRX1")
#    → node appears in results (previously returned nothing)
#
# 2. thoughts_for_entity text fallback:
#    think_graph(thoughts=[{thought: "CPT1A drives FAO shift"}])  # no entity_refs
#    think_bridge(action="thoughts_for_entity", entity_name="CPT1A")
#    → node found via text match (marked "text match")
#
# 3. domain_context:
#    think_model(items=[{id: "m1", ..., domain: "metabolism"}], auto_graph=True)
#    knowledge_batch(nodes=[{entity: "CPT1A", domain: "metabolism"}])
#    think_bridge(action="domain_context", domain="metabolism")
#    → returns m1 under Models + CPT1A under Graph
#
# 4. domain_connections:
#    add records with domain="metabolism" (CPT1A, PDHX entities)
#    add records with domain="inflammation" (IL6, MMP9 entities)
#    link CPT1A -[causes]-> IL6 in graph
#    think_bridge(action="domain_connections", domain="metabolism", domain_b="inflammation")
#    → graph section shows CPT1A-IL6 edge
#
# 5. domain on KnowledgeNode:
#    knowledge_batch(nodes=[{entity: "MX1", domain: "antiviral_response"}])
#    graph_query("MATCH (n:KnowledgeNode WHERE n.domain='antiviral_response') RETURN n.name")
#    → MX1 returned
```

---

## TLDR

Two structural improvements to make AISmartBuddy's cross-domain reasoning first-class: (1) close
the entity registration gap by adding `entity_refs: list[str]` to `think_graph thoughts=[]` items
(auto-writes to ThoughtNode `metadata["knowledge_refs"]`) and adding a text-search fallback to
`thoughts_for_entity` — bridge queries work without manual registration; (2) add `domain: str = ""`
to four dataclasses (ModelRecord, DecisionRecord, InquiryRecord, MonitorRecord), expose it on all
batch tool items[], add a `domain STRING` column to KnowledgeNode, and expose it via two new bridge
actions — `domain_context(domain)` and `domain_connections(domain, domain_b)`. These changes follow
existing patterns (authority column, HypothesisRecord.domain) and require no architectural shifts.
