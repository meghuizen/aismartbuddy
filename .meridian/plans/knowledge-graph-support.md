# Knowledge Graph Support + SQL Import Fixes

## Verbatim Requirements

### Original Request
> Does the graph also function as a proper knowledge graph, or what is needed to support knowledge graphs as well. Look into this mcp server as well as example on how knowledge graphs are implemented and how it works or if this solution needs extra additions for that as well: C:\Users\michiele\source\repos\clearthought-onepointfive

### Additional Context
> make sure it works in local and remote settings

---

## Context

AISmartBuddy currently has a **property graph** (LadybugDB/Cypher) with 11 tools. ClearThought 1.5 implements a **PDR Knowledge Graph** with hierarchical+network structure, typed nodes (subject/concept/evidence/question/insight), typed weighted edges (supports/contradicts/refines/questions/leads-to/relates-to/derived-from/clusters-with), PageRank centrality, connected components, and provenance metadata (createdInPass, confidence, justification).

Our graph is missing 5 key knowledge graph features: (1) provenance/confidence tracking, (2) semantic edge types for reasoning, (3) graph algorithms (PageRank, clustering), (4) knowledge gap detection, (5) ontology/hierarchy tools.

Additionally, the SQL import code review found 3 bugs that need fixing first.

---

## Part A: Fix SQL Import Bugs (from pending code review)

**File:** `src/aismartbuddy/engines/duckdb_engine.py`

### Fix 1 (p0): Delimiter injection — validate single character
At the top of `_build_read_function`, before interpolating delimiter:
```python
if delimiter is not None:
    if len(delimiter) != 1:
        raise ValueError("Delimiter must be a single character.")
    if delimiter in ("'", "\\"):
        raise ValueError(f"Invalid delimiter: {delimiter!r}")
```

### Fix 2 (p1): Base64 decode error — wrap with user-friendly message
In `_write_temp_file_binary`:
```python
try:
    raw = base64.b64decode(base64_data)
except Exception as exc:
    raise ValueError(
        "Invalid base64 data for parquet format. "
        "Ensure the parquet file is base64-encoded."
    ) from exc
```

### Fix 3 (p2): import_batch docstring — note table replacement
Add to docstring: "The first chunk creates (or replaces) the table with auto-detected schema."

---

## Part B: Knowledge Graph Additions

### What ClearThought Has (that we should adopt)

| Feature | ClearThought Implementation | Our Approach |
|---------|---------------------------|--------------|
| Typed nodes with confidence | PDRNode.scores.confidence | Add confidence property support |
| Typed edges with weight + justification | PDREdge.weight, metadata.justification | Semantic edge types |
| PageRank centrality | PDRGraphAlgorithms.ts | Implement via Cypher iterative queries |
| Connected components | BFS-based detection | Implement via Cypher |
| Clustering with coherence | Cluster interface | Add clustering tool |
| Knowledge gaps | GraphMetrics.gaps | Add gap detection tool |
| Provenance (createdInPass, timestamp) | PDRNode.metadata | Add provenance support |

### New Tools to Add (4 tools)

**A. `graph_knowledge_add(session_id, entity, entity_type, properties, confidence, source)`**
Add a knowledge node with provenance metadata. Entity types follow knowledge graph conventions: "concept", "entity", "fact", "evidence", "question", "insight". Automatically adds `_confidence` (0-1), `_source`, `_created_at` properties. This is a higher-level wrapper around graph_query that enforces knowledge graph patterns.

**B. `graph_knowledge_relate(session_id, from_name, from_type, to_name, to_type, relation, weight, justification)`**
Add a knowledge relationship with semantic type and weight. Relation types: "supports", "contradicts", "refines", "causes", "prevents", "requires", "part_of", "similar_to", "derived_from". Stores weight (0-1) and justification string as edge properties.

**C. `graph_knowledge_infer(session_id, inference_type)`**
Run inference-like analytical queries:
- `"contradictions"` — find pairs of nodes connected by both "supports" and "contradicts" edges
- `"gaps"` — find nodes with high degree but low average edge confidence (uncertain hubs)
- `"chains"` — find transitive chains (A supports B, B supports C → A transitively supports C)
- `"clusters"` — group related nodes by connectivity density

**D. `graph_knowledge_summary(session_id)`**
Comprehensive knowledge graph overview in one call: total entities by type, relationships by type, confidence distribution, top hubs with confidence, identified gaps and contradictions, cluster overview. This is the "total graph perspective" for the AI.

### Schema Convention for Knowledge Graphs

When `graph_knowledge_add` creates node tables, it uses this enhanced schema:
```
CREATE NODE TABLE Concept (
  id INT64 PRIMARY KEY,
  name STRING,
  description STRING,
  entity_type STRING,     -- concept/entity/fact/evidence/question/insight
  confidence DOUBLE,      -- 0.0 to 1.0
  source STRING,          -- provenance: who/what added this
  created_at STRING       -- ISO timestamp
);
```

When `graph_knowledge_relate` creates relationship tables, it uses:
```
CREATE REL TABLE Supports (
  FROM Concept TO Concept,
  weight DOUBLE,          -- 0.0 to 1.0
  justification STRING,   -- why this relationship exists
  source STRING,
  created_at STRING
);
```

### Implementation in Existing Files

**`src/aismartbuddy/tools/graph.py`** — Add 4 new async tool functions
**`src/aismartbuddy/server.py`** — Register 4 new tools, add `knowledge-guide` prompt
**`tests/test_knowledge_graph.py`** — Test knowledge graph tools with pathophysiology data

The knowledge tools are **additive** — they work alongside existing graph tools. Users can mix raw Cypher queries with knowledge-level operations. The knowledge tools just enforce conventions (confidence, provenance, semantic edge types) that make the graph function as a proper knowledge graph.

---

## Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `src/aismartbuddy/engines/duckdb_engine.py` | Modify | Fix delimiter injection, base64 error, docstring |
| `src/aismartbuddy/tools/graph.py` | Modify | Add 4 knowledge graph tools |
| `src/aismartbuddy/server.py` | Modify | Register 4 new tools, add knowledge-guide prompt |
| `tests/test_knowledge_graph.py` | Create | Test knowledge graph tools |
| `README.md` | Modify | Add knowledge graph tools to reference |
| `CLAUDE.md` | Modify | Update tool count (22 total) |

---

## Verification

1. `uv run pytest -v` — all existing 73 + new tests pass
2. `uv run ruff check src/ tests/` — lint clean
3. Test knowledge workflow: create session → add entities with confidence → relate with weight → infer contradictions → get summary
4. Verify knowledge tools work on both stdio and SSE transport

---

## TLDR

Add 4 knowledge graph tools (graph_knowledge_add, graph_knowledge_relate, graph_knowledge_infer, graph_knowledge_summary) that layer semantic knowledge graph patterns on top of the existing LadybugDB property graph. These enforce confidence scores, provenance metadata, semantic relationship types (supports/contradicts/refines/etc.), and provide inference-like analytics (contradiction detection, gap analysis, clustering, transitive chains). Also fix 3 SQL import bugs from the pending code review. Total tools grows from 18 to 22. Inspired by ClearThought's PDR Knowledge Graph but implemented natively in Cypher rather than in-memory TypeScript.
