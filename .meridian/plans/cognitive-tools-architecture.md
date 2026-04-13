# Plan: Implement Structured Thinking Tools in AISmartBuddy

## Verbatim Requirements

### Original Request
> Look at how this mcp server build sequential thinking tool. look at description, mcp tool api structure, response type, what data store it uses and look at how this can be implemented in our mcp server. Also think like how you as an AI use it and where it can have some improvements. Then also validate if the solution can work for multiple users and multiple instances and multiple projects at the same time (locally and remote). use clear-thought

## Context

The `@waldzellai/clear-thought` MCP server provides 9 structured thinking tools (sequentialthinking, mentalmodel, debuggingapproach, decisionframework, metacognitivemonitoring, scientificmethod, structuredargumentation, collaborativereasoning, visualreasoning). These tools serve as **structured scratchpads** for AI reasoning — they don't compute anything, they accept structured input, track state, and return confirmation metadata. The AI does all the thinking; the tools impose structure and maintain history.

Clear-thought has several architectural limitations:
- **No session isolation**: Single `thoughtHistory[]` shared across all uses within a process
- **No persistence**: All state lost on server restart
- **No multi-user safety**: In a shared server scenario, users would see each other's thoughts
- **Node.js dependency**: Separate runtime from our Python stack
- **JSON blob responses**: Not token-optimized

AISmartBuddy already has the infrastructure to solve all of these problems: SessionManager for isolation, thread-safe state management, both stdio and SSE transport, and token-optimized formatting.

---

## Analysis: How Clear-Thought Works

### Architecture
```
TypeScript MCP Server (stdio)
├── SequentialThinkingServer class (main)
│   ├── thoughtHistory: Thought[] (in-memory array)
│   ├── branches: {[branchId]: Thought[]} (in-memory map)
│   └── Memory limits: 1000 thoughts, 50 branches, 100/branch
├── 9 tool handlers (one per thinking tool)
├── Zod schema validation per tool
└── StdioServerTransport
```

### Data Store
Pure in-memory JavaScript objects. No persistence layer. FIFO cleanup when limits exceeded.

### Response Format
All tools return `{content: [{type: "text", text: JSON.stringify({...metadata}, null, 2)}]}`.
Sequential thinking returns: `{thoughtNumber, totalThoughts, nextThoughtNeeded, branches[], thoughtHistoryLength, status}`.
Other tools return their structured input back with a status field — essentially echoing the AI's reasoning with validation confirmation.

### Key Insight
These tools are **structured logging for AI reasoning**. The value is in:
1. **Forced structure** — the schema makes the AI organize thoughts explicitly
2. **State tracking** — thought numbers, branches, revision chains
3. **Memory limits** — preventing unbounded growth
4. **Validation** — catching malformed reasoning inputs

---

## Analysis: How I (Claude) Use These Tools

### Usage patterns by frequency:
1. **Sequential thinking** (most used): Chain 3-10 thoughts for complex analysis. Revision and branching for course correction.
2. **Decision framework**: Multi-criteria evaluation with weighted scores. Produces clear, defensible recommendations.
3. **Mental models**: Structured framework application (first principles, Pareto). Quick framing tool.
4. **Debugging approach**: Systematic issue diagnosis. Less frequent but high value when needed.
5. **Others** (argumentation, collaborative, scientific, metacognitive, visual): Situational.

### Where improvements would help most:
1. **Session isolation**: Tag thinking chains with session/project context so different analyses don't intermingle
2. **Token-optimized output**: Return concise text summaries instead of JSON blobs with pretty-printed whitespace
3. **Thought summarization** (NEW): After a long chain, get a condensed summary instead of re-reading all thoughts
4. **Cross-tool integration**: Reference SQL/graph data sessions from within thinking — "analyze the data in session X"
5. **Structured output**: Use FastMCP's Pydantic model return for programmatic clients while keeping text for AI consumption

---

## Multi-User/Multi-Instance Validation

### Scenario Matrix

| Scenario | How it works | Status |
|----------|-------------|--------|
| **Local stdio, 1 user, 1 project** | One server process per Claude Code session. Thinking state in-memory per process. | Works (same as clear-thought) |
| **Local stdio, 1 user, N projects** | Each project launches own server process (separate working directories). Complete process-level isolation. | Works |
| **Remote SSE, N users, 1 server** | Multiple clients connect to one server. Each gets unique session_id via SessionManager. ThinkingEngine instance per session = full isolation. Thread-safe via existing lock. | Works |
| **N server instances (horizontal)** | Each instance has own SessionManager + in-memory state. Load balancer must be sticky for multi-step chains. | Works (with sticky sessions) |
| **N projects, remote SSE, 1 user** | Different session_ids per project. No collision (UUID-based). | Works |

### Key architectural requirement
ThinkingEngine must be **session-scoped** (one per session_id), NOT server-scoped. This is clear-thought's biggest flaw — it has a single shared `thoughtHistory`.

---

## Design Decision: Storage Backend

Evaluated via multi-criteria analysis (simplicity 0.3, multi-user safety 0.25, performance 0.2, pattern alignment 0.15, extensibility 0.1):

| Option | Score | Notes |
|--------|-------|-------|
| **In-memory Python dicts** | **0.87** | Simplest, fastest, session-isolated via SessionManager |
| DuckDB-backed | 0.72 | Overkill for ~100 text thoughts per session |
| Hybrid (memory + optional DB) | 0.68 | Two code paths, highest complexity |

**Decision: In-memory Python dicts**, session-scoped. ThinkingEngine is a lightweight class (not extending BaseEngine ABC since it doesn't need `execute(query)` interface). Future migration to DuckDB is straightforward if persistence becomes needed.

---

## Implementation Plan

### New files to create:
- `src/aismartbuddy/engines/thinking_engine.py` — ThinkingEngine class
- `src/aismartbuddy/tools/think.py` — Thinking tool functions

### Files to modify:
- `src/aismartbuddy/session.py` — Accept "think" session type, widen engine Union type
- `src/aismartbuddy/server.py` — Import and register thinking tools, update prompts/resource

### Step 1: ThinkingEngine (`engines/thinking_engine.py`)

A lightweight in-memory engine. Does NOT extend BaseEngine (different interface — no SQL/Cypher `execute()`).

```
ThinkingEngine
├── thoughts: list[ThoughtRecord]         # Sequential thought chain
├── branches: dict[str, list[ThoughtRecord]]  # Named branches
├── models: dict[str, ModelRecord]        # Mental model applications
├── decisions: dict[str, DecisionRecord]  # Decision framework state
├── debugs: dict[str, DebugRecord]        # Debugging approach state
├── argues: dict[str, list[ArgRecord]]    # Argumentation chains
├── collaborations: dict[str, CollabRecord]  # Collaborative sessions
├── inquiries: dict[str, InquiryRecord]   # Scientific method inquiries
├── monitors: dict[str, MonitorRecord]    # Metacognitive monitoring
├── diagrams: dict[str, DiagramRecord]    # Visual reasoning diagrams
├── Memory limits:
│   MAX_THOUGHTS = 1000
│   MAX_BRANCHES = 50
│   MAX_BRANCH_SIZE = 100
├── connect() → no-op (in-memory)
├── close() → clear all state
├── add_thought() → append + cleanup
├── get_summary() → condensed view of all thoughts
└── cleanup_memory() → FIFO eviction when limits exceeded
```

Data models (dataclasses):
- `ThoughtRecord`: number, content, total_thoughts, next_needed, is_revision, revises_thought, branch_from, branch_id, timestamp
- `ModelRecord`: model_name, problem, steps, reasoning, conclusion
- `DecisionRecord`: decision_id, statement, options, criteria, evaluations, stage, recommendation
- `DebugRecord`: approach_name, issue, steps, findings, resolution
- `ArgRecord`: argument_id, claim, premises, conclusion, argument_type, confidence, responds_to, supports, contradicts
- `CollabRecord`: session_id, topic, personas, contributions, stage, consensus_points, disagreements
- `InquiryRecord`: inquiry_id, stage, hypothesis, experiment, analysis, conclusion
- `MonitorRecord`: monitoring_id, task, stage, claims, reasoning_steps, overall_confidence
- `DiagramRecord`: diagram_id, diagram_type, elements, operations_log

### Step 2: Session Integration (`session.py`)

- Add `"think"` to valid session types in `create_session()` — change the validation check at line 83 from `("sql", "graph")` to `("sql", "graph", "think")`
- Add an `elif session_type == "think"` branch (after the existing sql/graph branches at lines 92-103) that: imports ThinkingEngine, instantiates it (no db_path/max_rows/max_chars needed), calls `engine.connect()` (no-op), and sets `db_path = ""`
- Widen `SessionInfo.engine` type to include `ThinkingEngine`
- Think sessions don't need disk storage — `db_path` is empty string, `temp_dir` still created for consistency but no files written
- Update error message in `get_session()` to mention thinking sessions

### Step 3: Thinking Tools (`tools/think.py`)

Tool naming: `think_*` prefix (consistent with `sql_*` and `graph_*`).

**Auto-session design:** Tools accept an optional `session_id` parameter. If omitted or empty, the tool auto-creates a new thinking session and returns its ID in the response. This eliminates friction — the AI doesn't need to explicitly call a create function first. The session_id is returned in every response so subsequent calls can reuse it.

```
# First call — no session_id → auto-creates
think_step(thought="...", thought_number=1, ...) → "Session: a1b2c3d4 | Thought 1/5 | ..."

# Subsequent calls — pass session_id
think_step(session_id="a1b2c3d4", thought="...", thought_number=2, ...) → "Session: a1b2c3d4 | Thought 2/5 | ..."
```

**Helper function:**
- `_get_or_create_think_session(session_id: str | None) -> tuple[SessionManager, SessionInfo]`
  - If session_id provided: validate it's a "think" session, return it
  - If session_id is None/empty: auto-create new "think" session via SessionManager, return it
  - This is the ONE pattern all thinking tools share

**All 11 tools:**

1. `think_step(thought, thought_number, total_thoughts, next_thought_needed, session_id?, is_revision?, revises_thought?, branch_from_thought?, branch_id?, needs_more_thoughts?)` → Core sequential thinking
2. `think_decide(decision_statement, options, analysis_type, stage, decision_id, iteration, next_stage_needed, session_id?, criteria?, evaluations?, recommendation?, ...)` → Decision framework
3. `think_model(model_name, problem, session_id?, steps?, reasoning?, conclusion?)` → Mental models (first_principles, opportunity_cost, error_propagation, rubber_duck, pareto_principle, occams_razor)
4. `think_debug(approach_name, issue, session_id?, steps?, findings?, resolution?)` → Debugging approaches (binary_search, reverse_engineering, divide_conquer, backtracking, cause_elimination, program_slicing)
5. `think_argue(claim, premises, conclusion, argument_type, confidence, next_argument_needed, session_id?, argument_id?, responds_to?, supports?, contradicts?, ...)` → Structured argumentation
6. `think_collaborate(topic, personas, contributions, stage, active_persona_id, collaboration_id, iteration, next_contribution_needed, session_id?, ...)` → Collaborative reasoning
7. `think_science(stage, inquiry_id, iteration, next_stage_needed, session_id?, question?, hypothesis?, experiment?, analysis?, conclusion?)` → Scientific method
8. `think_monitor(task, stage, overall_confidence, monitoring_id, iteration, next_assessment_needed, session_id?, claims?, reasoning_steps?, ...)` → Metacognitive monitoring
9. `think_visualize(operation, diagram_id, diagram_type, iteration, next_operation_needed, session_id?, elements?, ...)` → Visual reasoning
10. `think_summarize(session_id)` → NEW: Token-optimized summary of all thinking activity in session
11. `think_destroy_session(session_id)` → Destroy thinking session and free memory

**Response format — compact text, not JSON:**
```
Session: a1b2c3d4 | Thought 3/5 | Branches: main, alt-a | History: 3
Status: thinking
```
Instead of clear-thought's pretty-printed JSON (`{"thoughtNumber": 3, "totalThoughts": 5, ...}`). This saves ~60% tokens on metadata responses.

Every response includes the `Session: <id>` prefix so the AI can capture it for subsequent calls.

### Step 4: Server Registration (`server.py`)

- Import all think tool functions from `tools/think.py`
- Add to `_TOOLS` list with appropriate annotations:
  - `think_step`, `think_decide`, `think_model`, `think_debug` → `_DEFAULT` (auto-create sessions, modify state)
  - `think_argue`, `think_collaborate`, `think_science`, `think_monitor`, `think_visualize` → `_DEFAULT`
  - `think_summarize` → `_READONLY` (read-only view of session)
  - `think_destroy_session` → `_DESTRUCTIVE`
- Update `aismartbuddy-guide` prompt to include thinking tools section
- Update `list_sessions` resource to show think sessions
- Total tools: 22 existing + 11 thinking = 33 tools

### Step 5: Update CLAUDE.md

- Update tool count from "22 total tools" to "33 total tools: 6 SQL, 15 graph, 1 meta, 11 thinking"
- Add `tools/think.py → engines/thinking_engine.py` to the architecture diagram
- Add `"think"` to session types documentation
- Document the auto-session creation pattern and compact text response format as key patterns
- Add ThinkingEngine to the engines description

### Step 6: Tests

- `tests/test_think_tools.py` — Unit tests for all thinking tools
  - Test auto-session creation (call think_step without session_id → session auto-created, id returned)
  - Test session reuse (pass session_id from first call into subsequent calls)
  - Test sequential thinking chain (3+ thoughts)
  - Test thought revision (is_revision=True, revises_thought=N)
  - Test branching (branch_from_thought, branch_id)
  - Test memory limits (exceed MAX_THOUGHTS, verify FIFO eviction)
  - Test decision framework multi-stage flow
  - Test mental model application with each model type
  - Test debugging approach with each approach type
  - Test structured argumentation thesis/antithesis/synthesis chain
  - Test collaborative reasoning with multiple personas
  - Test scientific method multi-stage inquiry
  - Test metacognitive monitoring
  - Test visual reasoning diagram creation/update
  - Test summarize output format
  - Test think_destroy_session cleanup
  - Test multi-session isolation (two concurrent sessions don't share state)
  - Test compact text response format (no JSON, includes session ID)

---

## Layer 2: Persistent Cognitive Tools (Expanded Vision)

Beyond the clear-thought thinking tools (Layer 1), 5 additional tool groups provide **persistent cognition** backed by AISmartBuddy's existing DuckDB and Graph engines. These are higher-level abstractions — they generate SQL/Cypher internally, no new engines needed.

### Architecture

```
Layer 1: EPHEMERAL REASONING (ThinkingEngine — in-memory, conversation-scoped)
  think_step, think_decide, think_model, think_debug, think_argue,
  think_collaborate, think_science, think_monitor, think_visualize,
  think_summarize, think_destroy_session

Layer 2: PERSISTENT COGNITION (DuckDB + LadybugDB — project-scoped)
  ┌─── DuckDB-backed ──────────────────┐  ┌─── Graph DB-backed ──────────┐
  │ notebook_* (5 tools)                │  │ tree_* (7 tools)             │
  │   Tables: entries, versions         │  │   Nodes: Thought, Evaluation │
  │                                     │  │   Edges: BRANCHES, REFINES,  │
  │ loop_* (4 tools)                    │  │          CONTRADICTS          │
  │   Tables: loops, iterations, scores │  │                              │
  │                                     │  │ map_* (6 tools)              │
  │ framework_* (5 tools)               │  │   Nodes: Concept, Cluster    │
  │   Tables: frameworks, instances,    │  │   Edges: CAUSES, ENABLES,    │
  │           sections                  │  │          BLOCKS, SUPPORTS,    │
  └─────────────────────────────────────┘  │          DEPENDS, CONTRADICTS │
        │                                  └──────────────────────────────┘
        ▼                                         │
  DuckDBEngine (existing)                  LadybugEngine (existing)
        │                                         │
        └──────────── SessionManager ─────────────┘
```

### How Layer 2 augments Layer 1 (not replaces)

| Layer 1 Tool | Layer 2 Counterpart | Relationship |
|-------------|---------------------|-------------|
| `think_step` (ephemeral thought chain) | `tree_*` (persistent hypothesis tree) | think_step = scratchpad; tree = formal record. Promote insights via tree_branch |
| `think_decide` (one-shot decision) | `loop_*` (iterative refinement) | think_decide evaluates options once; loop refines artifacts across iterations |
| `think_model` (quick framework app) | `framework_*` (full executable framework) | think_model = lightweight; framework = persistent, exportable analysis |
| `think_visualize` (ephemeral diagram) | `map_*` (persistent concept map) | think_visualize = sketch; map = persistent relational analysis with tension detection |
| (no equivalent) | `notebook_*` (persistent scratch space) | Genuinely new — hierarchical entries, versioning, full-text search |

### Composition pattern
```
think_step (reason) → notebook_write (persist insight)
think_decide (evaluate) → tree_converge (record decision)
think_model (apply framework) → framework_instantiate (full analysis)
loop_score (evaluate iteration) → think_step (reason about next change)
map_find_tensions → think_debug (diagnose contradictions)
```

### Tool groups detail

#### Notebook (DuckDB) — 5 tools in `tools/notebook.py`
- `notebook_create(name, schema?)` → Create named notebook workspace. Auto-creates DuckDB session, initializes `entries` and `versions` tables.
- `notebook_write(session_id, key, content, tags?, parent_key?)` → Write entry. `parent_key` enables hierarchical (holonic) nesting. Auto-versions.
- `notebook_read(session_id, key?, tag?, depth?)` → Read by key, tag, or subtree. Depth controls holonic zoom level.
- `notebook_diff(session_id, key, version_a, version_b)` → Diff two versions of an entry. Temporal self-audit.
- `notebook_search(session_id, query, limit?)` → Full-text search across entries.

DuckDB schema:
```sql
CREATE TABLE entries (
  key VARCHAR PRIMARY KEY, content TEXT, parent_key VARCHAR,
  version INT DEFAULT 1, created_at TIMESTAMP, updated_at TIMESTAMP
);
CREATE TABLE entry_tags (key VARCHAR, tag VARCHAR);
CREATE TABLE versions (
  key VARCHAR, version INT, content TEXT, created_at TIMESTAMP,
  PRIMARY KEY (key, version)
);
```

#### Thinking Tree (Graph DB) — 7 tools in `tools/tree.py`
- `tree_create(name, root_thesis)` → Start thinking tree. Auto-creates Graph session, initializes Thought/Evaluation node tables.
- `tree_branch(session_id, parent_id, hypothesis, branch_type?)` → Fork branch. Types: alternative, refinement, contradiction, decomposition.
- `tree_evaluate(session_id, node_id, criteria, scores, notes?)` → Score a node against criteria. Enables pruning decisions.
- `tree_compare(session_id, node_ids)` → Side-by-side comparison of branches.
- `tree_prune(session_id, node_id, reason)` → Kill branch with documented reasoning. Audit trail preserved.
- `tree_converge(session_id, winner_id, absorbed_ids, synthesis)` → Merge branches into conclusion.
- `tree_visualize(session_id, format?)` → Render tree state (Mermaid diagram text).

Graph schema:
```cypher
CREATE NODE TABLE Thought (id SERIAL PRIMARY KEY, content STRING, branch_type STRING, status STRING, created_at STRING);
CREATE NODE TABLE Evaluation (id SERIAL PRIMARY KEY, criteria STRING, scores STRING, notes STRING);
CREATE REL TABLE BRANCHES (FROM Thought TO Thought);
CREATE REL TABLE REFINES (FROM Thought TO Thought);
CREATE REL TABLE CONTRADICTS (FROM Thought TO Thought);
CREATE REL TABLE EVALUATED_BY (FROM Thought TO Evaluation);
```

#### Feedback Loop (DuckDB) — 4 tools in `tools/loop.py`
- `loop_define(name, objective, eval_criteria, max_iterations?)` → Define refinement loop with success criteria. `eval_criteria: [{"name": "clarity", "weight": 0.3, "threshold": 7.0}]`
- `loop_submit(session_id, iteration, artifact)` → Submit artifact for evaluation.
- `loop_score(session_id, iteration, scores, diagnosis)` → Record scores. Returns whether threshold met or next action needed.
- `loop_history(session_id)` → Full iteration history showing learning trajectory.

DuckDB schema:
```sql
CREATE TABLE loops (name VARCHAR, objective TEXT, max_iterations INT, created_at TIMESTAMP);
CREATE TABLE criteria (name VARCHAR, weight DOUBLE, threshold DOUBLE);
CREATE TABLE iterations (iteration INT PRIMARY KEY, artifact TEXT, submitted_at TIMESTAMP);
CREATE TABLE scores (iteration INT, criterion VARCHAR, score DOUBLE, diagnosis TEXT);
```

#### Framework Templates (DuckDB) — 5 tools in `tools/framework.py`
- `framework_list()` → List available frameworks: cynefin, mece, wardley, five_whys, pre_mortem, holonic_decomposition, etc.
- `framework_instantiate(framework, context)` → Create working instance. Returns skeleton structure to populate.
- `framework_populate(session_id, instance_id, section, content)` → Fill in a section.
- `framework_validate(session_id, instance_id)` → Check completeness, internal consistency, flag gaps.
- `framework_export(session_id, instance_id, format?)` → Export as markdown.

DuckDB schema:
```sql
CREATE TABLE instances (id VARCHAR PRIMARY KEY, framework VARCHAR, context TEXT, created_at TIMESTAMP);
CREATE TABLE sections (instance_id VARCHAR, section VARCHAR, content TEXT, filled BOOLEAN DEFAULT FALSE);
```

#### Spatial/Relational Map (Graph DB) — 6 tools in `tools/map.py`
- `map_create(name, description?)` → Create concept map. Auto-creates Graph session.
- `map_add_node(session_id, label, node_type?, properties?, cluster?)` → Add concept. Cluster enables spatial grouping.
- `map_add_edge(session_id, from_id, to_id, relation, weight?)` → Connect concepts. Relations: causes, enables, blocks, contains, contradicts, supports, depends_on.
- `map_query(session_id, query)` → Graph query — shortest path, neighborhood, cluster analysis.
- `map_find_tensions(session_id)` → Auto-detect contradictions, circular dependencies, unsupported nodes.
- `map_render(session_id, format?, focus_node?, depth?)` → Render with optional focus — zoom into subgraph.

Graph schema:
```cypher
CREATE NODE TABLE Concept (id SERIAL PRIMARY KEY, label STRING, node_type STRING, cluster STRING, properties STRING);
CREATE REL TABLE CAUSES (FROM Concept TO Concept, weight DOUBLE);
CREATE REL TABLE ENABLES (FROM Concept TO Concept, weight DOUBLE);
CREATE REL TABLE BLOCKS (FROM Concept TO Concept, weight DOUBLE);
CREATE REL TABLE CONTAINS (FROM Concept TO Concept);
CREATE REL TABLE CONTRADICTS (FROM Concept TO Concept);
CREATE REL TABLE SUPPORTS (FROM Concept TO Concept, weight DOUBLE);
CREATE REL TABLE DEPENDS_ON (FROM Concept TO Concept, weight DOUBLE);
```

### Multi-user validation (Layer 2)

All Layer 2 tools use existing SessionManager for isolation:
- DuckDB-backed tools: Each session creates a separate .duckdb file in temp dir. No shared state.
- Graph-backed tools: Each session creates a separate .lbug file. No shared state.
- Session IDs are UUID-unique — no collision across users, projects, or instances.
- Auto-session creation follows the same pattern as Layer 1 think_* tools.
- **Persistence bonus**: DuckDB and LadybugDB files survive server restarts on disk. Future enhancement: session recovery from disk.

### Implementation phasing

| Phase | Tools | Count | Dependency |
|-------|-------|-------|------------|
| **Phase 1** | Layer 1 thinking tools (think_*) | 11 | None — new ThinkingEngine + tool module |
| **Phase 2** | Notebook + Thinking Tree | 12 | Existing DuckDB + Graph engines |
| **Phase 3** | Feedback Loop + Framework Templates | 9 | Existing DuckDB engine |
| **Phase 4** | Spatial/Relational Map | 6 | Existing Graph engine |
| **Total** | All cognitive tools | 38 | + 22 existing = 60 tools |

### Phase 2-4 implementation pattern (same for each phase)

Each phase follows this repeatable recipe — the same steps as Phase 1 but for DB-backed tools:

1. **Create tool module** (e.g., `tools/notebook.py`). Include:
   - `_ensure_schema(info)` — idempotent schema init using `CREATE TABLE IF NOT EXISTS` (DuckDB) or `CREATE NODE TABLE IF NOT EXISTS` with try/except fallback (Graph, following `graph_knowledge_add` pattern at `graph.py:654-665`)
   - `_get_or_create_X_session(session_id)` — auto-create SQL or Graph session on first call, call `_ensure_schema()`, return `(mgr, info)`
   - Tool functions following existing patterns: validate inputs, `anyio.to_thread.run_sync()` for blocking DB calls, compact text output

2. **Register in server.py** — add imports and `_TOOLS` entries with annotations:
   - Read-only tools (`_read`, `_search`, `_history`, `_compare`, `_list`, `_visualize`, `_render`, `_export`, `_find_tensions`) → `_READONLY`
   - Mutating tools (`_create`, `_write`, `_branch`, `_submit`, `_score`, `_add_node`, `_add_edge`, `_populate`) → `_DEFAULT`
   - Destructive tools (none planned for Layer 2; sessions use existing `sql_destroy_session`/`graph_destroy_session`)
   - Special: `framework_list()` → `_READONLY`, takes no parameters, no session needed

3. **Write tests** in `tests/test_X_tools.py` — session lifecycle, CRUD operations, schema idempotency, multi-session isolation

4. **Update docs** — CLAUDE.md tool counts/architecture, `aismartbuddy-guide` prompt, `list_sessions` resource

---

## Improvements Over Clear-Thought

| Aspect | Clear-Thought | AISmartBuddy Implementation |
|--------|--------------|----------------------------|
| Session isolation | None (shared array) | Session-scoped via SessionManager |
| Multi-user safety | Single-user only (stdio) | Thread-safe, works with SSE |
| Token efficiency | JSON blobs (~200 tokens/response) | Compact text (~80 tokens/response) |
| Persistence | Lost on restart | Extensible to DuckDB later |
| Summarization | None | `think_summarize` tool |
| Cross-tool integration | Separate server | Same server as SQL/graph |
| Runtime | Node.js + npx | Python (no extra runtime) |
| Validation | Zod schemas | Python type hints + FastMCP auto-validation |

---

## Verification

### Phase 1 (Layer 1 — Thinking Tools)
1. `uv run pytest tests/test_think_tools.py -v` — All thinking tool tests pass
2. `uv run pyright` — Type checks pass
3. `uv run ruff check src/ tests/` — Lint passes
4. Manual test: Start server, run a 5-step sequential thinking chain, verify compact text output format
5. Multi-session test: Create 2 thinking sessions concurrently, verify thoughts don't leak between sessions
6. Memory limit test: Add >1000 thoughts to a session, verify FIFO eviction works

### Phase 2 (Notebook + Thinking Tree)
7. `uv run pytest tests/test_notebook_tools.py tests/test_tree_tools.py -v`
8. Manual test: Create notebook, write hierarchical entries, search, diff versions
9. Manual test: Create thinking tree, branch, evaluate, prune, converge, visualize as Mermaid
10. Verify DuckDB schema initialization is idempotent (call notebook_write twice on same session)
11. Verify Graph schema initialization is idempotent (call tree_branch twice on same session)

### Phase 3 (Feedback Loop + Framework)
12. `uv run pytest tests/test_loop_tools.py tests/test_framework_tools.py -v`
13. Manual test: Define loop, submit 3 iterations, score each, verify threshold detection
14. Manual test: Instantiate cynefin framework, populate sections, validate completeness, export

### Phase 4 (Spatial Map)
15. `uv run pytest tests/test_map_tools.py -v`
16. Manual test: Create map, add nodes/edges, find_tensions, render with focus

---

## Non-Goals

- **DuckDB persistence for Layer 1 thinking**: In-memory is sufficient. Layer 2 already provides persistence.
- **Replacing clear-thought**: This is an alternative implementation, not a fork.
- **Visual rendering to images**: `think_visualize`, `tree_visualize`, and `map_render` output text (Mermaid/ASCII), not rendered images.
- **Cross-server composition**: Tools compose within a single AISmartBuddy instance. Cross-server tool references are out of scope.
- **Real-time collaboration**: Multi-user safety means isolation, not shared editing.

---

## TLDR

Build a two-layer cognitive architecture in AISmartBuddy: **Layer 1** (11 `think_*` tools) mirrors clear-thought with session isolation, in-memory state, and compact text output. **Layer 2** (27 tools across `notebook_*`, `tree_*`, `loop_*`, `framework_*`, `map_*`) provides persistent cognition backed by AISmartBuddy's existing DuckDB and Graph engines — no new infrastructure needed, just higher-level abstractions. Auto-session creation for zero friction. Phased delivery across 4 releases. Total: 22 existing + 38 cognitive = 60 tools, all session-isolated, thread-safe, multi-user ready.
