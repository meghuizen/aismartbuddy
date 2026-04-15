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
    DebugRecord,
    DecisionRecord,
    InquiryRecord,
    InterferenceRecord,
    ModelRecord,
    MonitorRecord,
    RuleItem,
    RuleProfile,
    ThinkingEngine,
    ThoughtNode,
    ValidationAssessment,
)
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import get_session_manager, size_guarded

if TYPE_CHECKING:
    from aismartbuddy.session import SessionInfo, SessionManager

# ── Valid enum values ────────────────────────────────────────

_MODEL_NAMES = frozenset(
    {
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
    }
)

_DEBUG_APPROACHES = frozenset(
    {
        "binary_search",
        "reverse_engineering",
        "divide_conquer",
        "backtracking",
        "cause_elimination",
        "program_slicing",
    }
)

_ARGUMENT_TYPES = frozenset(
    {
        "thesis",
        "antithesis",
        "synthesis",
        "objection",
        "rebuttal",
    }
)

_SCIENCE_STAGES = frozenset(
    {
        "observation",
        "question",
        "hypothesis",
        "experiment",
        "analysis",
        "conclusion",
        "iteration",
    }
)

_MONITOR_STAGES = frozenset(
    {
        "knowledge-assessment",
        "planning",
        "execution",
        "monitoring",
        "evaluation",
        "reflection",
        # items[] strict-form records use this stage value for one-shot
        # self-assessment (distinct from the iterative monitoring stages above).
        "self-assess",
    }
)

_DECISION_STAGES = frozenset(
    {
        "problem-definition",
        "options",
        "criteria",
        "evaluation",
        "analysis",
        "recommendation",
    }
)

_DECISION_TYPES = frozenset(
    {
        "expected-utility",
        "multi-criteria",
        "maximin",
        "minimax-regret",
        "satisficing",
    }
)

_KNOWLEDGE_LEVELS = frozenset(
    {
        "expert",
        "proficient",
        "familiar",
        "basic",
        "minimal",
        "none",
    }
)

_SUGGESTED_ASSESSMENTS = frozenset(
    {
        "knowledge",
        "claim",
        "reasoning",
        "overall",
    }
)
_RULE_ACTIONS = frozenset(
    {
        "create_profile",
        "add_rules_batch",
        "update_weights_batch",
        "deprecate_rules_batch",
        "list_profiles",
        "show_profile",
        "bind_profile",
        "pin_snapshot",
        "resolve_conflicts",
    }
)
_RULE_KINDS = frozenset({"hard", "soft"})
_RULE_STATUSES = frozenset({"active", "superseded"})
_VALIDATION_STATUSES = frozenset(
    {
        "satisfies",
        "violates",
        "uncertain",
        "not_applicable",
    }
)


# ── Helpers ──────────────────────────────────────────────────


def _get_or_create_think_session(
    session_id: str | None,
    ctx: _MCPContext | None = None,
) -> tuple[SessionManager, SessionInfo]:
    """Return an existing think session or auto-create one.

    If session_id is provided, accepts either a direct think session_id OR
    a parent session_id whose backends include "think". Identity of the
    caller is NOT re-checked (session_id acts as capability).

    If None/empty, resolves caller identity via `resolve_identity(ctx, ...)`
    and creates a NEW standalone think session. Auto-creation does NOT happen
    inside an existing parent — if you want a think backend in a parent,
    pass backends=['think', ...] to session_create up front.
    """
    mgr = get_session_manager()
    if session_id:
        # resolve_backend_session handles both parent-id and direct-child
        # cases; raises if the parent has no think backend.
        info = mgr.resolve_backend_session(session_id, "think")
        return mgr, info
    # Auto-create with caller-scoped identity (standalone think session)
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


def _rule_bindings_from_profile_ids(
    engine: ThinkingEngine,
    rule_profile_ids: list[str] | None,
) -> list[dict]:
    """Validate explicit rule profile ids and convert to bindings."""
    bindings: list[dict] = []
    seen: set[str] = set()
    for profile_id in rule_profile_ids or []:
        if profile_id in seen:
            continue
        if engine.get_rule_profile(profile_id) is None:
            raise ValueError(f"Rule profile '{profile_id}' not found")
        seen.add(profile_id)
        bindings.append({"profile_id": profile_id, "snapshot_id": None})
    return bindings


def _format_rule_validation_summary(summary: dict) -> str:
    """Render a compact human-readable validation summary."""
    if not summary.get("bindings"):
        return "Rule validation: no bound profiles"
    lines = [
        "Rule validation:",
        (f"- Bound profiles: {', '.join(b['profile_id'] for b in summary['bindings'])}"),
    ]
    if summary.get("latest_validation_id"):
        lines.append(
            f"- Latest validation: {summary['latest_validation_id']}"
            f" | hard_gates={'pass' if summary['passed_hard_gates'] else 'fail'}"
            + (
                f" | weighted_score={summary['weighted_score']:.1f}"
                if summary.get("weighted_score") is not None
                else ""
            )
        )
    if summary.get("hard_failures"):
        lines.append(f"- Hard failures: {', '.join(summary['hard_failures'])}")
    if summary.get("uncovered_rules"):
        lines.append(
            f"- Uncovered rules: {', '.join(summary['uncovered_rules'][:8])}"
            + (" ..." if len(summary["uncovered_rules"]) > 8 else "")
        )
    if summary.get("conflicts"):
        lines.append(f"- Unresolved conflicts: {', '.join(summary['conflicts'])}")
    if summary.get("nuance_notes"):
        lines.append(f"- Nuance notes: {' | '.join(summary['nuance_notes'][:3])}")
    return "\n".join(lines)


async def _materialize_rule_graph(
    session_id: str | None,
    *,
    profile: RuleProfile | None = None,
    rules: list[RuleItem] | None = None,
    validation=None,
) -> None:
    """Best-effort graph materialization for rules and validations."""
    if not session_id:
        return
    mgr = get_session_manager()
    if session_id not in getattr(mgr, "_parent_sessions", {}):
        return
    try:
        from aismartbuddy.tools.graph import graph_knowledge_add, graph_knowledge_relate

        if profile is not None:
            profile_node = f"rule_profile:{profile.id}"
            await graph_knowledge_add(
                session_id=session_id,
                entity=profile_node,
                entity_type="concept",
                properties={
                    "name": profile.name,
                    "description": profile.description,
                    "rules": len(profile.rules),
                },
                confidence=1.0,
                source="think_rules",
            )
            for rule in rules or profile.rules:
                rule_node = f"rule:{rule.id}"
                await graph_knowledge_add(
                    session_id=session_id,
                    entity=rule_node,
                    entity_type="fact",
                    properties={
                        "text": rule.text,
                        "weight": rule.weight,
                        "kind": rule.kind,
                        "status": rule.status,
                    },
                    confidence=1.0,
                    source="think_rules",
                )
                await graph_knowledge_relate(
                    session_id=session_id,
                    from_name=rule_node,
                    to_name=profile_node,
                    relation="part_of",
                    weight=1.0,
                    justification="rule belongs to profile",
                    source="think_rules",
                )
                for conflict_id in rule.conflicts_with:
                    try:
                        await graph_knowledge_relate(
                            session_id=session_id,
                            from_name=rule_node,
                            to_name=f"rule:{conflict_id}",
                            relation="contradicts",
                            weight=1.0,
                            justification="declared rule conflict",
                            source="think_rules",
                        )
                    except Exception:
                        continue
        if validation is not None:
            v_node = f"validation:{validation.id}"
            await graph_knowledge_add(
                session_id=session_id,
                entity=v_node,
                entity_type="insight",
                properties={
                    "subject_id": validation.subject_id,
                    "subject_kind": validation.subject_kind,
                    "weighted_score": validation.weighted_score,
                    "passed_hard_gates": validation.passed_hard_gates,
                },
                confidence=1.0,
                source="think_validate",
            )
            target = f"{validation.subject_kind}:{validation.subject_id}"
            try:
                await graph_knowledge_relate(
                    session_id=session_id,
                    from_name=v_node,
                    to_name=target,
                    relation="applies_to",
                    weight=1.0,
                    justification="validation target",
                    source="think_validate",
                )
            except Exception:
                pass
            for binding in validation.rule_bindings:
                try:
                    await graph_knowledge_relate(
                        session_id=session_id,
                        from_name=v_node,
                        to_name=f"rule_profile:{binding['profile_id']}",
                        relation="derived_from",
                        weight=1.0,
                        justification="validation used rule profile",
                        source="think_validate",
                    )
                except Exception:
                    continue
    except Exception:
        return


def _parent_graph_session_id(session_id: str | None) -> str | None:
    """Return the parent session id only when it exposes graph backend state."""
    if not session_id:
        return None
    mgr = get_session_manager()
    if session_id in getattr(mgr, "_parent_sessions", {}):
        return session_id
    return None


async def _materialize_subject_rule_bindings(
    engine: ThinkingEngine,
    session_id: str | None,
    *,
    subject_kind: str,
    subject_id: str,
    subject_label: str,
    bindings: list[dict],
    source: str,
) -> None:
    """Best-effort graph materialization for a rule-bound subject."""
    parent_session_id = _parent_graph_session_id(session_id)
    if not parent_session_id or not bindings:
        return
    try:
        from aismartbuddy.tools.graph import graph_knowledge_add, graph_knowledge_relate

        subject_node = f"{subject_kind}:{subject_id}"
        await graph_knowledge_add(
            session_id=parent_session_id,
            entity=subject_node,
            entity_type="insight" if subject_kind != "holon" else "entity",
            properties={"label": subject_label[:200], "subject_kind": subject_kind},
            confidence=1.0,
            source=source,
        )

        profiles_seen: set[str] = set()
        rules_seen: set[str] = set()
        for binding in bindings:
            profile_id = binding["profile_id"]
            if profile_id in profiles_seen:
                continue
            profiles_seen.add(profile_id)
            profile = engine.get_rule_profile(profile_id)
            if profile is None:
                continue
            await _materialize_rule_graph(parent_session_id, profile=profile)
            await graph_knowledge_relate(
                session_id=parent_session_id,
                from_name=subject_node,
                to_name=f"rule_profile:{profile_id}",
                relation="requires",
                weight=1.0,
                justification="subject is governed by this rule profile",
                source=source,
            )

        for profile_id, _, rule in engine.get_effective_rules(bindings):
            if rule.id in rules_seen:
                continue
            rules_seen.add(rule.id)
            try:
                await graph_knowledge_relate(
                    session_id=parent_session_id,
                    from_name=subject_node,
                    to_name=f"rule:{rule.id}",
                    relation="requires",
                    weight=max(0.1, float(rule.weight)),
                    justification=f"subject is governed by rule profile {profile_id}",
                    source=source,
                )
            except Exception:
                continue
    except Exception:
        return


# ── Thought Graph constants ──────────────────────────────────

_GRAPH_ACTIONS = frozenset(
    {
        "think",
        "branch",
        "revise",
        "synthesize",
    }
)

_VALIDATE_CHECK_TYPES = frozenset(
    {
        "coverage",
        "contradictions",
        "gaps",
        "leaps",
        "completeness",
        "dependencies",
    }
)

_VALIDATE_RESULTS = frozenset(
    {
        "pass",
        "fail",
        "warning",
    }
)

_DELEGATE_ACTIONS = frozenset(
    {
        "package",
        "receive",
    }
)


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
    children: list[dict] | None = None,
    expected_children: int | None = None,
    min_children: int | None = None,
    rule_profile_ids: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Thought graph — structured thinking with progressive complexity.

    Every thought is a node in a graph. Supports simple sequential chains,
    hierarchical tree decomposition, multi-tree forests, revision with
    history, and synthesis.

    KEEP THOUGHTS CONCISE. One thought = one move (a claim, an observation,
    a sub-goal, a conclusion). Aim for 1–3 sentences per node, not paragraphs.
    If a thought is becoming an essay, use action="branch" and split into
    children. Long stories collapse to noise; short nodes stay queryable.

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
        children: Optional list of child specs to create atomically with the
            parent in one call (one round trip instead of N+1). Each child:
            {thought: str, metadata?: dict, action?: str}. Returns parent_id +
            child_ids[]. Use with action="branch" for decomposition batching.
        expected_children: Planning horizon — declare how many children you
            intend to create. When action="synthesize" runs later, the tool
            warns if the actual count differs.

    Returns:
        Compact status with node position and tree structure.
    """
    _validate_enum(action, _GRAPH_ACTIONS, "action")

    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
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
            f"Tree '{tree_id}' already has a root. Use parent_id to add nodes to an existing tree."
        )
    else:
        effective_tree_id = tree_id or uuid.uuid4().hex[:10]

    parent_meta = metadata or {}
    if expected_children is not None:
        parent_meta = {**parent_meta, "expected_children": int(expected_children)}

    parent_node = ThoughtNode(
        id=nid,
        tree_id=effective_tree_id,
        content=thought,
        action=action,
        parent_id=parent_id,
        depends_on=depends_on or [],
        refs=refs or [],
        rule_bindings=_rule_bindings_from_profile_ids(engine, rule_profile_ids),
        depth=depth,
        metadata=parent_meta,
    )

    # ── Batch path: parent + children atomically ─────────
    child_ids: list[str] = []
    if children:
        if min_children is not None and len(children) < min_children:
            raise ValueError(
                f"think_graph(action='{action}', children=[...]) received "
                f"{len(children)} children but min_children={min_children}. "
                "Quantity-before-convergence rule rejects below threshold."
            )
        _, child_ids = engine.add_node_with_children(parent_node, children)
    else:
        engine.add_node(parent_node)

    # Synthesize warning when expected_children mismatches actual
    synth_warning = ""
    if action == "synthesize" and parent_id:
        parent = engine.get_node(parent_id)
        if parent and parent.metadata:
            exp = parent.metadata.get("expected_children")
            if exp is not None:
                actual = len(parent.children)
                if actual != int(exp):
                    synth_warning = (
                        f"\n⚠ Synthesis: parent expected {exp} children, found {actual}."
                    )

    # Build output
    siblings = 0
    if parent_id:
        parent = engine.get_node(parent_id)
        if parent:
            siblings = len(parent.children) - 1  # exclude self

    path_str = _build_path_string(engine, nid)
    parts = [
        f"Session: {sid} | Tree: {effective_tree_id} | Node: {nid}",
        (f"Action: {action} | Depth: {depth} | Children: {len(child_ids)} | Siblings: {siblings}"),
    ]
    if parent_id:
        parts.append(f"Parent: {parent_id} | Path: {path_str}")
    if child_ids:
        parts.append(f"Batch: {len(child_ids)} children created")
        parts.append("Children: " + ", ".join(child_ids))
    parts.append("Status: added" + synth_warning)
    await _materialize_subject_rule_bindings(
        engine,
        session_id,
        subject_kind="thought",
        subject_id=nid,
        subject_label=thought,
        bindings=parent_node.rule_bindings,
        source="think_graph",
    )
    return "\n".join(parts)


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
            context_lines.append(f"{indent}> {marker}{n.content[:80]}")

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
            f"Context depth: {len(path)} nodes\n" + "\n".join(context_lines)
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
    decision_statement: str = "",
    options: list[dict] | None = None,
    analysis_type: str = "multi-criteria",
    stage: str = "recommendation",
    decision_id: str = "",
    iteration: int = 1,
    next_stage_needed: bool = False,
    session_id: str | None = None,
    criteria: list[dict] | None = None,
    evaluations: list[dict] | None = None,
    recommendation: str | None = None,
    items: list[dict] | None = None,
    rule_profile_ids: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Multi-criteria decision analysis (1..N decisions).

    Use when: a decision has 2+ defensible options + explicit criteria.
    Do NOT use when: the answer is obvious (skip; just decide).

    items[]: STRICT batch — each item: id, decision_statement, options[≥2],
      criteria[≥1] (each {name, weight}), evaluations[], recommendation.
      Server REJECTS items missing any required field.
    Single-form: backward-compat staged form (problem-definition → options
      → criteria → evaluation → analysis → recommendation).

    Args:
      items: STRICT — list of decision items as above.
      decision_statement, options, analysis_type, stage, decision_id,
        iteration, next_stage_needed, criteria, evaluations, recommendation:
        single-form fields.
      session_id: omit to auto-create.

    Returns: decision ids[] in items[] mode, or single-form status.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Items[] strict batch path ────────────────────────────
    if items is not None:
        from aismartbuddy.tools import validate_items

        def _check_options(o: object) -> str | None:
            if not isinstance(o, list) or len(o) < 2:
                return "must be a list with at least 2 options"
            return None

        def _check_criteria(c: object) -> str | None:
            if not isinstance(c, list) or not c:
                return "must be a non-empty list of {name, weight}"
            for j, x in enumerate(c):
                if not isinstance(x, dict) or not x.get("name"):
                    return f"criteria[{j}] missing 'name'"
                if "weight" not in x:
                    return f"criteria[{j}] missing 'weight'"
            return None

        validate_items(
            items,
            required=["decision_statement", "options", "criteria", "recommendation"],
            tool="think_decide",
            item_validators={
                "options": _check_options,
                "criteria": _check_criteria,
            },
        )

        ids: list[str] = []
        bindings = _rule_bindings_from_profile_ids(engine, rule_profile_ids)
        with engine.state_lock:
            for it in items:
                rec = DecisionRecord(
                    decision_id=it["id"],
                    statement=it["decision_statement"],
                    options=list(it["options"]),
                    analysis_type=it.get("analysis_type", "multi-criteria"),
                    stage="recommendation",
                    iteration=1,
                    criteria=list(it["criteria"]),
                    evaluations=list(it.get("evaluations") or []),
                    recommendation=it["recommendation"],
                    rule_bindings=list(bindings),
                )
                engine.upsert_decision(rec)
                ids.append(it["id"])
        for it in items:
            await _materialize_subject_rule_bindings(
                engine,
                session_id,
                subject_kind="decision",
                subject_id=it["id"],
                subject_label=it["decision_statement"],
                bindings=bindings,
                source="think_decide",
            )

        return (
            f"Session: {info.session_id} | Decisions: {len(ids)}\n"
            f"IDs: {', '.join(ids)}\n"
            "Status: decided"
        )

    # ── Single-form backward-compat path ────────────────────
    _validate_enum(analysis_type, _DECISION_TYPES, "analysis_type")
    _validate_enum(stage, _DECISION_STAGES, "stage")
    if not decision_statement or not options or not decision_id:
        raise ValueError("single-form requires decision_statement, options, decision_id")

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
        rule_bindings=_rule_bindings_from_profile_ids(engine, rule_profile_ids),
    )
    engine.upsert_decision(record)
    await _materialize_subject_rule_bindings(
        engine,
        session_id,
        subject_kind="decision",
        subject_id=decision_id,
        subject_label=decision_statement,
        bindings=record.rule_bindings,
        source="think_decide",
    )

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
    problem: str = "",
    session_id: str | None = None,
    steps: list[str] | None = None,
    reasoning: str | None = None,
    conclusion: str | None = None,
    items: list[dict] | None = None,
    auto_graph: bool = False,
    rule_profile_ids: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Apply a mental model to 1..N problems. Call FIRST.

    Use when: starting an analysis (reasoning NOT yet done); decomposing N
    sub-problems with the same model; you want the schema to FORCE structure.
    Do NOT use when: mid-elaboration (use think_graph); you already finished
    the reasoning and just want to record it (that's ceremony — skip).
    For assay-heavy data, import/profile first, then scaffold:
    `sql_import` / `sql_import_batch` → `data_profile` / `data_anomalies` →
    `extract_findings_from_sql` → `think_model`.
    Separate measured signal from inferred mechanism. Use `items[]` and
    `refs/connects_to` when you need an audit trail across later claims,
    findings, and graph materialization.

    Two forms:
      items[]: STRICT batch — each item must have id/problem/steps/reasoning/
        conclusion. Server REJECTS lazy items with the failing field name.
        Optional connects_to (list of other item ids) becomes auto_graph edges.
      single-item: backward-compat flexible form (problem/steps/reasoning/
        conclusion all optional). Use only for mid-analysis ad-hoc model
        application; prefer items[] at analysis START.

    Models: first_principles, opportunity_cost, error_propagation, rubber_duck,
    pareto_principle, assumptions_xray, fishbone, value_of_info, swot,
    pre_mortem, design_review, complexity, root_cause.

    Good fits for omics / assay interpretation:
    - measurement-boundary review
    - confounder x-ray
    - signal vs mechanism decomposition
    - cross-domain bridge mapping
    - intervention coverage / loop-breaking coverage

    Args:
      model_name: which mental model to apply.
      items: STRICT — each item dict needs id, problem, steps[≥1], reasoning,
        conclusion; optional connects_to[], metadata{}.
      problem, steps, reasoning, conclusion: single-item form fields.
      auto_graph: when True + parent session has graph backend, materialise
        each item as a KnowledgeNode + connects_to edges in one round trip.
      rule_profile_ids: optional reusable rule profiles to bind to each record.
      session_id: omit to auto-create think session.

    Returns: item_ids[] (+ graph node count if auto_graph) or single-item status.
    """
    _validate_enum(model_name, _MODEL_NAMES, "model_name")

    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Items[] strict batch path ────────────────────────────
    if items is not None:
        from aismartbuddy.tools import materialize_auto_graph, validate_items

        validate_items(
            items,
            required=["problem", "steps", "reasoning", "conclusion"],
            tool="think_model",
        )
        from aismartbuddy.tools import collect_item_refs

        item_ids: list[str] = []
        bindings = _rule_bindings_from_profile_ids(engine, rule_profile_ids)
        with engine.state_lock:
            for it in items:
                rec = ModelRecord(
                    model_name=model_name,
                    problem=it["problem"],
                    steps=list(it["steps"]),
                    reasoning=it["reasoning"],
                    conclusion=it["conclusion"],
                    record_id=it["id"],
                    refs=collect_item_refs(it),
                    rule_bindings=list(bindings),
                )
                engine.add_model(rec)
                item_ids.append(it["id"])
        for it in items:
            await _materialize_subject_rule_bindings(
                engine,
                session_id,
                subject_kind="model",
                subject_id=it["id"],
                subject_label=it["problem"],
                bindings=bindings,
                source="think_model",
            )

        graph_count = 0
        if auto_graph:
            if not session_id:
                raise ValueError(
                    "auto_graph requires an explicit unified session_id from "
                    "session_create(backends=['think','graph'])."
                )
            graph_count = await materialize_auto_graph(
                session_id,
                items,
                source_tag=f"think_model:{model_name}",
                entity_type="concept",
                description_field="conclusion",
            )

        out = [
            f"Session: {info.session_id} | Model: {model_name} | Items: {len(item_ids)}",
            f"Item IDs: {', '.join(item_ids)}",
        ]
        if auto_graph:
            out.append(f"Graph nodes created: {graph_count}")
        out.append("Status: scaffolded")
        return "\n".join(out)

    # ── Single-item backward-compat path ─────────────────────
    record = ModelRecord(
        model_name=model_name,
        problem=problem,
        steps=steps or [],
        reasoning=reasoning or "",
        conclusion=conclusion or "",
        record_id=uuid.uuid4().hex[:10] if rule_profile_ids else "",
        rule_bindings=_rule_bindings_from_profile_ids(engine, rule_profile_ids),
    )
    engine.add_model(record)

    parts = [
        f"Session: {info.session_id}",
        f"Model: {model_name}",
        f"Steps: {len(steps or [])}",
    ]
    header = " | ".join(parts)

    lines = [header]
    if record.record_id:
        lines.append(f"Record ID: {record.record_id}")
    if not steps and not conclusion:
        # No steps yet — return framework guidance to help the AI
        lines.append(_MODEL_GUIDANCE[model_name])
        lines.append("Status: framework loaded — apply the steps above")
    elif conclusion:
        lines.append(f"Conclusion: {conclusion[:200]}")
    else:
        lines.append("Status: applied")
    await _materialize_subject_rule_bindings(
        engine,
        session_id,
        subject_kind="model",
        subject_id=record.record_id or uuid.uuid4().hex[:8],
        subject_label=problem or model_name,
        bindings=record.rule_bindings,
        source="think_model",
    )
    return "\n".join(lines)


# ── Tool: Debugging Approach ─────────────────────────────────


async def think_debug(
    approach_name: str = "binary_search",
    issue: str = "",
    session_id: str | None = None,
    steps: list[str] | None = None,
    findings: str | None = None,
    resolution: str | None = None,
    items: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Apply systematic debugging (1..N issues).

    Use when: technical issue needs methodical investigation. Approaches:
    binary_search, reverse_engineering, divide_conquer, backtracking,
    cause_elimination, program_slicing.

    items[]: STRICT batch — each: id, approach, issue, steps[≥1], findings,
      resolution. Lets you record N parallel debugging investigations atomically.
    Single-form: backward-compat — record one approach + issue + optional fields.

    Args:
      items: STRICT — list of debug-record items as above.
      approach_name, issue, steps, findings, resolution: single-form fields.
      session_id: omit to auto-create.

    Returns: debug ids[] (items[] mode) or single status.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Items[] strict batch path ────────────────────────────
    if items is not None:
        from aismartbuddy.tools import validate_items

        validate_items(
            items,
            required=["approach", "issue", "steps", "findings", "resolution"],
            tool="think_debug",
        )
        for i, it in enumerate(items):
            if it["approach"] not in _DEBUG_APPROACHES:
                raise ValueError(
                    f"think_debug.items[{i}].approach '{it['approach']}' "
                    f"invalid. Valid: {sorted(_DEBUG_APPROACHES)}"
                )

        from aismartbuddy.tools import collect_item_refs

        ids: list[str] = []
        with engine.state_lock:
            for it in items:
                rec = DebugRecord(
                    approach_name=it["approach"],
                    issue=it["issue"],
                    steps=list(it["steps"]),
                    findings=it["findings"],
                    resolution=it["resolution"],
                    record_id=it["id"],
                    refs=collect_item_refs(it),
                )
                engine.add_debug(rec)
                ids.append(it["id"])

        return (
            f"Session: {info.session_id} | Debugs: {len(ids)}\n"
            f"IDs: {', '.join(ids)}\n"
            "Status: debugged"
        )

    # ── Single-form backward-compat ─────────────────────────
    _validate_enum(approach_name, _DEBUG_APPROACHES, "approach_name")
    if not issue:
        raise ValueError("single-form requires 'issue'")
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
    claim: str = "",
    premises: list[str] | None = None,
    conclusion: str = "",
    argument_type: str = "thesis",
    confidence: float = 0.5,
    next_argument_needed: bool = False,
    session_id: str | None = None,
    argument_id: str | None = None,
    responds_to: str | None = None,
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
    strengths: list[str] | None = None,
    weaknesses: list[str] | None = None,
    chain: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """Dialectical reasoning through thesis, antithesis, synthesis.

    Build chains of arguments that support, contradict, or synthesize each other.
    Types: thesis, antithesis, synthesis, objection, rebuttal.

    Single mode: pass claim/premises/conclusion/argument_type for one argument.

    Batch mode: pass `chain=[{type, claim, premises, conclusion, confidence,
    responds_to_index?, strengths?, weaknesses?, supports?, contradicts?}, ...]`
    to submit a full thesis→antithesis→synthesis dialectic in one call.
    Sequential — entries processed in submission order. responds_to_index
    references a prior entry in this chain (0-based).

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
        chain: Batch mode — list of argument dicts. Returns chain_id +
            argument_ids[]. KEEPS structural validation per-entry.

    Returns:
        Single mode: compact status with argumentation chain progress.
        Batch mode: chain_id + ordered list of argument_ids.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Batch chain mode ─────────────────────────────────
    if chain is not None:
        if len(chain) < 1:
            raise ValueError("chain must be non-empty")
        # Validate every entry up front
        for i, entry in enumerate(chain):
            etype = entry.get("type") or entry.get("argument_type")
            if not etype:
                raise ValueError(f"chain[{i}] missing 'type'")
            _validate_enum(etype, _ARGUMENT_TYPES, f"chain[{i}].type")
            if not entry.get("claim"):
                raise ValueError(f"chain[{i}] missing 'claim'")
            if not entry.get("conclusion"):
                raise ValueError(f"chain[{i}] missing 'conclusion'")
            if not isinstance(entry.get("premises"), list):
                raise ValueError(f"chain[{i}] 'premises' must be a list[str]")
            if not entry["premises"]:
                raise ValueError(f"chain[{i}] 'premises' must be non-empty")

        # Process under one engine state lock so the chain is atomic
        ids: list[str] = []
        with engine.state_lock:
            chain_id = uuid.uuid4().hex[:8]
            for i, entry in enumerate(chain):
                aid = entry.get("argument_id") or uuid.uuid4().hex[:8]
                rt_idx = entry.get("responds_to_index")
                rt = None
                if rt_idx is not None:
                    if not (0 <= int(rt_idx) < i):
                        raise ValueError(
                            f"chain[{i}].responds_to_index={rt_idx} must reference a prior entry"
                        )
                    rt = ids[int(rt_idx)]
                etype = entry.get("type") or entry.get("argument_type")
                conf = max(0.0, min(1.0, float(entry.get("confidence", 0.5))))
                rec = ArgRecord(
                    argument_id=aid,
                    claim=entry["claim"],
                    premises=list(entry["premises"]),
                    conclusion=entry["conclusion"],
                    argument_type=etype,
                    confidence=conf,
                    responds_to=rt,
                    supports=list(entry.get("supports") or []),
                    contradicts=list(entry.get("contradicts") or []),
                    strengths=list(entry.get("strengths") or []),
                    weaknesses=list(entry.get("weaknesses") or []),
                )
                engine.add_argument(chain_id, rec)
                ids.append(aid)
        return (
            f"Session: {info.session_id} | Chain: {chain_id}"
            f" | Batch: {len(ids)} arguments\n"
            f"Arg IDs: {', '.join(ids)}\n"
            "Status: dialectic batch applied"
        )

    # ── Single argument mode (existing) ──────────────────
    _validate_enum(argument_type, _ARGUMENT_TYPES, "argument_type")
    confidence = max(0.0, min(1.0, confidence))
    if not claim:
        raise ValueError("claim is required for single-argument mode")
    if not premises:
        raise ValueError("premises are required for single-argument mode")
    if not conclusion:
        raise ValueError("conclusion is required for single-argument mode")

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


# ── Tool: Scientific Method ──────────────────────────────────


_MIN_FALSIFIABILITY_CHARS = 20


def _validate_hypothesis_dict(h: dict) -> str | None:
    """Per-item hypothesis validator. Returns None on OK, error string otherwise."""
    if not isinstance(h, dict):
        return "must be a dict with statement/variables/assumptions/confidence/falsifiability"
    if not h.get("statement"):
        return "missing 'statement'"
    vars_ = h.get("variables")
    if not isinstance(vars_, list) or not vars_:
        return "'variables' must be non-empty list of {name, role}"
    for j, v in enumerate(vars_):
        if not isinstance(v, dict) or not v.get("name") or not v.get("role"):
            return f"variables[{j}] missing name/role"
        if v["role"] not in ("independent", "dependent", "controlled"):
            return f"variables[{j}].role must be independent|dependent|controlled"
    if not isinstance(h.get("assumptions"), list) or not h["assumptions"]:
        return "'assumptions' must be non-empty list"
    if "confidence" not in h:
        return "missing 'confidence' (0.0-1.0)"
    f = h.get("falsifiability") or ""
    if len(f) < _MIN_FALSIFIABILITY_CHARS:
        return (
            f"'falsifiability' must be ≥ {_MIN_FALSIFIABILITY_CHARS} chars "
            "(state a SPECIFIC observation that proves the hypothesis WRONG)"
        )
    return None


async def think_science(
    stage: str = "hypothesis",
    inquiry_id: str = "",
    iteration: int = 1,
    next_stage_needed: bool = False,
    session_id: str | None = None,
    observation: str | None = None,
    question: str | None = None,
    hypothesis: dict | None = None,
    experiment: dict | None = None,
    analysis: str | None = None,
    conclusion: str | None = None,
    items: list[dict] | None = None,
    auto_graph: bool = False,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Generate falsifiable hypotheses (1..N). Call FIRST.

    Use when: claim that needs testing; multiple competing hypotheses to record.
    Do NOT use when: post-hoc result logging (use think_graph).
    For biology or assay-heavy interpretation, use this to force competing
    hypotheses, explicit falsifiability criteria, and missing-data tests
    after you have profiled the imported table. Prefer multiple `items[]`
    entries over a single favorite narrative.

    items[]: STRICT batch — each item: id, observation, question, hypothesis
      {statement, variables[{name, role∈{independent,dependent,controlled}}],
       assumptions[≥1], confidence, falsifiability ≥ 20 chars}.
      Server REJECTS items where falsifiability is short or variables/assumptions
      are missing.
    Single-stage: backward-compat staged form (observation → hypothesis →
      experiment → analysis → conclusion). Use mid-iteration.

    Args:
      items: STRICT — list of hypothesis items as above.
      auto_graph: when True + parent session has graph backend, materialise
        each item as a KnowledgeNode (entity_type=question).
      stage / inquiry_id / iteration / next_stage_needed: single-form fields.
      observation, question, hypothesis, experiment, analysis, conclusion:
        single-form payload.
      session_id: omit to auto-create.

    Returns: hypothesis_ids[] in items[] mode, or single-stage status.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Items[] strict batch path ────────────────────────────
    if items is not None:
        from aismartbuddy.tools import materialize_auto_graph, validate_items

        validate_items(
            items,
            required=["observation", "question", "hypothesis"],
            tool="think_science",
            item_validators={"hypothesis": _validate_hypothesis_dict},
        )

        ids: list[str] = []
        with engine.state_lock:
            for it in items:
                rec = InquiryRecord(
                    inquiry_id=it["id"],
                    stage="hypothesis",
                    iteration=1,
                    observation=it["observation"],
                    question=it["question"],
                    hypothesis=it["hypothesis"],
                )
                engine.upsert_inquiry(rec)
                ids.append(it["id"])

        graph_count = 0
        if auto_graph:
            if not session_id:
                raise ValueError(
                    "auto_graph requires explicit unified session_id from "
                    "session_create(backends=['think','graph'])."
                )
            # Build description from hypothesis.statement
            normalized = [{**it, "_desc": it["hypothesis"]["statement"]} for it in items]
            graph_count = await materialize_auto_graph(
                session_id,
                normalized,
                source_tag="think_science",
                entity_type="question",
                description_field="_desc",
            )

        out = [
            f"Session: {info.session_id} | Hypotheses: {len(ids)}",
            f"IDs: {', '.join(ids)}",
        ]
        if auto_graph:
            out.append(f"Graph nodes created: {graph_count}")
        out.append("Status: hypothesized")
        return "\n".join(out)

    # ── Single-stage backward-compat path ─────────────────────
    _validate_enum(stage, _SCIENCE_STAGES, "stage")
    if not inquiry_id:
        raise ValueError("inquiry_id required for single-stage form")

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


_CLAIM_STATUSES = frozenset({"fact", "inference", "speculation", "uncertain"})
_STATUS_WEIGHT = {
    "fact": 1.0,
    "inference": 0.75,
    "speculation": 0.5,
    "uncertain": 0.25,
}


def _validate_monitor_knowledge(k: dict) -> str | None:
    """Per-item validator for monitor knowledge field."""
    if not isinstance(k, dict):
        return "must be a dict {domain, level, confidence, limitations[≥1]}"
    if k.get("level") not in _KNOWLEDGE_LEVELS:
        return f"level must be one of {sorted(_KNOWLEDGE_LEVELS)}"
    if "confidence" not in k:
        return "missing 'confidence' (0.0-1.0)"
    lim = k.get("limitations")
    if not isinstance(lim, list) or not lim:
        return (
            "'limitations' must be a non-empty list of strings — "
            "self-assessment REJECTS empty limitations because the "
            "forcing function is making 'what I don't know' explicit"
        )
    for j, x in enumerate(lim):
        if not isinstance(x, str) or not x.strip():
            return f"limitations[{j}] must be a non-empty string"
    return None


def _validate_monitor_claims(claims_list: list) -> str | None:
    """Per-item validator for monitor claims field."""
    if not isinstance(claims_list, list) or not claims_list:
        return "must be a non-empty list of {claim, status, confidence, evidence}"
    for j, c in enumerate(claims_list):
        if not isinstance(c, dict) or not c.get("claim"):
            return f"claims[{j}] missing 'claim'"
        if c.get("status") not in _CLAIM_STATUSES:
            return f"claims[{j}].status must be one of {sorted(_CLAIM_STATUSES)}"
        if "confidence" not in c:
            return f"claims[{j}] missing 'confidence'"
        if not c.get("evidence"):
            return f"claims[{j}] missing 'evidence'"
    return None


async def think_monitor(
    task: str = "",
    stage: str = "monitoring",
    overall_confidence: float = 0.5,
    monitoring_id: str = "",
    iteration: int = 1,
    next_assessment_needed: bool = False,
    session_id: str | None = None,
    knowledge_assessment: dict | None = None,
    claims: list[dict] | None = None,
    reasoning_steps: list[dict] | None = None,
    uncertainty_areas: list[str] | None = None,
    recommended_approach: str | None = None,
    suggested_assessments: list[str] | None = None,
    items: list[dict] | None = None,
    auto_graph: bool = False,
    ctx: _MCPContext | None = None,
) -> str:
    """[ASSESS] Self-monitor knowledge boundaries + claim certainty. Call LAST.

    Use when: honest calibration AFTER an analysis (limitations + claim
    certainty); batch-assessing N tasks with the items[] form.
    Do NOT use when: mid-elaboration (use think_graph metadata).
    For assay-heavy or omics-style work, use this to record tissue-validity
    limits, cell-composition confounding, assay-boundary constraints, and
    mechanistic-overreach risks before conclusions or scoring.

    items[]: STRICT batch — each item: id, task, knowledge {domain, level∈
      {expert,proficient,familiar,basic,minimal,none}, confidence,
       limitations[≥1]}, claims[≥1] of {claim, status∈{fact,inference,
       speculation,uncertain}, confidence, evidence}. REJECTS empty
       limitations.
    Single-form: backward-compat staged form for iterative monitoring.

    Args:
      items: STRICT — list of monitoring items as above.
      auto_graph: when True + parent session has graph backend, materialise
        each item as a KnowledgeNode (entity_type=insight).
      task / stage / monitoring_id / iteration / next_assessment_needed:
        single-form fields.
      knowledge_assessment, claims, reasoning_steps, uncertainty_areas,
        recommended_approach, suggested_assessments: single-form payload.
      session_id: omit to auto-create.

    Returns: assessment ids[] in items[] mode, or single-form status.

    Stages (single-form): knowledge-assessment, planning, execution,
    monitoring, evaluation, reflection. Single-form uses the legacy key names
    `knowledgeLevel` / `confidenceScore` / `knownLimitations` inside
    knowledge_assessment. The items[] form uses the short names
    `level` / `confidence` / `limitations` — stick to ONE form per call.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Items[] strict batch path ────────────────────────────
    if items is not None:
        from aismartbuddy.tools import materialize_auto_graph, validate_items

        validate_items(
            items,
            required=["task", "knowledge", "claims"],
            tool="think_monitor",
            item_validators={
                "knowledge": _validate_monitor_knowledge,
                "claims": _validate_monitor_claims,
            },
        )

        ids: list[str] = []
        with engine.state_lock:
            for it in items:
                k = it["knowledge"]
                cl = it["claims"]
                weighted = sum(float(c["confidence"]) * _STATUS_WEIGHT[c["status"]] for c in cl)
                weight_sum = sum(_STATUS_WEIGHT[c["status"]] for c in cl)
                overall = weighted / weight_sum if weight_sum > 0 else 0.0
                rec = MonitorRecord(
                    monitoring_id=it["id"],
                    task=it["task"],
                    stage="self-assess",
                    iteration=1,
                    overall_confidence=overall,
                    knowledge_assessment={
                        "domain": k.get("domain", ""),
                        "knowledgeLevel": k["level"],
                        "confidence": float(k["confidence"]),
                        "limitations": list(k["limitations"]),
                    },
                    claims=list(cl),
                )
                engine.upsert_monitor(rec)
                ids.append(it["id"])

        graph_count = 0
        if auto_graph:
            if not session_id:
                raise ValueError(
                    "auto_graph requires explicit unified session_id from "
                    "session_create(backends=['think','graph'])."
                )
            normalized = [{**it, "_desc": it["task"]} for it in items]
            graph_count = await materialize_auto_graph(
                session_id,
                normalized,
                source_tag="think_monitor",
                entity_type="insight",
                description_field="_desc",
            )

        out = [
            f"Session: {info.session_id} | Assessments: {len(ids)}",
            f"IDs: {', '.join(ids)}",
        ]
        if auto_graph:
            out.append(f"Graph nodes created: {graph_count}")
        out.append("Status: monitored")
        return "\n".join(out)

    # ── Single-form backward-compat path ────────────────────
    _validate_enum(stage, _MONITOR_STAGES, "stage")
    if not monitoring_id:
        raise ValueError("monitoring_id required for single-form")
    overall_confidence = max(0.0, min(1.0, overall_confidence))

    if knowledge_assessment:
        level = knowledge_assessment.get("knowledgeLevel", "")
        if level:
            _validate_enum(level, _KNOWLEDGE_LEVELS, "knowledgeLevel")
        cs = knowledge_assessment.get("confidenceScore")
        if cs is not None:
            if not isinstance(cs, (int, float)) or not (0.0 <= cs <= 1.0):
                raise ValueError(
                    f"Invalid confidenceScore: {cs!r}. Must be a number between 0.0 and 1.0"
                )

    if suggested_assessments:
        for sa in suggested_assessments:
            _validate_enum(sa, _SUGGESTED_ASSESSMENTS, "suggested assessment")

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


async def think_rules(
    action: str,
    session_id: str | None = None,
    profile_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    rules: list[dict] | None = None,
    updates: list[dict] | None = None,
    rule_ids: list[str] | None = None,
    refs: list[str] | None = None,
    subject_id: str | None = None,
    subject_kind: str | None = None,
    bindings: list[dict] | None = None,
    label: str | None = None,
    conflict_resolutions: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Manage weighted reusable rule profiles for long-running plans.

    Use when: you need persistent weighted requirements, design rules, security
    constraints, or plan-specific validation criteria that survive compaction,
    branch changes, and related subplans.

    Actions:
      create_profile: define a reusable rule profile.
      add_rules_batch: strict batch add of rules to a profile.
      update_weights_batch: strict batch update of numeric weights.
      deprecate_rules_batch: mark rules superseded without deleting history.
      list_profiles: list known profiles in the session.
      show_profile: show one profile, its rules, and snapshots.
      bind_profile: bind one or more profiles to a thought/model/decision/holon/evaluation.
      pin_snapshot: freeze current profile state into a snapshot; optionally bind it.
      resolve_conflicts: explicitly resolve open rule conflicts.
    """
    _validate_enum(action, _RULE_ACTIONS, "action")
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    if action == "create_profile":
        if not profile_id or not name:
            raise ValueError("profile_id and name are required for create_profile")
        record = RuleProfile(
            id=profile_id,
            name=name,
            description=description or "",
            refs=list(dict.fromkeys(list(refs or []))),
        )
        engine.upsert_rule_profile(record)
        await _materialize_rule_graph(session_id, profile=record)
        return (
            f"Session: {info.session_id} | Rule profile: {profile_id}\n"
            f"Name: {name}\n"
            "Status: created"
        )

    if action == "list_profiles":
        profiles = sorted(engine.get_rule_profiles(), key=lambda p: p.created_at)
        if not profiles:
            return f"Session: {info.session_id}\nNo rule profiles defined."
        lines = [f"Session: {info.session_id}", f"Rule profiles ({len(profiles)}):"]
        for profile in profiles:
            active_rules = sum(1 for rule in profile.rules if rule.status == "active")
            lines.append(
                f"  {profile.id}: {profile.name} | {active_rules} active rules"
                f" | snapshots={len(profile.snapshots)}"
            )
        return "\n".join(lines)

    if not profile_id and action not in {"bind_profile", "resolve_conflicts"}:
        raise ValueError("profile_id is required for this action")

    if action == "show_profile":
        profile = engine.get_rule_profile(profile_id)
        if profile is None:
            raise ValueError(f"Rule profile '{profile_id}' not found")
        lines = [
            f"Session: {info.session_id} | Rule profile: {profile.id}",
            f"Name: {profile.name}",
            f"Description: {profile.description or '(none)'}",
            f"Snapshots: {len(profile.snapshots)}",
            "Rules:",
        ]
        for rule in profile.rules:
            lines.append(
                f"  {rule.id}: [{rule.kind}] w={rule.weight} | {rule.status} | {rule.text[:120]}"
            )
        return "\n".join(lines)

    if action == "add_rules_batch":
        from aismartbuddy.tools import validate_items

        validate_items(
            rules or [],
            required=["text", "weight", "kind"],
            tool="think_rules",
        )
        parsed: list[RuleItem] = []
        seen_ids: set[str] = set()
        for i, rule in enumerate(rules or []):
            rid = rule["id"]
            if rid in seen_ids:
                raise ValueError(f"think_rules.rules[{i}] duplicate id '{rid}'")
            seen_ids.add(rid)
            _validate_enum(rule["kind"], _RULE_KINDS, f"rules[{i}].kind")
            status = rule.get("status", "active")
            _validate_enum(status, _RULE_STATUSES, f"rules[{i}].status")
            parsed.append(
                RuleItem(
                    id=rid,
                    text=rule["text"],
                    weight=float(rule["weight"]),
                    kind=rule["kind"],
                    status=status,
                    rationale=rule.get("rationale", "") or "",
                    tags=list(rule.get("tags") or []),
                    refs=list(rule.get("refs") or []),
                    conflicts_with=list(rule.get("conflicts_with") or []),
                )
            )
        profile = engine.add_rules_batch(profile_id, parsed)
        await _materialize_rule_graph(session_id, profile=profile, rules=parsed)
        return (
            f"Session: {info.session_id} | Rule profile: {profile_id}\n"
            f"Rules added: {len(parsed)}\n"
            f"Rule IDs: {', '.join(rule.id for rule in parsed)}\n"
            "Status: updated"
        )

    if action == "update_weights_batch":
        if not updates:
            raise ValueError("updates must be a non-empty list")
        for i, update in enumerate(updates):
            if not isinstance(update, dict):
                raise ValueError(f"think_rules.updates[{i}] must be a dict")
            if not update.get("rule_id"):
                raise ValueError(f"think_rules.updates[{i}] missing 'rule_id'")
            if "weight" not in update:
                raise ValueError(f"think_rules.updates[{i}] missing 'weight'")
        profile = engine.update_rule_weights(profile_id, list(updates or []))
        return (
            f"Session: {info.session_id} | Rule profile: {profile_id}\n"
            f"Weights updated: {len(updates or [])}\n"
            "Status: updated"
        )

    if action == "deprecate_rules_batch":
        if not rule_ids:
            raise ValueError("rule_ids is required for deprecate_rules_batch")
        engine.deprecate_rules(profile_id, list(rule_ids))
        return (
            f"Session: {info.session_id} | Rule profile: {profile_id}\n"
            f"Rules superseded: {', '.join(rule_ids)}\n"
            "Status: updated"
        )

    if action == "bind_profile":
        if not subject_id:
            raise ValueError("subject_id is required for bind_profile")
        if not bindings:
            raise ValueError("bindings is required for bind_profile")
        resolved_kind, bound = engine.bind_rule_profiles(subject_id, subject_kind, bindings)
        await _materialize_subject_rule_bindings(
            engine,
            session_id,
            subject_kind=resolved_kind,
            subject_id=subject_id,
            subject_label=f"bound-{resolved_kind}-{subject_id}",
            bindings=bound,
            source="think_rules",
        )
        return (
            f"Session: {info.session_id} | Subject: {subject_id}\n"
            f"Kind: {resolved_kind} | Bound profiles: "
            f"{', '.join(b['profile_id'] for b in bound)}\n"
            "Status: bound"
        )

    if action == "pin_snapshot":
        snapshot_id = f"{profile_id}-snap-{uuid.uuid4().hex[:8]}"
        snapshot = engine.create_rule_snapshot(profile_id, snapshot_id, label or "")
        if subject_id:
            resolved_kind, bound = engine.bind_rule_profiles(
                subject_id,
                subject_kind,
                [{"profile_id": profile_id, "snapshot_id": snapshot.id}],
            )
            await _materialize_subject_rule_bindings(
                engine,
                session_id,
                subject_kind=resolved_kind,
                subject_id=subject_id,
                subject_label=f"bound-{resolved_kind}-{subject_id}",
                bindings=bound,
                source="think_rules",
            )
        return (
            f"Session: {info.session_id} | Rule profile: {profile_id}\n"
            f"Snapshot: {snapshot.id}\n"
            + (f"Bound to: {subject_id}\n" if subject_id else "")
            + "Status: pinned"
        )

    if not conflict_resolutions:
        raise ValueError("conflict_resolutions is required for resolve_conflicts")
    resolved = []
    for i, item in enumerate(conflict_resolutions):
        conflict_id = item.get("conflict_id")
        if not conflict_id:
            raise ValueError(f"conflict_resolutions[{i}] missing 'conflict_id'")
        resolution_note = item.get("resolution_note", "") or ""
        resolved.extend(engine.resolve_rule_conflicts([conflict_id], resolution_note))
    return (
        f"Session: {info.session_id} | Conflicts resolved: {len(resolved)}\n"
        f"Conflict IDs: {', '.join(r.id for r in resolved)}\n"
        "Status: resolved"
    )


async def think_validate(
    subject_id: str = "",
    session_id: str | None = None,
    subject_kind: str | None = None,
    assessments: list[dict] | None = None,
    validation_id: str | None = None,
    rule_profile_ids: list[str] | None = None,
    use_bound_profiles: bool = True,
    nuance_notes: list[str] | None = None,
    refs: list[str] | None = None,
    items: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ASSESS] Validate a plan/artifact against weighted hard+soft rule profiles.

    Returns a validation record with hard-gate status, weighted score, gaps,
    uncovered rules, conflicts, and nuance notes. Use this when rules must
    persist across long chats and related subplans.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    if items is not None:
        from aismartbuddy.tools import validate_items

        validate_items(
            items,
            required=["subject_id"],
            tool="think_validate",
        )
        ids: list[str] = []
        for i, item in enumerate(items):
            parsed_assessments: list[ValidationAssessment] = []
            for j, assessment in enumerate(item.get("assessments") or []):
                _validate_enum(
                    assessment["status"],
                    _VALIDATION_STATUSES,
                    f"items[{i}].assessments[{j}].status",
                )
                parsed_assessments.append(
                    ValidationAssessment(
                        rule_id=assessment["rule_id"],
                        status=assessment["status"],
                        note=assessment.get("note", "") or "",
                        refs=list(assessment.get("refs") or []),
                    )
                )
            vid = item.get("validation_id") or uuid.uuid4().hex[:10]
            record = engine.validate_subject(
                item["subject_id"],
                item.get("subject_kind"),
                parsed_assessments,
                rule_profile_ids=item.get("rule_profile_ids"),
                use_bound_profiles=item.get("use_bound_profiles", True),
                validation_id=vid,
                refs=item.get("refs"),
                nuance_notes=item.get("nuance_notes"),
            )
            ids.append(record.id)
            await _materialize_rule_graph(session_id, validation=record)
        return (
            f"Session: {info.session_id} | Validations: {len(ids)}\n"
            f"IDs: {', '.join(ids)}\n"
            "Status: validated"
        )

    if not subject_id:
        raise ValueError("subject_id is required")
    parsed_assessments = []
    for i, assessment in enumerate(assessments or []):
        _validate_enum(assessment["status"], _VALIDATION_STATUSES, f"assessments[{i}].status")
        parsed_assessments.append(
            ValidationAssessment(
                rule_id=assessment["rule_id"],
                status=assessment["status"],
                note=assessment.get("note", "") or "",
                refs=list(assessment.get("refs") or []),
            )
        )
    record = engine.validate_subject(
        subject_id,
        subject_kind,
        parsed_assessments,
        rule_profile_ids=rule_profile_ids,
        use_bound_profiles=use_bound_profiles,
        validation_id=validation_id or uuid.uuid4().hex[:10],
        refs=refs,
        nuance_notes=nuance_notes,
    )
    await _materialize_rule_graph(session_id, validation=record)
    lines = [
        f"Session: {info.session_id} | Validation: {record.id}",
        f"Subject: {record.subject_kind}:{record.subject_id}",
        f"Hard gates: {'PASS' if record.passed_hard_gates else 'FAIL'}",
        f"Weighted score: {record.weighted_score:.1f}",
        (
            "Hard failures: "
            + (", ".join(record.hard_failures) if record.hard_failures else "(none)")
        ),
        (
            "Uncovered rules: "
            + (", ".join(record.uncovered_rules) if record.uncovered_rules else "(none)")
        ),
        (
            "Conflicts: "
            + (", ".join(record.conflicting_rules) if record.conflicting_rules else "(none)")
        ),
    ]
    if record.weighted_gaps:
        lines.append(
            "Weighted gaps: "
            + ", ".join(
                f"{gap['rule_id']}[{gap['status']}]:{gap['weight']}"
                for gap in record.weighted_gaps[:8]
            )
        )
    if record.nuance_notes:
        lines.append("Nuance: " + " | ".join(record.nuance_notes[:4]))
    return "\n".join(lines)


# ── Tool: Summarize ──────────────────────────────────────────


@size_guarded
async def think_summarize(
    session_id: str,
    max_items_per_category: int = 20,
) -> str:
    """Get a token-optimized summary of all thinking activity in a session.

    Returns a compact overview of all thought graphs, mental models,
    decisions, debugging approaches, arguments, collaborations, inquiries,
    monitors, and diagrams recorded in the session.

    Args:
        session_id: Thinking session ID.
        max_items_per_category: Cap on items per category to prevent huge
            responses on sessions with hundreds of items. Default 20.
            Excess items collapse to "... (N more)" footer.

    Returns:
        Compact summary of all thinking activity.
    """
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    return f"Session: {session_id}\n{engine.get_summary(max_items_per_category)}"


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

_IP_ACTIONS = frozenset(
    {
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
    }
)

_IP_AUDIT_TYPES = frozenset(
    {
        "first_principles",
        "ecosystem",
        "contingency",
        "failure_modes",
    }
)

_IP_VERDICTS = frozenset(
    {
        "survives",
        "dies",
        "wounded",
    }
)

_IP_MIN_SOURCES = 2
_IP_MIN_FRAGMENTS = 5

_IP_NECESSITY_STATUSES = frozenset(
    {
        "untested",
        "holds",
        "fails",
    }
)

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
        (f"Session: {session_id} | Protocol: {record.protocol_id}"),
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

    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)
    sid = info.session_id

    # Interference is a multi-phase state machine. Every action reads the
    # current record, checks phase gates, mutates, and upserts. Without a
    # lock, two agents sharing a protocol_id could both pass the phase gate
    # and corrupt each other's transitions. RLock reentry keeps nested
    # @_synchronized engine calls safe.
    with engine.state_lock:
        return _think_interfere_locked(
            engine,
            sid,
            action,
            protocol_id,
            target_domain,
            frame,
            source_domain,
            law,
            isomorphism,
            fragment,
            tension_laws,
            tension_description,
            name,
            properties,
            conclusion,
            prerequisites,
            chain_index,
            prereq_index,
            new_status,
            audit_type,
            audit_result,
            verdict,
            new_domain,
            concept_as_law,
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
            sid,
            record,
            f"Domain set: '{target_domain}'. Add suspended frames "
            "and at least 2 source laws from distant domains.",
        )

    # ── All other actions require protocol_id ────────────
    if not protocol_id:
        raise ValueError(
            "protocol_id is required. Use action='set_domain' to start a new protocol."
        )
    record = engine.get_interference(protocol_id)
    if record is None:
        raise ValueError(f"Protocol '{protocol_id}' not found.")

    # ── Phase gate check ─────────────────────────────────
    allowed_phases = _IP_PHASE_GATES.get(action, set())
    if allowed_phases and record.phase not in allowed_phases:
        valid = _IP_VALID_ACTIONS.get(record.phase, [])
        return _ip_status_output(
            sid,
            record,
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
            sid,
            record,
            f"Frame suspended: '{frame[:80]}'",
        )

    # ── add_source ───────────────────────────────────────
    if action == "add_source":
        if not source_domain or not law or not isomorphism:
            raise ValueError("source_domain, law, and isomorphism are all required for add_source")
        record.source_laws.append(
            {
                "domain": source_domain,
                "law": law,
                "isomorphism": isomorphism,
            }
        )
        if len(record.source_laws) >= _IP_MIN_SOURCES:
            record.phase = "sources_ready"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid,
            record,
            f"Source added: [{source_domain}] {law[:60]}. "
            f"Total: {len(record.source_laws)} sources"
            + (
                f" (need {_IP_MIN_SOURCES}+, ready for fragments)"
                if len(record.source_laws) >= _IP_MIN_SOURCES
                else f" (need {_IP_MIN_SOURCES}+ to proceed)"
            ),
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
            sid,
            record,
            f"Fragment {len(record.fragments)}/{_IP_MIN_FRAGMENTS}: "
            f"'{fragment[:60]}'"
            + (" — saturated, ready to crystallize" if record.phase == "saturated" else ""),
        )

    # ── add_tension ──────────────────────────────────────
    if action == "add_tension":
        if tension_laws is None or not tension_description:
            raise ValueError("tension_laws and tension_description are required for add_tension")
        for idx in tension_laws:
            if idx not in range(len(record.source_laws)):
                raise ValueError(
                    f"tension_laws index {idx} out of range "
                    f"(have {len(record.source_laws)} sources)"
                )
        record.tensions.append(
            {
                "between": tension_laws,
                "description": tension_description,
            }
        )
        engine.upsert_interference(record)
        return _ip_status_output(
            sid,
            record,
            f"Tension recorded between sources {tension_laws}: '{tension_description[:60]}'",
        )

    # ── crystallize ──────────────────────────────────────
    if action == "crystallize":
        if not name or not properties:
            raise ValueError("name and properties are required for crystallize")
        # Emergence test
        novel_props = [p for p in properties if p.get("novel", False)]
        if len(novel_props) < 2:
            return _ip_status_output(
                sid,
                record,
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
                        sid,
                        record,
                        f"REJECTED: Property '{p_text}' "
                        f"references nonexistent source index "
                        f"{idx} (have {len(record.source_laws)} "
                        "sources).",
                    )
            if len(src_laws) < 2:
                return _ip_status_output(
                    sid,
                    record,
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
            sid,
            record,
            f"Crystallized: '{name}' with "
            f"{len(properties)} properties "
            f"({len(novel_props)} novel). "
            "Emergence test passed.",
        )

    # ── add_necessity ────────────────────────────────────
    if action == "add_necessity":
        if not conclusion or not prerequisites:
            raise ValueError("conclusion and prerequisites are required for add_necessity")
        for p in prerequisites:
            status = p.get("status", "untested")
            _validate_enum(status, _IP_NECESSITY_STATUSES, "prerequisite status")
        record.necessity_chains.append(
            {
                "conclusion": conclusion,
                "prerequisites": prerequisites,
            }
        )
        record.phase = "necessities_derived"
        engine.upsert_interference(record)
        return _ip_status_output(
            sid,
            record,
            f"Necessity chain added: '{conclusion[:60]}' "
            f"with {len(prerequisites)} prerequisites. "
            f"Total chains: {len(record.necessity_chains)}",
        )

    # ── update_necessity ─────────────────────────────────
    if action == "update_necessity":
        if chain_index is None or prereq_index is None or not new_status:
            raise ValueError(
                "chain_index, prereq_index, and new_status are required for update_necessity"
            )
        _validate_enum(new_status, _IP_NECESSITY_STATUSES, "new_status")
        if chain_index not in range(len(record.necessity_chains)):
            raise ValueError(
                f"chain_index {chain_index} out of range "
                f"(have {len(record.necessity_chains)} chains)"
            )
        chain = record.necessity_chains[chain_index]
        prereqs = chain["prerequisites"]
        if prereq_index not in range(len(prereqs)):
            raise ValueError(
                f"prereq_index {prereq_index} out of range (chain has {len(prereqs)} prerequisites)"
            )
        prereqs[prereq_index]["status"] = new_status
        engine.upsert_interference(record)

        # Check chain health
        all_fail = all(p.get("status") == "fails" for p in prereqs)
        health = " — CHAIN BROKEN (all prerequisites fail)" if all_fail else ""
        return _ip_status_output(
            sid,
            record,
            f"Updated chain {chain_index} prereq {prereq_index} → {new_status}{health}",
        )

    # ── stress_test ──────────────────────────────────────
    if action == "stress_test":
        if not audit_type or not audit_result:
            raise ValueError("audit_type and audit_result are required for stress_test")
        _validate_enum(audit_type, _IP_AUDIT_TYPES, "audit_type")
        record.audit_results[audit_type] = audit_result
        engine.upsert_interference(record)
        return _ip_status_output(
            sid,
            record,
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
            sid,
            record,
            f"Verdict: {verdict}. "
            f"Concept '{record.emergent_name}' "
            + (
                "survives stress testing. Ready to recurse or export."
                if verdict == "survives"
                else f"verdict={verdict}. Consider revising or accepting limitations."
            ),
        )

    # ── recurse ──────────────────────────────────────────
    if action == "recurse":
        if not new_domain or not concept_as_law:
            raise ValueError("new_domain and concept_as_law are required for recurse")
        new_pid = uuid.uuid4().hex[:12]
        new_record = InterferenceRecord(
            protocol_id=new_pid,
            phase="domain_set",
            iteration=record.iteration + 1,
            target_domain=new_domain,
            source_laws=[
                {
                    "domain": f"[emerged] {record.emergent_name}",
                    "law": concept_as_law,
                    "isomorphism": (f"Emergent concept from iteration {record.iteration}"),
                }
            ],
        )
        engine.upsert_interference(new_record)
        return _ip_status_output(
            sid,
            new_record,
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
        f"Phase: {record.phase} | Iter: {record.iteration} | Domain: {record.target_domain}",
    ]

    if record.suspended_frames:
        lines.append(f"\n## Suspended Frames ({len(record.suspended_frames)})")
        for i, f in enumerate(record.suspended_frames):
            lines.append(f"  {i}. {f}")

    if record.source_laws:
        lines.append(f"\n## Source Laws ({len(record.source_laws)})")
        for i, s in enumerate(record.source_laws):
            lines.append(f"  {i}. [{s['domain']}] {s['law']}")
            lines.append(f"     Isomorphism: {s['isomorphism']}")

    if record.fragments:
        lines.append(f"\n## Fragments ({len(record.fragments)})")
        for i, frag in enumerate(record.fragments):
            lines.append(f"  {i}. {frag[:120]}")

    if record.tensions:
        lines.append(f"\n## Tensions ({len(record.tensions)})")
        for t in record.tensions:
            lines.append(f"  Between sources {t['between']}: {t['description'][:100]}")

    if record.emergent_name:
        lines.append(f"\n## Emergent Concept: {record.emergent_name}")
        for i, p in enumerate(record.emergent_properties):
            novel = " [NOVEL]" if p.get("novel") else ""
            srcs = p.get("source_laws", [])
            lines.append(f"  {i}. {p['text'][:100]}{novel} (sources: {srcs})")

    if record.necessity_chains:
        lines.append(f"\n## Necessity Chains ({len(record.necessity_chains)})")
        for ci, chain in enumerate(record.necessity_chains):
            lines.append(f"  Chain {ci}: {chain['conclusion'][:80]}")
            for pi, prereq in enumerate(chain["prerequisites"]):
                status = prereq.get("status", "untested")
                lines.append(f"    {pi}. [{status}] {prereq['claim'][:80]}")

    if record.audit_results:
        lines.append(f"\n## Audit Results ({len(record.audit_results)})")
        for atype, aresult in record.audit_results.items():
            lines.append(f"  {atype}: {aresult[:120]}")

    if record.verdict:
        lines.append(f"\nVerdict: {record.verdict}")

    return "\n".join(lines)
