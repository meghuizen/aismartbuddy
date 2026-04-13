# Plan: Replace think_step with Thought Graph Tools

## Verbatim Requirements

### Original Request
> I want you to use clear-thought and also analyze your use of the clear-thought sequential thinking tool. Now I want to upgrade that experience for this mcp. [User's full design for a thought graph system with ThoughtNode, progressive complexity from sequential to hierarchical to delegated, holonic structure, 3 MCP tools (think, validate, delegate), structural validation, and delegation packaging]

### Clarifications
**Q:** Should think_step be fully replaced by the new thought graph tools?
**A:** Replace think_step (Recommended)

**Q:** Should validation and delegation be separate tools or actions within one tool?
**A:** 3 separate tools (Recommended)

## Context

The current `think_step` tool provides flat sequential thinking (linear chain with basic branching/revision). The user designed a thought graph system where every thought is a node in a graph, supporting progressive complexity: simple sequential chains, hierarchical tree decomposition, multi-tree forests, delegation to subagents, and structural validation. The holonic property is emergent — every node is both a self-contained whole (itself + subtree) and a part (of its parent's decomposition).

This replaces `think_step` with 3 new tools: `think_graph`, `think_graph_validate`, `think_graph_delegate`. Net tool count: 35 - 1 + 3 = 37.

---

## Current State (what gets removed)

**ThoughtRecord** (thinking_engine.py:28-42): Flat record with number, content, total_thoughts, next_needed, is_revision, revises_thought, branch_from, branch_id, needs_more_thoughts.

**ThinkingEngine** collections: `self.thoughts: list[ThoughtRecord]`, `self.branches: dict[str, list[ThoughtRecord]]`

**Methods**: add_thought(), get_thought_count(), get_branch_names(), _cleanup_memory() for thoughts/branches

**Constants**: MAX_THOUGHTS=1000, MAX_BRANCHES=50, MAX_BRANCH_SIZE=100

**Tool**: think_step() in tools/think.py (lines 184-244)

**Tests affected**: 15 tests across TestThinkingEngine (8 tests), TestThinkSessionIntegration (1 test), TestThinkStepTool (4 tests), TestCompactTextFormat (1 test), test_summary_with_content (1 test)

---

## Design

### Data Model: ThoughtNode replaces ThoughtRecord

```
ThoughtNode:
    id: str                           # unique node ID (auto-generated)
    tree_id: str                      # which tree this belongs to
    parent_id: str | None             # None = root node
    action: str                       # think | branch | revise | synthesize
    content: str                      # the actual thinking
    children: list[str]               # child node IDs (ordered)
    revision_of: str | None           # ID of node this revises
    revision_history: list[str]       # previous content versions
    delegation_state: str | None      # None | pending | completed
    delegation_context: str           # serialized context for subagent
    delegation_result: str            # result received from subagent
    validation_results: list[dict]    # [{check_type, result, details, suggestions}]
    depth: int                        # distance from root (computed on creation)
    created_at: datetime
    metadata: dict
```

### ThinkingEngine changes

**Remove**: thoughts list, branches dict, ThoughtRecord, MAX_THOUGHTS/MAX_BRANCHES/MAX_BRANCH_SIZE, add_thought(), get_thought_count(), get_branch_names(), _cleanup_memory() for thoughts/branches, Sequential Thinking section in get_summary()

**Add**:
```
MAX_NODES = 2000      # total nodes across all trees
MAX_TREES = 50        # maximum concurrent trees

thought_nodes: dict[str, ThoughtNode]    # all nodes by ID
thought_trees: dict[str, str]            # tree_id → root_node_id
```

**New methods**:
- `add_node(node)` — store node, update parent's children list, trigger memory cleanup
- `get_node(node_id)` → ThoughtNode | None
- `get_tree_root(tree_id)` → ThoughtNode | None (via thought_trees mapping)
- `get_subtree_nodes(node_id)` → list[ThoughtNode] (BFS/DFS from node, includes self)
- `get_path_to_root(node_id)` → list[ThoughtNode] (trace parent_id chain up)
- `revise_node(node_id, new_content)` → push old content to revision_history, update content
- `get_tree_ids()` → list[str]
- `get_node_count()` → int (total across all trees)
- `_cleanup_memory()` — if nodes > MAX_NODES, evict oldest full trees. If trees > MAX_TREES, evict oldest trees.

**Updated get_summary()**: Replace "Sequential Thinking" section with "Thought Graphs" section:
```
### Thought Graphs: {n_trees} trees, {n_nodes} nodes
- tree-abc: "{root_content[:40]}" — {n_nodes} nodes, depth {max_depth}, {delegated_count} delegated
```

**Updated close()**: clear thought_nodes and thought_trees

### Tool 1: `think_graph` (core operations)

Replaces think_step. Actions: think, branch, revise, synthesize.

**Signature**:
```python
async def think_graph(
    thought: str,                       # the thinking content
    action: str = "think",              # think | branch | revise | synthesize
    session_id: str | None = None,      # auto-create
    parent_id: str | None = None,       # None = new root (new tree)
    node_id: str | None = None,         # for revise: which node to revise
    tree_id: str | None = None,         # optionally assign to existing tree
    metadata: dict | None = None,       # flexible context bag
) -> str:
```

**Action behaviors**:
- `think`: Add a thought node. parent_id=None creates new tree root. parent_id=X adds as child of X. Chaining parent→child→grandchild IS sequential thinking.
- `branch`: Same as think but signals decomposition intent. Content describes the decomposition strategy. Subsequent children are the branches.
- `revise`: Update an existing node's content. Requires node_id. Pushes old content to revision_history. Keeps same position in graph.
- `synthesize`: Add a node that explicitly combines children's findings. Same mechanics as think but with "synthesize" action tag, signaling "pulling up from children."

**Parameter precedence**: When parent_id is provided, tree_id is inferred from the parent node. An explicit tree_id parameter is ignored when parent_id is set. When neither is provided, a new tree is created.

**Output format**:
```
Session: {sid} | Tree: {tree_id} | Node: {node_id}
Action: think | Depth: 2 | Children: 0 | Siblings: 3
Parent: {parent_id} | Path: root > decompose > branch-A
Status: added
```

For simple sequential use (like old think_step):
```
think_graph(thought="First insight", action="think")              → new root
think_graph(thought="Building on that...", parent_id="node-1")    → child of first
think_graph(thought="Therefore...", parent_id="node-2")           → grandchild = linear chain
```

### Tool 2: `think_graph_validate` (structural validation)

**Signature**:
```python
async def think_graph_validate(
    session_id: str,
    target_id: str,                     # node_id or tree_id
    check_type: str,                    # coverage | contradictions | gaps | leaps | completeness
    result: str,                        # pass | fail | warning
    details: str,                       # explanation
    suggestions: list[str] | None = None,  # remediation ideas
) -> str:
```

Validation is AI-driven (the AI fills in the check), tool-tracked (stored on the node). The tool doesn't do NLP analysis — it stores the AI's structural assessment.

**target_id resolution**: If target_id matches a node_id in thought_nodes, store validation on that node. If target_id matches a tree_id in thought_trees, store validation on the tree's root node. If neither, raise ValueError.

**check_type values**:
- `coverage`: Do children collectively address the parent's problem?
- `contradictions`: Do sibling nodes contradict each other?
- `gaps`: Are there unstated assumptions or missing steps?
- `leaps`: Does any node make a conclusion not supported by its content?
- `completeness`: Does the tree have synthesis at root level?

**Output**:
```
Session: {sid} | Node: {target_id}
Validation: {check_type} = {result}
Details: {details[:100]}
Total checks on node: {n}
```

### Tool 3: `think_graph_delegate` (delegation boundary)

**Signature**:
```python
async def think_graph_delegate(
    session_id: str,
    node_id: str,
    action: str = "package",            # package | receive
    result: str | None = None,          # for receive: the subagent's result
) -> str:
```

**Actions**:
- `package`: Serializes the node + its ancestry (path to root) into a delegation context string. Sets node's delegation_state to "pending". Returns the context package text that the AI can pass to a subagent.
- `receive`: Accepts results back for a delegated node. Stores in delegation_result, sets delegation_state to "completed".

The tool does NOT run subagents. It manages the delegation boundary: package context out, receive results back.

**Output for package**:
```
Session: {sid} | Node: {node_id} | Delegation: packaged
Context depth: {path_length} nodes
--- Delegation Package ---
Root: {root_content[:80]}
  > {parent_content[:80]}
    > [THIS NODE] {node_content[:80]}
Subtree: {n_children} child nodes
---
```

**Output for receive**:
```
Session: {sid} | Node: {node_id} | Delegation: completed
Result stored. Node now has delegation result.
```

---

## Implementation Steps

### Step 1: Replace ThoughtRecord with ThoughtNode (`engines/thinking_engine.py`)

- Remove ThoughtRecord dataclass, MAX_THOUGHTS, MAX_BRANCHES, MAX_BRANCH_SIZE constants
- Add ThoughtNode dataclass and MAX_NODES=2000, MAX_TREES=50 constants
- Replace `self.thoughts` and `self.branches` with `self.thought_nodes` and `self.thought_trees` in __init__
- Replace add_thought/get_thought_count/get_branch_names with add_node/get_node/get_tree_root/get_subtree_nodes/get_path_to_root/revise_node/get_tree_ids/get_node_count
- Replace _cleanup_memory() thought/branch logic with node/tree eviction
- Replace Sequential Thinking section in get_summary() with Thought Graphs section
- Update close() to clear thought_nodes and thought_trees

### Step 2: Replace think_step with 3 new tools (`tools/think.py`)

- Remove think_step function
- Remove ThoughtRecord from imports, add ThoughtNode
- Add validation constants: _GRAPH_ACTIONS, _VALIDATE_CHECK_TYPES, _VALIDATE_RESULTS, _DELEGATE_ACTIONS
- Add think_graph function (core operations: think, branch, revise, synthesize)
- Add think_graph_validate function (structural validation)
- Add think_graph_delegate function (delegation packaging)
- Follow existing patterns: auto-session, _get_or_create_think_session, compact text output

### Step 3: Update server.py

- Replace `think_step` import with `think_graph, think_graph_validate, think_graph_delegate`
- Replace think_step entry in _TOOLS with 3 new entries:
  - `(think_graph, "think_graph", "Thought Graph", _DEFAULT)`
  - `(think_graph_validate, "think_graph_validate", "Validate Thought Graph", _DEFAULT)`
  - `(think_graph_delegate, "think_graph_delegate", "Delegate Thought Subtree", _DEFAULT)`
- Update aismartbuddy-guide prompt: replace "think_step" section with thought graph description

### Step 4: Update CLAUDE.md

- Update tool count: 37 total (6 SQL + 15 graph + 1 meta + 15 thinking)
- Replace "think_step" references with "think_graph" in key patterns

### Step 5: Rewrite tests (`tests/test_think_tools.py`)

**Remove**: TestThinkStepTool class (4 tests), thought-related tests in TestThinkingEngine (8 tests), think_step part of TestThinkSessionIntegration, TestCompactTextFormat's think_step test

**Add TestThoughtGraph class**:
- test_simple_sequential_chain — think 3 nodes linearly (parent→child→grandchild), verify depth and path
- test_new_tree_root — think with parent_id=None creates new tree
- test_hierarchical_branching — branch node, add 3 children, verify parent-child relationships
- test_deep_nesting — branch→sub-branch→sub-sub-branch, verify depth tracking
- test_revise_node — revise content, verify history preserved, content updated
- test_synthesize — add children then synthesize at parent level
- test_multi_tree_forest — create 2 independent trees, verify isolation
- test_auto_session_creation — call think_graph without session_id
- test_memory_limit_nodes — exceed MAX_NODES, verify oldest tree evicted
- test_memory_limit_trees — exceed MAX_TREES, verify eviction

**Add TestThoughtGraphValidate class**:
- test_validate_coverage — validate a node, verify stored
- test_validate_multiple_checks — add multiple validations to same node
- test_invalid_check_type — verify rejection

**Add TestThoughtGraphDelegate class**:
- test_package_subtree — delegate a node, verify context returned and state=pending
- test_receive_result — receive delegation result, verify state=completed
- test_package_includes_ancestry — verify delegation context includes path to root

**Add error-case tests** (matching project pattern):
- test_invalid_action — bad action string → ValueError
- test_revise_missing_node_id — revise without node_id → ValueError
- test_nonexistent_parent — parent_id not found → ValueError
- test_invalid_validate_result — bad result string → ValueError
- test_delegate_nonexistent_node — package on missing node → ValueError

**Update existing tests**:
- TestThinkingEngine: Replace thought tests with node/tree tests
- TestThinkSessionIntegration: Replace thought isolation test with node isolation test
- test_summary_with_content: Use think_graph instead of think_step, assert "Thought Graphs" not "Sequential Thinking"
- TestThinkSummarizeTool.test_summarize_empty: Replace think_step with think_graph, update assertion from "Sequential Thinking" to "Thought Graphs"
- TestThinkDestroyTool.test_destroy: Replace think_step with think_graph

---

## Verification

1. `uv run pytest tests/test_think_tools.py -v` — all tests pass
2. `uv run ruff check src/ tests/` — lint clean
3. `uv run pytest -v` — full suite passes, no regressions
4. Manual test: Create a hierarchical thought tree with branches, validate, delegate, synthesize

---

## Non-Goals

- **Auto-decomposition**: The tool doesn't decide when to branch. The AI decides; the tool stores structure.
- **Truth validation**: Validation checks logical structure, not factual correctness.
- **Running subagents**: The delegate tool packages context and receives results. Actual subagent execution is external.
- **Visualization**: No Mermaid rendering. Compact text + tree paths.
- **Persistent storage**: In-memory only (Layer 1).

---

## TLDR

Replace `think_step` with 3 tools (`think_graph`, `think_graph_validate`, `think_graph_delegate`) that implement a thought graph where every node is both a self-contained whole and part of a larger decomposition. Supports progressive complexity: simple sequential chains (like old think_step), hierarchical tree decomposition, multi-tree forests, structural validation, and delegation packaging for subagents. ThoughtRecord becomes ThoughtNode with parent/children/revision_history/delegation_state. 37 total tools.
