# Pathophysiology Graph Test — Tool Gap Analysis & Improvements

## Verbatim Requirements

### Original Request
> Now to test the graph database I want you to build a full graph using the tools of this mcp server (as use case) for the full pathophysiology of the following case and use the graph database as tools to find patterns, anomilies, not connected items, broken links, subcategories and any time the functionality is lacking, this will need as improvement on the graph functionality. You need also the ability to find categories in the data, look at it from holistic visual perspective, query against it, focus on sub parts, focus on different hierarchies. The goal of this test is to see if the MCP server is capable enough or if the exposed tools needs to be changed/extended.

---

## Context

The AISmartBuddy MCP server was just built with 5 graph tools (`graph_create_session`, `graph_query`, `graph_import`, `graph_schema`, `graph_destroy_session`). We need to stress-test these tools against a real-world complex use case — modeling the pathophysiology of a chronic post-infectious immune-dysregulation state with ~47 genes across 4 interacting biological systems. The test will reveal tool gaps and drive improvements.

---

## Phase 1: Build the Pathophysiology Graph

### Graph Data Model

```
Node Tables:
  Gene          (id INT64 PK, name STRING, z_score DOUBLE, direction STRING, description STRING, system STRING)
  Pathway       (id INT64 PK, name STRING, category STRING, status STRING)
  BioProcess    (id INT64 PK, name STRING, status STRING, description STRING)
  CellType      (id INT64 PK, name STRING, activation_status STRING)
  Phenotype     (id INT64 PK, name STRING, description STRING)

Relationship Tables:
  ParticipatesIn  (FROM Gene TO Pathway)           — role STRING
  Regulates       (FROM Gene TO Gene)              — type STRING (activates/inhibits/assembles)
  DrivesProcess   (FROM Gene TO BioProcess)        — mechanism STRING
  CellExpresses   (FROM CellType TO Gene)          — context STRING
  PathwayInteracts(FROM Pathway TO Pathway)        — mechanism STRING, direction STRING
  CompensatesFor  (FROM Gene TO Gene)              — mechanism STRING
  ProducesPhenotype(FROM Pathway TO Phenotype)     — confidence STRING
```

### Gene Data (~47 genes across 4 systems)

**System 1 — Interferon/Antiviral (13 genes):**
| Gene | Z-score | Direction | Description |
|------|---------|-----------|-------------|
| MX1 | -2.0 | reduced | Antiviral effector, blocks viral replication |
| OAS2 | -1.8 | reduced | Viral RNA degradation enzyme |
| RSAD2 | -1.9 | reduced | Restricts viral budding (viperin) |
| IFI6 | -1.5 | reduced | Interferon-stimulated gene, anti-apoptotic |
| IFI27 | -1.6 | reduced | Interferon-stimulated gene |
| LY6E | -1.4 | reduced | Blocks viral membrane fusion |
| DDX60 | -1.3 | reduced | Interferon-stimulated helicase |
| USP18 | -1.7 | reduced | ISG15 deconjugase, IFN feedback |
| TLR3 | -1.5 | reduced | Viral dsRNA sensor |
| TAP2 | -1.2 | reduced | MHC-I antigen loading |
| IFNGR1 | 1.8 | elevated | IFN-gamma receptor |
| JAK2 | 1.6 | elevated | Cytokine signaling kinase |
| NLRX1 | 1.4 | elevated | Inhibits RIG-I/MAVS antiviral pathway |

**System 2 — Inflammation (14 genes):**
| Gene | Z-score | Direction | Description |
|------|---------|-----------|-------------|
| IL6 | 2.98 | elevated | Pro-inflammatory cytokine (most elevated) |
| IL18 | 2.40 | elevated | Inflammasome-activated cytokine |
| C1S | 1.3 | elevated | Complement activation (classical pathway) |
| MMP9 | 2.1 | elevated | Neutrophil degranulation, ECM degradation |
| LTB4R | 1.5 | elevated | Leukotriene B4 receptor, neutrophil chemotaxis |
| KIT | 1.4 | elevated | Mast cell activation/expansion marker |
| SIGLEC8 | 1.3 | elevated | Mast cell/eosinophil marker |
| GATA3 | -1.6 | reduced | Th2 master regulator |
| IKZF3 | -1.4 | reduced | Plasmablast differentiation |
| IL21R | -1.3 | reduced | Germinal center support receptor |
| BACH2 | -1.5 | reduced | B-cell memory maintenance |
| SLAMF6 | -1.2 | reduced | Adaptive immune signaling |
| CCL5 | -1.4 | reduced | T-cell/monocyte chemokine |
| GZMK | -1.6 | reduced | CD8 cytotoxic capacity (granzyme K) |

**System 3 — Metabolic/Mitochondrial (14 genes):**
| Gene | Z-score | Direction | Description |
|------|---------|-----------|-------------|
| SLC2A1 | -1.5 | reduced | GLUT1, glucose transporter |
| CPT1A | 1.7 | elevated | Fatty acid import to mitochondria (rate-limiting) |
| HADHB | 1.4 | elevated | Beta-oxidation trifunctional protein |
| PDHX | -1.6 | reduced | Pyruvate dehydrogenase (glycolysis→TCA link) |
| BCS1L | -1.3 | reduced | Complex III assembly factor |
| MT_ND3 | -1.8 | reduced | Complex I subunit |
| TSFM | -1.4 | reduced | Mitochondrial translation factor |
| MTERF4 | -1.3 | reduced | Mitochondrial translation termination |
| TFAM | 1.5 | elevated | Mitochondrial biogenesis (compensatory) |
| TEFM | 1.3 | elevated | Mitochondrial transcription (compensatory) |
| TK2 | 1.2 | elevated | Mitochondrial dNTP synthesis (compensatory) |
| COQ7 | 1.4 | elevated | CoQ10 biosynthesis (compensatory) |
| SMDT1 | 1.1 | elevated | Mitochondrial calcium uniporter regulator |
| OPTN | -1.2 | reduced | Mitophagy receptor (quality control) |

**System 4 — Neuroimmune-Endocrine (9 genes):**
| Gene | Z-score | Direction | Description |
|------|---------|-----------|-------------|
| S1PR1 | -2.0 | reduced | Lymphocyte egress from lymph nodes |
| CCR5 | -1.3 | reduced | Effector T-cell homing to inflammation |
| S1PR2 | -1.1 | reduced | Sphingosine signaling |
| CLOCK | -1.5 | reduced | Circadian master transcription factor |
| DUSP1 | 1.6 | elevated | Glucocorticoid-responsive MAPK phosphatase |
| AVP | 10.14 | elevated | Vasopressin — most deviant gene in dataset |
| PCSK2 | 1.8 | elevated | ACTH-processing convertase |
| OPRM1 | -1.2 | reduced | Mu-opioid receptor (pain processing) |
| CACNA1A | -1.1 | reduced | Calcium channel (neurotransmission) |

### Pathway Data (4 major systems + 8 sub-pathways)

| id | name | category | status |
|----|------|----------|--------|
| 1 | Interferon Antiviral Response | interferon | suppressed |
| 2 | Innate Inflammatory Activation | inflammation | active |
| 3 | Mitochondrial Energy Metabolism | metabolic | stressed |
| 4 | Neuroimmune-Endocrine Regulation | neuroimmune | dysregulated |
| 5 | ISG Effector Program | interferon | suppressed |
| 6 | IL-6/IL-18 Inflammasome Axis | inflammation | active |
| 7 | Adaptive Immune Response | inflammation | suppressed |
| 8 | Electron Transport Chain | metabolic | impaired |
| 9 | Mitochondrial Biogenesis | metabolic | compensatory |
| 10 | Fatty Acid Oxidation | metabolic | active |
| 11 | Lymphocyte Trafficking | neuroimmune | impaired |
| 12 | HPA Stress Axis | neuroimmune | activated |

### BioProcess Data (12 processes)

| id | name | status | description |
|----|------|--------|-------------|
| 1 | Viral RNA Degradation | impaired | OAS2-mediated viral RNA cleavage |
| 2 | Viral Budding Restriction | impaired | RSAD2/viperin blocks viral egress |
| 3 | MHC-I Antigen Presentation | impaired | TAP2-dependent peptide loading |
| 4 | Neutrophil Degranulation | active | MMP9-mediated ECM degradation |
| 5 | Complement Activation | active | Classical pathway via C1S |
| 6 | Mast Cell Activation | active | KIT/SIGLEC8 driven expansion |
| 7 | Glycolysis | impaired | SLC2A1 reduced, PDHX blocked |
| 8 | Beta-Oxidation | active | CPT1A/HADHB fatty acid utilization |
| 9 | Mitochondrial Quality Control | impaired | OPTN-dependent mitophagy offline |
| 10 | Circadian Immune Gating | impaired | CLOCK-dependent trafficking rhythms |
| 11 | Cortisol Signaling | active | DUSP1-mediated MAPK suppression |
| 12 | Lymphocyte Egress | impaired | S1PR1-dependent node exit |

### CellType Data (6 cell types)

| id | name | activation_status |
|----|------|-------------------|
| 1 | Neutrophil | activated |
| 2 | Mast Cell | activated |
| 3 | CD8 T Cell | exhausted |
| 4 | Th2 Cell | suppressed |
| 5 | B Cell | impaired |
| 6 | Plasmablast | suppressed |

### Phenotype Data (5 clinical phenotypes)

| id | name | description |
|----|------|-------------|
| 1 | Impaired Antiviral Defense | Reduced ISG expression, poor viral clearance |
| 2 | Chronic Systemic Inflammation | Persistent IL-6/IL-18 driven inflammation |
| 3 | Metabolic Exhaustion | Energy production failure with compensatory shift |
| 4 | Immune Cell Trafficking Defect | Poor lymphocyte homing and egress |
| 5 | Neuroendocrine Stress | HPA axis activation, circadian disruption, altered pain |

### Relationships — Complete Enumeration

**ParticipatesIn (Gene → Pathway) — 50 edges:**
Each gene maps to its primary system pathway AND relevant sub-pathway:
- System 1 genes (MX1, OAS2, RSAD2, IFI6, IFI27, LY6E, DDX60, USP18, TLR3, TAP2) → Pathway 1 + Pathway 5
- IFNGR1, JAK2 → Pathway 1 (but elevated — receptor amplification)
- NLRX1 → Pathway 1 + Pathway 3 (cross-system link)
- System 2 elevated (IL6, IL18, C1S, MMP9, LTB4R, KIT, SIGLEC8) → Pathway 2 + Pathway 6
- System 2 reduced (GATA3, IKZF3, IL21R, BACH2, SLAMF6, CCL5, GZMK) → Pathway 2 + Pathway 7
- System 3 reduced (SLC2A1, PDHX, BCS1L, MT_ND3, TSFM, MTERF4, OPTN) → Pathway 3 + Pathway 8
- System 3 elevated biogenesis (TFAM, TEFM, TK2, COQ7, SMDT1) → Pathway 3 + Pathway 9
- CPT1A, HADHB → Pathway 3 + Pathway 10
- System 4 trafficking (S1PR1, CCR5, S1PR2) → Pathway 4 + Pathway 11
- System 4 HPA (AVP, PCSK2, DUSP1) → Pathway 4 + Pathway 12
- CLOCK → Pathway 4 + Pathway 11
- OPRM1, CACNA1A → Pathway 4

**Regulates (Gene → Gene) — 20 edges:**
| from | to | type |
|------|----|------|
| IFNGR1 | JAK2 | activates |
| JAK2 | MX1 | activates |
| JAK2 | OAS2 | activates |
| NLRX1 | MX1 | inhibits |
| NLRX1 | OAS2 | inhibits |
| NLRX1 | RSAD2 | inhibits |
| IL18 | IL6 | activates |
| IL6 | MMP9 | activates |
| IL6 | C1S | activates |
| DUSP1 | GATA3 | inhibits |
| DUSP1 | BACH2 | inhibits |
| CLOCK | S1PR1 | activates |
| CLOCK | CCR5 | activates |
| AVP | PCSK2 | activates |
| PDHX | SLC2A1 | enables |
| BCS1L | MT_ND3 | assembles |
| TSFM | MT_ND3 | translates |
| MTERF4 | BCS1L | translates |
| LTB4R | MMP9 | amplifies |
| USP18 | IFNGR1 | inhibits |

**CompensatesFor (Gene → Gene) — 6 edges:**
| from | to | mechanism |
|------|----|-----------|
| CPT1A | SLC2A1 | fatty acid replaces glucose uptake |
| TFAM | MT_ND3 | biogenesis replaces failed ETC |
| TEFM | BCS1L | transcription compensates assembly failure |
| TK2 | TSFM | dNTP supply supports translation |
| COQ7 | BCS1L | CoQ biosynthesis aids ETC |
| SMDT1 | OPTN | calcium handling while mitophagy offline |

**DrivesProcess (Gene → BioProcess) — 14 edges:**
| gene | process_id | mechanism |
|------|------------|-----------|
| OAS2 | 1 | enzymatic RNA cleavage |
| RSAD2 | 2 | membrane lipid disruption |
| TAP2 | 3 | peptide transport |
| MMP9 | 4 | matrix metalloproteinase |
| C1S | 5 | complement protease |
| KIT | 6 | receptor tyrosine kinase |
| SLC2A1 | 7 | glucose transport |
| CPT1A | 8 | fatty acid shuttling |
| OPTN | 9 | mitophagy receptor |
| CLOCK | 10 | transcriptional regulation |
| DUSP1 | 11 | phosphatase signaling |
| S1PR1 | 12 | sphingosine receptor |
| PDHX | 7 | pyruvate oxidation |
| SIGLEC8 | 6 | cell surface receptor |

**CellExpresses (CellType → Gene) — 10 edges:**
| cell_id | gene | context |
|---------|------|---------|
| 1 | MMP9 | degranulation product |
| 1 | LTB4R | chemotaxis receptor |
| 2 | KIT | activation marker |
| 2 | SIGLEC8 | surface receptor |
| 3 | GZMK | cytotoxic effector |
| 3 | CCL5 | chemokine production |
| 4 | GATA3 | master regulator |
| 5 | BACH2 | memory maintenance |
| 5 | IL21R | germinal center receptor |
| 6 | IKZF3 | differentiation factor |

**PathwayInteracts (Pathway → Pathway) — 6 edges:**
| from_id | to_id | mechanism | direction |
|---------|-------|-----------|-----------|
| 1 | 2 | NLRX1 suppresses antiviral while inflammation active | bidirectional |
| 3 | 1 | mitochondrial stress reduces antiviral signaling | causal |
| 4 | 2 | HPA axis suppresses adaptive immunity | causal |
| 3 | 2 | energy failure sustains inflammatory activation | causal |
| 4 | 1 | circadian disruption impairs immune timing | causal |
| 3 | 4 | metabolic stress drives neuroendocrine activation | causal |

**ProducesPhenotype (Pathway → Phenotype) — 6 edges:**
| pathway_id | phenotype_id | confidence |
|------------|-------------|------------|
| 1 | 1 | high |
| 2 | 2 | high |
| 3 | 3 | high |
| 4 | 4 | high |
| 4 | 5 | high |
| 11 | 4 | moderate |

---

## Phase 2: Test Query Matrix

Each query tests a specific analytical capability. Mark pass/fail/awkward.

| # | Requirement | Test Query | Tests |
|---|-------------|------------|-------|
| 1 | Basic query | All genes in System 1 | MATCH + WHERE |
| 2 | Aggregation | Count genes by direction per pathway | GROUP BY, COUNT |
| 3 | Find patterns | Elevated genes in suppressed pathways (contradictions) | Complex MATCH + WHERE |
| 4 | Anomalies | Genes with \|z_score\| > 2.5 | Property filter |
| 5 | Disconnected | Genes not connected to any pathway | Negative pattern / NOT EXISTS |
| 6 | Broken links | Pathways with no cross-system connections | OPTIONAL MATCH |
| 7 | Subcategories | All compensatory genes (elevated + compensates_for relationship) | Multi-pattern MATCH |
| 8 | Holistic view | Count all nodes/edges by type | Schema query + counts |
| 9 | Hub analysis | Genes with most relationships (any type) | Variable-length paths, degree |
| 10 | Path finding | Shortest path from AVP to IL6 | shortest_path() |
| 11 | Cross-system | Genes participating in 2+ pathways | Multi-hop + count |
| 12 | Hierarchy | Pathway → Gene → Process chain | Multi-hop MATCH |
| 13 | Subgraph focus | Extract only System 3 with all internal relationships | Filtered MATCH |
| 14 | Direction analysis | Ratio of elevated:reduced per pathway | Aggregation + case |
| 15 | Regulatory chains | All genes downstream of NLRX1 (transitive) | Variable-length path |
| 16 | Graph comparison | Compare two patient graphs (structure diff) | graph_compare tool |
| 17 | Cross-reference | Find shared/unique genes between two patients | graph_cross_reference tool |
| 18 | Property comparison | Compare z-scores for shared genes across graphs | Property diff |

---

## Phase 3: Tool Improvements (Based on Anticipated Gaps)

### New Tools to Add

**A. `graph_statistics(session_id)`**
Returns compact overview: node counts by type, relationship counts by type, total nodes/edges, most-connected nodes (top 5 by degree). This is the "holistic view" tool. Implementation: run `CALL show_tables()` then count queries for each table.

**B. `graph_neighbors(session_id, node_name, node_type, depth=1, direction="both")`**
Returns the N-hop neighborhood of a specific node. Essential for "focus on sub-parts." Uses variable-length path `[:*1..{depth}]` in Cypher. Returns nodes and relationship types in the neighborhood.

**C. `graph_find_connections(session_id, from_name, from_type, to_name, to_type, max_depth=5, max_paths=20)`**
Find paths between two nodes up to max_depth. Returns paths with intermediate nodes, capped at max_paths (shortest-first). Uses `MATCH p = (a)-[*1..{depth}]-(b)` with LIMIT.

**D. `graph_analyze(session_id, analysis_type)`**
Pre-built analytical queries:
- `"orphans"` — nodes with no relationships (uses OPTIONAL MATCH + WHERE IS NULL)
- `"hubs"` — nodes with highest degree, top 10 (count relationships per node)
- `"categories"` — group nodes by type and property values (e.g., direction, status)
- `"cross_connections"` — nodes that participate in 2+ different node-type relationships (cross-system links)

**E. `graph_compare(session_id_a, session_id_b, compare_type="structure")`**
Compare two graph sessions to find differences and similarities. Compare types:
- `"structure"` — compare node/edge counts, table schemas, overlap in node names
- `"nodes"` — find nodes present in A but not B, and vice versa (by name+type)
- `"relationships"` — find edges present in one graph but not the other
- `"properties"` — for shared nodes, compare property values (e.g., z_score differences between two patients)

Implementation: query both sessions, compute diffs in Python, return as compact table. This enables cross-referencing different patients, time points, or datasets.

**F. `graph_cross_reference(session_id_a, session_id_b, node_type, key_property="name")`**
Cross-reference nodes between two graph sessions by matching on key_property. Returns a merged view showing which nodes appear in both, only-in-A, only-in-B, and property differences for shared nodes. Output as CSV for token efficiency. Essential for comparing two patient profiles or time-series data.

### Existing Tools to Improve

**G. `graph_query` — Add batch mode**
New method `execute_all()` on LadybugEngine returns all result sets as `list[tuple[list[str], list[tuple]]]`. The graph_query tool formats multiple results separated by `--- Result 1 ---`, `--- Result 2 ---` headers. The existing `execute()` method stays unchanged (backward compatible).

**H. `graph_schema` — Enhance with counts**
Add node/relationship counts per table type so the AI can see the graph size at a glance. Append count queries after `show_tables()`.

**I. Graph prompts — Add analytical query patterns**
The `graph-guide` prompt needs examples for:
- OPTIONAL MATCH for finding missing relationships
- Variable-length paths `[:REL*1..5]` for traversal
- Aggregation patterns (COUNT, COLLECT, GROUP BY)
- NOT EXISTS patterns for orphan detection
- UNWIND for batch operations
- Cross-session comparison patterns

---

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `tests/data/__init__.py` | Create | Package init for test data |
| `tests/data/pathophysiology.py` | Create | Gene/pathway/relationship data as Python constants |
| `tests/test_pathophysiology_graph.py` | Create | Full integration test: build graph, 18 analytical queries |
| `src/aismartbuddy/tools/graph.py` | Modify | Add graph_statistics, graph_neighbors, graph_find_connections, graph_analyze, graph_compare, graph_cross_reference |
| `src/aismartbuddy/engines/ladybug_engine.py` | Modify | Add get_statistics, get_neighbors, execute_all methods |
| `src/aismartbuddy/server.py` | Modify | Register 6 new graph tools (total: 17 tools), enhance graph prompts with analytical patterns |
| `README.md` | Modify | Add new tools to reference table |
| `CLAUDE.md` | Modify | Update tool count and architecture notes |

---

## Implementation Order

1. **Create test data module** (`tests/data/pathophysiology.py`) — all gene/pathway/relationship data
2. **Write integration test** (`tests/test_pathophysiology_graph.py`) — build graph, run all 15 queries using EXISTING tools only
3. **Run tests, document failures** — which queries fail or are too awkward with current tools
4. **Implement new tools** (graph_statistics, graph_neighbors, graph_find_connections, graph_analyze)
5. **Enhance existing tools** (graph_schema with counts, better prompts)
6. **Update integration test** to use new tools where they simplify queries
7. **Update docs**

---

## Verification

1. `uv run pytest tests/test_pathophysiology_graph.py -v` — all queries pass
2. `uv run pytest -v` — all 44 existing tests + new tests pass
3. `uv run ruff check src/ tests/` — lint clean
4. Manual review: each of the 15 test queries produces meaningful results
5. Document: for each query, note whether it needed a new tool or worked with existing graph_query

---

## TLDR

Build a 47-gene pathophysiology graph across 4 biological systems (interferon, inflammation, metabolic, neuroimmune) with 12 pathways, 12 biological processes, 6 cell types, 5 phenotypes, and ~112 relationships to stress-test the graph tools. Run 18 analytical queries covering patterns, anomalies, disconnected nodes, subcategories, hierarchy navigation, hub analysis, and cross-graph comparison. Document where existing tools fall short, then implement 6 new graph tools (graph_statistics, graph_neighbors, graph_find_connections, graph_analyze, graph_compare, graph_cross_reference) plus enhancements to graph_schema, graph_query batch mode, and prompts. Total tools grows from 11 to 17. This is test-driven development: build the test first, let failures drive the improvements.
