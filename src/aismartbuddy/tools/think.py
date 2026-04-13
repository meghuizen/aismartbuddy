"""Structured thinking tools for AI reasoning.

Layer 1 cognitive tools — ephemeral, in-memory, session-scoped.
Mirrors clear-thought MCP server functionality with session isolation,
auto-session creation, and token-optimized compact text output.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import anyio

# Aliased to avoid colliding with this module's heavy use of "context" in
# domain types (ThoughtNode metadata, holon contexts, etc.). holon.py uses
# the same alias for the same reason; sql.py/graph.py/score.py use the
# unaliased name where there's no conflict.
from mcp.server.fastmcp import Context as _MCPContext

from aismartbuddy.engines.thinking_engine import (
    ArgRecord,
    CollabRecord,
    DebugRecord,
    DecisionRecord,
    DiagramRecord,
    InquiryRecord,
    InterferenceRecord,
    ModelRecord,
    MonitorRecord,
    ThinkingEngine,
    ThoughtNode,
)
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import get_session_manager

if TYPE_CHECKING:
    from aismartbuddy.session import SessionInfo, SessionManager

# ── Valid enum values ────────────────────────────────────────

_MODEL_NAMES = frozenset({
    "first_principles",
    "opportunity_cost",
    "error_propagation",
    "rubber_duck",
    "pareto_principle",
    "assumptions_xray",
    "fishbone",
    "value_of_info",
    "swot",
    "pre_mortem",
    "design_review",
    "complexity",
    "root_cause",
})

_DEBUG_APPROACHES = frozenset({
    "binary_search",
    "reverse_engineering",
    "divide_conquer",
    "backtracking",
    "cause_elimination",
    "program_slicing",
})

_ARGUMENT_TYPES = frozenset({
    "thesis",
    "antithesis",
    "synthesis",
    "objection",
    "rebuttal",
})

_COLLAB_STAGES = frozenset({
    "problem-definition",
    "ideation",
    "critique",
    "integration",
    "decision",
    "reflection",
})

_SCIENCE_STAGES = frozenset({
    "observation",
    "question",
    "hypothesis",
    "experiment",
    "analysis",
    "conclusion",
    "iteration",
})

_MONITOR_STAGES = frozenset({
    "knowledge-assessment",
    "planning",
    "execution",
    "monitoring",
    "evaluation",
    "reflection",
})

_DECISION_STAGES = frozenset({
    "problem-definition",
    "options",
    "criteria",
    "evaluation",
    "analysis",
    "recommendation",
})

_DECISION_TYPES = frozenset({
    "expected-utility",
    "multi-criteria",
    "maximin",
    "minimax-regret",
    "satisficing",
})

_DIAGRAM_TYPES = frozenset({
    "graph",
    "flowchart",
    "stateDiagram",
    "conceptMap",
    "treeDiagram",
    "custom",
})

_DIAGRAM_OPS = frozenset({
    "create",
    "update",
    "delete",
    "transform",
    "observe",
})

_KNOWLEDGE_LEVELS = frozenset({
    "expert",
    "proficient",
    "familiar",
    "basic",
    "minimal",
    "none",
})

_SUGGESTED_ASSESSMENTS = frozenset({
    "knowledge",
    "claim",
    "reasoning",
    "overall",
})


# ── Helpers ──────────────────────────────────────────────────


def _get_or_create_think_session(
    session_id: str | None,
    ctx: _MCPContext | None = None,
) -> tuple[SessionManager, SessionInfo]:
    """Return an existing think session or auto-create one.

    If session_id is provided, validates it's a "think" session. Identity
    of the caller is NOT re-checked (session_id acts as capability).

    If None/empty, resolves caller identity via `resolve_identity(ctx, ...)`
    and creates a new think session bound to (user_id, project_id). This
    means: under Bearer auth the session is bound to ctx.client_id; under
    stdio it falls back to the configured default.
    """
    mgr = get_session_manager()
    if session_id:
        info = mgr.get_session(session_id)
        if info.session_type != "think":
            raise ValueError(
                f"Session '{session_id}' is a {info.session_type} session, not a thinking session."
            )
        return mgr, info
    # Auto-create with caller-scoped identity
    user_id, project_id = resolve_identity(ctx, None, None)
    info = mgr.create_session("think", user_id, project_id)
    return mgr, info


def _require_think_session(session_id: str) -> tuple[SessionManager, SessionInfo]:
    """Validate and return an existing think session. Raises if wrong type."""
    if not session_id:
        raise ValueError("session_id is required")
    return _get_or_create_think_session(session_id)


def _engine(info: SessionInfo) -> ThinkingEngine:
    """Extract ThinkingEngine from session info with type narrowing."""
    assert isinstance(info.engine, ThinkingEngine)
    return info.engine


def _validate_enum(value: str, valid: frozenset[str], label: str) -> str:
    if value not in valid:
        raise ValueError(f"Invalid {label}: {value!r}. Must be one of: {', '.join(sorted(valid))}")
    return value


# ── Thought Graph constants ──────────────────────────────────

_GRAPH_ACTIONS = frozenset({
    "think",
    "branch",
    "revise",
    "synthesize",
})

_VALIDATE_CHECK_TYPES = frozenset({
    "coverage",
    "contradictions",
    "gaps",
    "leaps",
    "completeness",
    "dependencies",
})

_VALIDATE_RESULTS = frozenset({
    "pass",
    "fail",
    "warning",
})

_DELEGATE_ACTIONS = frozenset({
    "package",
    "receive",
})


# ── Tool: Thought Graph ─────────────────────────────────────


def _build_path_string(engine: ThinkingEngine, node_id: str) -> str:
    """Build a human-readable path from root to node."""
    path = engine.get_path_to_root(node_id)
    if not path:
        return ""
    # path is [node, parent, ..., root] — reverse it
    path.reverse()
    parts = []
    for n in path:
        label = n.content[:25].replace("\n", " ")
        if n.id == node_id:
            parts.append(f"[{label}]")
        else:
            parts.append(label)
    return " > ".join(parts)


async def think_graph(
    thought: str,
    action: str = "think",
    session_id: str | None = None,
    parent_id: str | None = None,
    node_id: str | None = None,
    tree_id: str | None = None,
    depends_on: list[str] | None = None,
    refs: list[str] | None = None,
    metadata: dict | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Thought graph — structured thinking with progressive complexity.

    Every thought is a node in a graph. Supports simple sequential chains,
    hierarchical tree decomposition, multi-tree forests, revision with
    history, and synthesis.

    For simple sequential thinking (like a chain of thoughts):
        think_graph(thought="First insight")  → creates root
        think_graph(thought="Building on that...", parent_id="<prev>")
        think_graph(thought="Therefore...", parent_id="<prev>")

    For hierarchical decomposition:
        think_graph(thought="Break this into parts", action="branch")
        think_graph(thought="Part A analysis", parent_id="<branch>")
        think_graph(thought="Part B analysis", parent_id="<branch>")
        think_graph(thought="Combined conclusion", action="synthesize",
                    parent_id="<branch>")

    Actions:
        think: Add a thought node (default). parent_id=None creates
            a new tree root. parent_id=X adds as child of X.
        branch: Same as think but signals decomposition — children
            of this node are the sub-problems.
        revise: Update existing node's content (requires node_id).
            Preserves revision history.
        synthesize: Combine children's findings into a conclusion.
            Same mechanics as think but tagged as synthesis.

    Args:
        thought: The thinking content.
        action: What kind of thought: think, branch, revise, synthesize.
        session_id: Thinking session ID. Omit to auto-create.
        parent_id: Parent node ID. None creates new tree root.
        node_id: For revise action — which node to update.
        tree_id: Optionally assign to existing tree (ignored when
            parent_id is set — tree is inferred from parent).
        metadata: Flexible context bag for additional data.

    Returns:
        Compact status with node position and tree structure.
    """
    _validate_enum(action, _GRAPH_ACTIONS, "action")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)
    sid = info.session_id

    # ── Revise: update existing node ─────────────────────
    if action == "revise":
        if not node_id:
            raise ValueError("node_id is required for revise action")
        node = engine.revise_node(node_id, thought)
        if node is None:
            raise ValueError(f"Node '{node_id}' not found")
        path_str = _build_path_string(engine, node.id)
        return (
            f"Session: {sid} | Tree: {node.tree_id} | Node: {node.id}\n"
            f"Action: revise | Depth: {node.depth}"
            f" | Revisions: {len(node.revision_history)}\n"
            f"Path: {path_str}\n"
            f"Status: revised"
        )

    # ── Think / Branch / Synthesize: add new node ────────
    nid = uuid.uuid4().hex[:10]
    depth = 0

    if parent_id:
        parent = engine.get_node(parent_id)
        if parent is None:
            raise ValueError(f"Parent node '{parent_id}' not found")
        effective_tree_id = parent.tree_id
        depth = parent.depth + 1
    elif tree_id and tree_id in engine.thought_trees:
        # Existing tree — must add as child, not replace root
        raise ValueError(
            f"Tree '{tree_id}' already has a root. "
            "Use parent_id to add nodes to an existing tree."
        )
    else:
        effective_tree_id = tree_id or uuid.uuid4().hex[:10]

    node = ThoughtNode(
        id=nid,
        tree_id=effective_tree_id,
        content=thought,
        action=action,
        parent_id=parent_id,
        depends_on=depends_on or [],
        refs=refs or [],
        depth=depth,
        metadata=metadata or {},
    )
    engine.add_node(node)

    # Build output
    siblings = 0
    if parent_id:
        parent = engine.get_node(parent_id)
        if parent:
            siblings = len(parent.children) - 1  # exclude self

    path_str = _build_path_string(engine, nid)
    parts = [
        f"Session: {sid} | Tree: {effective_tree_id} | Node: {nid}",
        (
            f"Action: {action} | Depth: {depth}"
            f" | Children: 0 | Siblings: {siblings}"
        ),
    ]
    if parent_id:
        parts.append(f"Parent: {parent_id} | Path: {path_str}")
    parts.append("Status: added")
    return "\n".join(parts)


# ── Tool: Thought Graph Validate ─────────────────────────────


async def think_graph_validate(
    session_id: str,
    target_id: str,
    check_type: str,
    result: str,
    details: str,
    suggestions: list[str] | None = None,
) -> str:
    """Validate structure of a thought graph node or tree.

    Stores your structural assessment on a node. The tool tracks
    validations — it doesn't perform NLP analysis. You (the AI) do
    the assessment; the tool records it.

    Check types:
        coverage: Do children collectively address the parent's problem?
        contradictions: Do sibling nodes contradict each other?
        gaps: Are there unstated assumptions or missing steps?
        leaps: Does any node make unsupported conclusions?
        completeness: Does the tree have a synthesis at root level?

    Args:
        session_id: Thinking session ID.
        target_id: Node ID or tree ID to validate. If tree ID,
            validation is stored on the root node.
        check_type: What structural aspect to validate.
        result: Assessment result — pass, fail, or warning.
        details: Explanation of the assessment.
        suggestions: Optional remediation ideas.

    Returns:
        Compact status with validation summary.
    """
    _validate_enum(check_type, _VALIDATE_CHECK_TYPES, "check_type")
    _validate_enum(result, _VALIDATE_RESULTS, "result")

    _, info = _require_think_session(session_id)
    engine = _engine(info)

    validation = {
        "check_type": check_type,
        "result": result,
        "details": details,
        "suggestions": suggestions or [],
    }
    # Hold the engine lock across lookup + mutation so a concurrent
    # eviction can't remove the node between the two steps.
    with engine.state_lock:
        node = engine.get_node(target_id)
        if node is None:
            root = engine.get_tree_root(target_id)
            if root is None:
                raise ValueError(
                    f"'{target_id}' not found as node ID or tree ID"
                )
            node = root
        node.validation_results.append(validation)
        total_checks = len(node.validation_results)
        node_id_out = node.id

    return (
        f"Session: {session_id} | Node: {node_id_out}\n"
        f"Validation: {check_type} = {result}\n"
        f"Details: {details[:100]}\n"
        f"Total checks on node: {total_checks}"
    )


# ── Tool: Thought Graph Delegate ─────────────────────────────


async def think_graph_delegate(
    session_id: str,
    node_id: str,
    action: str = "package",
    result: str | None = None,
) -> str:
    """Manage delegation boundaries for thought graph subtrees.

    Package a node's context for handoff to a subagent, or receive
    results back. The tool does NOT run subagents — it manages the
    boundary: package context out, receive results back.

    Actions:
        package: Serialize the node + its ancestry (path to root)
            into a delegation context. Sets state to "pending".
        receive: Accept results back for a delegated node.
            Sets state to "completed".

    Args:
        session_id: Thinking session ID.
        node_id: The node to delegate or receive results for.
        action: package or receive.
        result: For receive — the subagent's result text.

    Returns:
        For package: delegation context with ancestry.
        For receive: confirmation of result storage.
    """
    _validate_enum(action, _DELEGATE_ACTIONS, "action")

    _, info = _require_think_session(session_id)
    engine = _engine(info)

    node = engine.get_node(node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' not found")

    if action == "package":
        path = engine.get_path_to_root(node_id)
        path.reverse()  # root first

        # Build delegation context
        context_lines = ["--- Delegation Package ---"]
        for i, n in enumerate(path):
            indent = "  " * i
            marker = "[THIS NODE] " if n.id == node_id else ""
            context_lines.append(
                f"{indent}> {marker}{n.content[:80]}"
            )

        subtree = engine.get_subtree_nodes(node_id)
        child_count = len(subtree) - 1  # exclude self
        context_lines.append(f"Subtree: {child_count} child nodes")
        context_lines.append("---")

        with engine.state_lock:
            node.delegation_state = "pending"
            node.delegation_context = "\n".join(context_lines)

        return (
            f"Session: {session_id} | Node: {node_id}"
            f" | Delegation: packaged\n"
            f"Context depth: {len(path)} nodes\n"
            + "\n".join(context_lines)
        )

    # action == "receive"
    if not result:
        raise ValueError("result is required for receive action")
    with engine.state_lock:
        if node.delegation_state != "pending":
            raise ValueError(
                f"Node '{node_id}' is not in pending delegation state "
                f"(current: {node.delegation_state})"
            )
        node.delegation_state = "completed"
        node.delegation_result = result

    return (
        f"Session: {session_id} | Node: {node_id}"
        f" | Delegation: completed\n"
        "Result stored. Node now has delegation result."
    )


# ── Tool: Decision Framework ─────────────────────────────────


async def think_decide(
    decision_statement: str,
    options: list[dict],
    analysis_type: str,
    stage: str,
    decision_id: str,
    iteration: int,
    next_stage_needed: bool,
    session_id: str | None = None,
    criteria: list[dict] | None = None,
    evaluations: list[dict] | None = None,
    recommendation: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Structured decision analysis with multi-criteria evaluation.

    Supports expected-utility, multi-criteria, maximin, minimax-regret, and
    satisficing analysis types. Work through stages: problem-definition,
    options, criteria, evaluation, analysis, recommendation.

    Args:
        decision_statement: What decision is being made.
        options: List of options, each with 'name' and 'description'.
        analysis_type: One of: expected-utility, multi-criteria,
            maximin, minimax-regret, satisficing.
        stage: Current stage: problem-definition, options, criteria,
            evaluation, analysis, recommendation.
        decision_id: Unique identifier for this decision.
        iteration: Current iteration of the analysis.
        next_stage_needed: Whether another stage is needed.
        session_id: Thinking session ID. Omit to auto-create.
        criteria: Evaluation criteria with name, weight, description.
        evaluations: Scores per criterion per option.
        recommendation: Final recommendation text.

    Returns:
        Compact status with decision progress.
    """
    _validate_enum(analysis_type, _DECISION_TYPES, "analysis_type")
    _validate_enum(stage, _DECISION_STAGES, "stage")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    record = DecisionRecord(
        decision_id=decision_id,
        statement=decision_statement,
        options=options,
        analysis_type=analysis_type,
        stage=stage,
        iteration=iteration,
        criteria=criteria or [],
        evaluations=evaluations or [],
        recommendation=recommendation or "",
    )
    engine.upsert_decision(record)

    parts = [
        f"Session: {info.session_id}",
        f"Decision: {decision_id}",
        f"Stage: {stage}",
        f"Iter: {iteration}",
        f"Options: {len(options)}",
    ]
    if criteria:
        parts.append(f"Criteria: {len(criteria)}")
    status = "analyzing" if next_stage_needed else "decided"
    if recommendation:
        return " | ".join(parts) + f"\nStatus: {status}\nRecommendation: {recommendation[:200]}"
    return " | ".join(parts) + f"\nStatus: {status}"


# ── Tool: Mental Model ───────────────────────────────────────


# Framework guidance per mental model — helps AI apply each model correctly
_MODEL_GUIDANCE: dict[str, str] = {
    "first_principles": (
        "Framework: First Principles Thinking\n"
        "1. Identify assumptions — what are you taking for granted?\n"
        "2. Break down to fundamentals — what is definitely true?\n"
        "3. Rebuild from ground truth — what can you construct "
        "from these fundamentals?"
    ),
    "opportunity_cost": (
        "Framework: Opportunity Cost Analysis\n"
        "1. Identify the options — what alternatives exist?\n"
        "2. Value each option — what do you gain from each?\n"
        "3. Assess what you give up — choosing A means not-B"
    ),
    "error_propagation": (
        "Framework: Error Propagation Understanding\n"
        "1. Identify error sources — where can things go wrong?\n"
        "2. Trace propagation — how do errors compound?\n"
        "3. Assess impact — what is the blast radius of each error?"
    ),
    "rubber_duck": (
        "Framework: Rubber Duck Debugging\n"
        "1. Explain the problem aloud — state what should happen\n"
        "2. Walk through step by step — describe each part\n"
        "3. Find the gap — where does explanation diverge from code?"
    ),
    "pareto_principle": (
        "Framework: Pareto Principle (80/20)\n"
        "1. Identify all factors — what contributes to the outcome?\n"
        "2. Rank by impact — which 20% drives 80% of results?\n"
        "3. Focus effort — prioritize the vital few over trivial many"
    ),
    "assumptions_xray": (
        "Framework: Assumption X-Ray\n"
        "1. Surface hidden assumptions — what must be true "
        "for this claim to hold?\n"
        "2. Rate confidence in each assumption (0.0-1.0)\n"
        "3. Propose falsification tests — how could each "
        "assumption be disproven?"
    ),
    "fishbone": (
        "Framework: Fishbone Diagram (Ishikawa)\n"
        "1. State the problem/effect clearly\n"
        "2. Identify cause categories: methods, materials, "
        "people, environment, measurement, machines "
        "(customize for domain)\n"
        "3. For each category, list specific potential causes\n"
        "4. Identify which causes are most likely and testable"
    ),
    "value_of_info": (
        "Framework: Value of Information\n"
        "1. List decision options and their expected outcomes\n"
        "2. Identify key uncertainties that affect the decision\n"
        "3. For each uncertainty: what would perfect info change?\n"
        "4. Prioritize: investigate uncertainties where info "
        "changes the decision"
    ),
    "swot": (
        "Framework: SWOT Analysis\n"
        "1. Strengths — internal advantages and capabilities\n"
        "2. Weaknesses — internal limitations and gaps\n"
        "3. Opportunities — external favorable conditions\n"
        "4. Threats — external risks and challenges"
    ),
    "pre_mortem": (
        "Framework: Pre-Mortem\n"
        "Assume this design/plan has FAILED. Work backward:\n"
        "1. List failure modes — what specifically went wrong?\n"
        "2. Rate likelihood of each (high/medium/low)\n"
        "3. Identify root causes — why did each failure happen?\n"
        "4. Propose preventions — what changes would avoid each?"
    ),
    "design_review": (
        "Framework: Design Review\n"
        "1. Simplest break — what is the simplest input or "
        "sequence that breaks this design?\n"
        "2. Assumption audit — what am I assuming about data, "
        "state, ordering, or user behavior?\n"
        "3. State machine check — can every reachable state "
        "transition to a valid end state?\n"
        "4. Edge cases — empty inputs, duplicates, concurrent "
        "access, unexpected order of operations"
    ),
    "complexity": (
        "Framework: Complexity Analysis\n"
        "1. Cyclomatic complexity — how many independent paths "
        "through the logic? (aim for <10 per function)\n"
        "2. Coupling — how many other components does this "
        "depend on or get depended on by?\n"
        "3. Cognitive load — can a reader understand this in "
        "one pass without scrolling?\n"
        "4. Abstraction level — is this the right level of "
        "abstraction, or over/under-engineered?"
    ),
    "root_cause": (
        "Framework: Root Cause Analysis (5 Whys + Ishikawa)\n"
        "1. State the problem/symptom precisely\n"
        "2. Ask 'Why?' — what directly caused this?\n"
        "3. For each cause, ask 'Why?' again — dig deeper\n"
        "4. Repeat until you reach a root cause (typically "
        "3-5 levels deep)\n"
        "5. Categorize root causes: process, people, tools, "
        "environment, design, dependencies\n"
        "6. For each root cause: what systemic fix prevents "
        "recurrence (not just this instance)?"
    ),
}


async def think_model(
    model_name: str,
    problem: str,
    session_id: str | None = None,
    steps: list[str] | None = None,
    reasoning: str | None = None,
    conclusion: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Apply a structured mental model to a problem.

    Available models:
    - first_principles: Break down to fundamental truths, rebuild.
    - opportunity_cost: Evaluate what you give up by choosing.
    - error_propagation: Trace how errors compound through a system.
    - rubber_duck: Explain the problem step by step to find the gap.
    - pareto_principle: Find the 20% driving 80% of results.
    - assumptions_xray: Surface hidden assumptions in a claim,
      rate confidence, propose falsification tests.
    - fishbone: Ishikawa diagram — categorize causes by type
      (methods, materials, people, environment, etc).
    - value_of_info: Assess whether gathering information is
      worth the cost before deciding.
    - swot: Strengths, weaknesses, opportunities, threats.
    - pre_mortem: Assume failure, work backward to find causes.
    - design_review: Find what breaks a design — edge cases,
      state machine gaps, assumption audit.
    - complexity: Cyclomatic complexity, coupling, cognitive
      load, abstraction level analysis.
    - root_cause: 5 Whys + Ishikawa — dig to root causes,
      categorize, find systemic fixes.

    Args:
        model_name: Which mental model to apply.
        problem: The problem being analyzed.
        session_id: Thinking session ID. Omit to auto-create.
        steps: Reasoning steps taken following the model's framework.
        reasoning: Detailed reasoning text.
        conclusion: Final conclusion.

    Returns:
        Compact status with framework guidance and conclusion.
    """
    _validate_enum(model_name, _MODEL_NAMES, "model_name")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    record = ModelRecord(
        model_name=model_name,
        problem=problem,
        steps=steps or [],
        reasoning=reasoning or "",
        conclusion=conclusion or "",
    )
    engine.add_model(record)

    parts = [
        f"Session: {info.session_id}",
        f"Model: {model_name}",
        f"Steps: {len(steps or [])}",
    ]
    header = " | ".join(parts)

    lines = [header]
    if not steps and not conclusion:
        # No steps yet — return framework guidance to help the AI
        lines.append(_MODEL_GUIDANCE[model_name])
        lines.append("Status: framework loaded — apply the steps above")
    elif conclusion:
        lines.append(f"Conclusion: {conclusion[:200]}")
    else:
        lines.append("Status: applied")
    return "\n".join(lines)


# ── Tool: Debugging Approach ─────────────────────────────────


async def think_debug(
    approach_name: str,
    issue: str,
    session_id: str | None = None,
    steps: list[str] | None = None,
    findings: str | None = None,
    resolution: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Apply a systematic debugging approach to a technical issue.

    Available approaches: binary_search, reverse_engineering, divide_conquer,
    backtracking, cause_elimination, program_slicing.

    Args:
        approach_name: Which debugging approach to use.
        issue: The technical issue being debugged.
        session_id: Thinking session ID. Omit to auto-create.
        steps: Debugging steps taken.
        findings: What was discovered.
        resolution: How the issue was resolved.

    Returns:
        Compact status with debugging progress.
    """
    _validate_enum(approach_name, _DEBUG_APPROACHES, "approach_name")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    record = DebugRecord(
        approach_name=approach_name,
        issue=issue,
        steps=steps or [],
        findings=findings or "",
        resolution=resolution or "",
    )
    engine.add_debug(record)

    parts = [
        f"Session: {info.session_id}",
        f"Approach: {approach_name}",
        f"Steps: {len(steps or [])}",
    ]
    if resolution:
        return " | ".join(parts) + f"\nResolution: {resolution[:200]}"
    return " | ".join(parts) + "\nStatus: investigating"


# ── Tool: Structured Argumentation ───────────────────────────


async def think_argue(
    claim: str,
    premises: list[str],
    conclusion: str,
    argument_type: str,
    confidence: float,
    next_argument_needed: bool,
    session_id: str | None = None,
    argument_id: str | None = None,
    responds_to: str | None = None,
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
    strengths: list[str] | None = None,
    weaknesses: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Dialectical reasoning through thesis, antithesis, synthesis.

    Build chains of arguments that support, contradict, or synthesize each other.
    Types: thesis, antithesis, synthesis, objection, rebuttal.

    Args:
        claim: The central claim of this argument.
        premises: Supporting premises for the claim.
        conclusion: What follows from the premises.
        argument_type: One of: thesis, antithesis, synthesis, objection, rebuttal.
        confidence: Confidence in this argument (0.0 to 1.0).
        next_argument_needed: Whether the dialectic needs more arguments.
        session_id: Thinking session ID. Omit to auto-create.
        argument_id: Unique ID for this argument.
        responds_to: ID of the argument this responds to.
        supports: IDs of arguments this supports.
        contradicts: IDs of arguments this contradicts.
        strengths: Notable strong points.
        weaknesses: Notable weak points.

    Returns:
        Compact status with argumentation chain progress.
    """
    _validate_enum(argument_type, _ARGUMENT_TYPES, "argument_type")
    confidence = max(0.0, min(1.0, confidence))

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    arg_id = argument_id or uuid.uuid4().hex[:8]
    record = ArgRecord(
        argument_id=arg_id,
        claim=claim,
        premises=premises,
        conclusion=conclusion,
        argument_type=argument_type,
        confidence=confidence,
        responds_to=responds_to,
        supports=supports or [],
        contradicts=contradicts or [],
        strengths=strengths or [],
        weaknesses=weaknesses or [],
    )
    # Atomic chain-resolution + insert. Under concurrent add_argument from
    # multiple agents sharing a session, this prevents a race where we
    # resolve chain_id against a stale engine.args snapshot.
    with engine.state_lock:
        chain_id = arg_id
        if responds_to:
            for cid, chain in engine.args.items():
                if any(a.argument_id == responds_to for a in chain):
                    chain_id = cid
                    break
            else:
                chain_id = responds_to
        engine.add_argument(chain_id, record)
        chain = engine.get_arg_chain(chain_id)
    parts = [
        f"Session: {info.session_id}",
        f"Arg: {arg_id}",
        f"Type: {argument_type}",
        f"Confidence: {confidence:.2f}",
        f"Chain: {len(chain)} arguments",
    ]
    status = "dialectic ongoing" if next_argument_needed else "dialectic complete"
    return " | ".join(parts) + f"\nStatus: {status}"


# ── Tool: Collaborative Reasoning ────────────────────────────


async def think_collaborate(
    topic: str,
    personas: list[dict],
    contributions: list[dict],
    stage: str,
    active_persona_id: str,
    collaboration_id: str,
    iteration: int,
    next_contribution_needed: bool,
    session_id: str | None = None,
    consensus_points: list[str] | None = None,
    disagreements: list[dict] | None = None,
    open_questions: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Simulate expert collaboration with diverse perspectives.

    Define personas with expertise and biases, then make contributions
    from each perspective. Stages: problem-definition, ideation, critique,
    integration, decision, reflection.

    Args:
        topic: The problem being discussed.
        personas: Expert personas with id, name, expertise,
            background, perspective, biases, communication.
        contributions: List of contributions with personaId, content, type, confidence.
        stage: Current stage of collaboration.
        active_persona_id: Which persona is currently contributing.
        collaboration_id: Unique ID for this collaboration session.
        iteration: Current iteration.
        next_contribution_needed: Whether more contributions are needed.
        session_id: Thinking session ID. Omit to auto-create.
        consensus_points: Points of agreement.
        disagreements: Points of disagreement with positions.
        open_questions: Unresolved questions.

    Returns:
        Compact status with collaboration progress.
    """
    _validate_enum(stage, _COLLAB_STAGES, "stage")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    record = CollabRecord(
        session_id=collaboration_id,
        topic=topic,
        personas=personas,
        contributions=contributions,
        stage=stage,
        iteration=iteration,
        active_persona_id=active_persona_id,
        consensus_points=consensus_points or [],
        disagreements=disagreements or [],
        open_questions=open_questions or [],
    )
    engine.upsert_collaboration(record)

    parts = [
        f"Session: {info.session_id}",
        f"Collab: {collaboration_id}",
        f"Stage: {stage}",
        f"Personas: {len(personas)}",
        f"Contributions: {len(contributions)}",
        f"Iter: {iteration}",
    ]
    status = "collaborating" if next_contribution_needed else "concluded"
    return " | ".join(parts) + f"\nStatus: {status}"


# ── Tool: Scientific Method ──────────────────────────────────


async def think_science(
    stage: str,
    inquiry_id: str,
    iteration: int,
    next_stage_needed: bool,
    session_id: str | None = None,
    observation: str | None = None,
    question: str | None = None,
    hypothesis: dict | None = None,
    experiment: dict | None = None,
    analysis: str | None = None,
    conclusion: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Apply formal scientific reasoning with structured hypothesis testing.

    Work through stages: observation, question, hypothesis, experiment,
    analysis, conclusion, iteration.

    Args:
        stage: Current stage in scientific method.
        inquiry_id: Unique identifier for this inquiry.
        iteration: Current iteration of the process.
        next_stage_needed: Whether another stage is needed.
        session_id: Thinking session ID. Omit to auto-create.
        observation: Initial observation.
        question: Research question.
        hypothesis: Structured hypothesis with statement, variables, assumptions.
        experiment: Experiment design with methodology, predictions.
        analysis: Analysis of results.
        conclusion: Final conclusion.

    Returns:
        Compact status with inquiry progress.
    """
    _validate_enum(stage, _SCIENCE_STAGES, "stage")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    record = InquiryRecord(
        inquiry_id=inquiry_id,
        stage=stage,
        iteration=iteration,
        observation=observation or "",
        question=question or "",
        hypothesis=hypothesis,
        experiment=experiment,
        analysis=analysis or "",
        conclusion=conclusion or "",
    )
    engine.upsert_inquiry(record)

    parts = [
        f"Session: {info.session_id}",
        f"Inquiry: {inquiry_id}",
        f"Stage: {stage}",
        f"Iter: {iteration}",
    ]
    status = "investigating" if next_stage_needed else "concluded"
    if conclusion:
        return " | ".join(parts) + f"\nStatus: {status}\nConclusion: {conclusion[:200]}"
    return " | ".join(parts) + f"\nStatus: {status}"


# ── Tool: Metacognitive Monitoring ───────────────────────────


async def think_monitor(
    task: str,
    stage: str,
    overall_confidence: float,
    monitoring_id: str,
    iteration: int,
    next_assessment_needed: bool,
    session_id: str | None = None,
    knowledge_assessment: dict | None = None,
    claims: list[dict] | None = None,
    reasoning_steps: list[dict] | None = None,
    uncertainty_areas: list[str] | None = None,
    recommended_approach: str | None = None,
    suggested_assessments: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Systematic self-monitoring of knowledge and reasoning quality.

    Track knowledge boundaries, claim certainty, and reasoning biases.
    Stages: knowledge-assessment, planning, execution, monitoring,
    evaluation, reflection.

    Args:
        task: What task is being monitored.
        stage: Current monitoring stage.
        overall_confidence: Overall confidence (0.0 to 1.0).
        monitoring_id: Unique ID for this monitoring session.
        iteration: Current iteration.
        next_assessment_needed: Whether further assessment is needed.
        session_id: Thinking session ID. Omit to auto-create.
        knowledge_assessment: Structured self-assessment with keys:
            domain (str), knowledgeLevel (expert/proficient/familiar/
            basic/minimal/none), confidenceScore (0-1),
            supportingEvidence (str), knownLimitations (list[str]).
        claims: Claims with status (fact/inference/speculation/
            uncertain), confidenceScore (0-1), evidenceBasis (str),
            and optional alternativeInterpretations, falsifiability.
        reasoning_steps: Steps with potentialBiases (list[str]),
            assumptions (list[str]), logicalValidity (0-1),
            inferenceStrength (0-1).
        uncertainty_areas: Areas of uncertainty.
        recommended_approach: Recommended approach going forward.
        suggested_assessments: Suggested next assessments to perform.
            Values: knowledge, claim, reasoning, overall.

    Returns:
        Compact status with monitoring assessment.
    """
    _validate_enum(stage, _MONITOR_STAGES, "stage")
    overall_confidence = max(0.0, min(1.0, overall_confidence))

    if knowledge_assessment:
        level = knowledge_assessment.get("knowledgeLevel", "")
        if level:
            _validate_enum(level, _KNOWLEDGE_LEVELS, "knowledgeLevel")
        cs = knowledge_assessment.get("confidenceScore")
        if cs is not None:
            if not isinstance(cs, (int, float)) or not (0.0 <= cs <= 1.0):
                raise ValueError(
                    f"Invalid confidenceScore: {cs!r}. "
                    "Must be a number between 0.0 and 1.0"
                )

    if suggested_assessments:
        for sa in suggested_assessments:
            _validate_enum(sa, _SUGGESTED_ASSESSMENTS, "suggested assessment")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    record = MonitorRecord(
        monitoring_id=monitoring_id,
        task=task,
        stage=stage,
        iteration=iteration,
        overall_confidence=overall_confidence,
        knowledge_assessment=knowledge_assessment,
        claims=claims or [],
        reasoning_steps=reasoning_steps or [],
        uncertainty_areas=uncertainty_areas or [],
        recommended_approach=recommended_approach or "",
        suggested_assessments=suggested_assessments or [],
    )
    engine.upsert_monitor(record)

    parts = [
        f"Session: {info.session_id}",
        f"Monitor: {monitoring_id}",
        f"Stage: {stage}",
        f"Confidence: {overall_confidence:.2f}",
        f"Iter: {iteration}",
    ]
    if knowledge_assessment:
        domain = knowledge_assessment.get("domain", "?")
        level = knowledge_assessment.get("knowledgeLevel", "?")
        parts.append(f"Knowledge: {domain}={level}")
    if claims:
        parts.append(f"Claims: {len(claims)}")
    if reasoning_steps:
        parts.append(f"Steps: {len(reasoning_steps)}")
    if uncertainty_areas:
        parts.append(f"Uncertainties: {len(uncertainty_areas)}")
    status = "monitoring" if next_assessment_needed else "assessed"
    lines = [" | ".join(parts), f"Status: {status}"]
    if suggested_assessments:
        lines.append(f"Next: {', '.join(suggested_assessments)}")
    return "\n".join(lines)


# ── Tool: Visual Reasoning ───────────────────────────────────


async def think_visualize(
    operation: str,
    diagram_id: str,
    diagram_type: str,
    iteration: int,
    next_operation_needed: bool,
    session_id: str | None = None,
    elements: list[dict] | None = None,
    observation: str | None = None,
    hypothesis: str | None = None,
    insight: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Visual thinking through diagrams and spatial representations.

    Supports graph, flowchart, stateDiagram, conceptMap, treeDiagram, custom.
    Operations: create, update, delete, transform, observe.

    Args:
        operation: What to do: create, update, delete, transform, observe.
        diagram_id: Unique identifier for the diagram.
        diagram_type: Type of diagram.
        iteration: Current iteration.
        next_operation_needed: Whether another operation is needed.
        session_id: Thinking session ID. Omit to auto-create.
        elements: Diagram elements (nodes, edges, containers, annotations).
        observation: What you observe in the diagram.
        hypothesis: Hypothesis about the visual structure.
        insight: Insight derived from visual analysis.

    Returns:
        Compact status with diagram state.
    """
    _validate_enum(operation, _DIAGRAM_OPS, "operation")
    _validate_enum(diagram_type, _DIAGRAM_TYPES, "diagram_type")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    # Atomic read-modify-write: another agent could concurrently mutate the
    # same diagram record between get_diagram and upsert_diagram.
    with engine.state_lock:
        existing = engine.get_diagram(diagram_id)
        if operation == "delete":
            engine.delete_diagram(diagram_id)
            return f"Session: {info.session_id} | Diagram: {diagram_id} | Deleted"
        elif existing:
            if elements is not None:
                existing.elements = elements
            log_entry: dict = {"op": operation, "iter": iteration}
            if observation:
                log_entry["observation"] = observation
            if hypothesis:
                log_entry["hypothesis"] = hypothesis
            existing.operations_log.append(log_entry)
            record = existing
        else:
            init_log: dict = {"op": operation, "iter": iteration}
            if observation:
                init_log["observation"] = observation
            if hypothesis:
                init_log["hypothesis"] = hypothesis
            record = DiagramRecord(
                diagram_id=diagram_id,
                diagram_type=diagram_type,
                elements=elements or [],
                operations_log=[init_log],
            )
        engine.upsert_diagram(record)

    parts = [
        f"Session: {info.session_id}",
        f"Diagram: {diagram_id}",
        f"Type: {record.diagram_type}",
        f"Elements: {len(record.elements)}",
        f"Op: {operation}",
    ]
    status = "evolving" if next_operation_needed else "stable"
    if insight:
        return " | ".join(parts) + f"\nStatus: {status}\nInsight: {insight[:200]}"
    return " | ".join(parts) + f"\nStatus: {status}"


# ── Tool: Summarize ──────────────────────────────────────────


async def think_summarize(session_id: str) -> str:
    """Get a token-optimized summary of all thinking activity in a session.

    Returns a compact overview of all thought graphs, mental models,
    decisions, debugging approaches, arguments, collaborations, inquiries,
    monitors, and diagrams recorded in the session.

    Args:
        session_id: Thinking session ID.

    Returns:
        Compact summary of all thinking activity.
    """
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    return f"Session: {session_id}\n{engine.get_summary()}"


# ── Tool: Destroy Session ────────────────────────────────────


async def think_create_session(
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Create a new thinking session bound to (user_id, project_id).

    Most think_* tools auto-create sessions on first call, but this tool
    lets you create an identity-bound session explicitly when you need to
    share it across multiple agents in the same project.

    Multi-tenant: if Bearer auth is configured, user_id comes from
    ctx.client_id (parameter ignored); otherwise the parameter (or the
    configured default) is used.

    Example: think_create_session(project_id="analysis") → returns session_id

    Args:
        user_id: Owner identity. Ignored when Bearer auth is configured.
        project_id: Project scope. Default: configured default_project_id.

    Returns:
        Session ID bound to the resolved (user_id, project_id).
    """
    resolved_user, resolved_project = resolve_identity(ctx, user_id, project_id)
    mgr = get_session_manager()
    info = await anyio.to_thread.run_sync(
        lambda: mgr.create_session("think", resolved_user, resolved_project)
    )
    return (
        f"Thinking session created.\n"
        f"session_id: {info.session_id}\n"
        f"user_id: {info.user_id} | project_id: {info.project_id}\n"
        f"Pass this session_id to think_graph, think_decide, think_model, etc. "
        f"to scope thinking to this project. Share the session_id with other "
        f"agents in the same project to collaborate."
    )


async def think_destroy_session(session_id: str) -> str:
    """Destroy a thinking session and free its memory.

    Args:
        session_id: Thinking session ID to destroy.

    Returns:
        Confirmation of session destruction.
    """
    mgr, _ = _require_think_session(session_id)
    await anyio.to_thread.run_sync(lambda: mgr.destroy_session(session_id))
    return f"Session: {session_id} | Destroyed"


# ── Interference Protocol constants ──────────────────────────

_IP_ACTIONS = frozenset({
    "set_domain",
    "add_frame",
    "add_source",
    "add_fragment",
    "add_tension",
    "crystallize",
    "add_necessity",
    "update_necessity",
    "stress_test",
    "finalize",
    "recurse",
})

_IP_AUDIT_TYPES = frozenset({
    "first_principles",
    "ecosystem",
    "contingency",
    "failure_modes",
})

_IP_VERDICTS = frozenset({
    "survives",
    "dies",
    "wounded",
})

_IP_MIN_SOURCES = 2
_IP_MIN_FRAGMENTS = 5

_IP_NECESSITY_STATUSES = frozenset({
    "untested",
    "holds",
    "fails",
})

# Phase gate: which phases allow which actions
_IP_PHASE_GATES: dict[str, set[str]] = {
    "set_domain": set(),  # creates new — no phase required
    "add_frame": {"domain_set"},
    "add_source": {"domain_set", "sources_ready"},
    "add_fragment": {"sources_ready", "interfering"},
    "add_tension": {"interfering", "saturated"},
    "crystallize": {"saturated"},
    "add_necessity": {"crystallized", "necessities_derived"},
    "update_necessity": {"necessities_derived"},
    "stress_test": {
        "necessities_derived",
        "stress_tested",
    },
    "finalize": {"necessities_derived", "stress_tested"},
    "recurse": {"stress_tested"},
}

# Valid next actions per phase (for guidance)
_IP_VALID_ACTIONS: dict[str, list[str]] = {
    "uninitiated": ["set_domain"],
    "domain_set": ["add_frame", "add_source"],
    "sources_ready": ["add_source", "add_fragment"],
    "interfering": ["add_fragment", "add_tension"],
    "saturated": ["add_tension", "crystallize"],
    "crystallized": [
        "add_necessity",
    ],
    "necessities_derived": [
        "update_necessity",
        "stress_test",
        "finalize",
    ],
    "stress_tested": ["stress_test", "finalize", "recurse"],
}


# ── Tool: Interference Protocol ──────────────────────────────


def _ip_status_output(
    session_id: str,
    record: InterferenceRecord,
    status_msg: str,
) -> str:
    """Build compact text output for interference protocol responses."""
    lines = [
        (
            f"Session: {session_id} | Protocol: {record.protocol_id}"
        ),
        (
            f"Phase: {record.phase} | Iter: {record.iteration}"
            f" | Domain: {record.target_domain or '(not set)'}"
        ),
        (
            f"Sources: {len(record.source_laws)}"
            f" | Fragments: {len(record.fragments)}/{_IP_MIN_FRAGMENTS}"
            f" | Frames: {len(record.suspended_frames)}"
        ),
        f"Status: {status_msg}",
    ]

    # Next actions guidance
    valid = _IP_VALID_ACTIONS.get(record.phase, [])
    if valid:
        lines.append(f"Next: {', '.join(valid)}")

    # Include suspended frames for frame detection (phases before stress_test)
    if record.phase not in ("stress_tested",) and record.suspended_frames:
        frames_preview = "; ".join(record.suspended_frames[:5])
        if len(record.suspended_frames) > 5:
            frames_preview += f" (+{len(record.suspended_frames) - 5} more)"
        lines.append(f"Suspended frames: {frames_preview}")

    return "\n".join(lines)


async def think_interfere(
    action: str,
    session_id: str | None = None,
    protocol_id: str | None = None,
    target_domain: str | None = None,
    frame: str | None = None,
    source_domain: str | None = None,
    law: str | None = None,
    isomorphism: str | None = None,
    fragment: str | None = None,
    tension_laws: list[int] | None = None,
    tension_description: str | None = None,
    name: str | None = None,
    properties: list[dict] | None = None,
    conclusion: str | None = None,
    prerequisites: list[dict] | None = None,
    chain_index: int | None = None,
    prereq_index: int | None = None,
    new_status: str | None = None,
    audit_type: str | None = None,
    audit_result: str | None = None,
    verdict: str | None = None,
    new_domain: str | None = None,
    concept_as_law: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Interference Protocol — structured novelty generation.

    A multi-phase thinking framework that produces genuinely novel
    concepts by forcing unrelated structural laws into simultaneous
    truth and finding emergent interference patterns.

    Actions (must proceed in phase order):
      set_domain: Start protocol. Provide target_domain.
      add_frame: Add a suspended structural assumption.
      add_source: Add a source law (need 2+).
        Provide source_domain, law, isomorphism.
      add_fragment: Add an interference observation (need 5+).
      add_tension: Record tension between source laws.
        Provide tension_laws (indices), tension_description.
      crystallize: Name the emergent concept.
        Provide name, properties [{text, novel, source_laws}].
        Emergence test: 2+ novel properties must reference 2+ sources.
      add_necessity: Add a necessity chain.
        Provide conclusion, prerequisites [{claim, status}].
      update_necessity: Update prerequisite status.
        Provide chain_index, prereq_index, new_status.
      stress_test: Add audit result.
        Provide audit_type, audit_result.
      finalize: Set final verdict.
        Provide verdict (survives/dies/wounded).
      recurse: Start new cycle with emergent concept as source.
        Provide new_domain, concept_as_law.

    The tool enforces phase gates and returns suspended frames
    so you can apply frame detection to your own reasoning.

    Args:
        action: Which operation to perform.
        session_id: Thinking session ID. Omit to auto-create.
        protocol_id: Protocol ID. Omit for set_domain (auto-created).
        target_domain: The domain to explore (for set_domain).
        frame: A structural assumption to suspend (for add_frame).
        source_domain: Domain of the source law (for add_source).
        law: One-sentence structural constraint (for add_source).
        isomorphism: "This and target are both instances of ___"
            (for add_source).
        fragment: Interference observation text (for add_fragment).
        tension_laws: Source law indices creating tension
            (for add_tension).
        tension_description: Description of the tension
            (for add_tension).
        name: Emergent concept name (for crystallize).
        properties: Concept properties (for crystallize).
            Each: {text, novel (bool), source_laws (list[int])}.
        conclusion: What must be true (for add_necessity).
        prerequisites: What must hold (for add_necessity).
            Each: {claim, status (untested/holds/fails)}.
        chain_index: Which necessity chain to update.
        prereq_index: Which prerequisite in the chain to update.
        new_status: New status for the prerequisite.
        audit_type: Type of stress test audit (for stress_test).
        audit_result: Audit findings text (for stress_test).
        verdict: Final verdict (for finalize).
        new_domain: New target domain (for recurse).
        concept_as_law: Emergent concept as a one-sentence law
            (for recurse).

    Returns:
        Compact status with phase, state, and guidance.
    """
    _validate_enum(action, _IP_ACTIONS, "action")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)
    sid = info.session_id

    # Interference is a multi-phase state machine. Every action reads the
    # current record, checks phase gates, mutates, and upserts. Without a
    # lock, two agents sharing a protocol_id could both pass the phase gate
    # and corrupt each other's transitions. RLock reentry keeps nested
    # @_synchronized engine calls safe.
    with engine.state_lock:
        return _think_interfere_locked(
            engine, sid, action, protocol_id, target_domain, frame,
            source_domain, law, isomorphism, fragment, tension_laws,
            tension_description, name, properties, conclusion,
            prerequisites, chain_index, prereq_index, new_status,
            audit_type, audit_result, verdict, new_domain, concept_as_law,
        )


def _think_interfere_locked(
    engine: ThinkingEngine,
    sid: str,
    action: str,
    protocol_id: str | None,
    target_domain: str | None,
    frame: str | None,
    source_domain: str | None,
    law: str | None,
    isomorphism: str | None,
    fragment: str | None,
    tension_laws: list[int] | None,
    tension_description: str | None,
    name: str | None,
    properties: list[dict] | None,
    conclusion: str | None,
    prerequisites: list[dict] | None,
    chain_index: int | None,
    prereq_index: int | None,
    new_status: str | None,
    audit_type: str | None,
    audit_result: str | None,
    verdict: str | None,
    new_domain: str | None,
    concept_as_law: str | None,
) -> str:
    """Body of think_interfere executed while holding engine.state_lock.

    Callers MUST hold engine.state_lock (enforced by think_interfere's
    with-block). RLock reentry allows @_synchronized engine methods
    called from this body (e.g. upsert_interference) to work safely.
    """
    # ── set_domain: creates a new protocol ───────────────
    if action == "set_domain":
        if not target_domain:
            raise ValueError("target_domain is required for set_domain")
        pid = uuid.uuid4().hex[:12]
        record = InterferenceRecord(
            protocol_id=pid,
            phase="domain_set",
            target_domain=target_domain,
        )
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Domain set: '{target_domain}'. Add suspended frames "
            "and at least 2 source laws from distant domains.",
        )

    # ── All other actions require protocol_id ────────────
    if not protocol_id:
        raise ValueError(
            "protocol_id is required. Use action='set_domain' to "
            "start a new protocol."
        )
    record = engine.get_interference(protocol_id)
    if record is None:
        raise ValueError(f"Protocol '{protocol_id}' not found.")

    # ── Phase gate check ─────────────────────────────────
    allowed_phases = _IP_PHASE_GATES.get(action, set())
    if allowed_phases and record.phase not in allowed_phases:
        valid = _IP_VALID_ACTIONS.get(record.phase, [])
        return _ip_status_output(
            sid, record,
            f"REJECTED: '{action}' not allowed in phase "
            f"'{record.phase}'. Valid actions: {', '.join(valid)}",
        )

    # ── add_frame ────────────────────────────────────────
    if action == "add_frame":
        if not frame:
            raise ValueError("frame is required for add_frame")
        record.suspended_frames.append(frame)
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Frame suspended: '{frame[:80]}'",
        )

    # ── add_source ───────────────────────────────────────
    if action == "add_source":
        if not source_domain or not law or not isomorphism:
            raise ValueError(
                "source_domain, law, and isomorphism are all "
                "required for add_source"
            )
        record.source_laws.append({
            "domain": source_domain,
            "law": law,
            "isomorphism": isomorphism,
        })
        if len(record.source_laws) >= _IP_MIN_SOURCES:
            record.phase = "sources_ready"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Source added: [{source_domain}] {law[:60]}. "
            f"Total: {len(record.source_laws)} sources"
            + (f" (need {_IP_MIN_SOURCES}+, ready for fragments)"
               if len(record.source_laws) >= _IP_MIN_SOURCES
               else f" (need {_IP_MIN_SOURCES}+ to proceed)"),
        )

    # ── add_fragment ─────────────────────────────────────
    if action == "add_fragment":
        if not fragment:
            raise ValueError("fragment is required for add_fragment")
        record.fragments.append(fragment)
        if record.phase == "sources_ready":
            record.phase = "interfering"
        if len(record.fragments) >= _IP_MIN_FRAGMENTS:
            record.phase = "saturated"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Fragment {len(record.fragments)}/{_IP_MIN_FRAGMENTS}: "
            f"'{fragment[:60]}'"
            + (" — saturated, ready to crystallize"
               if record.phase == "saturated" else ""),
        )

    # ── add_tension ──────────────────────────────────────
    if action == "add_tension":
        if tension_laws is None or not tension_description:
            raise ValueError(
                "tension_laws and tension_description are "
                "required for add_tension"
            )
        for idx in tension_laws:
            if idx not in range(len(record.source_laws)):
                raise ValueError(
                    f"tension_laws index {idx} out of range "
                    f"(have {len(record.source_laws)} sources)"
                )
        record.tensions.append({
            "between": tension_laws,
            "description": tension_description,
        })
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Tension recorded between sources "
            f"{tension_laws}: '{tension_description[:60]}'",
        )

    # ── crystallize ──────────────────────────────────────
    if action == "crystallize":
        if not name or not properties:
            raise ValueError(
                "name and properties are required for crystallize"
            )
        # Emergence test
        novel_props = [
            p for p in properties if p.get("novel", False)
        ]
        if len(novel_props) < 2:
            return _ip_status_output(
                sid, record,
                f"REJECTED: Need at least 2 novel properties, "
                f"got {len(novel_props)}. Mark properties as "
                "novel=True if they require interference.",
            )
        for p in novel_props:
            p_text = p.get("text", "(no text)")[:40]
            src_laws = p.get("source_laws", [])
            for idx in src_laws:
                if idx not in range(len(record.source_laws)):
                    return _ip_status_output(
                        sid, record,
                        f"REJECTED: Property '{p_text}' "
                        f"references nonexistent source index "
                        f"{idx} (have {len(record.source_laws)} "
                        "sources).",
                    )
            if len(src_laws) < 2:
                return _ip_status_output(
                    sid, record,
                    f"REJECTED: Novel property "
                    f"'{p_text}' traces to "
                    f"{len(src_laws)} source(s) — need 2+ for "
                    "emergence (mashup, not interference).",
                )
        record.emergent_name = name
        record.emergent_properties = properties
        record.phase = "crystallized"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Crystallized: '{name}' with "
            f"{len(properties)} properties "
            f"({len(novel_props)} novel). "
            "Emergence test passed.",
        )

    # ── add_necessity ────────────────────────────────────
    if action == "add_necessity":
        if not conclusion or not prerequisites:
            raise ValueError(
                "conclusion and prerequisites are required "
                "for add_necessity"
            )
        for p in prerequisites:
            status = p.get("status", "untested")
            _validate_enum(
                status, _IP_NECESSITY_STATUSES, "prerequisite status"
            )
        record.necessity_chains.append({
            "conclusion": conclusion,
            "prerequisites": prerequisites,
        })
        record.phase = "necessities_derived"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Necessity chain added: '{conclusion[:60]}' "
            f"with {len(prerequisites)} prerequisites. "
            f"Total chains: {len(record.necessity_chains)}",
        )

    # ── update_necessity ─────────────────────────────────
    if action == "update_necessity":
        if (
            chain_index is None
            or prereq_index is None
            or not new_status
        ):
            raise ValueError(
                "chain_index, prereq_index, and new_status "
                "are required for update_necessity"
            )
        _validate_enum(
            new_status, _IP_NECESSITY_STATUSES, "new_status"
        )
        if chain_index not in range(len(record.necessity_chains)):
            raise ValueError(
                f"chain_index {chain_index} out of range "
                f"(have {len(record.necessity_chains)} chains)"
            )
        chain = record.necessity_chains[chain_index]
        prereqs = chain["prerequisites"]
        if prereq_index not in range(len(prereqs)):
            raise ValueError(
                f"prereq_index {prereq_index} out of range "
                f"(chain has {len(prereqs)} prerequisites)"
            )
        prereqs[prereq_index]["status"] = new_status
        engine.upsert_interference(record)

        # Check chain health
        all_fail = all(
            p.get("status") == "fails" for p in prereqs
        )
        health = " — CHAIN BROKEN (all prerequisites fail)" if all_fail else ""
        return _ip_status_output(
            sid, record,
            f"Updated chain {chain_index} prereq "
            f"{prereq_index} → {new_status}{health}",
        )

    # ── stress_test ──────────────────────────────────────
    if action == "stress_test":
        if not audit_type or not audit_result:
            raise ValueError(
                "audit_type and audit_result are required "
                "for stress_test"
            )
        _validate_enum(audit_type, _IP_AUDIT_TYPES, "audit_type")
        record.audit_results[audit_type] = audit_result
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Audit recorded: {audit_type}. "
            f"Audits: {len(record.audit_results)}/4 "
            f"({', '.join(record.audit_results.keys())})",
        )

    # ── finalize ─────────────────────────────────────────
    if action == "finalize":
        if not verdict:
            raise ValueError("verdict is required for finalize")
        _validate_enum(verdict, _IP_VERDICTS, "verdict")
        record.verdict = verdict
        record.phase = "stress_tested"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid, record,
            f"Verdict: {verdict}. "
            f"Concept '{record.emergent_name}' "
            + ("survives stress testing. Ready to recurse or "
               "export." if verdict == "survives"
               else f"verdict={verdict}. Consider revising or "
               "accepting limitations."),
        )

    # ── recurse ──────────────────────────────────────────
    if action == "recurse":
        if not new_domain or not concept_as_law:
            raise ValueError(
                "new_domain and concept_as_law are required "
                "for recurse"
            )
        new_pid = uuid.uuid4().hex[:12]
        new_record = InterferenceRecord(
            protocol_id=new_pid,
            phase="domain_set",
            iteration=record.iteration + 1,
            target_domain=new_domain,
            source_laws=[{
                "domain": f"[emerged] {record.emergent_name}",
                "law": concept_as_law,
                "isomorphism": (
                    f"Emergent concept from iteration "
                    f"{record.iteration}"
                ),
            }],
        )
        engine.upsert_interference(new_record)
        return _ip_status_output(
            sid, new_record,
            f"Recursion: new protocol {new_pid} (iter "
            f"{new_record.iteration}) for domain "
            f"'{new_domain}'. Pre-loaded with concept "
            f"'{record.emergent_name}' as source #0. "
            "Add more sources and suspended frames.",
        )

    # Should not reach here due to _validate_enum
    raise ValueError(f"Unhandled action: {action}")


# ── Tool: Interference Protocol State ────────────────────────


async def think_interfere_state(
    session_id: str,
    protocol_id: str,
) -> str:
    """Query the full state of an Interference Protocol session.

    Returns all accumulated state: phase, domain, suspended frames,
    source laws, fragments, tensions, emergent concept, necessity
    chains, and audit results.

    Args:
        session_id: Thinking session ID.
        protocol_id: Protocol ID to query.

    Returns:
        Full state dump in compact text.
    """
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    record = engine.get_interference(protocol_id)
    if record is None:
        raise ValueError(f"Protocol '{protocol_id}' not found.")

    lines = [
        f"Session: {session_id} | Protocol: {protocol_id}",
        f"Phase: {record.phase} | Iter: {record.iteration}"
        f" | Domain: {record.target_domain}",
    ]

    if record.suspended_frames:
        lines.append(
            f"\n## Suspended Frames ({len(record.suspended_frames)})"
        )
        for i, f in enumerate(record.suspended_frames):
            lines.append(f"  {i}. {f}")

    if record.source_laws:
        lines.append(
            f"\n## Source Laws ({len(record.source_laws)})"
        )
        for i, s in enumerate(record.source_laws):
            lines.append(
                f"  {i}. [{s['domain']}] {s['law']}"
            )
            lines.append(
                f"     Isomorphism: {s['isomorphism']}"
            )

    if record.fragments:
        lines.append(
            f"\n## Fragments ({len(record.fragments)})"
        )
        for i, frag in enumerate(record.fragments):
            lines.append(f"  {i}. {frag[:120]}")

    if record.tensions:
        lines.append(
            f"\n## Tensions ({len(record.tensions)})"
        )
        for t in record.tensions:
            lines.append(
                f"  Between sources {t['between']}: "
                f"{t['description'][:100]}"
            )

    if record.emergent_name:
        lines.append(f"\n## Emergent Concept: {record.emergent_name}")
        for i, p in enumerate(record.emergent_properties):
            novel = " [NOVEL]" if p.get("novel") else ""
            srcs = p.get("source_laws", [])
            lines.append(
                f"  {i}. {p['text'][:100]}{novel} (sources: {srcs})"
            )

    if record.necessity_chains:
        lines.append(
            f"\n## Necessity Chains ({len(record.necessity_chains)})"
        )
        for ci, chain in enumerate(record.necessity_chains):
            lines.append(f"  Chain {ci}: {chain['conclusion'][:80]}")
            for pi, prereq in enumerate(chain["prerequisites"]):
                status = prereq.get("status", "untested")
                lines.append(
                    f"    {pi}. [{status}] {prereq['claim'][:80]}"
                )

    if record.audit_results:
        lines.append(
            f"\n## Audit Results ({len(record.audit_results)})"
        )
        for atype, aresult in record.audit_results.items():
            lines.append(f"  {atype}: {aresult[:120]}")

    if record.verdict:
        lines.append(f"\nVerdict: {record.verdict}")

    return "\n".join(lines)
