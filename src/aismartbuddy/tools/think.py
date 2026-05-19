"""Structured thinking tools for AI reasoning.

Layer 1 cognitive tools — ephemeral, in-memory, session-scoped.
Mirrors clear-thought MCP server functionality with session isolation,
auto-session creation, and token-optimized compact text output.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import TYPE_CHECKING, Callable

import anyio

# Aliased to avoid colliding with this module's heavy use of "context" in
# domain types (ThoughtNode metadata, holon contexts, etc.). holon.py uses
# the same alias for the same reason; sql.py/graph.py/score.py use the
# unaliased name where there's no conflict.
from mcp.server.fastmcp import Context as _MCPContext

from aismartbuddy.engines.thinking_engine import (
    ArgRecord,
    ConstraintRecord,
    ConstraintValidationRecord,
    DebugRecord,
    DecisionRecord,
    EvidenceChainRecord,
    EvidenceRecord,
    HypothesisRecord,
    InquiryRecord,
    InterferenceRecord,
    ModelRecord,
    MonitorRecord,
    RuleItem,
    RuleProfile,
    ThinkingEngine,
    ThoughtNode,
    TopologyRecord,
    ValidationAssessment,
)
from aismartbuddy.identity import resolve_identity
from aismartbuddy.tools import (
    effective_session_id,
    get_session_manager,
    resolve_active_or_provided_session_id,
    resolve_auto_graph,
    run_with_lock,
    size_guarded,
)

if TYPE_CHECKING:
    from aismartbuddy.session import SessionInfo, SessionManager

logger = logging.getLogger("aismartbuddy.tools.think")

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
        "kuba",
        "systems_dynamics",
        "inversion",
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
_HYPOTHESIS_ACTIONS = frozenset(
    {"register", "evidence", "compare", "discriminate", "update", "invalidate"}
)
_HYPOTHESIS_EVIDENCE_DIRECTIONS = frozenset({"supports", "weakens", "neutral"})
_CONSTRAINT_ACTIONS = frozenset({"register", "validate", "list", "remove", "check_all"})
_CONSTRAINT_TYPES = frozenset({"hard", "soft"})
_CONSTRAINT_VALIDATION_RESULTS = frozenset({"pass", "fail", "uncertain"})
_TOPOLOGY_ACTIONS = frozenset({"define", "abstract", "compare", "translate", "search"})
_TOPOLOGY_NODE_ROLES = frozenset(
    {"SOURCE", "SINK", "SENSOR", "EFFECTOR", "BUFFER", "SWITCH", "GATE", "JUNCTION"}
)
_TOPOLOGY_EDGE_TYPES = frozenset(
    {"AMPLIFIES", "SUPPRESSES", "DELAYS", "SATURATES", "OSCILLATES", "THRESHOLDS", "COUPLES"}
)
_EVIDENCE_ACTIONS = frozenset({"register", "chain", "trace", "strength", "list"})
_EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "measurement",
        "observation",
        "literature",
        "inference",
        "analogy",
        "simulation",
        "expert_opinion",
    }
)
_EVIDENCE_INFERENCE_TYPES = frozenset({"deductive", "inductive", "abductive", "analogical"})
_BRIDGE_ACTIONS = frozenset(
    {
        "thoughts_for_entity",
        "entities_for_thought",
        "hypotheses_for_entity",
        "evidence_for_hypothesis",
        "constraints_for_hypothesis",
        "full_context",
        "bundle",
        "authoritative_source",
        "domain_context",
        "domain_connections",
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
    session_id = resolve_active_or_provided_session_id(session_id)
    if session_id:
        # resolve_backend_session handles both parent-id and direct-child
        # cases; raises if the parent has no think backend.
        info = mgr.resolve_backend_session(session_id, "think")
        return mgr, info
    # Auto-create: parent session with think + graph backends so auto_graph works
    # without requiring an explicit session_create call first.
    user_id, project_id = resolve_identity(ctx, None, None)
    parent = mgr.create_parent_session(["think", "graph"], user_id, project_id)
    info = mgr.resolve_backend_session(parent.parent_id, "think")
    return mgr, info


def _require_think_session(session_id: str | None) -> tuple[SessionManager, SessionInfo]:
    """Validate and return an existing think session. Raises if wrong type."""
    session_id = resolve_active_or_provided_session_id(session_id)
    if not session_id:
        raise ValueError(
            "session_id is required unless an active session is set. "
            "Use think_set_active_session(session_id)."
        )
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


def _idempotent_result(session_id: str | None, idempotency_key: str | None) -> str | None:
    """Return cached result for a write op if this idempotency key already succeeded."""
    if not session_id or not idempotency_key:
        return None
    return get_session_manager().get_idempotent_result(session_id, idempotency_key)


def _store_idempotent_result(
    session_id: str | None, idempotency_key: str | None, result: str
) -> str:
    """Persist idempotent write result and return it unchanged."""
    if session_id and idempotency_key:
        get_session_manager().store_idempotent_result(session_id, idempotency_key, result)
    return result


def _companion_graph_session_id(think_session_id: str) -> str | None:
    """Return the graph companion session for a think session when unified."""
    return get_session_manager().find_companion_session(think_session_id, "graph")


async def _safe_graph_context_lines(
    think_session_id: str,
    *,
    entity_names: list[str] | None = None,
    target_name: str | None = None,
) -> list[str]:
    """Best-effort graph-backed context. Returns [] if graph is unavailable or errors."""
    graph_session_id = _companion_graph_session_id(think_session_id)
    if not graph_session_id:
        return []
    try:
        from aismartbuddy.tools.graph import graph_focus_summary, graph_query

        lines = [f"Graph companion: {graph_session_id}"]
        if entity_names:
            names = [name for name in dict.fromkeys(entity_names) if str(name).strip()][:5]
            if names:
                lines.append("Graph-backed knowledge refs:")
                focus = await graph_focus_summary(
                    session_id=graph_session_id,
                    node_names=names,
                    node_type="KnowledgeNode",
                    depth=1,
                )
                lines.extend(f"  {line}" for line in focus.splitlines()[:12])
        if target_name:
            quoted = target_name.replace("'", "''")
            result = await graph_query(
                session_id=graph_session_id,
                query=(
                    "MATCH (n:KnowledgeNode) "
                    f"WHERE n.name = '{quoted}' "
                    "RETURN n.name AS name, n.entity_type AS entity_type LIMIT 5;"
                ),
            )
            if "name" in result:
                lines.append("Graph node match:")
                lines.extend(f"  {line}" for line in result.splitlines()[:6])
        return lines
    except Exception:
        return []


def _short(text: str, limit: int = 80) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _emit_domain_section(
    lines: list[str],
    title: str,
    records: list,
    id_fn: Callable[[object], str],
    text_fn: Callable[[object], str],
    cap: int = 30,
) -> None:
    if not records:
        return
    lines.append(f"## {title}")
    for rec in records[:cap]:
        lines.append(f"  {id_fn(rec)}: {_short(text_fn(rec), 80)}")


def _node_to_export_dict(node: ThoughtNode) -> dict:
    return {
        "id": node.id,
        "tree_id": node.tree_id,
        "action": node.action,
        "parent_id": node.parent_id,
        "depth": node.depth,
        "thought": node.content,
        "metadata": node.metadata,
        "refs": list(node.refs),
        "depends_on": list(node.depends_on),
        "children": list(node.children),
        "validation_results": list(node.validation_results),
    }


def _render_subtree_outline(engine: ThinkingEngine, node_id: str, depth: int | None = None) -> str:
    root = engine.get_node(node_id)
    if root is None:
        return ""
    lines: list[str] = []

    def _walk(current_id: str, level: int) -> None:
        node = engine.get_node(current_id)
        if node is None:
            return
        if depth is not None and level > depth:
            return
        lines.append(f"{'  ' * level}- {node.id} [{node.action}] {_short(node.content, 100)}")
        if node.validation_results:
            latest = node.validation_results[-1]
            lines.append(
                f"{'  ' * (level + 1)}validation: "
                f"hard_gates={'pass' if latest.get('passed_hard_gates', True) else 'fail'} "
                f"score={latest.get('weighted_score')}"
            )
        for child_id in node.children:
            _walk(child_id, level + 1)

    _walk(root.id, 0)
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

# Soft threshold above which a single thought node is flagged as essay-length.
# Long thoughts defeat graph queryability — short nodes stay addressable.
_LONG_THOUGHT_THRESHOLD = 1500


def _compose_next_hint(tool: str, key_arg: str, ids: list[str]) -> str:
    """Format a 'Suggested next:' line to nudge cross-tool composition.

    Return format: `Suggested next: <tool>(<key_arg>=["id1","id2"])`.
    Empty id list ⇒ empty string (no nudge when there's nothing to pass).
    """
    if not ids:
        return ""
    # Cap to avoid flooding the hint with 50+ ids from a batch.
    shown = ids[:8]
    ids_repr = ", ".join(f'"{i}"' for i in shown)
    more = f", ...+{len(ids) - len(shown)} more" if len(ids) > len(shown) else ""
    return f'Suggested next: {tool}({key_arg}=[{ids_repr}{more}])'


def _long_thought_warnings(entries: list[tuple[str, str]]) -> str:
    """Return a compact advisory string for entries whose content exceeds the
    soft length threshold, or "" if none.

    entries: list of (label, content) pairs, where label identifies the
    offending thought (e.g. "thought", "thoughts[3]", "children[1]").

    Single offender: full per-entry note. Multiple offenders: single-line
    summary count to keep the response compact (the agent has already
    submitted; itemising every long entry just inflates the response).
    """
    offenders: list[tuple[str, int]] = []
    for label, content in entries:
        length = len(content or "")
        if length > _LONG_THOUGHT_THRESHOLD:
            offenders.append((label, length))
    if not offenders:
        return ""
    if len(offenders) == 1:
        label, length = offenders[0]
        return (
            f"Note: {label} is {length} chars — consider action='branch' "
            f"with children=[...] to keep nodes queryable.\n"
        )
    return (
        f"Note: {len(offenders)} thoughts exceed {_LONG_THOUGHT_THRESHOLD} chars "
        f"(use action='branch' to split).\n"
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
    thought: str = "",
    action: str = "think",
    session_id: str | None = None,
    parent_id: str | None = None,
    node_id: str | None = None,
    tree_id: str | None = None,
    depends_on: list[str] | None = None,
    refs: list[str] | None = None,
    metadata: dict | None = None,
    children: list[dict] | None = None,
    thoughts: list[dict] | None = None,
    expected_children: int | None = None,
    min_children: int | None = None,
    rule_profile_ids: list[str] | None = None,
    idempotency_key: str | None = None,
    auto_graph: bool = False,
    ctx: _MCPContext | None = None,
) -> str:
    """Thought graph — structured thinking with progressive complexity.

    Every thought is a node in a graph. Supports simple sequential chains,
    hierarchical tree decomposition, multi-tree forests, revision with
    history, and synthesis.

    PREFERRED: use the `thoughts=[...]` batch parameter for new chains and
    trees. One call creates N nodes atomically — this is the fastest, most
    queryable shape for sequential or hierarchical analysis. Fall back to
    single-call mode only for incremental mid-analysis additions.

    KEEP THOUGHTS CONCISE. One thought = one move (a claim, an observation,
    a sub-goal, a conclusion). Aim for 1–3 sentences per node, not paragraphs.
    If a thought is becoming an essay, use action="branch" and split into
    children. Long stories collapse to noise; short nodes stay queryable.

    Thought-unit granularity rules:
    - One node = one semantic unit. Do not combine multiple independent claims,
      multiple reasoning steps, or a problem and its solution in one node.
    - If a thought says "A implies B, and B implies C", that is at least two
      thought units plus an optional synthesis, not one node.
    - If a thought contains "however", "therefore", "additionally", or
      another connector joining distinct ideas, split them unless they are
      inseparable parts of the same inference step.
    - Evidence and claim should usually be separate nodes linked by refs,
      so validation can challenge the claim without losing the evidence.

    PREFERRED — sequential chain in one call:
        think_graph(thoughts=[
            {"thought": "First insight"},
            {"thought": "Building on that...", "parent_ref": 0},
            {"thought": "Therefore...", "parent_ref": 1},
            {"thought": "Implication for decision", "parent_ref": 2},
        ])
        # parent_ref is an integer index into this same batch, or an existing
        # node_id string. Index 0 is the root of a new tree.

    PREFERRED — hierarchical decomposition in one call:
        think_graph(thoughts=[
            {"thought": "Break this into parts", "action": "branch"},
            {"thought": "Part A analysis", "parent_ref": 0},
            {"thought": "Part B analysis", "parent_ref": 0},
            {"thought": "Combined conclusion",
             "action": "synthesize", "parent_ref": 0},
        ])

    Incremental (mid-analysis additions, not for new chains):
        think_graph(thought="Follow-up point", parent_id="<existing_id>")
        think_graph(thought="Revised claim", action="revise",
                    node_id="<existing_id>")

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
        thoughts: PREFERRED. Batch mode — each item is one atomic thought unit:
            {thought, action?, parent_ref?, metadata?, refs?, depends_on?,
             entity_refs?, domain?}.
            parent_ref may be an existing node_id string OR an integer index
            pointing at another item earlier in this same batch (0 = the first
            item, which becomes a new tree root). Batch mode collapses N
            round-trips to 1 and is the default for new chains or trees. It is
            not a place to hide one large mixed-meaning essay inside a single
            array entry — one item, one thought unit.
            entity_refs: list[str] — external entity names auto-registered into
              metadata["knowledge_refs"] so think_bridge(thoughts_for_entity)
              finds this node. BATCH-ONLY — not available on the single-call path.
            domain: str — free-text domain tag written to metadata["domain"].
              Enables think_bridge(domain_context/domain_connections). BATCH-ONLY.
        thought: The thinking content (single-call / incremental mode).
        action: What kind of thought: think, branch, revise, synthesize.
        session_id: Thinking session ID. Omit to auto-create.
        parent_id: Parent node ID. None creates new tree root.
        node_id: For revise action — which node to update.
        tree_id: Optionally assign to existing tree (ignored when
            parent_id is set — tree is inferred from parent).
        metadata: Flexible context bag for additional data.
            Recommended conventions:
            - knowledge_refs: [entity_name, ...]
            - hypothesis_refs: [hypothesis_id, ...]
            - constraint_refs: [constraint_id, ...]
            - evidence_refs: [evidence_id, ...]
            - topology_refs: [topology_id, ...]
            - confidence: 0.0-1.0
            - claim_type: fact | inference | speculation | assumption
            - domain: free-text domain tag
        children: Optional list of child specs to create atomically with the
            parent in one call (one round trip instead of N+1). Each child:
            {thought: str, metadata?: dict, action?: str}. Returns parent_id +
            child_ids[]. Use with action="branch" for decomposition batching.
            Each child is still one thought unit. Batch children exist to reduce
            round-trips, not to pack large multi-part analyses into one entry.
        expected_children: Planning horizon — declare how many children you
            intend to create. When action="synthesize" runs later, the tool
            warns if the actual count differs.
        idempotency_key: Optional retry token for safe write retries. If the
            same session_id + key combination already completed, the server
            returns the original result without creating duplicate nodes.
        auto_graph: Batch-only (thoughts=[...]). When True + parent session
            has graph backend, materialise each thought as a KnowledgeNode and
            each parent_ref as a BranchOf edge in one round trip.

    Pass auto_graph=True (requires session_create(backends=['think','graph']))
    to materialise each item as a KnowledgeNode with BranchOf edges in one
    round-trip.

    Returns a 'Suggested next:' line at end of response with canonical
    follow-up call pre-filled (after action='synthesize'). Read it before
    deciding the next step.

    Returns:
        Compact status with node position and tree structure.
    """
    _validate_enum(action, _GRAPH_ACTIONS, "action")

    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)
    sid = info.session_id
    cached = _idempotent_result(sid, idempotency_key)
    if cached is not None:
        return cached

    if thought and thoughts:
        raise ValueError("Provide either thought or thoughts, not both")

    # ── Revise: update existing node ─────────────────────
    if action == "revise":
        if not node_id:
            raise ValueError("node_id is required for revise action")
        if not thought:
            raise ValueError("thought content is required for revise action")
        node = engine.revise_node(node_id, thought)
        if node is None:
            raise ValueError(f"Node '{node_id}' not found")
        path_str = _build_path_string(engine, node.id)
        return _store_idempotent_result(
            sid,
            idempotency_key,
            (
                f"Session: {sid} | Tree: {node.tree_id} | Node: {node.id}\n"
                f"Action: revise | Depth: {node.depth}"
                f" | Revisions: {len(node.revision_history)}\n"
                f"Path: {path_str}\n"
                f"Status: revised"
            ),
        )

    if thoughts is not None:
        if not thoughts:
            raise ValueError("thoughts batch must be non-empty")
        bindings = _rule_bindings_from_profile_ids(engine, rule_profile_ids)
        specs: list[dict] = []
        created_refs: list[str] = []
        for index, item in enumerate(thoughts):
            content = str(item.get("thought", "")).strip()
            if not content:
                raise ValueError(f"thoughts[{index}] missing 'thought'")
            item_action = item.get("action", action)
            _validate_enum(str(item_action), _GRAPH_ACTIONS - {"revise"}, "batch action")
            parent_ref = item.get("parent_ref")
            resolved_parent_id = None
            item_tree_id = item.get("tree_id")
            item_depth = 0
            if isinstance(parent_ref, int):
                if parent_ref < 0 or parent_ref >= len(specs):
                    raise ValueError(
                        f"thoughts[{index}].parent_ref={parent_ref} is out of range for this batch"
                    )
                resolved_parent_id = specs[parent_ref]["id"]
                item_tree_id = specs[parent_ref]["tree_id"]
                item_depth = specs[parent_ref]["depth"] + 1
            elif isinstance(parent_ref, str) and parent_ref.strip():
                parent_node = engine.get_node(parent_ref.strip())
                if parent_node is None:
                    raise ValueError(f"thoughts[{index}] parent_ref '{parent_ref}' not found")
                resolved_parent_id = parent_node.id
                item_tree_id = parent_node.tree_id
                item_depth = parent_node.depth + 1
            elif item_tree_id and item_tree_id in engine.thought_trees:
                raise ValueError(
                    f"thoughts[{index}] targets existing tree '{item_tree_id}' without parent_ref"
                )
            item_metadata: dict = dict(item.get("metadata") or {})
            entity_refs_val = [str(x) for x in (item.get("entity_refs") or []) if x]
            if entity_refs_val:
                existing_refs = [str(x) for x in (item_metadata.get("knowledge_refs") or [])]
                item_metadata["knowledge_refs"] = list(
                    dict.fromkeys(existing_refs + entity_refs_val)
                )
            domain_val = str(item.get("domain", "")).strip()
            if domain_val:
                item_metadata["domain"] = domain_val
            specs.append(
                {
                    "id": uuid.uuid4().hex[:10],
                    "tree_id": item_tree_id or uuid.uuid4().hex[:10],
                    "content": content,
                    "action": item_action,
                    "parent_id": resolved_parent_id,
                    "depends_on": list(item.get("depends_on") or []),
                    "refs": list(item.get("refs") or []),
                    "rule_bindings": list(bindings),
                    "depth": item_depth,
                    "metadata": item_metadata,
                }
            )

        created = engine.add_nodes_batch(specs)
        for node in created:
            created_refs.append(node.id)
            await _materialize_subject_rule_bindings(
                engine,
                session_id,
                subject_kind="thought",
                subject_id=node.id,
                subject_label=node.content,
                bindings=node.rule_bindings,
                source="think_graph",
            )

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            from aismartbuddy.tools import materialize_auto_graph

            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            # Build assigned-id list in batch order so int parent_ref values
            # resolve to the engine-assigned node ids.
            thought_ids = [node.id for node in created]
            synthetic = [
                {
                    "id": thought_ids[i],
                    "thought": specs[i]["content"],
                    "domain": thoughts[i].get("domain", ""),
                    "parent_ref": (
                        [thoughts[i]["parent_ref"]]
                        if thoughts[i].get("parent_ref") is not None
                        else []
                    ),
                }
                for i in range(len(thought_ids))
            ]

            def _resolve_thought_ref(r: object) -> str | None:
                if isinstance(r, int):
                    if 0 <= r < len(thought_ids):
                        return thought_ids[r]
                    return None
                # str → pass through (existing node id); None handled by
                # the empty list short-circuit above.
                return None

            graph_count = await materialize_auto_graph(
                eff_sid,
                synthetic,
                source_tag="think_graph",
                entity_type="thought",
                description_field="thought",
                edge_label="BranchOf",
                ref_field="parent_ref",
                ref_resolver=_resolve_thought_ref,
            )

        warning = _long_thought_warnings(
            [(f"thoughts[{i}]", spec["content"]) for i, spec in enumerate(specs)]
        )
        out_lines = [
            f"Session: {sid} | Batch nodes created: {len(created)}",
            "Node IDs: " + ", ".join(created_refs),
            "Trees: " + ", ".join(dict.fromkeys(node.tree_id for node in created)),
        ]
        if eff_auto_graph:
            out_lines.append(f"Graph nodes created: {graph_count}")
        out_lines.append("Status: batch added")
        result = warning + "\n".join(out_lines)
        return _store_idempotent_result(sid, idempotency_key, result)

    # ── Think / Branch / Synthesize: add new node ────────
    if not thought:
        raise ValueError(
            "thought is required in single-node mode. PREFER thoughts=[{thought, "
            "parent_ref, ...}, ...] for batch creation — same lock, fewer round-trips."
        )
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
    length_entries: list[tuple[str, str]] = [("thought", thought or "")]
    if children:
        for i, child in enumerate(children):
            child_content = str((child or {}).get("thought", ""))
            length_entries.append((f"children[{i}]", child_content))
    warning = _long_thought_warnings(length_entries)
    # Compose-next hint: after synthesize, nudge toward metacognitive review.
    if action == "synthesize":
        hint = _compose_next_hint("think_monitor", "refs", [nid])
        if hint:
            parts.append(hint)
    return _store_idempotent_result(sid, idempotency_key, warning + "\n".join(parts))


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

    Persona guidance for delegated analytical passes:
        - Domain Specialist: deep local expertise, high nuance, higher domain bias
        - Domain Alien: foreign-domain structural reasoning, useful for analogs
        - Constraint Auditor: checks hard limits and impossibility claims
        - Epistemologist: audits evidence quality and assumption load
        - Synthesis Integrator: reconciles multiple viewpoints into a coherent path

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
    auto_graph: bool = False,
    rule_profile_ids: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Multi-criteria decision analysis (1..N decisions).

    Use when: a decision has 2+ defensible options + explicit criteria.
    Do NOT use when: the answer is obvious (skip; just decide).

    items[]: STRICT batch — each item: id, decision_statement, options[≥2],
      criteria[≥1] (each {name, weight}), evaluations[], recommendation.
      Server REJECTS items missing any required field.
      Each item must be one decision. Do not pack multiple independent
      decisions, multiple recommendations, or unrelated tradeoff spaces into
      one item just because they share a topic.
    Single-form: backward-compat staged form (problem-definition → options
      → criteria → evaluation → analysis → recommendation).

    Pass auto_graph=True (requires session_create(backends=['think','graph']))
    to materialise each item as a KnowledgeNode with DerivedFrom edges in one
    round-trip.

    Args:
      items: STRICT — list of decision items as above.
      decision_statement, options, analysis_type, stage, decision_id,
        iteration, next_stage_needed, criteria, evaluations, recommendation:
        single-form fields.
      auto_graph: items[]-only. When True + parent session has graph backend,
        materialise each item as a KnowledgeNode + connects_to edges
        (DerivedFrom) in one round trip.
      session_id: omit to auto-create.

    Returns: decision ids[] in items[] mode, or single-form status.

    Returns a 'Suggested next:' line at end of response (items[] path) with
    canonical follow-up call pre-filled. Read it before deciding the next step.
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
                domain_val = str(it.get("domain", "")).strip()
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
                    domain=domain_val,
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

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            from aismartbuddy.tools import materialize_auto_graph

            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            graph_count = await materialize_auto_graph(
                eff_sid,
                items,
                source_tag="think_decide",
                entity_type="decision",
                description_field="recommendation",
                edge_label="DerivedFrom",
            )

        out_lines = [
            f"Session: {info.session_id} | Decisions: {len(ids)}",
            f"IDs: {', '.join(ids)}",
        ]
        if eff_auto_graph:
            out_lines.append(f"Graph nodes created: {graph_count}")
        out_lines.append("Status: decided")
        base = "\n".join(out_lines)
        hint = _compose_next_hint("score_evaluate", "analysis_refs", ids)
        return base + (f"\n{hint}" if hint else "")

    # ── Single-form backward-compat path ────────────────────
    _validate_enum(analysis_type, _DECISION_TYPES, "analysis_type")
    _validate_enum(stage, _DECISION_STAGES, "stage")
    if not decision_statement or not options or not decision_id:
        raise ValueError(
            "single-form requires decision_statement, options, decision_id. "
            "PREFER items=[{id, decision_statement, options, criteria, recommendation}, ...] "
            "for batch decisions."
        )

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
        Each item is one problem decomposition unit. Do not put several
        distinct subproblems, alternative conclusions, or unrelated reasoning
        branches into one item. If you have N meaningfully separate thoughts,
        create N items.
      single-item: backward-compat flexible form (problem/steps/reasoning/
        conclusion all optional). Use only for mid-analysis ad-hoc model
        application; prefer items[] at analysis START.

    Models: first_principles, opportunity_cost, error_propagation, rubber_duck,
    pareto_principle, assumptions_xray, fishbone, value_of_info, swot,
    pre_mortem, design_review, complexity, root_cause, kuba,
    systems_dynamics, inversion.

    Good fits for omics / assay interpretation:
    - measurement-boundary review
    - confounder x-ray
    - signal vs mechanism decomposition
    - cross-domain bridge mapping
    - intervention coverage / loop-breaking coverage

    Additional domain-general frames:
    - kuba: Know / Understand / Believe / Act progression and bottleneck finding
    - systems_dynamics: reinforcing loops, balancing loops, delays, leverage points
    - inversion: solve by analyzing guaranteed failure conditions first

    Output convention for downstream chaining:
    - conclusions should capture the main finding
    - include surfaced assumptions in reasoning or refs when they matter later
    - where possible, make the next tool call obvious from the conclusion

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

    Returns a 'Suggested next:' line at end of response (items[] path) with
    canonical follow-up call pre-filled. Read it before deciding the next step.
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
                domain_val = str(it.get("domain", "")).strip()
                rec = ModelRecord(
                    model_name=model_name,
                    problem=it["problem"],
                    steps=list(it["steps"]),
                    reasoning=it["reasoning"],
                    conclusion=it["conclusion"],
                    record_id=it["id"],
                    refs=collect_item_refs(it),
                    domain=domain_val,
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

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            graph_count = await materialize_auto_graph(
                eff_sid,
                items,
                source_tag=f"think_model:{model_name}",
                entity_type="concept",
                description_field="conclusion",
            )

        out = [
            f"Session: {info.session_id} | Model: {model_name} | Items: {len(item_ids)}",
            f"Item IDs: {', '.join(item_ids)}",
        ]
        if eff_auto_graph:
            out.append(f"Graph nodes created: {graph_count}")
        out.append("Status: scaffolded")
        hint = _compose_next_hint("score_evaluate", "analysis_refs", item_ids)
        if hint:
            out.append(hint)
        if model_name == "systems_dynamics":
            out.append(
                "Also consider: think_model(model_name=\"inversion\") — "
                "maps guaranteed-failure conditions from the loops you just identified."
            )
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
        # No steps yet — return framework guidance to help the AI.
        # Only emit the full framework block on the FIRST model call in this
        # session (engine.models has just been appended above, so count==1
        # means this is the first). Subsequent guidance-only calls get a
        # short pointer back to prior guidance.
        if len(engine.models) <= 1:
            lines.append(_MODEL_GUIDANCE[model_name])
            lines.append("Status: framework loaded — apply the steps above")
        else:
            lines.append(
                f"Status: framework {model_name} loaded — see prior guidance for steps"
            )
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
      Each item is one debugging thread. If you are chasing three independent
      failure modes, use three items rather than one blended narrative.
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
    auto_graph: bool = False,
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
    Each chain entry is one argument move. Do not collapse thesis,
    counterargument, rebuttal, and synthesis into one oversized entry.

    Pass auto_graph=True (requires session_create(backends=['think','graph']))
    to materialise each item as a KnowledgeNode with RespondsTo edges in one
    round-trip.

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
        auto_graph: chain[]-only. When True + parent session has graph backend,
            materialise each argument as a KnowledgeNode and each
            responds_to_index as a RespondsTo edge in one round trip.

    Returns:
        Single mode: compact status with argumentation chain progress.
        Batch mode: chain_id + ordered list of argument_ids.

    Returns a 'Suggested next:' line at end of response (chain[] path) with
    canonical follow-up call pre-filled. Read it before deciding the next step.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    # ── Batch chain mode ─────────────────────────────────
    if chain is not None:
        if len(chain) < 1:
            raise ValueError(
                "chain must be non-empty. Use chain=[{type, claim, premises, "
                "conclusion, ...}, ...] (PREFERRED) or single-mode with claim+premises+conclusion."
            )
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

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            from aismartbuddy.tools import materialize_auto_graph

            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            argument_ids = list(ids)
            synthetic = [
                {
                    "id": argument_ids[i],
                    "claim": entry.get("claim", ""),
                    "responds_to_index": (
                        [entry["responds_to_index"]]
                        if entry.get("responds_to_index") is not None
                        else []
                    ),
                }
                for i, entry in enumerate(chain)
            ]

            def _resolve_arg_ref(r: object) -> str | None:
                if isinstance(r, int) and 0 <= r < len(argument_ids):
                    return argument_ids[r]
                return None

            graph_count = await materialize_auto_graph(
                eff_sid,
                synthetic,
                source_tag="think_argue",
                entity_type="argument",
                description_field="claim",
                edge_label="RespondsTo",
                ref_field="responds_to_index",
                ref_resolver=_resolve_arg_ref,
            )

        out_lines = [
            f"Session: {info.session_id} | Chain: {chain_id}"
            f" | Batch: {len(ids)} arguments",
            f"Arg IDs: {', '.join(ids)}",
        ]
        if eff_auto_graph:
            out_lines.append(f"Graph nodes created: {graph_count}")
        out_lines.append("Status: dialectic batch applied")
        base = "\n".join(out_lines)
        hint = _compose_next_hint("think_monitor", "refs", ids)
        return base + (f"\n{hint}" if hint else "")

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
      Each item is one candidate hypothesis. Competing hypotheses belong in
      separate items so they remain independently addressable and falsifiable.
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

    Returns a 'Suggested next:' line at end of response (items[] path) with
    canonical follow-up call pre-filled. Read it before deciding the next step.
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

        from aismartbuddy.tools import collect_item_refs

        ids: list[str] = []
        with engine.state_lock:
            for it in items:
                domain_val = str(it.get("domain", "")).strip()
                rec = InquiryRecord(
                    inquiry_id=it["id"],
                    stage="hypothesis",
                    iteration=1,
                    observation=it["observation"],
                    question=it["question"],
                    hypothesis=it["hypothesis"],
                    refs=collect_item_refs(it),
                    domain=domain_val,
                )
                engine.upsert_inquiry(rec)
                ids.append(it["id"])

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            # Build description from hypothesis.statement
            normalized = [{**it, "_desc": it["hypothesis"]["statement"]} for it in items]
            graph_count = await materialize_auto_graph(
                eff_sid,
                normalized,
                source_tag="think_science",
                entity_type="question",
                description_field="_desc",
            )

        out = [
            f"Session: {info.session_id} | Hypotheses: {len(ids)}",
            f"IDs: {', '.join(ids)}",
        ]
        if eff_auto_graph:
            out.append(f"Graph nodes created: {graph_count}")
        if len(ids) == 1 and len(engine.inquiries) == 1:
            out.append(
                "Note: single hypothesis registered — consider adding competing "
                "alternatives. Single-hypothesis analysis is harder to falsify."
            )
        out.append("Status: hypothesized")
        hint = _compose_next_hint("think_argue", "chain", ids)
        if hint:
            out.append(hint)
        out.append(
            "Also consider: think_evidence(refs=[...]) to register supporting "
            "or refuting evidence for each hypothesis."
        )
        return "\n".join(out)

    # ── Single-stage backward-compat path ─────────────────────
    _validate_enum(stage, _SCIENCE_STAGES, "stage")
    if not inquiry_id:
        raise ValueError(
            "inquiry_id required for single-stage form. "
            "PREFER items=[{id, observation, question, hypothesis:{...}}, ...] "
            "for batch hypotheses."
        )

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
    action: str | None = None,
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

    action="density": return session load stats (node_count, tree_count, max_depth,
      entity_refs, export_token_estimate, recommendation: summarize|delegate|continue).
      No items or stage needed. session_id: omit to auto-create or reuse active session.

    items[]: STRICT batch — each item: id, task, knowledge {domain, level∈
      {expert,proficient,familiar,basic,minimal,none}, confidence,
       limitations[≥1]}, claims[≥1] of {claim, status∈{fact,inference,
       speculation,uncertain}, confidence, evidence}. REJECTS empty
       limitations.
      Each item is one assessment target. Do not combine multiple tasks,
      multiple subjects, or unrelated claim sets into one item.
    Single-form: backward-compat staged form for iterative monitoring.

    Args:
      action: optional dispatch — "density" returns session load stats; omit
        for the standard items[]/single-form monitoring behavior.
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

    Returns a 'Suggested next:' line at end of response (items[] path) with
    canonical follow-up call pre-filled. Read it before deciding the next step.
    """
    if action == "density":
        _, info = await anyio.to_thread.run_sync(
            lambda: _get_or_create_think_session(session_id, ctx)
        )
        engine = _engine(info)
        stats = await anyio.to_thread.run_sync(engine.get_session_stats)
        total = stats.get("total_records", stats["node_count"])
        if total > 100 or stats["export_token_estimate"] > 6000:
            rec = "summarize"
        elif stats["tree_count"] > 4 and total > 50:
            rec = "delegate"
        else:
            rec = "continue"
        by_type = stats.get("record_counts", {})
        lines = [
            f"Session: {info.session_id}",
            f"total_records: {total}  nodes: {stats['node_count']}  "
            f"trees: {stats['tree_count']}  max_depth: {stats['max_depth']}",
            f"entity_refs: {stats['entity_count']}  revisions: {stats['revision_count']}",
            f"export_token_estimate: {stats['export_token_estimate']}",
            f"by_type: {by_type}",
            f"recommendation: {rec}",
        ]
        return "\n".join(lines)

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
                domain_val = str(it.get("domain", "")).strip()
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
                    domain=domain_val,
                )
                engine.upsert_monitor(rec)
                ids.append(it["id"])

        eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
        eff_sid = effective_session_id(session_id, info)
        graph_count = 0
        if eff_auto_graph:
            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            normalized = [{**it, "_desc": it["task"]} for it in items]
            graph_count = await materialize_auto_graph(
                eff_sid,
                normalized,
                source_tag="think_monitor",
                entity_type="insight",
                description_field="_desc",
            )

        out = [
            f"Session: {info.session_id} | Assessments: {len(ids)}",
            f"IDs: {', '.join(ids)}",
        ]
        if eff_auto_graph:
            out.append(f"Graph nodes created: {graph_count}")
        out.append("Status: monitored")
        hint = _compose_next_hint("think_validate", "refs", ids)
        if hint:
            out.append(hint)
        return "\n".join(out)

    # ── Single-form backward-compat path ────────────────────
    _validate_enum(stage, _MONITOR_STAGES, "stage")
    if not monitoring_id:
        raise ValueError(
            "monitoring_id required for single-form. "
            "PREFER items=[{id, task, knowledge:{...}, claims:[...]}, ...] "
            "for batch self-assessment."
        )
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
      add_rules_batch: strict batch add of rules to a profile. Each batch
        entry is one rule, not a paragraph containing several requirements.
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
    auto_graph: bool = False,
    ctx: _MCPContext | None = None,
) -> str:
    """[ASSESS] Validate a plan/artifact against weighted hard+soft rule profiles.

    Returns a validation record with hard-gate status, weighted score, gaps,
    uncovered rules, conflicts, and nuance notes. Use this when rules must
    persist across long chats and related subplans.

    Pass auto_graph=True (requires session_create(backends=['think','graph']))
    to materialise each item as a KnowledgeNode with Validates edges in one
    round-trip. Validates edges require the subject_id to already be a
    KnowledgeNode (e.g., chain auto_graph from your scaffold/decision tools
    earlier in the session). Otherwise the edge is silently skipped.

    items[]: each item requires:
        subject_id (str, required): ID of the thing being validated.
        assessments (list, required): list of assessment dicts, each requiring:
            rule_id (str, required): identifier for the rule being assessed.
            status (str, required): one of satisfies | violates | uncertain |
                not_applicable.
            note (str, optional): explanation.
            refs (list[str], optional): supporting reference IDs.
        subject_kind (str, optional): label for the subject type.
        rule_profile_ids (list[str], optional): rule profiles to check against.
        use_bound_profiles (bool, optional): include session-bound profiles.
        validation_id (str, optional): stable ID; auto-generated if omitted.
        refs (list[str], optional): cross-record references.
        nuance_notes (list[str], optional): caveats that do not affect scoring.
    """
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)
    eff_auto_graph = resolve_auto_graph(auto_graph, info, session_id)
    eff_sid = effective_session_id(session_id, info)

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
                rule_id = assessment.get("rule_id") or ""
                if not rule_id:
                    raise ValueError(
                        f"think_validate items[{i}].assessments[{j}]: "
                        "rule_id is required. Provide a rule identifier string "
                        "(e.g. \"must_cover_auth\", \"R1\")."
                    )
                parsed_assessments.append(
                    ValidationAssessment(
                        rule_id=rule_id,
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
            await _materialize_rule_graph(eff_sid, validation=record)

        graph_count = 0
        if eff_auto_graph:
            from aismartbuddy.tools import materialize_auto_graph

            if not eff_sid:
                raise ValueError(
                    "auto_graph requires a parent session with a graph backend. "
                    "Use session_create(backends=['think','graph']) or omit session_id "
                    "to auto-create a session with graph support."
                )
            # subject_id is a single string per item — wrap as a 1-element list
            # so materialize_auto_graph iterates a single Validates edge per
            # validation. The Validates edge is silently skipped if the
            # subject_id is not already a KnowledgeNode.
            synthetic = [
                {
                    "id": ids[i],
                    "rationale": (
                        item.get("rationale")
                        or item.get("note")
                        or item.get("subject_id", "")
                    ),
                    "subject_id": (
                        [item["subject_id"]] if item.get("subject_id") else []
                    ),
                }
                for i, item in enumerate(items)
            ]
            graph_count = await materialize_auto_graph(
                eff_sid,
                synthetic,
                source_tag="think_validate",
                entity_type="validation",
                description_field="rationale",
                edge_label="Validates",
                ref_field="subject_id",
            )

        out_lines = [
            f"Session: {info.session_id} | Validations: {len(ids)}",
            f"IDs: {', '.join(ids)}",
        ]
        if eff_auto_graph:
            out_lines.append(f"Graph nodes created: {graph_count}")
        out_lines.append("Status: validated")
        return "\n".join(out_lines)

    if not subject_id:
        raise ValueError("subject_id is required")
    parsed_assessments = []
    for i, assessment in enumerate(assessments or []):
        _validate_enum(assessment["status"], _VALIDATION_STATUSES, f"assessments[{i}].status")
        rule_id = assessment.get("rule_id") or ""
        if not rule_id:
            raise ValueError(
                f"think_validate assessments[{i}]: "
                "rule_id is required. Provide a rule identifier string "
                "(e.g. \"must_cover_auth\", \"R1\")."
            )
        parsed_assessments.append(
            ValidationAssessment(
                rule_id=rule_id,
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


async def think_set_active_session(session_id: str) -> str:
    """[ELABORATE] Set the implicit active session for subsequent tools."""
    mgr = get_session_manager()
    actual = await anyio.to_thread.run_sync(lambda: mgr.set_active_session(session_id))
    return f"Active session set.\nsession_id: {actual}"


@size_guarded
async def think_get_subtree(
    node_id: str,
    session_id: str | None = None,
    depth: int | None = None,
) -> str:
    """[ELABORATE] Return a node and its descendants as an outline."""
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    node = engine.get_node(node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' not found")
    if depth is not None and depth < 0:
        raise ValueError("depth must be >= 0")
    outline = _render_subtree_outline(engine, node_id, depth)
    return (
        f"Session: {info.session_id}\n"
        f"Node: {node_id} | Tree: {node.tree_id} | "
        f"Depth limit: {depth if depth is not None else 'full'}\n"
        f"{outline}"
    )


async def think_get_path(node_id: str, session_id: str | None = None) -> str:
    """[ELABORATE] Return the ancestry path from root to a node."""
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    path = engine.get_path_to_root(node_id)
    if not path:
        raise ValueError(f"Node '{node_id}' not found")
    path.reverse()
    lines = [f"Session: {info.session_id}", f"Path length: {len(path)}"]
    for level, node in enumerate(path):
        lines.append(f"{level}. {node.id} [{node.action}] {_short(node.content, 100)}")
    return "\n".join(lines)


@size_guarded
async def think_export_session(
    session_id: str | None = None,
    format: str = "outline",
) -> str:
    """[ELABORATE] Export full thought-tree state for session handoff/resume."""
    if format not in {"outline", "flat", "json"}:
        raise ValueError("format must be outline|flat|json")
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    if format == "json":
        import json

        payload = {
            "session_id": info.session_id,
            "trees": [
                {
                    "tree_id": tree_id,
                    "root_id": root_id,
                    "nodes": [
                        _node_to_export_dict(node) for node in engine.get_subtree_nodes(root_id)
                    ],
                }
                for tree_id, root_id in engine.thought_trees.items()
            ],
        }
        return json.dumps(payload, indent=2)
    if format == "flat":
        lines = [f"Session: {info.session_id}", "Thought nodes:"]
        for node in sorted(
            engine.thought_nodes.values(), key=lambda n: (n.tree_id, n.depth, n.created_at)
        ):
            lines.append(
                f"- {node.id} | tree={node.tree_id} | parent={node.parent_id or '-'} "
                f"| depth={node.depth} | {node.action} | {_short(node.content, 100)}"
            )
        return "\n".join(lines)

    lines = [
        f"Session: {info.session_id}",
        f"Trees: {len(engine.thought_trees)} | Nodes: {len(engine.thought_nodes)}",
    ]
    for tree_id, root_id in engine.thought_trees.items():
        root = engine.get_node(root_id)
        lines.append(f"\nTree {tree_id} — {_short(root.content if root else root_id, 80)}")
        lines.append(_render_subtree_outline(engine, root_id, None))
    return "\n".join(lines)


async def think_link_sessions(
    session_a: str,
    node_a_id: str,
    session_b: str,
    node_b_id: str,
    relationship: str,
) -> str:
    """[ELABORATE] Create a cross-session relationship between two nodes/artifacts."""
    mgr = get_session_manager()
    link = await anyio.to_thread.run_sync(
        lambda: mgr.add_session_link(session_a, node_a_id, session_b, node_b_id, relationship)
    )
    return (
        f"Link: {link.id}\n"
        f"{link.session_a}:{link.node_a_id} --[{link.relationship}]--> "
        f"{link.session_b}:{link.node_b_id}"
    )


async def think_get_session_links(session_id: str | None = None) -> str:
    """[ELABORATE] Return all cross-session links touching a session."""
    actual_session_id = resolve_active_or_provided_session_id(session_id)
    if not actual_session_id:
        raise ValueError("session_id is required unless an active session is set")
    mgr = get_session_manager()
    links = await anyio.to_thread.run_sync(lambda: mgr.list_session_links(actual_session_id))
    if not links:
        return f"Session: {actual_session_id}\nNo cross-session links."
    lines = [f"Session: {actual_session_id}", f"Links: {len(links)}"]
    for link in links:
        lines.append(
            f"- {link.id}: {link.session_a}:{link.node_a_id} "
            f"--[{link.relationship}]--> {link.session_b}:{link.node_b_id}"
        )
    return "\n".join(lines)


async def think_graph_validate(
    node_id: str,
    session_id: str | None = None,
    auto_branch_on_warning: bool = False,
) -> str:
    """[ELABORATE] Validate a thought node for granularity and structural completeness."""
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    node = engine.get_node(node_id)
    if node is None:
        raise ValueError(f"Node '{node_id}' not found")

    warnings: list[str] = []
    suggestions: list[str] = []
    content = node.content.strip()
    sentence_count = len([part for part in re.split(r"[.!?]+", content) if part.strip()])
    if len(content) > 280 or sentence_count > 3:
        warnings.append("Node is too long; split into smaller thought units")
        suggestions.append("Split this node into smaller claims or sub-questions")
    if re.search(
        r"\b(however|therefore|additionally|meanwhile|on the other hand)\b", content, re.I
    ):
        warnings.append("Node likely contains multiple semantic moves")
        suggestions.append("Separate the contrasted or sequential ideas into sibling child nodes")
    if node.action == "synthesize" and not node.children and not node.refs:
        warnings.append("Synthesis node has no explicit synthesis inputs")
        suggestions.append("Add refs to the nodes this synthesis depends on")
    expected_children = node.metadata.get("expected_children")
    if expected_children is not None and len(node.children) < int(expected_children):
        warnings.append(f"Expected {expected_children} children but found {len(node.children)}")
        suggestions.append("Add missing child nodes before relying on this branch as complete")

    status = "pass" if not warnings else "warning"
    created_ids: list[str] = []
    if warnings and auto_branch_on_warning:
        created = engine.add_nodes_batch(
            [
                {
                    "id": uuid.uuid4().hex[:10],
                    "tree_id": node.tree_id,
                    "content": suggestion,
                    "action": "think",
                    "parent_id": node.id,
                    "depth": node.depth + 1,
                    "metadata": {"origin": "think_graph_validate", "validation_target": node.id},
                    "refs": [],
                    "depends_on": [],
                    "rule_bindings": [],
                }
                for suggestion in dict.fromkeys(suggestions)
            ]
        )
        created_ids = [created_node.id for created_node in created]

    node.validation_results.append(
        {
            "validation_id": uuid.uuid4().hex[:10],
            "passed_hard_gates": not warnings,
            "weighted_score": 100.0 if not warnings else max(40.0, 100.0 - (len(warnings) * 20.0)),
            "warnings": list(warnings),
            "suggestions": list(dict.fromkeys(suggestions)),
        }
    )
    lines = [f"Session: {info.session_id}", f"Node: {node_id}", f"Status: {status}"]
    if warnings:
        lines.append("Warnings: " + " | ".join(warnings))
    if suggestions:
        lines.append("Suggestions: " + " | ".join(dict.fromkeys(suggestions)))
    if created_ids:
        lines.append("Auto-branch created: " + ", ".join(created_ids))
    return "\n".join(lines)


async def think_hypothesis(
    action: str,
    session_id: str | None = None,
    hypothesis_id: str | None = None,
    statement: str | None = None,
    domain: str | None = None,
    prior_weight: float = 0.5,
    predictions: list[dict] | None = None,
    evidence_text: str | None = None,
    direction: str | None = None,
    strength: float = 0.5,
    source_domain: str | None = None,
    hypothesis_ids: list[str] | None = None,
    new_predictions: list[dict] | None = None,
    revised_statement: str | None = None,
    reason: str | None = None,
    invalidated_by: str | None = None,
    items: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[SCAFFOLD] Register, compare, update, and invalidate competing hypotheses.

    PREFER items=[...] (or *_ids=[...] for invalidate/remove) on every action
    when handling one-or-more records — list-form scales without added
    round-trips. Single-record args remain supported for backward-compat.
    """
    _validate_enum(action, _HYPOTHESIS_ACTIONS, "action")
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    if action == "register":
        # ── List-form path ──────────────────────────────────
        if items is not None:
            from aismartbuddy.tools import validate_items

            single_form_args = bool(
                statement
                or hypothesis_id
                or domain
                or predictions
            )
            if single_form_args:
                raise ValueError(
                    "think_hypothesis.register: pass either items=[...] "
                    "(preferred) or single-record args, not both."
                )
            validate_items(
                items,
                required=["statement"],
                tool="think_hypothesis",
            )
            from aismartbuddy.tools import collect_item_refs as _collect_refs

            ids: list[str] = []
            with engine.state_lock:
                for it in items:
                    pw = float(it.get("prior_weight", 0.5))
                    confidence = float(it.get("confidence", pw))
                    record = HypothesisRecord(
                        id=it["id"],
                        statement=it["statement"],
                        domain=str(it.get("domain", "") or it.get("kind", "") or ""),
                        prior_weight=max(0.0, min(1.0, pw)),
                        posterior_weight=max(0.0, min(1.0, confidence)),
                        predictions=list(it.get("predictions") or []),
                        refs=_collect_refs(it),
                    )
                    engine.upsert_hypothesis(record)
                    ids.append(it["id"])
            return (
                f"Hypotheses registered: {len(ids)}\n"
                f"IDs: {', '.join(ids)}\n"
                "Status: registered"
            )

        if not statement:
            raise ValueError("statement is required for register")
        hid = hypothesis_id or f"hyp_{uuid.uuid4().hex[:8]}"
        record = HypothesisRecord(
            id=hid,
            statement=statement,
            domain=domain or "",
            prior_weight=max(0.0, min(1.0, prior_weight)),
            posterior_weight=max(0.0, min(1.0, prior_weight)),
            predictions=list(predictions or []),
        )
        engine.upsert_hypothesis(record)
        return f"Session: {info.session_id} | Hypothesis: {hid}\nStatus: registered"

    if action == "evidence":
        if not hypothesis_id or not evidence_text or not direction:
            raise ValueError(
                "hypothesis_id, evidence_text, and direction are required for evidence"
            )
        _validate_enum(direction, _HYPOTHESIS_EVIDENCE_DIRECTIONS, "direction")
        record = engine.add_hypothesis_evidence(
            hypothesis_id,
            text=evidence_text,
            direction=direction,
            strength=strength,
            source_domain=source_domain or "",
        )
        return (
            f"Session: {info.session_id} | Hypothesis: {record.id}\n"
            f"Posterior: {record.posterior_weight:.3f} | Evidence count: {len(record.evidence)}"
        )

    if action == "compare":
        rows = sorted(
            engine.get_hypotheses(),
            key=lambda record: (record.invalidated, -record.posterior_weight, record.created_at),
        )
        if not rows:
            return f"Session: {info.session_id}\nNo hypotheses registered."
        lines = [f"Session: {info.session_id}", f"Hypotheses: {len(rows)}"]
        for record in rows:
            state = "invalidated" if record.invalidated else "active"
            lines.append(
                f"- {record.id}: {state} | prior={record.prior_weight:.3f} "
                f"| posterior={record.posterior_weight:.3f} | evidence={len(record.evidence)} "
                f"| domain={record.domain or '?'} | {_short(record.statement, 70)}"
            )
        return "\n".join(lines)

    if action == "discriminate":
        ids = hypothesis_ids or ([hypothesis_id] if hypothesis_id else [])
        if len(ids) < 2:
            raise ValueError("discriminate requires 2+ hypothesis ids")
        selected = []
        for hid in ids:
            record = engine.get_hypothesis(hid)
            if record is None:
                raise ValueError(f"Hypothesis '{hid}' not found")
            selected.append(record)
        prediction_map: dict[str, set[str]] = {}
        for record in selected:
            for prediction in record.predictions:
                observable = str(prediction.get("observable", "")).strip()
                predicted_value = str(prediction.get("predicted_value", "")).strip()
                if observable:
                    prediction_map.setdefault(observable, set()).add(
                        f"{record.id}:{predicted_value}"
                    )
        ranked = sorted(prediction_map.items(), key=lambda item: (-(len(item[1])), item[0]))
        if not ranked:
            return (
                f"Session: {info.session_id}\n"
                "No predictions registered for discriminating comparison."
            )
        observable, variants = ranked[0]
        return (
            f"Session: {info.session_id}\n"
            f"Best discriminating observable: {observable}\n"
            f"Predictions: {', '.join(sorted(variants))}"
        )

    if action == "update":
        if not hypothesis_id:
            raise ValueError("hypothesis_id is required for update")
        record = engine.update_hypothesis(
            hypothesis_id,
            new_predictions=new_predictions,
            revised_statement=revised_statement,
        )
        return f"Session: {info.session_id} | Hypothesis: {record.id}\nStatus: updated"

    # action == "invalidate"
    # ── List-form path ──────────────────────────────────
    if hypothesis_ids:
        if hypothesis_id:
            raise ValueError(
                "think_hypothesis.invalidate: pass either hypothesis_ids=[...] "
                "(preferred) or single-record args, not both."
            )
        validated_ids: list[str] = []
        for i, hid in enumerate(hypothesis_ids):
            if not (isinstance(hid, str) and hid):
                raise ValueError(
                    f"think_hypothesis.invalidate: hypothesis_ids[{i}] must be "
                    "a non-empty string"
                )
            validated_ids.append(hid)
        seen: set[str] = set()
        for i, hid in enumerate(validated_ids):
            if hid in seen:
                raise ValueError(
                    f"think_hypothesis.invalidate: hypothesis_ids[{i}] "
                    f"duplicate id '{hid}'"
                )
            seen.add(hid)
        invalidated_records: list[str] = []
        invalidation_reason = reason or invalidated_by or "invalidated"
        with engine.state_lock:
            for hid in validated_ids:
                rec = engine.invalidate_hypothesis(hid, invalidation_reason)
                invalidated_records.append(rec.id)
        return (
            f"Hypotheses invalidated: {len(invalidated_records)}\n"
            f"IDs: {', '.join(invalidated_records)}\n"
            f"Status: invalidated | Reason: {invalidation_reason}"
        )

    if not hypothesis_id:
        raise ValueError("hypothesis_id is required for invalidate")
    record = engine.invalidate_hypothesis(
        hypothesis_id,
        reason or invalidated_by or "invalidated",
    )
    return (
        f"Session: {info.session_id} | Hypothesis: {record.id}\n"
        f"Status: invalidated | Reason: {record.invalidation_reason}"
    )


async def think_constraint(
    action: str,
    session_id: str | None = None,
    constraint_id: str | None = None,
    domain: str | None = None,
    type: str | None = None,
    statement: str | None = None,
    check_description: str | None = None,
    applies_to: list[str] | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_text: str | None = None,
    status: str | None = None,
    note: str | None = None,
    items: list[dict] | None = None,
    constraint_ids: list[str] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Register constraints and validate targets against them.

    Constraints are composable informational units — named rules your reasoning
    can reference and check against. `type` ("hard"/"soft") is a semantic label
    only; the server does not auto-propagate constraint violations to confidence
    scores or block other records. The value is in making constraints explicit,
    addressable, and sweepable — not in enforcement.

    PREFER items=[...] (or *_ids=[...] for invalidate/remove) on every action
    when handling one-or-more records — list-form scales without added
    round-trips. Single-record args remain supported for backward-compat.

    `check_all` performs a real sweep: for each applicable constraint and each
    matching target, it returns a matrix row. Existing validations are reused;
    missing ones are created as `uncertain` so the gap remains explicit rather
    than silently skipped.
    """
    _validate_enum(action, _CONSTRAINT_ACTIONS, "action")
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    def _target_rows(kind: str, explicit_id: str | None) -> list[tuple[str, str]]:
        if kind == "hypothesis":
            rows = [(record.id, record.statement) for record in engine.get_hypotheses()]
        elif kind == "thought":
            rows = [(node.id, node.content) for node in engine.thought_nodes.values()]
        elif kind == "model":
            rows = [
                (
                    record.record_id or f"model:{index}",
                    record.problem or record.conclusion or record.model_name,
                )
                for index, record in enumerate(engine.models, start=1)
            ]
        elif kind == "decision":
            rows = [
                (
                    record.decision_id,
                    record.statement or record.recommendation or record.stage,
                )
                for record in engine.decisions.values()
            ]
        elif kind == "holon":
            rows = [
                (record.id, record.description or record.name)
                for record in engine.holon_nodes.values()
            ]
        elif kind == "evaluation":
            rows = [
                (record.id, record.context or record.rubric_id)
                for record in engine.evaluations.values()
            ]
        else:
            raise ValueError(
                "target_type must be one of: hypothesis, thought, model, "
                "decision, holon, evaluation"
            )
        if explicit_id:
            rows = [row for row in rows if row[0] == explicit_id]
            if not rows:
                raise ValueError(f"{kind} '{explicit_id}' not found")
        return rows

    if action == "register":
        # ── List-form path ──────────────────────────────────
        if items is not None:
            from aismartbuddy.tools import validate_items

            single_form_args = bool(
                constraint_id or statement or domain or type or applies_to
            )
            if single_form_args:
                raise ValueError(
                    "think_constraint.register: pass either items=[...] "
                    "(preferred) or single-record args, not both."
                )

            def _check_type(t: object) -> str | None:
                if t not in _CONSTRAINT_TYPES:
                    return f"must be one of {sorted(_CONSTRAINT_TYPES)}"
                return None

            validate_items(
                items,
                required=["domain", "type", "statement"],
                tool="think_constraint",
                item_validators={"type": _check_type},
            )
            from aismartbuddy.tools import collect_item_refs as _collect_refs

            registered_ids: list[str] = []
            with engine.state_lock:
                for it in items:
                    engine.upsert_constraint(
                        ConstraintRecord(
                            id=it["id"],
                            domain=str(it["domain"]),
                            constraint_type=str(it["type"]),
                            statement=str(it["statement"]),
                            check_description=str(it.get("check_description", "") or ""),
                            applies_to=list(it.get("applies_to") or []),
                            refs=_collect_refs(it),
                        )
                    )
                    registered_ids.append(it["id"])
            return (
                f"Constraints registered: {len(registered_ids)}\n"
                f"IDs: {', '.join(registered_ids)}\n"
                "Status: registered"
            )

        if not constraint_id or not statement or not domain or not type:
            raise ValueError("constraint_id, domain, type, and statement are required for register")
        _validate_enum(type, _CONSTRAINT_TYPES, "type")
        engine.upsert_constraint(
            ConstraintRecord(
                id=constraint_id,
                domain=domain,
                constraint_type=type,
                statement=statement,
                check_description=check_description or "",
                applies_to=list(applies_to or []),
            )
        )
        return f"Session: {info.session_id} | Constraint: {constraint_id}\nStatus: registered"

    if action == "list":
        rows = engine.get_constraints()
        if not rows:
            return f"Session: {info.session_id}\nNo constraints registered."
        lines = [f"Session: {info.session_id}", f"Constraints: {len(rows)}"]
        for row in rows:
            lines.append(
                f"- {row.id}: {row.constraint_type} | {row.domain} | {_short(row.statement, 80)}"
            )
        return "\n".join(lines)

    if action == "remove":
        # ── List-form path ──────────────────────────────────
        if constraint_ids:
            if constraint_id:
                raise ValueError(
                    "think_constraint.remove: pass either constraint_ids=[...] "
                    "(preferred) or single-record args, not both."
                )
            validated_ids: list[str] = []
            for i, cid in enumerate(constraint_ids):
                if not (isinstance(cid, str) and cid):
                    raise ValueError(
                        f"think_constraint.remove: constraint_ids[{i}] must be "
                        "a non-empty string"
                    )
                validated_ids.append(cid)
            seen: set[str] = set()
            for i, cid in enumerate(validated_ids):
                if cid in seen:
                    raise ValueError(
                        f"think_constraint.remove: constraint_ids[{i}] "
                        f"duplicate id '{cid}'"
                    )
                seen.add(cid)
            with engine.state_lock:
                for cid in validated_ids:
                    engine.remove_constraint(cid)
            return (
                f"Constraints removed: {len(validated_ids)}\n"
                f"IDs: {', '.join(validated_ids)}\n"
                "Status: removed"
            )

        if not constraint_id:
            raise ValueError("constraint_id is required for remove")
        engine.remove_constraint(constraint_id)
        return f"Session: {info.session_id} | Constraint: {constraint_id}\nStatus: removed"

    if action == "validate":
        if not constraint_id or not target_type:
            raise ValueError("constraint_id and target_type are required for validate")
        constraint = engine.get_constraint(constraint_id)
        if constraint is None:
            raise ValueError(f"Constraint '{constraint_id}' not found")
        result = status or "uncertain"
        _validate_enum(result, _CONSTRAINT_VALIDATION_RESULTS, "status")
        validation = ConstraintValidationRecord(
            id=f"cval_{uuid.uuid4().hex[:8]}",
            constraint_id=constraint_id,
            target_type=target_type,
            target_id=target_id or "",
            target_text=target_text or "",
            status=result,
            note=note or "",
        )
        engine.add_constraint_validation(validation)
        return (
            f"Session: {info.session_id} | Constraint validation: {validation.id}\n"
            f"Constraint: {constraint_id} | "
            f"Target: {target_type}:{target_id or '-'} | Status: {result}"
        )

    if not target_type:
        raise ValueError("target_type is required for check_all")

    targets = _target_rows(target_type, target_id)
    constraints = engine.get_constraints()
    applicable_constraints = [
        constraint
        for constraint in constraints
        if not constraint.applies_to or target_type in constraint.applies_to
    ]
    if not applicable_constraints:
        return (
            f"Session: {info.session_id}\n"
            f"Constraint sweep target_type={target_type}\n"
            "No applicable constraints."
        )
    if not targets:
        return (
            f"Session: {info.session_id}\n"
            f"Constraint sweep target_type={target_type}\n"
            "No targets found."
        )

    created = 0
    matrix_rows: list[ConstraintValidationRecord] = []
    for constraint in applicable_constraints:
        for row_target_id, row_text in targets:
            existing = engine.get_constraint_validations(
                constraint_id=constraint.id,
                target_type=target_type,
                target_id=row_target_id,
            )
            if existing:
                matrix_rows.append(existing[-1])
                continue
            validation = ConstraintValidationRecord(
                id=f"cval_{uuid.uuid4().hex[:8]}",
                constraint_id=constraint.id,
                target_type=target_type,
                target_id=row_target_id,
                target_text=row_text,
                status="uncertain",
                note=(
                    "Auto-generated by check_all. No explicit validation recorded yet; "
                    "manual assessment required."
                ),
            )
            engine.add_constraint_validation(validation)
            matrix_rows.append(validation)
            created += 1

    pass_count = sum(1 for row in matrix_rows if row.status == "pass")
    fail_count = sum(1 for row in matrix_rows if row.status == "fail")
    uncertain_count = sum(1 for row in matrix_rows if row.status == "uncertain")
    lines = [
        f"Session: {info.session_id}",
        (
            f"Constraint sweep: {len(applicable_constraints)} constraints x {len(targets)} "
            f"{target_type} targets = {len(matrix_rows)} checks"
        ),
        f"Created missing validations: {created}",
        f"Status counts: pass={pass_count} fail={fail_count} uncertain={uncertain_count}",
        "Matrix:",
    ]
    for row in matrix_rows[:30]:
        lines.append(
            f"- constraint={row.constraint_id} | target={row.target_type}:{row.target_id} "
            f"| status={row.status} | note={_short(row.note, 80)}"
        )
    if len(matrix_rows) > 30:
        lines.append(f"- ... ({len(matrix_rows) - 30} more)")
    return "\n".join(lines)


async def think_topology(
    action: str,
    session_id: str | None = None,
    topology_id: str | None = None,
    name: str | None = None,
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
    source_description: str | None = None,
    source_domain: str | None = None,
    topology_a_id: str | None = None,
    topology_b_id: str | None = None,
    target_domain: str | None = None,
    pattern: str | None = None,
    items: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Define, compare, and translate domain-neutral structural topologies.

    PREFER items=[...] (or *_ids=[...] for invalidate/remove) on every action
    when handling one-or-more records — list-form scales without added
    round-trips. Single-record args remain supported for backward-compat.
    """
    _validate_enum(action, _TOPOLOGY_ACTIONS, "action")
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    if action == "define":
        # ── List-form path ──────────────────────────────────
        if items is not None:
            from aismartbuddy.tools import validate_items

            single_form_args = bool(
                topology_id or name or nodes or edges
                or source_description or source_domain
            )
            if single_form_args:
                raise ValueError(
                    "think_topology.define: pass either items=[...] "
                    "(preferred) or single-record args, not both."
                )

            def _check_nodes(ns: object) -> str | None:
                if not isinstance(ns, list) or not ns:
                    return "must be a non-empty list of {id, role}"
                for j, n in enumerate(ns):
                    if not isinstance(n, dict):
                        return f"nodes[{j}] must be a dict"
                    if n.get("role") not in _TOPOLOGY_NODE_ROLES:
                        return (
                            f"nodes[{j}].role must be one of "
                            f"{sorted(_TOPOLOGY_NODE_ROLES)}"
                        )
                return None

            def _check_edges(es: object) -> str | None:
                if not isinstance(es, list):
                    return "must be a list"
                for j, e in enumerate(es):
                    if not isinstance(e, dict):
                        return f"edges[{j}] must be a dict"
                    if e.get("type") not in _TOPOLOGY_EDGE_TYPES:
                        return (
                            f"edges[{j}].type must be one of "
                            f"{sorted(_TOPOLOGY_EDGE_TYPES)}"
                        )
                return None

            validate_items(
                items,
                required=["domain", "nodes"],
                tool="think_topology",
                item_validators={
                    "nodes": _check_nodes,
                    "edges": _check_edges,
                },
            )
            defined_ids: list[str] = []
            with engine.state_lock:
                for it in items:
                    record = TopologyRecord(
                        id=it["id"],
                        name=str(it.get("name", "") or it["id"]),
                        source_domain=str(it["domain"]),
                        source_description=str(it.get("source_description", "") or ""),
                        nodes=list(it["nodes"]),
                        edges=list(it["edges"]),
                    )
                    engine.upsert_topology(record)
                    defined_ids.append(it["id"])
            return (
                f"Topologies defined: {len(defined_ids)}\n"
                f"IDs: {', '.join(defined_ids)}\n"
                "Status: defined"
            )

        if not topology_id or not name:
            raise ValueError("topology_id and name are required for define")
        for i, node in enumerate(nodes or []):
            if node.get("role") not in _TOPOLOGY_NODE_ROLES:
                raise ValueError(f"nodes[{i}].role must be one of {sorted(_TOPOLOGY_NODE_ROLES)}")
        for i, edge in enumerate(edges or []):
            if edge.get("type") not in _TOPOLOGY_EDGE_TYPES:
                raise ValueError(f"edges[{i}].type must be one of {sorted(_TOPOLOGY_EDGE_TYPES)}")
        engine.upsert_topology(
            TopologyRecord(
                id=topology_id,
                name=name,
                source_domain=source_domain or "",
                source_description=source_description or "",
                nodes=list(nodes or []),
                edges=list(edges or []),
            )
        )
        return f"Session: {info.session_id} | Topology: {topology_id}\nStatus: defined"

    if action == "abstract":
        if not source_description:
            raise ValueError("source_description is required for abstract")
        topology_id = topology_id or f"topo_{uuid.uuid4().hex[:8]}"
        abstract_nodes: list[dict] = []
        lower = source_description.lower()
        role_map = [
            ("sensor", "SENSOR"),
            ("detect", "SENSOR"),
            ("buffer", "BUFFER"),
            ("queue", "BUFFER"),
            ("switch", "SWITCH"),
            ("gate", "GATE"),
            ("source", "SOURCE"),
            ("sink", "SINK"),
            ("junction", "JUNCTION"),
        ]
        for token, role in role_map:
            if token in lower:
                abstract_nodes.append({"id": token, "role": role, "label": token})
        if not abstract_nodes:
            abstract_nodes = [{"id": "system", "role": "JUNCTION", "label": "system"}]
        record = TopologyRecord(
            id=topology_id,
            name=name or topology_id,
            source_domain=source_domain or "",
            source_description=source_description,
            nodes=abstract_nodes,
            edges=list(edges or []),
        )
        engine.upsert_topology(record)
        return (
            f"Session: {info.session_id} | Topology: {record.id}\n"
            f"Abstract nodes: {len(record.nodes)} | Status: abstracted"
        )

    if action == "compare":
        if not topology_a_id or not topology_b_id:
            raise ValueError("topology_a_id and topology_b_id are required for compare")
        left = engine.get_topology(topology_a_id)
        right = engine.get_topology(topology_b_id)
        if left is None or right is None:
            raise ValueError("Both topology ids must exist")
        left_roles = {node.get("role") for node in left.nodes}
        right_roles = {node.get("role") for node in right.nodes}
        shared_roles = sorted(left_roles & right_roles)
        left_edges = {edge.get("type") for edge in left.edges}
        right_edges = {edge.get("type") for edge in right.edges}
        shared_edge_types = ", ".join(sorted(left_edges & right_edges))
        return (
            f"Session: {info.session_id}\n"
            f"Shared roles: {', '.join(shared_roles) if shared_roles else '(none)'}\n"
            f"Shared edge types: {shared_edge_types or '(none)'}\n"
            f"Role overlap score: {len(shared_roles)}/{len(sorted(left_roles | right_roles)) or 1}"
        )

    if action == "translate":
        if not topology_id or not target_domain:
            raise ValueError("topology_id and target_domain are required for translate")
        record = engine.get_topology(topology_id)
        if record is None:
            raise ValueError(f"Topology '{topology_id}' not found")
        translation = {
            "target_domain": target_domain,
            "hypothesis": (
                f"In {target_domain}, a topology with roles "
                f"{', '.join(sorted({node.get('role') for node in record.nodes}))} "
                "likely implies analogous control or flow constraints."
            ),
        }
        record.translations.append(translation)
        engine.upsert_topology(record)
        return (
            f"Session: {info.session_id} | Topology: {record.id}\n"
            f"Translation: {translation['hypothesis']}"
        )

    rows = engine.get_topologies()
    if pattern:
        rows = [
            row
            for row in rows
            if pattern.lower() in row.source_description.lower()
            or any(pattern.upper() == str(edge.get("type", "")).upper() for edge in row.edges)
        ]
    if not rows:
        return f"Session: {info.session_id}\nNo matching topologies found."
    lines = [f"Session: {info.session_id}", f"Topologies: {len(rows)}"]
    for row in rows:
        lines.append(
            f"- {row.id}: {row.name} | domain={row.source_domain or '?'} "
            f"| nodes={len(row.nodes)} edges={len(row.edges)}"
        )
    return "\n".join(lines)


async def think_evidence(
    action: str,
    session_id: str | None = None,
    evidence_id: str | None = None,
    content: str | None = None,
    source_type: str | None = None,
    domain: str | None = None,
    confidence: float = 0.5,
    source_ref: str | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
    inference_type: str | None = None,
    assumptions: list[str] | None = None,
    claim_id: str | None = None,
    items: list[dict] | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Track evidence provenance chains and compute chain strength.

    PREFER items=[...] (or *_ids=[...] for invalidate/remove) on every action
    when handling one-or-more records — list-form scales without added
    round-trips. Single-record args remain supported for backward-compat.

    action: one of register | chain | trace | strength | list
        add: accepted as an alias for register.
        register: store an evidence node. Required: content, source_type.
            source_type must be one of: analogy, expert_opinion, inference,
            literature, measurement, observation, simulation.
        chain: link two evidence nodes. Required: from_id, to_id, inference_type.
            inference_type must be one of: abductive, analogical, deductive,
            inductive.
        trace: walk provenance paths to a claim. Required: claim_id.
        strength: compute aggregate evidence strength for a claim. Required: claim_id.
        list: return all registered evidence nodes.
    """
    if action == "add":
        action = "register"
    _validate_enum(action, _EVIDENCE_ACTIONS, "action")
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    if action == "register":
        # ── List-form path ──────────────────────────────────
        if items is not None:
            from aismartbuddy.tools import validate_items

            single_form_args = bool(
                evidence_id or content or source_type
                or domain or source_ref
            )
            if single_form_args:
                raise ValueError(
                    "think_evidence.register: pass either items=[...] "
                    "(preferred) or single-record args, not both."
                )

            def _check_source_type(s: object) -> str | None:
                if s not in _EVIDENCE_SOURCE_TYPES:
                    return f"must be one of {sorted(_EVIDENCE_SOURCE_TYPES)}"
                return None

            validate_items(
                items,
                required=["content", "source_type"],
                tool="think_evidence",
                item_validators={"source_type": _check_source_type},
            )
            from aismartbuddy.tools import collect_item_refs as _collect_refs

            registered_ids: list[str] = []
            with engine.state_lock:
                for it in items:
                    conf = float(it.get("confidence", 0.5))
                    engine.upsert_evidence(
                        EvidenceRecord(
                            id=it["id"],
                            content=str(it["content"]),
                            source_type=str(it["source_type"]),
                            domain=str(it.get("domain", "") or ""),
                            confidence=max(0.0, min(1.0, conf)),
                            source_ref=str(it.get("source_ref", "") or ""),
                            refs=_collect_refs(it),
                        )
                    )
                    registered_ids.append(it["id"])
            return (
                f"Evidence registered: {len(registered_ids)}\n"
                f"IDs: {', '.join(registered_ids)}\n"
                "Status: registered"
            )

        if not evidence_id or not content or not source_type:
            raise ValueError("evidence_id, content, and source_type are required for register")
        _validate_enum(source_type, _EVIDENCE_SOURCE_TYPES, "source_type")
        engine.upsert_evidence(
            EvidenceRecord(
                id=evidence_id,
                content=content,
                source_type=source_type,
                domain=domain or "",
                confidence=max(0.0, min(1.0, confidence)),
                source_ref=source_ref or "",
            )
        )
        return f"Session: {info.session_id} | Evidence: {evidence_id}\nStatus: registered"

    if action == "chain":
        # ── List-form path ──────────────────────────────────
        if items is not None:
            from aismartbuddy.tools import validate_items

            single_form_args = bool(
                from_id or to_id or inference_type or assumptions
            )
            if single_form_args:
                raise ValueError(
                    "think_evidence.chain: pass either items=[...] "
                    "(preferred) or single-record args, not both."
                )

            def _check_inference_type(t: object) -> str | None:
                if t not in _EVIDENCE_INFERENCE_TYPES:
                    return f"must be one of {sorted(_EVIDENCE_INFERENCE_TYPES)}"
                return None

            validate_items(
                items,
                required=["from_id", "to_id", "inference_type"],
                tool="think_evidence",
                item_validators={"inference_type": _check_inference_type},
            )
            chain_ids: list[str] = []
            with engine.state_lock:
                for it in items:
                    chain = EvidenceChainRecord(
                        id=it["id"],
                        from_id=str(it["from_id"]),
                        to_id=str(it["to_id"]),
                        inference_type=str(it["inference_type"]),
                        assumptions=list(it.get("assumptions") or []),
                    )
                    engine.add_evidence_chain(chain)
                    chain_ids.append(chain.id)
            return (
                f"Evidence chains added: {len(chain_ids)}\n"
                f"IDs: {', '.join(chain_ids)}\n"
                "Status: chained"
            )

        if not from_id or not to_id or not inference_type:
            raise ValueError("from_id, to_id, and inference_type are required for chain")
        _validate_enum(inference_type, _EVIDENCE_INFERENCE_TYPES, "inference_type")
        chain = EvidenceChainRecord(
            id=f"chain_{uuid.uuid4().hex[:8]}",
            from_id=from_id,
            to_id=to_id,
            inference_type=inference_type,
            assumptions=list(assumptions or []),
        )
        engine.add_evidence_chain(chain)
        return (
            f"Session: {info.session_id} | Evidence chain: {chain.id}\n"
            f"{from_id} --[{inference_type}]--> {to_id}"
        )

    if action == "trace":
        if not claim_id:
            raise ValueError("claim_id is required for trace")
        paths = engine.trace_evidence_paths(claim_id)
        if not paths:
            return f"Session: {info.session_id}\nNo provenance path found for {claim_id}."
        lines = [f"Session: {info.session_id}", f"Paths: {len(paths)}"]
        for path in paths[:10]:
            lines.append("- " + " -> ".join(path))
        return "\n".join(lines)

    if action == "strength":
        if not claim_id:
            raise ValueError("claim_id is required for strength")
        score = engine.compute_evidence_strength(claim_id)
        return f"Session: {info.session_id}\nClaim: {claim_id} | Evidence strength: {score:.3f}"

    rows = engine.get_all_evidence()
    if not rows:
        return f"Session: {info.session_id}\nNo evidence registered."
    lines = [f"Session: {info.session_id}", f"Evidence items: {len(rows)}"]
    for row in rows[:20]:
        lines.append(
            f"- {row.id}: {row.source_type} | conf={row.confidence:.2f} | {_short(row.content, 70)}"
        )
    return "\n".join(lines)


async def think_bridge(
    action: str,
    session_id: str | None = None,
    entity_name: str | None = None,
    node_id: str | None = None,
    hypothesis_id: str | None = None,
    target_id: str | None = None,
    target_type: str | None = None,
    entity_ids: list[str] | None = None,
    confidence_min: float | None = None,
    include_sql_tables: list[str] | None = None,
    domain: str | None = None,
    domain_b: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Query thought graph, hypotheses, constraints, evidence, topology state.

    Ten actions:
      thoughts_for_entity(entity_name) -- thoughts mentioning the entity.
          Matches ThoughtNode metadata['knowledge_refs'] first; if empty,
          falls back to case-insensitive substring search on node content
          (rows prefixed with "(text match) ").
      entities_for_thought(node_id) -- entities referenced by a thought.
      hypotheses_for_entity(entity_name) -- hypotheses mentioning the entity.
      evidence_for_hypothesis(hypothesis_id) -- direct + chained evidence.
      constraints_for_hypothesis(hypothesis_id) -- constraint validation rows.
      full_context(target_id, target_type?) -- everything we know about an id.
      bundle(entity_ids[], confidence_min?, include_sql_tables[])
          -- assemble think + graph + SQL context in one call
      authoritative_source(entity_name)
          -- ranked knowledge nodes by authority tier
             (ground_truth > primary > external > inferred)
      domain_context(domain)
          -- list all think records (thoughts, hypotheses, models, decisions,
             inquiries, monitors) AND graph KnowledgeNodes tagged with a given
             domain. Use for cross-record domain rollups.
      domain_connections(domain, domain_b)
          -- find graph edges and shared entities linking two domains. Useful
             for cross-domain bridge analysis.

    Args:
      action: one of the ten action names above.
      entity_name / node_id / hypothesis_id / target_id / target_type /
        entity_ids / confidence_min / include_sql_tables: per-action inputs.
      domain: domain tag for domain_context / domain_connections.
      domain_b: second domain tag for domain_connections.

    Note: ThoughtNodes produced via `think_graph(thoughts=[...])` accept
    `entity_refs: list[str]` (registers to metadata.knowledge_refs) and
    `domain: str` (registers to metadata.domain). Items[] forms of
    think_model / think_decide / think_science / think_monitor accept
    `domain: str` and write it to the record's `domain` field.

    When the current think session belongs to a unified think+graph workspace,
    the tool also attempts graph-backed context lookups. Those lookups are
    best-effort and fail safe: if no graph backend exists, or the graph query
    fails, the think-side response still succeeds.
    """
    _validate_enum(action, _BRIDGE_ACTIONS, "action")
    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)

    if action == "thoughts_for_entity":
        if not entity_name:
            raise ValueError("entity_name is required")
        matches = [
            f"{node.id}:{_short(node.content, 70)}"
            for node in engine.thought_nodes.values()
            if entity_name in node.metadata.get("knowledge_refs", [])
        ]
        if not matches:
            pattern = re.compile(rf"\b{re.escape(entity_name)}\b", re.IGNORECASE)
            for node in engine.thought_nodes.values():
                if pattern.search(node.content or ""):
                    matches.append(f"(text match) {node.id}:{_short(node.content, 70)}")
                    if len(matches) >= 50:
                        break
        lines = [f"Session: {info.session_id}", f"Thought matches: {len(matches)}"]
        lines.extend(f"- {item}" for item in matches[:20])
        graph_lines = await _safe_graph_context_lines(
            info.session_id,
            entity_names=[entity_name],
            target_name=entity_name,
        )
        if graph_lines:
            lines.append("Graph context:")
            lines.extend(f"  {line}" for line in graph_lines)
        return "\n".join(lines)

    if action == "entities_for_thought":
        if not node_id:
            raise ValueError("node_id is required")
        node = engine.get_node(node_id)
        if node is None:
            raise ValueError(f"Node '{node_id}' not found")
        entities = node.metadata.get("knowledge_refs", [])
        lines = [
            f"Session: {info.session_id}",
            f"Thought: {node_id}",
            f"Entities: {', '.join(entities) if entities else '(none)'}",
        ]
        graph_lines = await _safe_graph_context_lines(info.session_id, entity_names=list(entities))
        if graph_lines:
            lines.append("Graph context:")
            lines.extend(f"  {line}" for line in graph_lines)
        return "\n".join(lines)

    if action == "hypotheses_for_entity":
        if not entity_name:
            raise ValueError("entity_name is required")
        matches = []
        for record in engine.get_hypotheses():
            if entity_name.lower() in record.statement.lower() or any(
                entity_name.lower() in str(pred).lower() for pred in record.predictions
            ):
                matches.append(record)
        if not matches:
            return f"Session: {info.session_id}\nNo hypotheses mention {entity_name}."
        lines = [f"Session: {info.session_id}", f"Hypotheses for {entity_name}: {len(matches)}"]
        lines.extend(
            [
                f"- {record.id}: posterior={record.posterior_weight:.3f} | "
                f"{_short(record.statement, 80)}"
                for record in matches[:20]
            ]
        )
        graph_lines = await _safe_graph_context_lines(
            info.session_id,
            entity_names=[entity_name],
            target_name=entity_name,
        )
        if graph_lines:
            lines.append("Graph context:")
            lines.extend(f"  {line}" for line in graph_lines)
        return "\n".join(lines)

    if action == "evidence_for_hypothesis":
        if not hypothesis_id:
            raise ValueError("hypothesis_id is required")
        strength = engine.compute_evidence_strength(hypothesis_id)
        direct = engine.get_hypothesis(hypothesis_id)
        lines = [
            f"Session: {info.session_id}",
            f"Hypothesis: {hypothesis_id}",
            f"Strength: {strength:.3f}",
        ]
        if direct is not None and direct.evidence:
            lines.append("Direct evidence:")
            lines.extend(
                f"- {item.direction}:{item.strength:.2f} | {_short(item.text, 80)}"
                for item in direct.evidence[:10]
            )
        graph_lines = await _safe_graph_context_lines(info.session_id, target_name=hypothesis_id)
        if graph_lines:
            lines.append("Graph context:")
            lines.extend(f"  {line}" for line in graph_lines)
        return "\n".join(lines)

    if action == "constraints_for_hypothesis":
        if not hypothesis_id:
            raise ValueError("hypothesis_id is required")
        rows = engine.get_constraint_validations(target_type="hypothesis", target_id=hypothesis_id)
        if not rows:
            return f"Session: {info.session_id}\nNo constraint validations for {hypothesis_id}."
        lines = [f"Session: {info.session_id}", f"Constraint validations: {len(rows)}"]
        lines.extend(f"- {row.constraint_id}: {row.status} | {row.note}" for row in rows[:20])
        graph_lines = await _safe_graph_context_lines(info.session_id, target_name=hypothesis_id)
        if graph_lines:
            lines.append("Graph context:")
            lines.extend(f"  {line}" for line in graph_lines)
        return "\n".join(lines)

    if action == "authoritative_source":
        if not entity_name:
            raise ValueError("authoritative_source requires entity_name")
        from aismartbuddy.tools.graph import _escape_cypher_string

        think_session_id = info.session_id
        lines: list[str] = [
            f"Session: {think_session_id}",
            f"action: authoritative_source | entity: {entity_name}",
        ]
        # think-side: hypotheses referencing the entity
        hyps = engine.get_hypotheses()
        matching_hyps = [h for h in hyps if entity_name.lower() in h.statement.lower()]
        if matching_hyps:
            lines.append("## Think hypotheses")
            for h in matching_hyps[:5]:
                lines.append(
                    f"  {h.id}: {h.statement[:80]} "
                    f"(posterior={h.posterior_weight:.3f})"
                )
        # graph-side: knowledge nodes ranked by authority
        companion_id = _companion_graph_session_id(think_session_id)
        if companion_id:
            mgr2 = get_session_manager()
            g_info = mgr2.resolve_backend_session(companion_id, "graph")
            q = (
                f"MATCH (n:KnowledgeNode) "
                f"WHERE n.name = '{_escape_cypher_string(entity_name)}' "
                f"RETURN n.name, n.authority, n.source, n.confidence"
            )
            try:
                _, rows = await run_with_lock(
                    g_info, lambda: g_info.engine.execute(q)
                )
                if rows:
                    rank = {
                        "ground_truth": 0,
                        "primary": 1,
                        "external": 2,
                        "inferred": 3,
                    }
                    sorted_rows = sorted(rows, key=lambda r: rank.get(str(r[1]), 4))
                    lines.append("## Knowledge nodes (ranked by authority)")
                    for row in sorted_rows[:5]:
                        lines.append(
                            f"  name={row[0]} authority={row[1] or 'unset'} "
                            f"source={row[2]} confidence={row[3]}"
                        )
            except Exception as exc:
                logger.debug("graph authority query failed for %s: %s", entity_name, exc)
        else:
            graph_lines = await _safe_graph_context_lines(
                think_session_id, entity_names=[entity_name]
            )
            if graph_lines:
                lines.append("## Graph context")
                lines.extend(graph_lines)
        return "\n".join(lines)

    if action == "domain_context":
        if not domain or not domain.strip():
            raise ValueError("domain is required for domain_context")
        from aismartbuddy.tools.graph import _escape_cypher_string

        d = domain.strip()
        think_session_id = info.session_id

        matching_thoughts = [
            n for n in engine.thought_nodes.values() if n.metadata.get("domain") == d
        ]
        matching_hyps = [h for h in engine.hypotheses.values() if h.domain == d]
        matching_models = [m for m in engine.models if m.domain == d]
        matching_decisions = [
            dec for dec in engine.decisions.values() if dec.domain == d
        ]
        matching_inquiries = [
            i for i in engine.inquiries.values() if i.domain == d
        ]
        matching_monitors = [
            mo for mo in engine.monitors.values() if mo.domain == d
        ]

        graph_rows: list[tuple] = []
        companion_id = _companion_graph_session_id(think_session_id)
        if companion_id:
            mgr2 = get_session_manager()
            g_info = mgr2.resolve_backend_session(companion_id, "graph")
            q = (
                f"MATCH (n:KnowledgeNode) "
                f"WHERE n.domain = '{_escape_cypher_string(d)}' "
                f"RETURN n.name, n.entity_type, n.confidence, n.authority LIMIT 30"
            )
            try:
                _, rows = await run_with_lock(
                    g_info, lambda: g_info.engine.execute(q)
                )
                graph_rows = list(rows)
            except Exception as exc:
                logger.debug("domain_context graph query failed for %s: %s", d, exc)

        header_parts = [
            f"thoughts: {len(matching_thoughts)}",
            f"hypotheses: {len(matching_hyps)}",
            f"models: {len(matching_models)}",
            f"decisions: {len(matching_decisions)}",
            f"inquiries: {len(matching_inquiries)}",
            f"monitors: {len(matching_monitors)}",
        ]
        if companion_id:
            header_parts.append(f"graph_nodes: {len(graph_rows)}")
        lines = [
            f"Session: {think_session_id}",
            f"domain: {d} | " + ", ".join(header_parts),
        ]

        total = (
            len(matching_thoughts)
            + len(matching_hyps)
            + len(matching_models)
            + len(matching_decisions)
            + len(matching_inquiries)
            + len(matching_monitors)
            + len(graph_rows)
        )
        if total == 0:
            lines.append(f"(no records found for domain '{d}')")
            return "\n".join(lines)

        _emit_domain_section(
            lines, "Thoughts", matching_thoughts, lambda n: n.id, lambda n: n.content
        )
        _emit_domain_section(
            lines, "Hypotheses", matching_hyps, lambda h: h.id, lambda h: h.statement
        )
        _emit_domain_section(
            lines,
            "Models",
            matching_models,
            lambda m: f"{m.record_id or m.model_name} [{m.model_name}]",
            lambda m: m.problem,
        )
        _emit_domain_section(
            lines, "Decisions", matching_decisions,
            lambda d: d.decision_id, lambda d: d.statement,
        )
        _emit_domain_section(
            lines, "Inquiries", matching_inquiries,
            lambda i: i.inquiry_id, lambda i: i.question,
        )
        _emit_domain_section(
            lines, "Monitors", matching_monitors,
            lambda mo: mo.monitoring_id, lambda mo: mo.task,
        )
        if graph_rows:
            lines.append("## Graph KnowledgeNodes")
            for row in graph_rows[:30]:
                name = row[0] if len(row) > 0 else ""
                etype = row[1] if len(row) > 1 else ""
                conf = row[2] if len(row) > 2 else ""
                auth = row[3] if len(row) > 3 else ""
                lines.append(
                    f"  name={name} type={etype} conf={conf} auth={auth or 'unset'}"
                )
        return "\n".join(lines)

    if action == "domain_connections":
        if not domain or not domain.strip() or not domain_b or not domain_b.strip():
            raise ValueError("domain_connections requires both domain and domain_b")
        from aismartbuddy.tools.graph import _escape_cypher_string

        d_a = domain.strip()
        d_b = domain_b.strip()
        think_session_id = info.session_id
        if d_a == d_b:
            return (
                f"Session: {think_session_id}\n"
                f"domain_connections({d_a}, {d_b}): same domain — "
                "use domain_context instead\n"
            )

        lines = [
            f"Session: {think_session_id}",
            f"domain_connections: '{d_a}' <-> '{d_b}'",
        ]

        # Graph mode (if companion exists)
        companion_id = _companion_graph_session_id(think_session_id)
        if companion_id:
            mgr2 = get_session_manager()
            g_info = mgr2.resolve_backend_session(companion_id, "graph")
            q = (
                f"MATCH (a:KnowledgeNode)-[r]-(b:KnowledgeNode) "
                f"WHERE a.domain = '{_escape_cypher_string(d_a)}' "
                f"AND b.domain = '{_escape_cypher_string(d_b)}' "
                f"RETURN a.name, label(r), b.name, r.weight LIMIT 20"
            )
            try:
                _, rows = await run_with_lock(
                    g_info, lambda: g_info.engine.execute(q)
                )
                if rows:
                    lines.append("## Graph connections")
                    for row in rows:
                        a_name = row[0] if len(row) > 0 else ""
                        rel = row[1] if len(row) > 1 else ""
                        b_name = row[2] if len(row) > 2 else ""
                        weight = row[3] if len(row) > 3 else ""
                        lines.append(
                            f"  {a_name} -[{rel} w={weight}]- {b_name}"
                        )
                else:
                    lines.append("## Graph connections: (none)")
            except Exception as exc:
                logger.debug(
                    "domain_connections graph query failed for %s/%s: %s",
                    d_a,
                    d_b,
                    exc,
                )
                lines.append("## Graph connections: (error — see logs)")

        # Think-side mode (always)
        set_a: set[str] = set()
        set_b: set[str] = set()
        for n in engine.thought_nodes.values():
            dom = n.metadata.get("domain")
            refs = n.metadata.get("knowledge_refs", []) or []
            if dom == d_a:
                set_a.update(str(r) for r in refs)
            elif dom == d_b:
                set_b.update(str(r) for r in refs)
        shared = sorted(set_a & set_b)
        if shared:
            lines.append("## Shared entities")
            for entity in shared:
                lines.append(f"  {entity}")
        else:
            lines.append("## Shared entities: (none)")
        return "\n".join(lines)

    if action == "bundle":
        if not entity_ids:
            raise ValueError("bundle requires entity_ids (non-empty list)")
        from aismartbuddy.tools.graph import _escape_cypher_string

        think_session_id = info.session_id
        lines = [
            f"Session: {think_session_id}",
            f"action: bundle | entities: {', '.join(entity_ids)}",
        ]
        # think section
        think_lines: list[str] = []
        all_nodes = list(engine.thought_nodes.values())
        for eid in entity_ids:
            nodes_for_entity = [
                n
                for n in all_nodes
                if eid.lower() in (n.content or "").lower() or eid in (n.refs or [])
            ]
            for n in nodes_for_entity[:10]:
                think_lines.append(f"  [{n.id}] {n.content[:120]}")
        if think_lines:
            lines.append("## Think")
            lines.extend(think_lines)
        # graph section
        companion_id = _companion_graph_session_id(think_session_id)
        g_info = None
        if companion_id:
            mgr2 = get_session_manager()
            g_info = mgr2.resolve_backend_session(companion_id, "graph")
        if confidence_min is not None:
            conf_val = float(confidence_min)
            if g_info is not None:
                graph_conf_lines: list[str] = []
                for eid in entity_ids:
                    q = (
                        f"MATCH (n:KnowledgeNode) "
                        f"WHERE n.name = '{_escape_cypher_string(eid)}' "
                        f"AND n.confidence >= {conf_val} "
                        f"RETURN n.name, n.confidence, n.source, n.authority LIMIT 10"
                    )
                    try:
                        _, rows = await run_with_lock(
                            g_info, lambda q=q: g_info.engine.execute(q)
                        )
                        for row in rows:
                            graph_conf_lines.append(
                                f"  name={row[0]} conf={row[1]} src={row[2]} "
                                f"auth={row[3] or 'unset'}"
                            )
                    except Exception as exc:
                        logger.debug("graph confidence query failed for %s: %s", eid, exc)
                if graph_conf_lines:
                    lines.append(f"## Graph (confidence>={conf_val})")
                    lines.extend(graph_conf_lines)
            else:
                lines.append("## Graph — confidence_min ignored (no graph backend in session)")
        else:
            graph_ctx = await _safe_graph_context_lines(
                think_session_id, entity_names=entity_ids
            )
            if graph_ctx:
                lines.append("## Graph")
                lines.extend(graph_ctx)
        # SQL section
        if include_sql_tables:
            mgr3 = get_session_manager()
            sql_companion_id = mgr3.find_companion_session(think_session_id, "sql")
            if sql_companion_id:
                sql_info = mgr3.get_session(sql_companion_id)
                from aismartbuddy.tools import execute_and_format

                for table in include_sql_tables:
                    if not re.match(r"^[A-Za-z0-9_]+$", table):
                        lines.append(f"## SQL [{table}] — skipped (invalid identifier)")
                        continue
                    try:
                        csv_result = await execute_and_format(
                            sql_info, mgr3, f"SELECT * FROM {table} LIMIT 20"
                        )
                        lines.append(f"## SQL [{table}]")
                        lines.append(csv_result)
                    except Exception as exc:
                        lines.append(f"## SQL [{table}] — error: {exc}")
        return "\n".join(lines)

    if not target_id:
        raise ValueError("target_id is required for full_context")
    lines = [f"Session: {info.session_id}", f"Full context for {target_type or 'id'}:{target_id}"]
    if target_id in engine.thought_nodes:
        node = engine.thought_nodes[target_id]
        lines.append(f"Thought: {_short(node.content, 120)}")
        if node.metadata.get("knowledge_refs"):
            lines.append("Knowledge refs: " + ", ".join(node.metadata["knowledge_refs"]))
    if target_id in engine.hypotheses:
        hyp = engine.hypotheses[target_id]
        lines.append(f"Hypothesis posterior: {hyp.posterior_weight:.3f}")
    if target_id in engine.constraints:
        con = engine.constraints[target_id]
        lines.append(f"Constraint: {con.constraint_type} | {_short(con.statement, 100)}")
    if target_id in engine.evidence:
        ev = engine.evidence[target_id]
        lines.append(f"Evidence: {ev.source_type} | conf={ev.confidence:.2f}")
    ref_matches = []
    for node in engine.thought_nodes.values():
        if target_id in node.refs:
            ref_matches.append(f"thought:{node.id}")
    for record in engine.models:
        if target_id in record.refs:
            ref_matches.append(f"model:{record.record_id or record.model_name}")
    if ref_matches:
        lines.append("Inbound refs: " + ", ".join(ref_matches[:20]))
    graph_lines = await _safe_graph_context_lines(
        info.session_id,
        entity_names=list(node.metadata.get("knowledge_refs", []))
        if target_id in engine.thought_nodes
        else None,
        target_name=target_id,
    )
    if graph_lines:
        lines.append("Graph context:")
        lines.extend(f"  {line}" for line in graph_lines)
    return "\n".join(lines)


# ── Tool: Summarize ──────────────────────────────────────────


@size_guarded
async def think_summarize(
    session_id: str | None = None,
    max_items_per_category: int = 20,
    detail_level: str = "index",
) -> str:
    """[ASSESS] Get a token-optimized summary of all thinking activity in a session.

    Returns a compact overview of all thought graphs, mental models,
    decisions, debugging approaches, arguments, collaborations, inquiries,
    monitors, and diagrams recorded in the session.

    Args:
        session_id: Thinking session ID.
        max_items_per_category: Cap on items per category to prevent huge
            responses on sessions with hundreds of items. Default 20.
            Excess items collapse to "... (N more)" footer.
        detail_level: Verbosity of per-item content:
            - "index" (default, backward-compat): terse one-liners.
            - "synopsis": RECOMMENDED when resuming a session — ~400-char
              previews, more branches per tree, full synthesis nodes.
            - "full": all branches, long previews. For end-of-session review.

    Returns:
        Compact summary of all thinking activity.
    """
    _, info = _require_think_session(session_id)
    engine = _engine(info)
    summary = engine.get_summary(max_items_per_category, detail_level=detail_level)
    links = get_session_manager().list_session_links(info.session_id)
    if links:
        link_lines = ["\n### Cross-Session Links"]
        for link in links[:10]:
            link_lines.append(
                f"- {link.id}: {link.session_a}:{link.node_a_id} "
                f"--[{link.relationship}]--> {link.session_b}:{link.node_b_id}"
            )
        summary = summary + "\n" + "\n".join(link_lines)
    graph_refs = sorted(
        {
            ref
            for node in engine.thought_nodes.values()
            for ref in node.metadata.get("knowledge_refs", [])
        }
    )
    graph_lines = await _safe_graph_context_lines(
        info.session_id,
        entity_names=graph_refs[:5],
    )
    if graph_lines:
        summary = summary + "\n\n### Cross-Backend Graph Context\n" + "\n".join(
            f"- {line}" if index == 0 else f"  {line}"
            for index, line in enumerate(graph_lines)
        )
    return f"Session: {info.session_id}\n{summary}"


# ── Tool: Destroy Session ────────────────────────────────────


async def think_create_session(
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: _MCPContext | None = None,
) -> str:
    """[INFRA] Create a new thinking session bound to (user_id, project_id).

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
    """[INFRA] Destroy a thinking session and free its memory.

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
    """[ELABORATE] Interference Protocol — structured novelty generation.

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

    For analog search rather than novelty generation: use an abstract
    topology description as the target_domain, suspend domain-specific
    assumptions with add_frame, then add source laws from foreign domains
    that share the same control structure. The emergent concept becomes the
    cross-domain insight rather than a novel invented mechanism.

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
