# AISmartBuddy MCP Tools

This file is a human-readable snapshot of the MCP tools registered by
AISmartBuddy in [src/aismartbuddy/server.py](C:/Users/michiele/source/repos/aismartbuddy/src/aismartbuddy/server.py).

## Machine-Readable Alternative

MCP does **not** have one universal static file equivalent to `openapi.json`.
The closest standard mechanism is the runtime MCP protocol call:

- `tools/list` — returns tool names, descriptions, and input schemas

That is the authoritative machine-readable source for tool definitions.

In practice, you have three options:

1. Use `tools/list` against a running AISmartBuddy server.
2. Use MCP Inspector / host tooling that already calls `tools/list`.
3. Keep this `MCPTOOLS.MD` file as the human-readable catalog.

If you want, the repo can also grow a generated `mcptools.json` export later,
but that would be a project-specific convenience file, not an MCP standard.

## Tool Catalog

Total registered tools: **61**

### SQL / Explore

| Tool | Description |
| --- | --- |
| `sql_create_session` | Create a DuckDB-backed SQL session and return a `session_id`. |
| `sql_query` | Execute SQL with CSV/table output, optional offset/limit, and pagination. |
| `sql_query_next` | Fetch the next page from a paginated SQL query cursor. |
| `sql_import` | Import one CSV/TSV/TXT/JSON/JSONL/Parquet payload into a SQL table. |
| `sql_import_batch` | Import multiple chunks into the same SQL table. |
| `sql_schema` | Inspect the SQL schema for all tables or one table. |
| `data_profile` | Produce a compact statistical profile of a SQL table. |
| `data_anomalies` | Detect anomalies in SQL table columns using supported methods. |
| `sql_destroy_session` | Destroy a SQL session and clean up temporary state. |

### Graph / Knowledge Graph

| Tool | Description |
| --- | --- |
| `graph_create_session` | Create a LadybugDB graph session and return a `session_id`. |
| `graph_query` | Execute Cypher against a graph session with CSV/table output and paging options. |
| `graph_query_next` | Fetch the next page from a paginated graph query cursor. |
| `graph_import` | Import CSV data into graph node or relationship tables. |
| `graph_schema` | Show graph schema, including node and relationship tables. |
| `graph_destroy_session` | Destroy a graph session and clean up temporary state. |
| `graph_statistics` | Return a one-shot overview of graph node and edge counts. |
| `graph_neighbors` | Explore the neighborhood around one node up to a given depth. |
| `graph_find_connections` | Find paths between two graph nodes. |
| `graph_analyze` | Run higher-level graph analyses such as hubs, orphans, or categories. |
| `graph_compare` | Compare two graph sessions structurally or by content. |
| `graph_cross_reference` | Diff or cross-reference two graphs by a shared property. |
| `graph_knowledge_add` | Add a knowledge entity node into the graph knowledge layer. |
| `graph_knowledge_relate` | Add a typed relationship between knowledge entities. |
| `knowledge_batch` | Bulk-create knowledge nodes and relationships in one call. |
| `graph_knowledge_infer` | Run knowledge-layer inference such as contradictions, gaps, chains, or clusters. |
| `graph_knowledge_summary` | Summarize the knowledge graph state in compact form. |

### Meta / Session Infrastructure

| Tool | Description |
| --- | --- |
| `suggest_database` | Recommend SQL or Graph for a described use case. |
| `session_create` | Create one parent session that coordinates `think`, `graph`, and/or `sql` backends. |
| `session_destroy` | Destroy a unified parent session and its child backend sessions. |

### External Ingestion

| Tool | Description |
| --- | --- |
| `get_youtube_information` | Fetch YouTube metadata and optionally a transcript, with cache-aware degradation handling. |

### Structured Reasoning V2

| Tool | Description |
| --- | --- |
| `scaffold` | Force early structured analysis using a generic analytical model. |
| `hypothesize` | Create falsifiable hypotheses with mechanism and expected signals. |
| `argue` | Build a structured thesis / antithesis / synthesis argument chain. |
| `self_assess` | Record knowledge boundaries, limitations, and next-step guidance. |
| `brainstorm` | Generate divergent ideas without early convergence. |
| `iterate` | Track build-test-learn attempts with optional metric ratcheting. |
| `think_debug` | Apply systematic debugging with issue, approach, findings, and resolution. |
| `reason_graph` | Add short reasoning nodes to the graph-style thought canvas. |
| `model_system` | Model entities, roles, inputs, outputs, interactions, and assumptions. |
| `mine_patterns` | Store structured findings such as patterns, anomalies, clusters, or cohorts. |
| `test_interventions` | Record intervention analyses with risks, compensations, and failure modes. |
| `compare_models` | Compare competing explanations or candidate models. |
| `reason_trace` | Produce a grounded trace that links a conclusion path to prior artifacts. |
| `synthesize_conclusion` | Create a final grounded synthesis that may not introduce unsupported claims. |
| `reason_index` | List stored reasoning artifacts with filtering. |
| `reason_get` | Fetch one reasoning artifact and its immediate linked artifacts. |
| `reason_refs` | Find inbound references to a reasoning artifact. |
| `extract_findings_from_sql` | Run SQL and convert returned rows into reasoning artifacts. |
| `extract_findings_from_graph` | Run Cypher and convert returned rows into reasoning artifacts. |
| `session_resume` | Reconstruct compact operational context for a reasoning session. |
| `session_export` | Export reasoning session state as JSON. |
| `workflow_validate` | Check workflow sequencing and coverage for a reasoning session. |

### Holonic Modeling

| Tool | Description |
| --- | --- |
| `holon_create` | Create one holon or a batched holonic structure. |
| `holon_update` | Update holon state, relationships, memberships, or projections. |
| `holon_view` | Navigate a holarchy from a given holon and vantage. |
| `holon_analyze` | Run holonic analyses such as bridge, coherence, feedback loops, or propagation. |
| `holon_query` | Query a holonic structure from a chosen vantage and resolution. |

### Scoring / Evaluation

| Tool | Description |
| --- | --- |
| `score_rubric` | Create, list, inspect, or manage scoring rubrics. |
| `score_evaluate` | Start, update, batch-apply findings to, or finalize an evaluation. |
| `score_gate` | Apply pass/fail gate checks to an evaluation. |
| `rubric_templates` | List or load built-in rubric templates. |

## Notes

- This file lists **registered tools only**.
- AISmartBuddy also exposes MCP prompts, but those are intentionally not mixed
  into this file.
- The authoritative live tool surface is whatever `tools/list` returns from the
  running server.
