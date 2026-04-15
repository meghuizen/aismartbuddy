"""In-memory thinking engine for structured AI reasoning.

Provides session-scoped state management for thought graphs,
decision frameworks, mental models, debugging approaches, argumentation,
collaborative reasoning, scientific method, metacognitive monitoring,
visual reasoning, and interference protocols.

Does NOT extend BaseEngine — different interface (no SQL/Cypher execute).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger("aismartbuddy.engines.thinking")


def _synchronized(method):
    """Decorator: acquire self._state_lock around method body.

    Used on ThinkingEngine mutation methods for multi-agent safety — two
    agents sharing a session_id will serialize rather than corrupt state.
    Uses RLock so nested engine calls (e.g. add_node → _cleanup_graph_memory)
    don't deadlock.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)

    return wrapper


# Memory limits
MAX_NODES = 2000
MAX_TREES = 50


# ── Data models ──────────────────────────────────────────────


@dataclass
class ThoughtNode:
    """A node in a thought graph.

    Every node is simultaneously a self-contained whole (itself + subtree)
    and a part of a larger decomposition (its parent's tree). This holonic
    property is emergent from the parent-child structure.

    Supports progressive complexity:
    - Simple sequential chains (parent→child→grandchild)
    - Hierarchical tree decomposition (branch into sub-problems)
    - Revision with history tracking
    - Synthesis (combining children's findings)
    - Delegation to subagents
    - Structural validation
    """

    id: str
    tree_id: str
    content: str
    action: str = "think"  # think | branch | revise | synthesize
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    revision_history: list[str] = field(default_factory=list)
    delegation_state: str | None = None  # None | pending | completed
    delegation_context: str = ""
    delegation_result: str = ""
    depends_on: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    validation_results: list[dict] = field(default_factory=list)
    depth: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


@dataclass
class ModelRecord:
    """Application of a mental model to a problem.

    record_id is the addressable id when this record was produced via
    think_model(items=[...]) — it's the caller's item id. Empty for
    single-item backward-compat calls.

    refs holds the unified cross-reference list — populated from
    items[].connects_to and items[].refs so think_refs_query can find
    this record by any referenced entity_id.
    """

    model_name: str
    problem: str
    steps: list[str] = field(default_factory=list)
    reasoning: str = ""
    conclusion: str = ""
    record_id: str = ""
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DecisionRecord:
    """State for a multi-stage decision analysis.

    refs holds unified cross-references when produced via think_decide(items=[...]).
    """

    decision_id: str
    statement: str
    options: list[dict] = field(default_factory=list)
    analysis_type: str = "multi-criteria"
    stage: str = "problem-definition"
    iteration: int = 0
    criteria: list[dict] = field(default_factory=list)
    evaluations: list[dict] = field(default_factory=list)
    recommendation: str = ""
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DebugRecord:
    """Application of a debugging approach to an issue.

    record_id is the addressable id when this record was produced via
    think_debug(items=[...]) — it's the caller's item id. Empty for
    single-item backward-compat calls.
    """

    approach_name: str
    issue: str
    steps: list[str] = field(default_factory=list)
    findings: str = ""
    resolution: str = ""
    record_id: str = ""
    refs: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ArgRecord:
    """A single argument in a dialectical chain."""

    argument_id: str
    claim: str
    premises: list[str] = field(default_factory=list)
    conclusion: str = ""
    argument_type: str = "thesis"
    confidence: float = 0.5
    responds_to: str | None = None
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InquiryRecord:
    """State for a scientific method inquiry.

    refs holds unified cross-references when produced via think_science(items=[...]).
    """

    inquiry_id: str
    stage: str = "observation"
    iteration: int = 0
    observation: str = ""
    question: str = ""
    hypothesis: dict | None = None
    experiment: dict | None = None
    analysis: str = ""
    conclusion: str = ""
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MonitorRecord:
    """State for metacognitive monitoring.

    refs holds unified cross-references when produced via think_monitor(items=[...]).
    """

    monitoring_id: str
    task: str
    stage: str = "knowledge-assessment"
    iteration: int = 0
    overall_confidence: float = 0.5
    knowledge_assessment: dict | None = None
    claims: list[dict] = field(default_factory=list)
    reasoning_steps: list[dict] = field(default_factory=list)
    uncertainty_areas: list[str] = field(default_factory=list)
    recommended_approach: str = ""
    suggested_assessments: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InterferenceRecord:
    """State for an Interference Protocol session.

    Tracks a multi-phase structured thinking process that produces
    novel concepts by forcing unrelated structural laws into
    simultaneous truth and finding emergent interference patterns.
    """

    protocol_id: str
    phase: str = "uninitiated"
    iteration: int = 1
    target_domain: str = ""
    suspended_frames: list[str] = field(default_factory=list)
    source_laws: list[dict] = field(default_factory=list)
    fragments: list[str] = field(default_factory=list)
    tensions: list[dict] = field(default_factory=list)
    emergent_name: str = ""
    emergent_properties: list[dict] = field(default_factory=list)
    necessity_chains: list[dict] = field(default_factory=list)
    audit_results: dict = field(default_factory=dict)
    verdict: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HolonNode:
    """A holon — simultaneously a whole and a part.

    Participates in multiple holarchies simultaneously via memberships.
    Each membership gives the holon a different parent, role, and level.
    Projections are per-holarchy: what the holon exposes upward in each.
    """

    id: str
    name: str
    description: str = ""
    context: str = ""
    rules: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    memberships: list[dict] = field(default_factory=list)
    projections: dict[str, str] = field(default_factory=dict)
    stale_projections: set[str] = field(default_factory=set)
    description_stale: bool = False
    analytical_lenses: list[dict] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    children_by_holarchy: dict[str, list[str]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


MAX_HOLONS = 1000
MAX_HOLARCHIES = 30


@dataclass
class IterationRecord:
    """Tracks one ITERATE-mode build-test-learn loop.

    Lightweight by design — 3 fields per attempt (approach/result/learning).
    Optional metric_value enables ratcheting (Phase 5 / M5 — defer logic
    there but the storage shape is set up here).
    """

    iteration_id: str
    goal: str
    attempts: list[dict] = field(default_factory=list)
    conclusion: str = ""
    is_complete: bool = False
    # Metric ratcheting (M5)
    metric_name: str | None = None
    best_metric: float | None = None
    metric_history: list[float] = field(default_factory=list)
    # When higher metric is better. Set when first metric is recorded.
    higher_is_better: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FindingRecord:
    """A single finding in a scored evaluation."""

    id: str
    dimension: str
    severity: str
    kind: str = "finding"  # finding | note
    blocking: bool = False
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RubricRecord:
    """A reusable scoring framework."""

    id: str
    description: str = ""
    dimensions: list[dict] = field(default_factory=list)
    severity_levels: list[str] = field(default_factory=list)
    severity_deductions: dict[str, float] = field(default_factory=dict)
    pass_threshold: float = 9.0
    scale_min: int = 1
    scale_max: int = 10
    scoring_strategy: str = "weighted_deduction"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvaluationRecord:
    """A scored evaluation instance against a rubric."""

    id: str
    rubric_id: str
    session_id: str = ""
    parent_session_id: str | None = None
    context: str = ""
    status: str = "active"  # active | finalized
    findings: list[FindingRecord] = field(default_factory=list)
    dimension_scores: dict[str, float] = field(default_factory=dict)
    dimensions_reviewed: set[str] = field(default_factory=set)
    running_score: float = 0.0
    final_score: float | None = None
    passed: bool | None = None
    has_blocking: bool = False
    auto_fail: bool = False
    summary: str = ""
    refs: list[str] = field(default_factory=list)
    rule_bindings: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finalized_at: datetime | None = None


@dataclass
class RuleItem:
    """A single weighted rule/requirement inside a reusable profile."""

    id: str
    text: str
    weight: float
    kind: str = "soft"  # soft | hard
    status: str = "active"  # active | superseded
    rationale: str = ""
    tags: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)


@dataclass
class RuleSnapshot:
    """Pinned copy of a profile's rules for auditability."""

    id: str
    profile_id: str
    label: str = ""
    rules: list[RuleItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RuleProfile:
    """Reusable weighted rule profile."""

    id: str
    name: str
    description: str = ""
    rules: list[RuleItem] = field(default_factory=list)
    snapshots: list[RuleSnapshot] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RuleConflictRecord:
    """Unresolved conflict between active rules."""

    id: str
    rule_ids: list[str] = field(default_factory=list)
    profile_ids: list[str] = field(default_factory=list)
    status: str = "open"  # open | resolved
    resolution_note: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None


@dataclass
class ValidationAssessment:
    """Caller-supplied validation judgment for one rule."""

    rule_id: str
    status: str  # satisfies | violates | uncertain | not_applicable
    note: str = ""
    refs: list[str] = field(default_factory=list)


@dataclass
class ValidationRecord:
    """Persisted validation result against one subject and rule binding set."""

    id: str
    subject_id: str
    subject_kind: str
    rule_bindings: list[dict] = field(default_factory=list)
    passed_hard_gates: bool = True
    weighted_score: float = 100.0
    weighted_gaps: list[dict] = field(default_factory=list)
    uncovered_rules: list[str] = field(default_factory=list)
    conflicting_rules: list[str] = field(default_factory=list)
    nuance_notes: list[str] = field(default_factory=list)
    hard_failures: list[str] = field(default_factory=list)
    assessments: list[ValidationAssessment] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HypothesisEvidence:
    """Evidence directly attached to a hypothesis ranking."""

    text: str
    direction: str  # supports | weakens | neutral
    strength: float
    source_domain: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HypothesisRecord:
    """Competing hypothesis with accumulated evidence and predictions."""

    id: str
    statement: str
    domain: str = ""
    prior_weight: float = 0.5
    posterior_weight: float = 0.5
    predictions: list[dict] = field(default_factory=list)
    evidence: list[HypothesisEvidence] = field(default_factory=list)
    invalidated: bool = False
    invalidation_reason: str = ""
    history: list[dict] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConstraintRecord:
    """Reusable hard or soft constraint."""

    id: str
    domain: str
    constraint_type: str  # hard | soft
    statement: str
    check_description: str = ""
    applies_to: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConstraintValidationRecord:
    """Validation result of a target against a registered constraint."""

    id: str
    constraint_id: str
    target_type: str
    target_id: str = ""
    target_text: str = ""
    status: str = "uncertain"  # pass | fail | uncertain
    note: str = ""
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TopologyRecord:
    """Domain-neutral structural topology."""

    id: str
    name: str
    source_domain: str = ""
    source_description: str = ""
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    translations: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvidenceRecord:
    """Primary evidence item with provenance metadata."""

    id: str
    content: str
    source_type: str
    domain: str = ""
    confidence: float = 0.5
    source_ref: str = ""
    refs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvidenceChainRecord:
    """Directed provenance link from evidence/claim to another claim."""

    id: str
    from_id: str
    to_id: str
    inference_type: str
    assumptions: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_EVIDENCE_INFERENCE_RELIABILITY: dict[str, float] = {
    "deductive": 0.95,
    "inductive": 0.75,
    "abductive": 0.60,
    "analogical": 0.40,
}


@dataclass
class ArtifactRecord:
    """Unified V2 reasoning artifact stored in session memory."""

    id: str
    kind: str
    mode: str
    phase: str
    status: str = "active"
    model_name: str = ""
    domain_tags: list[str] = field(default_factory=list)
    content: dict = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)
    connects_to: list[str] = field(default_factory=list)
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    confidence: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


MAX_RUBRICS = 100
MAX_EVALUATIONS = 100
MAX_RULE_PROFILES = 100
MAX_RULE_VALIDATIONS = 500


def _clone_rule_item(item: RuleItem) -> RuleItem:
    """Return a deep-ish copy of a RuleItem."""
    return RuleItem(
        id=item.id,
        text=item.text,
        weight=float(item.weight),
        kind=item.kind,
        status=item.status,
        rationale=item.rationale,
        tags=list(item.tags),
        refs=list(item.refs),
        conflicts_with=list(item.conflicts_with),
    )


def _clone_rule_snapshot(snapshot: RuleSnapshot) -> RuleSnapshot:
    """Return a copy of a RuleSnapshot."""
    return RuleSnapshot(
        id=snapshot.id,
        profile_id=snapshot.profile_id,
        label=snapshot.label,
        rules=[_clone_rule_item(r) for r in snapshot.rules],
        created_at=snapshot.created_at,
    )


def _binding_key(binding: dict) -> tuple[str, str | None]:
    """Stable dedupe key for a rule binding dict."""
    return (str(binding.get("profile_id", "")), binding.get("snapshot_id"))


# ── ThinkingEngine ───────────────────────────────────────────


class ThinkingEngine:
    """In-memory engine for structured AI reasoning.

    Session-scoped: one instance per session_id via SessionManager.

    Thread-safety: methods acquire `_state_lock` for multi-agent safety.
    When multiple agents share a session (via passing the same session_id),
    their tool calls are serialized automatically — no data corruption in
    the 15 state dicts even under concurrent access. Atomic ops are short
    (dict/list mutations), so the lock has negligible contention cost.
    """

    def __init__(self) -> None:
        import threading

        # RLock so internal methods (e.g. add_node → _cleanup_graph_memory)
        # can re-acquire without deadlocking.
        self._state_lock = threading.RLock()
        self.thought_nodes: dict[str, ThoughtNode] = {}
        self.thought_trees: dict[str, str] = {}  # tree_id → root_node_id
        self.models: list[ModelRecord] = []
        self.decisions: dict[str, DecisionRecord] = {}
        self.debugs: list[DebugRecord] = []
        self.args: dict[str, list[ArgRecord]] = {}  # keyed by first argument_id
        self.inquiries: dict[str, InquiryRecord] = {}
        self.monitors: dict[str, MonitorRecord] = {}
        self.interferences: dict[str, InterferenceRecord] = {}
        self.holon_nodes: dict[str, HolonNode] = {}
        self.holon_holarchies: dict[str, str] = {}  # holarchy_id → root_id
        self.rubrics: dict[str, RubricRecord] = {}
        self.evaluations: dict[str, EvaluationRecord] = {}
        self.rule_profiles: dict[str, RuleProfile] = {}
        self.rule_conflicts: dict[str, RuleConflictRecord] = {}
        self.validations: dict[str, ValidationRecord] = {}
        self.hypotheses: dict[str, HypothesisRecord] = {}
        self.constraints: dict[str, ConstraintRecord] = {}
        self.constraint_validations: dict[str, ConstraintValidationRecord] = {}
        self.topologies: dict[str, TopologyRecord] = {}
        self.evidence: dict[str, EvidenceRecord] = {}
        self.evidence_chains: dict[str, EvidenceChainRecord] = {}
        self.iterations: dict[str, IterationRecord] = {}
        self.artifacts: dict[str, ArtifactRecord] = {}
        self._artifact_ids_by_kind: dict[str, set[str]] = {}
        self._artifact_ids_by_phase: dict[str, set[str]] = {}
        self._artifact_ids_by_mode: dict[str, set[str]] = {}
        self._artifact_ids_by_ref: dict[str, set[str]] = {}
        self._artifact_order: list[str] = []

    @property
    def state_lock(self):
        """Expose the internal RLock so tool-layer code can hold it during
        multi-step read-modify-write sequences on engine-owned dataclasses
        (e.g. holon_update, propagate_up/down, and the items[] batch paths
        in think_model / think_science / think_monitor / think_decide /
        think_debug).

        Use as `with engine.state_lock:`. Prefer `@_synchronized` engine
        methods for single-step mutations; use this only when the tool
        layer legitimately needs a compound atomic block.
        """
        return self._state_lock

    def connect(self) -> None:
        """No-op — in-memory engine needs no connection."""

    @_synchronized
    def close(self) -> None:
        """Clear all state."""
        self.thought_nodes.clear()
        self.thought_trees.clear()
        self.models.clear()
        self.decisions.clear()
        self.debugs.clear()
        self.args.clear()
        self.inquiries.clear()
        self.monitors.clear()
        self.interferences.clear()
        self.holon_nodes.clear()
        self.holon_holarchies.clear()
        self.rubrics.clear()
        self.evaluations.clear()
        self.rule_profiles.clear()
        self.rule_conflicts.clear()
        self.validations.clear()
        self.hypotheses.clear()
        self.constraints.clear()
        self.constraint_validations.clear()
        self.topologies.clear()
        self.evidence.clear()
        self.evidence_chains.clear()
        self.iterations.clear()
        self.artifacts.clear()
        self._artifact_ids_by_kind.clear()
        self._artifact_ids_by_phase.clear()
        self._artifact_ids_by_mode.clear()
        self._artifact_ids_by_ref.clear()
        self._artifact_order.clear()

    # ── Thought graph ──────────────────────────────────────

    @_synchronized
    def add_node(self, node: ThoughtNode) -> None:
        """Add a node to the thought graph. Updates parent's children list."""
        # Evict BEFORE inserting so the new node is never a victim
        self._cleanup_graph_memory()
        self.thought_nodes[node.id] = node
        if node.parent_id is None:
            # Root node — register the tree
            self.thought_trees[node.tree_id] = node.id
        elif node.parent_id in self.thought_nodes:
            parent = self.thought_nodes[node.parent_id]
            if node.id not in parent.children:
                parent.children.append(node.id)

    @_synchronized
    def add_node_with_children(
        self,
        parent_node: ThoughtNode,
        child_specs: list[dict],
    ) -> tuple[str, list[str]]:
        """Atomically add a parent node and N children in one lock acquisition.

        Each child_spec must contain 'thought' (str). Optional 'metadata' (dict)
        and 'action' (str, defaults to parent's action).

        Returns (parent_id, child_ids) in submission order.
        """
        import uuid as _uuid

        # Insert parent first so child.parent_id resolves
        self._cleanup_graph_memory()
        self.thought_nodes[parent_node.id] = parent_node
        if parent_node.parent_id is None:
            self.thought_trees[parent_node.tree_id] = parent_node.id
        elif parent_node.parent_id in self.thought_nodes:
            grandparent = self.thought_nodes[parent_node.parent_id]
            if parent_node.id not in grandparent.children:
                grandparent.children.append(parent_node.id)

        child_ids: list[str] = []
        for spec in child_specs:
            content = spec.get("thought", "")
            if not content:
                raise ValueError("Each child must include a non-empty 'thought' field")
            cid = _uuid.uuid4().hex[:10]
            child = ThoughtNode(
                id=cid,
                tree_id=parent_node.tree_id,
                content=content,
                action=spec.get("action", "think"),
                parent_id=parent_node.id,
                depth=parent_node.depth + 1,
                metadata=spec.get("metadata") or {},
            )
            self.thought_nodes[cid] = child
            parent_node.children.append(cid)
            child_ids.append(cid)
        return parent_node.id, child_ids

    @_synchronized
    def add_nodes_batch(self, node_specs: list[dict]) -> list[ThoughtNode]:
        """Atomically add multiple thought nodes with internal parent refs.

        node_specs entries must already be normalized with concrete node ids.
        parent_id may refer to an existing node or to another earlier-created
        batch node. Validation is fail-fast before any mutation.
        """
        if not node_specs:
            return []

        known_ids = set(self.thought_nodes.keys())
        batch_ids = {str(spec["id"]) for spec in node_specs}
        created: list[ThoughtNode] = []

        # Validate all parent links first.
        for spec in node_specs:
            parent_id = spec.get("parent_id")
            if parent_id and parent_id not in known_ids and parent_id not in batch_ids:
                raise ValueError(f"Parent node '{parent_id}' not found for batch node")

        self._cleanup_graph_memory()
        for spec in node_specs:
            node = ThoughtNode(
                id=str(spec["id"]),
                tree_id=str(spec["tree_id"]),
                content=str(spec["content"]),
                action=str(spec.get("action", "think")),
                parent_id=spec.get("parent_id"),
                children=[],
                depends_on=list(spec.get("depends_on") or []),
                refs=list(spec.get("refs") or []),
                rule_bindings=list(spec.get("rule_bindings") or []),
                depth=int(spec.get("depth", 0)),
                metadata=dict(spec.get("metadata") or {}),
            )
            self.thought_nodes[node.id] = node
            if node.parent_id is None:
                self.thought_trees[node.tree_id] = node.id
            else:
                parent = self.thought_nodes.get(node.parent_id)
                if parent is not None and node.id not in parent.children:
                    parent.children.append(node.id)
            created.append(node)
        return created

    def get_node(self, node_id: str) -> ThoughtNode | None:
        return self.thought_nodes.get(node_id)

    def get_tree_root(self, tree_id: str) -> ThoughtNode | None:
        root_id = self.thought_trees.get(tree_id)
        if root_id is None:
            return None
        return self.thought_nodes.get(root_id)

    def get_subtree_nodes(self, node_id: str) -> list[ThoughtNode]:
        """BFS from node, returns node + all descendants."""
        root = self.thought_nodes.get(node_id)
        if root is None:
            return []
        result: list[ThoughtNode] = []
        visited: set[str] = set()
        queue = deque([root])
        while queue:
            current = queue.popleft()
            if current.id in visited:
                continue
            visited.add(current.id)
            result.append(current)
            for child_id in current.children:
                if child_id not in visited:
                    child = self.thought_nodes.get(child_id)
                    if child:
                        queue.append(child)
        return result

    def get_path_to_root(self, node_id: str) -> list[ThoughtNode]:
        """Trace ancestry from node up to root. Returns [node, parent, ..., root]."""
        path: list[ThoughtNode] = []
        current = self.thought_nodes.get(node_id)
        seen: set[str] = set()
        while current and current.id not in seen:
            path.append(current)
            seen.add(current.id)
            if current.parent_id is None:
                break
            current = self.thought_nodes.get(current.parent_id)
        return path

    @_synchronized
    def revise_node(self, node_id: str, new_content: str) -> ThoughtNode | None:
        """Update a node's content, preserving history."""
        node = self.thought_nodes.get(node_id)
        if node is None:
            return None
        node.revision_history.append(node.content)
        node.content = new_content
        node.action = "revise"
        return node

    def get_tree_ids(self) -> list[str]:
        return list(self.thought_trees.keys())

    def get_node_count(self) -> int:
        return len(self.thought_nodes)

    # ── Unified artifacts ───────────────────────────────

    @_synchronized
    def upsert_artifact(self, record: ArtifactRecord) -> None:
        existing = self.artifacts.get(record.id)
        if existing is not None:
            self._deindex_artifact(existing)
        else:
            self._artifact_order.append(record.id)
        self.artifacts[record.id] = record
        self._index_artifact(record)

    @_synchronized
    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        return self.artifacts.get(artifact_id)

    def _artifact_related_refs(self, record: ArtifactRecord) -> set[str]:
        return set(
            record.refs
            + record.connects_to
            + record.supports
            + record.contradicts
            + record.derived_from
        )

    def _index_artifact(self, record: ArtifactRecord) -> None:
        self._artifact_ids_by_kind.setdefault(record.kind, set()).add(record.id)
        self._artifact_ids_by_phase.setdefault(record.phase, set()).add(record.id)
        self._artifact_ids_by_mode.setdefault(record.mode, set()).add(record.id)
        for ref in self._artifact_related_refs(record):
            self._artifact_ids_by_ref.setdefault(ref, set()).add(record.id)

    def _deindex_artifact(self, record: ArtifactRecord) -> None:
        buckets = (
            (self._artifact_ids_by_kind, record.kind),
            (self._artifact_ids_by_phase, record.phase),
            (self._artifact_ids_by_mode, record.mode),
        )
        for bucket_map, key in buckets:
            ids = bucket_map.get(key)
            if ids is None:
                continue
            ids.discard(record.id)
            if not ids:
                bucket_map.pop(key, None)
        for ref in self._artifact_related_refs(record):
            ids = self._artifact_ids_by_ref.get(ref)
            if ids is None:
                continue
            ids.discard(record.id)
            if not ids:
                self._artifact_ids_by_ref.pop(ref, None)

    @_synchronized
    def iter_artifact_ids(self, *, reverse: bool = True) -> list[str]:
        ids = list(self._artifact_order)
        if reverse:
            ids.reverse()
        return ids

    @_synchronized
    def recent_artifacts(self, limit: int) -> list[ArtifactRecord]:
        out: list[ArtifactRecord] = []
        for artifact_id in reversed(self._artifact_order):
            artifact = self.artifacts.get(artifact_id)
            if artifact is not None:
                out.append(artifact)
            if len(out) >= limit:
                break
        return out

    @_synchronized
    def list_artifacts(
        self,
        *,
        kind: str | None = None,
        phase: str | None = None,
        mode: str | None = None,
        ref: str | None = None,
        status: str | None = None,
    ) -> list[ArtifactRecord]:
        filters: list[set[str]] = []
        if kind:
            filters.append(set(self._artifact_ids_by_kind.get(kind, set())))
        if phase:
            filters.append(set(self._artifact_ids_by_phase.get(phase, set())))
        if mode:
            filters.append(set(self._artifact_ids_by_mode.get(mode, set())))
        if ref:
            filters.append(set(self._artifact_ids_by_ref.get(ref, set())))

        candidate_ids: set[str] | None = None
        for ids in filters:
            if candidate_ids is None:
                candidate_ids = ids
            else:
                candidate_ids &= ids
            if not candidate_ids:
                return []

        ordered: list[ArtifactRecord] = []
        for artifact_id in reversed(self._artifact_order):
            if candidate_ids is not None and artifact_id not in candidate_ids:
                continue
            artifact = self.artifacts.get(artifact_id)
            if artifact is None:
                continue
            if status is not None and artifact.status != status:
                continue
            ordered.append(artifact)
        return ordered

    # ── Mental models ────────────────────────────────────

    @_synchronized
    def add_model(self, record: ModelRecord) -> None:
        self.models.append(record)

    def get_model(self, record_id: str) -> ModelRecord | None:
        for record in self.models:
            if record.record_id == record_id:
                return record
        return None

    # ── Decisions ────────────────────────────────────────

    @_synchronized
    def upsert_decision(self, record: DecisionRecord) -> None:
        self.decisions[record.decision_id] = record

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        return self.decisions.get(decision_id)

    # ── Debugging ────────────────────────────────────────

    @_synchronized
    def add_debug(self, record: DebugRecord) -> None:
        self.debugs.append(record)

    # ── Argumentation ────────────────────────────────────

    @_synchronized
    def add_argument(self, chain_id: str, record: ArgRecord) -> None:
        self.args.setdefault(chain_id, []).append(record)

    def get_arg_chain(self, chain_id: str) -> list[ArgRecord]:
        return self.args.get(chain_id, [])

    # ── Scientific method ────────────────────────────────

    @_synchronized
    def upsert_inquiry(self, record: InquiryRecord) -> None:
        self.inquiries[record.inquiry_id] = record

    def get_inquiry(self, inquiry_id: str) -> InquiryRecord | None:
        return self.inquiries.get(inquiry_id)

    # ── Metacognitive monitoring ─────────────────────────

    @_synchronized
    def upsert_monitor(self, record: MonitorRecord) -> None:
        self.monitors[record.monitoring_id] = record

    def get_monitor(self, monitoring_id: str) -> MonitorRecord | None:
        return self.monitors.get(monitoring_id)

    # ── Interference Protocol ────────────────────────────

    @_synchronized
    def upsert_interference(self, record: InterferenceRecord) -> None:
        self.interferences[record.protocol_id] = record

    def get_interference(self, protocol_id: str) -> InterferenceRecord | None:
        return self.interferences.get(protocol_id)

    # ── Holonic workspace ────────────────────────────────

    @_synchronized
    def add_holon(self, node: HolonNode) -> None:
        """Add a holon. Registers holarchy root if first membership has no parent."""
        self._cleanup_holon_memory()
        self.holon_nodes[node.id] = node
        for m in node.memberships:
            hid = m["holarchy_id"]
            pid = m.get("parent_id")
            if pid is None:
                self.holon_holarchies[hid] = node.id
            elif pid in self.holon_nodes:
                parent = self.holon_nodes[pid]
                children = parent.children_by_holarchy.setdefault(hid, [])
                if node.id not in children:
                    children.append(node.id)

    @_synchronized
    def add_holons_batch(
        self,
        items: list[dict],
        default_holarchy_id: str,
    ) -> dict[str, str]:
        """Atomically create N holons with parent_ref resolution.

        Each item must have:
            ref: str — temp reference (must be unique within batch)
            name: str
            description: str
        Optional:
            parent_ref: str | None — either another item's ref OR an
                existing holon_id. None = root of holarchy.
            role_in_parent: str
            context: str
            rules: list[str]
            properties: list[str]
            projection: str
            holarchy_id: str — overrides default_holarchy_id

        Returns: {ref: holon_id} mapping for all created holons.

        Raises ValueError on: duplicate refs, unresolvable parent_ref,
        missing required fields, cycles in parent_ref graph.
        """
        import uuid as _uuid

        # Phase 1: validate refs are unique + required fields present
        refs_seen: set[str] = set()
        for item in items:
            ref = item.get("ref")
            if not ref:
                raise ValueError("Each holon in batch must have a 'ref' field")
            if ref in refs_seen:
                raise ValueError(f"Duplicate ref '{ref}' in batch")
            refs_seen.add(ref)
            if not item.get("name"):
                raise ValueError(f"Holon ref='{ref}' missing 'name'")
            if not item.get("description"):
                raise ValueError(f"Holon ref='{ref}' missing 'description'")

        # Phase 2: assign uuid IDs + topological sort
        ref_to_id: dict[str, str] = {ref: _uuid.uuid4().hex[:10] for ref in refs_seen}

        # Build dependency graph: ref -> parent_ref (or None for resolved/external)
        depends_on: dict[str, str | None] = {}
        for item in items:
            ref = item["ref"]
            pref = item.get("parent_ref")
            # parent_ref may be (a) None, (b) another item's ref, (c) existing holon_id
            if pref and pref in refs_seen:
                depends_on[ref] = pref
            else:
                depends_on[ref] = None  # external or root — no batch dependency

        # Topological order: process roots/externals first
        ordered: list[str] = []
        visited: set[str] = set()
        temp_mark: set[str] = set()

        def _visit(r: str) -> None:
            if r in visited:
                return
            if r in temp_mark:
                raise ValueError(f"Cycle detected in parent_ref graph at '{r}'")
            temp_mark.add(r)
            dep = depends_on.get(r)
            if dep is not None:
                _visit(dep)
            temp_mark.discard(r)
            visited.add(r)
            ordered.append(r)

        for r in refs_seen:
            _visit(r)

        # Phase 3: create holons in topological order
        self._cleanup_holon_memory()
        items_by_ref = {item["ref"]: item for item in items}
        for ref in ordered:
            item = items_by_ref[ref]
            hid = item.get("holarchy_id") or default_holarchy_id
            pref = item.get("parent_ref")
            parent_id: str | None
            level = 0
            if pref:
                # Resolve to existing or batch-allocated id
                parent_id = ref_to_id.get(pref) or pref
                parent = self.holon_nodes.get(parent_id)
                if parent is None:
                    raise ValueError(
                        f"parent_ref '{pref}' for ref='{ref}' "
                        "did not resolve to an existing or batched holon"
                    )
                # Infer holarchy from parent if not set
                if not item.get("holarchy_id"):
                    if parent.memberships:
                        hid = parent.memberships[0]["holarchy_id"]
                pm = next(
                    (m for m in parent.memberships if m["holarchy_id"] == hid),
                    None,
                )
                if pm:
                    level = pm["level"] + 1
            else:
                parent_id = None

            nid = ref_to_id[ref]
            projection = item.get("projection", "")
            node = HolonNode(
                id=nid,
                name=item["name"],
                description=item["description"],
                context=item.get("context", ""),
                rules=item.get("rules") or [],
                properties=item.get("properties") or [],
                memberships=[
                    {
                        "holarchy_id": hid,
                        "parent_id": parent_id,
                        "role_in_parent": item.get("role_in_parent", ""),
                        "level": level,
                    }
                ],
                projections={hid: projection} if projection else {},
            )
            self.holon_nodes[nid] = node
            if parent_id is None:
                self.holon_holarchies[hid] = nid
            elif parent_id in self.holon_nodes:
                parent = self.holon_nodes[parent_id]
                children = parent.children_by_holarchy.setdefault(hid, [])
                if nid not in children:
                    children.append(nid)

        return ref_to_id

    @_synchronized
    def join_holarchy(
        self,
        holon_id: str,
        holarchy_id: str,
        parent_id: str,
        role: str,
        level: int,
    ) -> HolonNode | None:
        """Add an existing holon to another holarchy."""
        node = self.holon_nodes.get(holon_id)
        if node is None:
            return None
        # Prevent duplicate memberships
        for m in node.memberships:
            if m["holarchy_id"] == holarchy_id:
                return node  # already a member
        node.memberships.append(
            {
                "holarchy_id": holarchy_id,
                "parent_id": parent_id,
                "role_in_parent": role,
                "level": level,
            }
        )
        if parent_id in self.holon_nodes:
            parent = self.holon_nodes[parent_id]
            children = parent.children_by_holarchy.setdefault(holarchy_id, [])
            if holon_id not in children:
                children.append(holon_id)
        return node

    def get_holon(self, holon_id: str) -> HolonNode | None:
        return self.holon_nodes.get(holon_id)

    def get_holon_children(self, holon_id: str, holarchy_id: str) -> list[HolonNode]:
        node = self.holon_nodes.get(holon_id)
        if node is None:
            return []
        child_ids = node.children_by_holarchy.get(holarchy_id, [])
        return [self.holon_nodes[cid] for cid in child_ids if cid in self.holon_nodes]

    def get_holon_parent(self, holon_id: str, holarchy_id: str) -> HolonNode | None:
        node = self.holon_nodes.get(holon_id)
        if node is None:
            return None
        for m in node.memberships:
            if m["holarchy_id"] == holarchy_id:
                pid = m.get("parent_id")
                if pid:
                    return self.holon_nodes.get(pid)
        return None

    def get_holon_siblings(self, holon_id: str, holarchy_id: str) -> list[HolonNode]:
        parent = self.get_holon_parent(holon_id, holarchy_id)
        if parent is None:
            return []
        return [c for c in self.get_holon_children(parent.id, holarchy_id) if c.id != holon_id]

    def get_holon_ancestry(self, holon_id: str, holarchy_id: str) -> list[HolonNode]:
        """Trace ancestry in a specific holarchy. Returns [node, parent, ..., root]."""
        path: list[HolonNode] = []
        seen: set[str] = set()
        current = self.holon_nodes.get(holon_id)
        while current and current.id not in seen:
            path.append(current)
            seen.add(current.id)
            parent = self.get_holon_parent(current.id, holarchy_id)
            if parent is None:
                break
            current = parent
        return path

    def get_holon_subtree(
        self,
        holon_id: str,
        holarchy_id: str,
        max_depth: int | None = None,
    ) -> list[HolonNode]:
        """BFS descendants in a specific holarchy with optional depth limit."""
        root = self.holon_nodes.get(holon_id)
        if root is None:
            return []
        result: list[HolonNode] = []
        visited: set[str] = set()
        queue: deque[tuple[HolonNode, int]] = deque([(root, 0)])
        while queue:
            current, depth = queue.popleft()
            if current.id in visited:
                continue
            if max_depth is not None and depth > max_depth:
                continue
            visited.add(current.id)
            result.append(current)
            for child in self.get_holon_children(current.id, holarchy_id):
                if child.id not in visited:
                    queue.append((child, depth + 1))
        return result

    def find_bridge(self, from_id: str, to_id: str) -> list[HolonNode]:
        """BFS across ALL holarchies to find shortest path between holons."""
        if from_id not in self.holon_nodes or to_id not in self.holon_nodes:
            return []
        if from_id == to_id:
            return [self.holon_nodes[from_id]]

        visited: set[str] = set()
        parent_map: dict[str, str] = {}
        queue: deque[str] = deque([from_id])
        visited.add(from_id)

        while queue:
            current_id = queue.popleft()
            if current_id == to_id:
                # Reconstruct path
                path: list[str] = [to_id]
                nid = to_id
                while nid in parent_map:
                    nid = parent_map[nid]
                    path.append(nid)
                path.reverse()
                return [self.holon_nodes[pid] for pid in path if pid in self.holon_nodes]

            node = self.holon_nodes.get(current_id)
            if node is None:
                continue

            # Traverse ALL connections: parents + children in every holarchy
            neighbors: set[str] = set()
            for m in node.memberships:
                hid = m["holarchy_id"]
                pid = m.get("parent_id")
                if pid:
                    neighbors.add(pid)
                for child_id in node.children_by_holarchy.get(hid, []):
                    neighbors.add(child_id)

            for nid in neighbors:
                if nid not in visited:
                    visited.add(nid)
                    parent_map[nid] = current_id
                    queue.append(nid)

        return []  # No path found

    def get_holarchy_ids(self) -> list[str]:
        return list(self.holon_holarchies.keys())

    def get_holon_count(self) -> int:
        return len(self.holon_nodes)

    def _cleanup_holon_memory(self) -> None:
        """Evict oldest holarchies when limits exceeded."""
        if len(self.holon_holarchies) >= MAX_HOLARCHIES:
            hids = list(self.holon_holarchies.keys())
            n_remove = max(1, len(hids) - MAX_HOLARCHIES + 1)
            for hid in hids[:n_remove]:
                self._evict_holarchy(hid)

        while len(self.holon_nodes) >= MAX_HOLONS and self.holon_holarchies:
            oldest = next(iter(self.holon_holarchies))
            self._evict_holarchy(oldest)

    def _evict_holarchy(self, holarchy_id: str) -> None:
        """Multi-membership-safe eviction of a holarchy."""
        self.holon_holarchies.pop(holarchy_id, None)
        to_delete: list[str] = []
        for hid, node in self.holon_nodes.items():
            # Remove membership for this holarchy
            node.memberships = [m for m in node.memberships if m["holarchy_id"] != holarchy_id]
            # Remove children tracking for this holarchy
            node.children_by_holarchy.pop(holarchy_id, None)
            # Remove projections/stale for this holarchy
            node.projections.pop(holarchy_id, None)
            node.stale_projections.discard(holarchy_id)
            # Mark for deletion if no memberships remain
            if not node.memberships:
                to_delete.append(hid)
        for hid in to_delete:
            self.holon_nodes.pop(hid, None)

    # ── Rule registry + plan-aware validation ───────────

    def _cleanup_rule_memory(self) -> None:
        """Evict oldest closed validations and unbound profiles if needed."""
        if len(self.validations) >= MAX_RULE_VALIDATIONS:
            ordered = sorted(
                self.validations.values(),
                key=lambda v: v.created_at,
            )
            n_remove = max(1, len(self.validations) - MAX_RULE_VALIDATIONS + 1)
            for record in ordered[:n_remove]:
                self.validations.pop(record.id, None)

        if len(self.rule_profiles) >= MAX_RULE_PROFILES:
            bound_profile_ids = {
                binding.get("profile_id")
                for subject in self._iter_rule_bound_subjects()
                for binding in getattr(subject, "rule_bindings", [])
            }
            removable = [
                p
                for p in sorted(self.rule_profiles.values(), key=lambda p: p.created_at)
                if p.id not in bound_profile_ids
            ]
            n_remove = max(1, len(self.rule_profiles) - MAX_RULE_PROFILES + 1)
            for profile in removable[:n_remove]:
                self.rule_profiles.pop(profile.id, None)

    def _iter_rule_bound_subjects(self) -> list[object]:
        """Return every subject type that can carry rule bindings."""
        subjects: list[object] = []
        subjects.extend(self.thought_nodes.values())
        subjects.extend(self.models)
        subjects.extend(self.decisions.values())
        subjects.extend(self.inquiries.values())
        subjects.extend(self.monitors.values())
        subjects.extend(self.holon_nodes.values())
        subjects.extend(self.evaluations.values())
        return subjects

    def _normalize_rule_bindings(self, bindings: list[dict] | None) -> list[dict]:
        """Validate and dedupe rule bindings while preserving order."""
        out: list[dict] = []
        seen: set[tuple[str, str | None]] = set()
        for binding in bindings or []:
            profile_id = str(binding.get("profile_id") or "").strip()
            snapshot_id = binding.get("snapshot_id")
            if not profile_id:
                raise ValueError("Rule binding missing profile_id")
            profile = self.rule_profiles.get(profile_id)
            if profile is None:
                raise ValueError(f"Rule profile '{profile_id}' not found")
            if snapshot_id:
                if all(s.id != snapshot_id for s in profile.snapshots):
                    raise ValueError(
                        f"Snapshot '{snapshot_id}' not found on profile '{profile_id}'"
                    )
            key = (profile_id, snapshot_id)
            if key in seen:
                continue
            seen.add(key)
            out.append({"profile_id": profile_id, "snapshot_id": snapshot_id})
        return out

    def _get_subject(self, subject_id: str, subject_kind: str | None = None) -> tuple[str, object]:
        """Resolve a subject id across supported record types."""
        normalized = (subject_kind or "").strip().lower()
        if normalized in {"thought", "thought_node", "node"}:
            node = self.thought_nodes.get(subject_id)
            if node is None:
                raise ValueError(f"Thought node '{subject_id}' not found")
            return "thought", node
        if normalized in {"model", "mental_model"}:
            rec = self.get_model(subject_id)
            if rec is None:
                raise ValueError(f"Model record '{subject_id}' not found")
            return "model", rec
        if normalized in {"decision"}:
            rec = self.decisions.get(subject_id)
            if rec is None:
                raise ValueError(f"Decision '{subject_id}' not found")
            return "decision", rec
        if normalized in {"inquiry", "science"}:
            rec = self.inquiries.get(subject_id)
            if rec is None:
                raise ValueError(f"Inquiry '{subject_id}' not found")
            return "inquiry", rec
        if normalized in {"monitor", "assessment"}:
            rec = self.monitors.get(subject_id)
            if rec is None:
                raise ValueError(f"Monitor '{subject_id}' not found")
            return "monitor", rec
        if normalized in {"holon"}:
            rec = self.holon_nodes.get(subject_id)
            if rec is None:
                raise ValueError(f"Holon '{subject_id}' not found")
            return "holon", rec
        if normalized in {"evaluation", "score"}:
            rec = self.evaluations.get(subject_id)
            if rec is None:
                raise ValueError(f"Evaluation '{subject_id}' not found")
            return "evaluation", rec

        candidates: list[tuple[str, object]] = []
        if subject_id in self.thought_nodes:
            candidates.append(("thought", self.thought_nodes[subject_id]))
        model = self.get_model(subject_id)
        if model is not None:
            candidates.append(("model", model))
        if subject_id in self.decisions:
            candidates.append(("decision", self.decisions[subject_id]))
        if subject_id in self.inquiries:
            candidates.append(("inquiry", self.inquiries[subject_id]))
        if subject_id in self.monitors:
            candidates.append(("monitor", self.monitors[subject_id]))
        if subject_id in self.holon_nodes:
            candidates.append(("holon", self.holon_nodes[subject_id]))
        if subject_id in self.evaluations:
            candidates.append(("evaluation", self.evaluations[subject_id]))
        if not candidates:
            raise ValueError(f"Subject '{subject_id}' not found")
        if len(candidates) > 1:
            kinds = ", ".join(k for k, _ in candidates)
            raise ValueError(
                f"Subject '{subject_id}' is ambiguous across kinds: {kinds}. "
                "Pass subject_kind to disambiguate."
            )
        return candidates[0]

    def _subject_rule_refs(self, bindings: list[dict], entity_id: str) -> bool:
        """Return whether a binding set references a profile, snapshot, or rule."""
        for binding in bindings:
            profile_id = binding.get("profile_id")
            snapshot_id = binding.get("snapshot_id")
            if entity_id == profile_id or entity_id == snapshot_id:
                return True
            for profile_ref, _, rule in self.get_effective_rules([binding]):
                if entity_id in {rule.id, profile_ref}:
                    return True
        return False

    def get_effective_rules(self, bindings: list[dict]) -> list[tuple[str, str | None, RuleItem]]:
        """Expand live/snapshot bindings into active rule items."""
        effective: list[tuple[str, str | None, RuleItem]] = []
        for binding in self._normalize_rule_bindings(bindings):
            profile_id = binding["profile_id"]
            snapshot_id = binding.get("snapshot_id")
            profile = self.rule_profiles[profile_id]
            if snapshot_id:
                snapshot = next(
                    (s for s in profile.snapshots if s.id == snapshot_id),
                    None,
                )
                if snapshot is None:
                    continue
                source_rules = snapshot.rules
            else:
                source_rules = profile.rules
            for rule in source_rules:
                if rule.status == "active":
                    effective.append((profile_id, snapshot_id, _clone_rule_item(rule)))
        return effective

    @_synchronized
    def upsert_rule_profile(self, record: RuleProfile) -> None:
        if record.id not in self.rule_profiles:
            self._cleanup_rule_memory()
        self.rule_profiles[record.id] = record

    def get_rule_profile(self, profile_id: str) -> RuleProfile | None:
        return self.rule_profiles.get(profile_id)

    def get_rule_profiles(self) -> list[RuleProfile]:
        return list(self.rule_profiles.values())

    @_synchronized
    def add_rules_batch(self, profile_id: str, rules: list[RuleItem]) -> RuleProfile:
        profile = self.rule_profiles.get(profile_id)
        if profile is None:
            raise ValueError(f"Rule profile '{profile_id}' not found")
        existing_ids = {r.id for r in profile.rules}
        for rule in rules:
            if rule.id in existing_ids:
                raise ValueError(f"Rule '{rule.id}' already exists in profile '{profile_id}'")
            existing_ids.add(rule.id)
            profile.rules.append(rule)
        return profile

    @_synchronized
    def update_rule_weights(self, profile_id: str, updates: list[dict]) -> RuleProfile:
        profile = self.rule_profiles.get(profile_id)
        if profile is None:
            raise ValueError(f"Rule profile '{profile_id}' not found")
        by_id = {r.id: r for r in profile.rules}
        for update in updates:
            rule_id = update["rule_id"]
            if rule_id not in by_id:
                raise ValueError(f"Rule '{rule_id}' not found in profile '{profile_id}'")
            by_id[rule_id].weight = float(update["weight"])
        return profile

    @_synchronized
    def deprecate_rules(self, profile_id: str, rule_ids: list[str]) -> RuleProfile:
        profile = self.rule_profiles.get(profile_id)
        if profile is None:
            raise ValueError(f"Rule profile '{profile_id}' not found")
        by_id = {r.id: r for r in profile.rules}
        for rule_id in rule_ids:
            if rule_id not in by_id:
                raise ValueError(f"Rule '{rule_id}' not found in profile '{profile_id}'")
            by_id[rule_id].status = "superseded"
        return profile

    @_synchronized
    def create_rule_snapshot(
        self, profile_id: str, snapshot_id: str, label: str = ""
    ) -> RuleSnapshot:
        profile = self.rule_profiles.get(profile_id)
        if profile is None:
            raise ValueError(f"Rule profile '{profile_id}' not found")
        if any(s.id == snapshot_id for s in profile.snapshots):
            raise ValueError(f"Snapshot '{snapshot_id}' already exists on profile '{profile_id}'")
        snapshot = RuleSnapshot(
            id=snapshot_id,
            profile_id=profile_id,
            label=label,
            rules=[_clone_rule_item(rule) for rule in profile.rules],
        )
        profile.snapshots.append(snapshot)
        return snapshot

    @_synchronized
    def bind_rule_profiles(
        self,
        subject_id: str,
        subject_kind: str | None,
        bindings: list[dict],
    ) -> tuple[str, list[dict]]:
        resolved_kind, subject = self._get_subject(subject_id, subject_kind)
        normalized = self._normalize_rule_bindings(bindings)
        merged: list[dict] = []
        seen: set[tuple[str, str | None]] = set()
        for binding in list(getattr(subject, "rule_bindings", [])) + normalized:
            key = _binding_key(binding)
            if key in seen:
                continue
            seen.add(key)
            merged.append({"profile_id": key[0], "snapshot_id": key[1]})
        subject.rule_bindings = merged
        return resolved_kind, merged

    def get_subject_rule_bindings(
        self, subject_id: str, subject_kind: str | None = None
    ) -> tuple[str, list[dict]]:
        resolved_kind, subject = self._get_subject(subject_id, subject_kind)
        return resolved_kind, list(getattr(subject, "rule_bindings", []))

    @_synchronized
    def resolve_rule_conflicts(
        self,
        conflict_ids: list[str],
        resolution_note: str,
    ) -> list[RuleConflictRecord]:
        resolved: list[RuleConflictRecord] = []
        for conflict_id in conflict_ids:
            record = self.rule_conflicts.get(conflict_id)
            if record is None:
                raise ValueError(f"Rule conflict '{conflict_id}' not found")
            record.status = "resolved"
            record.resolution_note = resolution_note
            record.resolved_at = datetime.now(timezone.utc)
            resolved.append(record)
        return resolved

    def _ensure_rule_conflicts(self, bindings: list[dict]) -> list[RuleConflictRecord]:
        """Detect active conflicts, creating records when needed."""
        open_conflicts: list[RuleConflictRecord] = []
        effective = self.get_effective_rules(bindings)
        seen_pairs: set[tuple[str, str]] = set()
        for idx, (profile_a, _, rule_a) in enumerate(effective):
            for profile_b, _, rule_b in effective[idx + 1 :]:
                if rule_a.id == rule_b.id:
                    continue
                if (
                    rule_b.id not in rule_a.conflicts_with
                    and rule_a.id not in rule_b.conflicts_with
                ):
                    continue
                pair = tuple(sorted((rule_a.id, rule_b.id)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                existing = next(
                    (
                        c
                        for c in self.rule_conflicts.values()
                        if tuple(sorted(c.rule_ids)) == pair and c.status == "open"
                    ),
                    None,
                )
                if existing is None:
                    conflict_id = f"conflict-{len(self.rule_conflicts) + 1:03d}"
                    existing = RuleConflictRecord(
                        id=conflict_id,
                        rule_ids=list(pair),
                        profile_ids=sorted({profile_a, profile_b}),
                    )
                    self.rule_conflicts[conflict_id] = existing
                open_conflicts.append(existing)
        return open_conflicts

    @_synchronized
    def validate_subject(
        self,
        subject_id: str,
        subject_kind: str | None,
        assessments: list[ValidationAssessment] | None = None,
        *,
        rule_profile_ids: list[str] | None = None,
        use_bound_profiles: bool = True,
        validation_id: str,
        refs: list[str] | None = None,
        nuance_notes: list[str] | None = None,
    ) -> ValidationRecord:
        resolved_kind, subject = self._get_subject(subject_id, subject_kind)
        bindings: list[dict] = []
        if use_bound_profiles:
            bindings.extend(getattr(subject, "rule_bindings", []))
        for profile_id in rule_profile_ids or []:
            bindings.append({"profile_id": profile_id, "snapshot_id": None})
        bindings = self._normalize_rule_bindings(bindings)
        conflicts = self._ensure_rule_conflicts(bindings)
        effective = self.get_effective_rules(bindings)
        assessment_map = {a.rule_id: a for a in assessments or []}

        hard_failures: list[str] = []
        uncovered_rules: list[str] = []
        weighted_gaps: list[dict] = []
        effective_notes: list[str] = list(nuance_notes or [])
        weighted_denominator = 0.0
        weighted_numerator = 0.0

        for profile_id, snapshot_id, rule in effective:
            assessment = assessment_map.get(rule.id)
            if assessment is None:
                uncovered_rules.append(rule.id)
                if rule.kind == "soft":
                    weighted_denominator += max(0.0, float(rule.weight))
                    weighted_gaps.append(
                        {
                            "rule_id": rule.id,
                            "profile_id": profile_id,
                            "snapshot_id": snapshot_id,
                            "status": "uncovered",
                            "weight": float(rule.weight),
                        }
                    )
                continue
            if rule.kind == "hard" and assessment.status == "violates":
                hard_failures.append(rule.id)
            if assessment.status == "uncertain":
                effective_notes.append(
                    f"Uncertain judgment on rule '{rule.id}': {assessment.note or rule.text[:80]}"
                )
            if rule.kind != "soft":
                continue
            if assessment.status == "not_applicable":
                continue
            weight = max(0.0, float(rule.weight))
            weighted_denominator += weight
            credit = 0.0
            if assessment.status == "satisfies":
                credit = weight
            elif assessment.status == "uncertain":
                credit = weight * 0.5
            else:
                weighted_gaps.append(
                    {
                        "rule_id": rule.id,
                        "profile_id": profile_id,
                        "snapshot_id": snapshot_id,
                        "status": assessment.status,
                        "weight": weight,
                        "note": assessment.note,
                    }
                )
            weighted_numerator += credit

        for conflict in conflicts:
            effective_notes.append(
                f"Unresolved conflict {conflict.id}: {' vs '.join(conflict.rule_ids)}"
            )

        weighted_score = 100.0
        if weighted_denominator > 0:
            weighted_score = round((weighted_numerator / weighted_denominator) * 100.0, 1)

        weighted_gaps.sort(key=lambda g: (-float(g.get("weight", 0.0)), g["rule_id"]))
        record = ValidationRecord(
            id=validation_id,
            subject_id=subject_id,
            subject_kind=resolved_kind,
            rule_bindings=bindings,
            passed_hard_gates=not hard_failures,
            weighted_score=weighted_score,
            weighted_gaps=weighted_gaps,
            uncovered_rules=sorted(dict.fromkeys(uncovered_rules)),
            conflicting_rules=[c.id for c in conflicts if c.status == "open"],
            nuance_notes=list(dict.fromkeys(effective_notes)),
            hard_failures=sorted(dict.fromkeys(hard_failures)),
            assessments=list(assessments or []),
            refs=list(dict.fromkeys(list(refs or []))),
        )
        self.validations[record.id] = record
        if hasattr(subject, "validation_results"):
            subject.validation_results.append(
                {
                    "validation_id": record.id,
                    "weighted_score": record.weighted_score,
                    "passed_hard_gates": record.passed_hard_gates,
                }
            )
        return record

    def get_validation(self, validation_id: str) -> ValidationRecord | None:
        return self.validations.get(validation_id)

    def get_latest_validation(
        self,
        subject_id: str,
        subject_kind: str | None = None,
    ) -> ValidationRecord | None:
        normalized = (subject_kind or "").strip().lower()
        candidates = [
            record
            for record in self.validations.values()
            if record.subject_id == subject_id
            and (not normalized or record.subject_kind == normalized)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda record: record.created_at, reverse=True)
        return candidates[0]

    @_synchronized
    def subject_rule_validation_summary(
        self,
        subject_id: str,
        subject_kind: str | None = None,
    ) -> dict:
        resolved_kind, subject = self._get_subject(subject_id, subject_kind)
        bindings = list(getattr(subject, "rule_bindings", []))
        latest = self.get_latest_validation(subject_id, resolved_kind)
        conflicts = self._ensure_rule_conflicts(bindings) if bindings else []
        return {
            "subject_kind": resolved_kind,
            "bindings": bindings,
            "latest_validation_id": latest.id if latest else None,
            "passed_hard_gates": latest.passed_hard_gates if latest else True,
            "weighted_score": latest.weighted_score if latest else None,
            "hard_failures": list(latest.hard_failures) if latest else [],
            "uncovered_rules": list(latest.uncovered_rules) if latest else [],
            "conflicts": [c.id for c in conflicts if c.status == "open"],
            "nuance_notes": list(latest.nuance_notes) if latest else [],
        }

    # ── Hypotheses / Constraints / Topologies / Evidence ─────────────

    def _bounded_weight(self, value: float) -> float:
        return max(0.01, min(0.99, float(value)))

    def _recompute_hypothesis_posterior(self, record: HypothesisRecord) -> float:
        odds = self._bounded_weight(record.prior_weight) / (
            1.0 - self._bounded_weight(record.prior_weight)
        )
        for item in record.evidence:
            factor = 1.0 + (2.0 * max(0.0, min(1.0, item.strength)))
            if item.direction == "supports":
                odds *= factor
            elif item.direction == "weakens":
                odds /= max(1.0, factor)
        posterior = odds / (1.0 + odds)
        record.posterior_weight = round(self._bounded_weight(posterior), 3)
        return record.posterior_weight

    @_synchronized
    def upsert_hypothesis(self, record: HypothesisRecord) -> None:
        self.hypotheses[record.id] = record
        self._recompute_hypothesis_posterior(record)

    def get_hypothesis(self, hypothesis_id: str) -> HypothesisRecord | None:
        return self.hypotheses.get(hypothesis_id)

    def get_hypotheses(self) -> list[HypothesisRecord]:
        return list(self.hypotheses.values())

    @_synchronized
    def add_hypothesis_evidence(
        self,
        hypothesis_id: str,
        *,
        text: str,
        direction: str,
        strength: float,
        source_domain: str = "",
    ) -> HypothesisRecord:
        record = self.hypotheses.get(hypothesis_id)
        if record is None:
            raise ValueError(f"Hypothesis '{hypothesis_id}' not found")
        record.evidence.append(
            HypothesisEvidence(
                text=text,
                direction=direction,
                strength=max(0.0, min(1.0, strength)),
                source_domain=source_domain,
            )
        )
        self._recompute_hypothesis_posterior(record)
        return record

    @_synchronized
    def invalidate_hypothesis(self, hypothesis_id: str, reason: str) -> HypothesisRecord:
        record = self.hypotheses.get(hypothesis_id)
        if record is None:
            raise ValueError(f"Hypothesis '{hypothesis_id}' not found")
        record.invalidated = True
        record.invalidation_reason = reason
        return record

    @_synchronized
    def update_hypothesis(
        self,
        hypothesis_id: str,
        *,
        new_predictions: list[dict] | None = None,
        revised_statement: str | None = None,
    ) -> HypothesisRecord:
        record = self.hypotheses.get(hypothesis_id)
        if record is None:
            raise ValueError(f"Hypothesis '{hypothesis_id}' not found")
        record.history.append(
            {
                "statement": record.statement,
                "predictions": list(record.predictions),
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if revised_statement:
            record.statement = revised_statement
        if new_predictions is not None:
            record.predictions = list(new_predictions)
        return record

    @_synchronized
    def upsert_constraint(self, record: ConstraintRecord) -> None:
        self.constraints[record.id] = record

    def get_constraint(self, constraint_id: str) -> ConstraintRecord | None:
        return self.constraints.get(constraint_id)

    def get_constraints(self) -> list[ConstraintRecord]:
        return list(self.constraints.values())

    @_synchronized
    def remove_constraint(self, constraint_id: str) -> None:
        self.constraints.pop(constraint_id, None)
        for cid in [
            vid
            for vid, validation in self.constraint_validations.items()
            if validation.constraint_id == constraint_id
        ]:
            self.constraint_validations.pop(cid, None)

    @_synchronized
    def add_constraint_validation(self, record: ConstraintValidationRecord) -> None:
        self.constraint_validations[record.id] = record

    def get_constraint_validations(
        self,
        *,
        constraint_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[ConstraintValidationRecord]:
        rows = list(self.constraint_validations.values())
        if constraint_id:
            rows = [row for row in rows if row.constraint_id == constraint_id]
        if target_type:
            rows = [row for row in rows if row.target_type == target_type]
        if target_id:
            rows = [row for row in rows if row.target_id == target_id]
        return rows

    @_synchronized
    def upsert_topology(self, record: TopologyRecord) -> None:
        self.topologies[record.id] = record

    def get_topology(self, topology_id: str) -> TopologyRecord | None:
        return self.topologies.get(topology_id)

    def get_topologies(self) -> list[TopologyRecord]:
        return list(self.topologies.values())

    @_synchronized
    def upsert_evidence(self, record: EvidenceRecord) -> None:
        self.evidence[record.id] = record

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        return self.evidence.get(evidence_id)

    def get_all_evidence(self) -> list[EvidenceRecord]:
        return list(self.evidence.values())

    @_synchronized
    def add_evidence_chain(self, record: EvidenceChainRecord) -> None:
        self.evidence_chains[record.id] = record

    def get_evidence_chains(self) -> list[EvidenceChainRecord]:
        return list(self.evidence_chains.values())

    def trace_evidence_paths(self, claim_id: str) -> list[list[str]]:
        """Return provenance paths ending at claim_id, starting from primary evidence."""
        incoming: dict[str, list[EvidenceChainRecord]] = {}
        for chain in self.evidence_chains.values():
            incoming.setdefault(chain.to_id, []).append(chain)

        paths: list[list[str]] = []

        def _walk(current: str, path: list[str], seen: set[str]) -> None:
            if current in seen:
                return
            seen = set(seen)
            seen.add(current)
            parents = incoming.get(current, [])
            if not parents:
                paths.append(list(reversed(path + [current])))
                return
            for chain in parents:
                _walk(chain.from_id, path + [current], seen)

        _walk(claim_id, [], set())
        return paths

    def compute_evidence_strength(self, claim_id: str) -> float:
        """Compute aggregate evidence chain reliability for a claim."""
        incoming: dict[str, list[EvidenceChainRecord]] = {}
        for chain in self.evidence_chains.values():
            incoming.setdefault(chain.to_id, []).append(chain)

        memo: dict[str, float] = {}

        def _score(node_id: str, seen: set[str]) -> float:
            if node_id in memo:
                return memo[node_id]
            if node_id in seen:
                return 0.0
            if node_id in self.evidence:
                confidence = max(0.0, min(1.0, self.evidence[node_id].confidence))
                memo[node_id] = confidence
                return confidence
            if node_id in self.hypotheses:
                base = self.hypotheses[node_id].posterior_weight
            else:
                base = 0.5
            parents = incoming.get(node_id, [])
            if not parents:
                memo[node_id] = base
                return base
            scores: list[float] = []
            next_seen = set(seen)
            next_seen.add(node_id)
            for chain in parents:
                parent_score = _score(chain.from_id, next_seen)
                edge_score = _EVIDENCE_INFERENCE_RELIABILITY.get(chain.inference_type, 0.5)
                scores.append(parent_score * edge_score)
            score = max(scores) if scores else base
            memo[node_id] = round(max(0.0, min(1.0, score)), 3)
            return memo[node_id]

        return _score(claim_id, set())

    def orphan_evidence_ids(self) -> list[str]:
        chained = {chain.from_id for chain in self.evidence_chains.values()} | {
            chain.to_id for chain in self.evidence_chains.values()
        }
        return sorted(eid for eid in self.evidence if eid not in chained)

    # ── Scoring ──────────────────────────────────────────

    def _cleanup_scoring_memory(self) -> None:
        """Evict oldest rubrics / evaluations when MAX limits are exceeded.

        Never evicts rubrics referenced by active evaluations. Never evicts
        active evaluations (only finalized ones).
        """
        # Evict oldest finalized evaluations if over limit
        if len(self.evaluations) >= MAX_EVALUATIONS:
            finalized = [eid for eid, e in self.evaluations.items() if e.status != "active"]
            n_to_remove = max(1, len(self.evaluations) - MAX_EVALUATIONS + 1)
            for eid in finalized[:n_to_remove]:
                self.evaluations.pop(eid, None)

        # Evict oldest unreferenced rubrics if over limit
        if len(self.rubrics) >= MAX_RUBRICS:
            referenced = {e.rubric_id for e in self.evaluations.values()}
            removable = [rid for rid in self.rubrics if rid not in referenced]
            n_to_remove = max(1, len(self.rubrics) - MAX_RUBRICS + 1)
            for rid in removable[:n_to_remove]:
                self.rubrics.pop(rid, None)

    @_synchronized
    def upsert_rubric(self, record: RubricRecord) -> None:
        active = [
            e
            for e in self.evaluations.values()
            if e.rubric_id == record.id and e.status == "active"
        ]
        if active:
            raise ValueError(
                f"Cannot overwrite rubric '{record.id}': "
                f"{len(active)} active evaluation(s) reference it"
            )
        # Enforce capacity before insert
        if record.id not in self.rubrics:
            self._cleanup_scoring_memory()
        self.rubrics[record.id] = record

    def get_rubric(self, rubric_id: str) -> RubricRecord | None:
        return self.rubrics.get(rubric_id)

    def get_rubrics(self) -> list[RubricRecord]:
        return list(self.rubrics.values())

    @_synchronized
    def upsert_evaluation(self, record: EvaluationRecord) -> None:
        # Enforce capacity before insert (won't evict active evals)
        if record.id not in self.evaluations:
            self._cleanup_scoring_memory()
        self.evaluations[record.id] = record

    def get_evaluation(self, eval_id: str) -> EvaluationRecord | None:
        return self.evaluations.get(eval_id)

    def get_evaluations(self, rubric_id: str | None = None) -> list[EvaluationRecord]:
        evals = list(self.evaluations.values())
        if rubric_id:
            evals = [e for e in evals if e.rubric_id == rubric_id]
        return evals

    def get_latest_active_evaluation(self) -> EvaluationRecord | None:
        active = [e for e in self.evaluations.values() if e.status == "active"]
        if not active:
            return None
        active.sort(key=lambda e: e.created_at, reverse=True)
        return active[0]

    @_synchronized
    def apply_finding(self, eval_id: str, finding: FindingRecord) -> float:
        """Apply a finding to an evaluation, return running score.

        If finding.id is empty, assigns a unique id based on current finding
        count (done inside the lock to prevent concurrent submissions from
        colliding on identical ids).
        """
        ev = self.evaluations.get(eval_id)
        if ev is None or ev.status != "active":
            return 0.0
        rubric = self.rubrics.get(ev.rubric_id)
        if rubric is None:
            return 0.0

        # Assign id inside the lock to prevent concurrent-id collisions.
        if not finding.id:
            finding.id = f"f-{len(ev.findings) + 1:03d}"

        # Record finding
        ev.findings.append(finding)
        ev.dimensions_reviewed.add(finding.dimension)
        if finding.refs:
            ev.refs = list(dict.fromkeys([*ev.refs, *finding.refs]))

        # Apply deduction
        deduction = rubric.severity_deductions.get(finding.severity, 0.0)
        if finding.dimension in ev.dimension_scores:
            ev.dimension_scores[finding.dimension] = max(
                ev.dimension_scores[finding.dimension] - deduction,
                float(rubric.scale_min),
            )

        # Check blocking / auto-fail
        if finding.blocking:
            ev.has_blocking = True
        dim_info = next(
            (d for d in rubric.dimensions if d["id"] == finding.dimension),
            None,
        )
        highest_severity = rubric.severity_levels[0] if rubric.severity_levels else "critical"
        if finding.severity == highest_severity and dim_info and dim_info.get("required", False):
            ev.auto_fail = True

        # Compute running score
        ev.running_score = self._compute_score(ev, rubric)
        return ev.running_score

    def _compute_score(self, ev: EvaluationRecord, rubric: RubricRecord) -> float:
        """Compute score based on rubric strategy."""
        dims = rubric.dimensions
        if not dims:
            return float(rubric.scale_max)

        total_weight = sum(d["weight"] for d in dims)
        if total_weight == 0:
            return float(rubric.scale_max)

        weighted_sum = sum(
            ev.dimension_scores.get(d["id"], rubric.scale_max) * d["weight"] for d in dims
        )
        avg = weighted_sum / total_weight

        if rubric.scoring_strategy == "minimum_floor":
            required_scores = [
                ev.dimension_scores.get(d["id"], rubric.scale_max)
                for d in dims
                if d.get("required", False)
            ]
            if required_scores:
                floor = min(required_scores)
                return round(min(avg, floor), 1)

        return round(avg, 1)

    @_synchronized
    def check_finalization(
        self, eval_id: str, extra_reviewed: list[str] | None = None
    ) -> list[str]:
        """Check if all required dimensions are reviewed. Returns missing."""
        ev = self.evaluations.get(eval_id)
        if ev is None:
            return []
        rubric = self.rubrics.get(ev.rubric_id)
        if rubric is None:
            return []

        reviewed = ev.dimensions_reviewed.copy()
        if extra_reviewed:
            reviewed.update(extra_reviewed)

        required = {d["id"] for d in rubric.dimensions if d.get("required", False)}
        return sorted(required - reviewed)

    @_synchronized
    def finalize_evaluation(
        self,
        eval_id: str,
        dimensions_reviewed: list[str] | None,
        summary: str,
    ) -> tuple[list[str], EvaluationRecord | None]:
        """Atomically finalize an evaluation.

        Returns (missing_required, evaluation). If missing_required is
        non-empty, the evaluation is NOT finalized (caller should return
        the missing list as an error). Otherwise evaluation is finalized
        and the updated record is returned.

        This whole operation runs under self._state_lock so concurrent
        finalize calls can't both succeed on the same evaluation.
        """
        ev = self.evaluations.get(eval_id)
        if ev is None:
            raise ValueError(f"Evaluation '{eval_id}' not found")
        if ev.status != "active":
            raise ValueError(f"Evaluation '{eval_id}' is already {ev.status}")
        rubric = self.rubrics.get(ev.rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{ev.rubric_id}' not found")

        # check_finalization is @_synchronized but RLock allows re-entry
        missing = self.check_finalization(eval_id, dimensions_reviewed)
        if missing:
            return missing, None

        # Merge extra reviewed dimensions
        if dimensions_reviewed:
            ev.dimensions_reviewed.update(dimensions_reviewed)

        # Determine pass/fail
        if ev.auto_fail:
            ev.passed = False
        elif ev.has_blocking:
            ev.passed = False
        else:
            ev.passed = ev.running_score >= rubric.pass_threshold

        ev.final_score = ev.running_score
        ev.status = "finalized"
        ev.summary = summary or ""
        ev.finalized_at = datetime.now(timezone.utc)

        return [], ev

    # ── Summary ──────────────────────────────────────────

    def get_summary(
        self,
        max_items_per_category: int = 20,
        detail_level: str = "index",
    ) -> str:
        """Return a token-optimized summary of all thinking activity.

        Args:
            max_items_per_category: Cap on items shown per category.
                Excess items collapse to "... (N more)" footer. Prevents
                huge responses on sessions with hundreds of items.
            detail_level: Verbosity of per-item content:
                - "index" (default, backward-compat): terse one-liners with
                  60-char previews. Good for dashboards and session listings.
                - "synopsis": ~400-char previews, more branches per tree,
                  full synthesis-node content. Good for resuming a session.
                - "full": ~1200-char previews and all branches per tree.
                  Good for end-of-session review.
        """
        cap = max(1, max_items_per_category)

        if detail_level not in ("index", "synopsis", "full"):
            detail_level = "index"
        # Per-level verbosity knobs.
        if detail_level == "index":
            preview_root = 60
            preview_branch = 50
            preview_synth = 40
            branches_per_tree = 4
            synth_count = 2
        elif detail_level == "synopsis":
            preview_root = 200
            preview_branch = 200
            preview_synth = 400
            branches_per_tree = 8
            synth_count = 6
        else:  # full
            preview_root = 1200
            preview_branch = 1200
            preview_synth = 1200
            branches_per_tree = 9999
            synth_count = 9999

        def _append_items(lines, items, render):
            shown = list(items)[:cap]
            for it in shown:
                lines.append(render(it))
            omitted = len(list(items)) - len(shown)
            if omitted > 0:
                lines.append(f"- ... ({omitted} more)")

        def _preview(text: str, limit: int = 80) -> str:
            cleaned = " ".join((text or "").split())
            return cleaned[:limit] + ("..." if len(cleaned) > limit else "")

        lines: list[str] = [f"## Thinking Session Summary (detail={detail_level})"]

        # Thought Graphs
        if self.thought_nodes:
            n_trees = len(self.thought_trees)
            n_nodes = len(self.thought_nodes)
            max_depth_all = max((node.depth for node in self.thought_nodes.values()), default=0)
            lines.append(
                f"\n### Thought Graphs: {n_trees} trees, {n_nodes} nodes, max depth {max_depth_all}"
            )
            tree_items = list(self.thought_trees.items())
            for tid, root_id in tree_items[:cap]:
                root = self.thought_nodes.get(root_id)
                if root:
                    subtree = self.get_subtree_nodes(root_id)
                    max_depth = max((n.depth for n in subtree), default=0)
                    delegated = sum(1 for n in subtree if n.delegation_state)
                    root_preview = _preview(root.content, preview_root)
                    line = (
                        f'- Tree {tid}: "{root_preview}" — {len(subtree)} nodes, depth {max_depth}'
                    )
                    if delegated:
                        line += f", {delegated} delegated"
                    lines.append(line)
                    direct_children = [
                        self.thought_nodes[cid]
                        for cid in root.children[:branches_per_tree]
                        if cid in self.thought_nodes
                    ]
                    for child in direct_children:
                        child_subtree = self.get_subtree_nodes(child.id)
                        lines.append(
                            f"  Branch: {_preview(child.content, preview_branch)} "
                            f"({len(child_subtree)} nodes)"
                        )
                    synths = [n for n in subtree if n.action == "synthesize"]
                    if synths:
                        lines.append(
                            "  Synthesis: "
                            + ", ".join(
                                f"{n.id}={_preview(n.content, preview_synth)}"
                                for n in synths[:synth_count]
                            )
                        )
                    warnings = []
                    for n in subtree:
                        latest_validation = (
                            n.validation_results[-1] if n.validation_results else None
                        )
                        if latest_validation and not latest_validation.get(
                            "passed_hard_gates", True
                        ):
                            warnings.append(
                                f"{n.id} hard_gates=fail "
                                f"score={latest_validation.get('weighted_score')}"
                            )
                    if warnings:
                        lines.append("  Validation warnings: " + " | ".join(warnings[:3]))
            if len(tree_items) > cap:
                lines.append(f"- ... ({len(tree_items) - cap} more)")

            knowledge_refs = sorted(
                {
                    ref
                    for node in self.thought_nodes.values()
                    for ref in node.metadata.get("knowledge_refs", [])
                }
            )
            hypothesis_refs = sorted(
                {
                    ref
                    for node in self.thought_nodes.values()
                    for ref in node.metadata.get("hypothesis_refs", [])
                }
            )
            constraint_refs = sorted(
                {
                    ref
                    for node in self.thought_nodes.values()
                    for ref in node.metadata.get("constraint_refs", [])
                }
            )
            if knowledge_refs or hypothesis_refs or constraint_refs:
                lines.append("Cross-links:")
                if knowledge_refs:
                    lines.append(
                        "  knowledge_refs: "
                        + ", ".join(knowledge_refs[:8])
                        + (" ..." if len(knowledge_refs) > 8 else "")
                    )
                if hypothesis_refs:
                    lines.append(
                        "  hypothesis_refs: "
                        + ", ".join(hypothesis_refs[:8])
                        + (" ..." if len(hypothesis_refs) > 8 else "")
                    )
                if constraint_refs:
                    lines.append(
                        "  constraint_refs: "
                        + ", ".join(constraint_refs[:8])
                        + (" ..." if len(constraint_refs) > 8 else "")
                    )

        # Models
        if self.models:
            lines.append(f"\n### Mental Models: {len(self.models)} applied")
            _append_items(
                lines,
                self.models,
                lambda m: (
                    f"- {m.model_name}: {m.conclusion[:100] if m.conclusion else '(no conclusion)'}"
                ),
            )

        # Decisions
        if self.decisions:
            lines.append(f"\n### Decisions: {len(self.decisions)}")
            _append_items(
                lines,
                self.decisions.values(),
                lambda d: (
                    f"- {d.decision_id}: "
                    f"{d.recommendation[:100] if d.recommendation else f'stage={d.stage}'}"
                ),
            )

        # Debugs
        if self.debugs:
            lines.append(f"\n### Debugging: {len(self.debugs)} approaches")
            _append_items(
                lines,
                self.debugs,
                lambda d: (
                    f"- {d.approach_name} on "
                    f"'{d.issue[:60]}': "
                    f"{d.resolution[:100] if d.resolution else '(in progress)'}"
                ),
            )

        # Arguments
        if self.args:
            total_args = sum(len(chain) for chain in self.args.values())
            lines.append(f"\n### Argumentation: {len(self.args)} chains, {total_args} arguments")

        # Inquiries
        if self.inquiries:
            lines.append(f"\n### Scientific Inquiries: {len(self.inquiries)}")
            _append_items(
                lines,
                self.inquiries.values(),
                lambda inq: f"- {inq.inquiry_id}: stage={inq.stage}, iter={inq.iteration}",
            )

        # Monitors
        if self.monitors:
            lines.append(f"\n### Metacognitive Monitors: {len(self.monitors)}")

            def _mon(mon):  # type: ignore[no-untyped-def]
                mon_line = (
                    f"- {mon.task[:60]}: confidence={mon.overall_confidence:.2f}, stage={mon.stage}"
                )
                if mon.knowledge_assessment:
                    domain = mon.knowledge_assessment.get("domain", "?")
                    level = mon.knowledge_assessment.get("knowledgeLevel", "?")
                    mon_line += f", knowledge={domain}({level})"
                return mon_line

            _append_items(lines, self.monitors.values(), _mon)

        # Interference Protocols
        if self.interferences:
            lines.append(f"\n### Interference Protocols: {len(self.interferences)}")

            def _ip(ip):  # type: ignore[no-untyped-def]
                ip_line = (
                    f"- {ip.protocol_id}: phase={ip.phase}, "
                    f"iter={ip.iteration}, domain={ip.target_domain[:40]}"
                )
                if ip.emergent_name:
                    ip_line += f", concept={ip.emergent_name}"
                ip_line += f", sources={len(ip.source_laws)}, fragments={len(ip.fragments)}"
                return ip_line

            _append_items(lines, self.interferences.values(), _ip)

        # Holonic Workspaces
        if self.holon_nodes:
            n_holarchies = len(self.holon_holarchies)
            n_holons = len(self.holon_nodes)
            multi = sum(1 for h in self.holon_nodes.values() if len(h.memberships) > 1)
            stale = sum(len(h.stale_projections) for h in self.holon_nodes.values())
            lines.append(f"\n### Holonic Workspaces: {n_holarchies} holarchies, {n_holons} holons")
            if multi:
                lines.append(f"Multi-membership holons: {multi}")
            if stale:
                lines.append(f"Stale projections: {stale}")
            for hid, root_id in self.holon_holarchies.items():
                root = self.holon_nodes.get(root_id)
                if root:
                    lines.append(f'- {hid}: "{root.name}" (root)')

        # Scoring
        if self.rubrics or self.evaluations:
            active = sum(1 for e in self.evaluations.values() if e.status == "active")
            finalized = sum(1 for e in self.evaluations.values() if e.status == "finalized")
            lines.append(
                f"\n### Scoring: {len(self.rubrics)} rubrics, "
                f"{len(self.evaluations)} evaluations "
                f"({active} active, {finalized} finalized)"
            )

        # Rule validation
        if self.rule_profiles or self.validations:
            bound_subjects = sum(
                1
                for subject in self._iter_rule_bound_subjects()
                if getattr(subject, "rule_bindings", [])
            )
            unresolved = sum(
                1 for conflict in self.rule_conflicts.values() if conflict.status == "open"
            )
            lines.append(
                f"\n### Rule Validation: {len(self.rule_profiles)} profiles, "
                f"{len(self.validations)} validations, "
                f"{unresolved} unresolved conflicts"
            )
            if bound_subjects:
                lines.append(f"Bound subjects: {bound_subjects}")
            for profile in sorted(self.rule_profiles.values(), key=lambda p: p.created_at)[:cap]:
                active_rules = sum(1 for rule in profile.rules if rule.status == "active")
                lines.append(
                    f"- {profile.id}: {profile.name[:50]} "
                    f"({active_rules} active rules, {len(profile.snapshots)} snapshots)"
                )
            if len(self.rule_profiles) > cap:
                lines.append(f"- ... ({len(self.rule_profiles) - cap} more)")

        if self.hypotheses:
            lines.append(f"\n### Hypotheses: {len(self.hypotheses)}")
            sorted_hypotheses = sorted(
                self.hypotheses.values(),
                key=lambda h: (h.invalidated, -h.posterior_weight, h.created_at),
            )
            for hyp in sorted_hypotheses[:cap]:
                state = "invalidated" if hyp.invalidated else "active"
                lines.append(
                    f"- {hyp.id}: {state} | posterior={hyp.posterior_weight:.3f} | "
                    f"evidence={len(hyp.evidence)} | {_preview(hyp.statement, 70)}"
                )
            unvalidated = [
                hyp.id
                for hyp in self.hypotheses.values()
                if not self.get_constraint_validations(target_type="hypothesis", target_id=hyp.id)
            ]
            if unvalidated:
                lines.append(
                    "Unvalidated hypotheses: "
                    + ", ".join(unvalidated[:8])
                    + (" ..." if len(unvalidated) > 8 else "")
                )

        if self.constraints or self.constraint_validations:
            lines.append(
                f"\n### Constraints: {len(self.constraints)} registered, "
                f"{len(self.constraint_validations)} validations"
            )
            for constraint in list(self.constraints.values())[:cap]:
                vals = self.get_constraint_validations(constraint_id=constraint.id)
                passes = sum(1 for row in vals if row.status == "pass")
                fails = sum(1 for row in vals if row.status == "fail")
                lines.append(
                    f"- {constraint.id}: {constraint.constraint_type} | "
                    f"pass={passes} fail={fails} | {_preview(constraint.statement, 70)}"
                )

        if self.evidence or self.evidence_chains:
            lines.append(
                f"\n### Evidence: {len(self.evidence)} items, "
                f"{len(self.evidence_chains)} provenance links"
            )
            orphan_ids = self.orphan_evidence_ids()
            if orphan_ids:
                lines.append(
                    "Orphan evidence: "
                    + ", ".join(orphan_ids[:8])
                    + (" ..." if len(orphan_ids) > 8 else "")
                )

        if self.topologies:
            lines.append(f"\n### Topologies: {len(self.topologies)}")
            for topology in list(self.topologies.values())[:cap]:
                lines.append(
                    f"- {topology.id}: {topology.name} | nodes={len(topology.nodes)} "
                    f"edges={len(topology.edges)} | domain={topology.source_domain or '?'}"
                )

        next_focus: list[str] = []
        warning_nodes = []
        for node in self.thought_nodes.values():
            latest_validation = node.validation_results[-1] if node.validation_results else None
            if latest_validation and not latest_validation.get("passed_hard_gates", True):
                warning_nodes.append(node.id)
        if warning_nodes:
            next_focus.append(
                "Validate or split thought nodes with warnings: "
                + ", ".join(warning_nodes[:5])
                + (" ..." if len(warning_nodes) > 5 else "")
            )
        if self.hypotheses:
            unvalidated = [
                hyp.id
                for hyp in self.hypotheses.values()
                if not self.get_constraint_validations(target_type="hypothesis", target_id=hyp.id)
            ]
            if unvalidated:
                next_focus.append(
                    "Run constraint sweep on hypotheses: "
                    + ", ".join(unvalidated[:5])
                    + (" ..." if len(unvalidated) > 5 else "")
                )
        orphan_ids = self.orphan_evidence_ids()
        if orphan_ids:
            next_focus.append(
                "Chain orphan evidence into claims: "
                + ", ".join(orphan_ids[:5])
                + (" ..." if len(orphan_ids) > 5 else "")
            )
        open_conflicts = [
            conflict.id for conflict in self.rule_conflicts.values() if conflict.status == "open"
        ]
        if open_conflicts:
            next_focus.append(
                "Resolve open rule conflicts: "
                + ", ".join(open_conflicts[:5])
                + (" ..." if len(open_conflicts) > 5 else "")
            )
        if next_focus:
            lines.append("\n### Suggested Next Focus")
            for item in next_focus[:cap]:
                lines.append(f"- {item}")

        if len(lines) == 1:
            return "Empty thinking session — no activity recorded."

        return "\n".join(lines)

    # ── Memory management ────────────────────────────────

    def _cleanup_graph_memory(self) -> None:
        """Evict oldest trees when memory limits are exceeded."""
        # Evict oldest trees if at/over limit (make room BEFORE insert)
        if len(self.thought_trees) >= MAX_TREES:
            tree_ids = list(self.thought_trees.keys())
            n_to_remove = max(1, len(tree_ids) - MAX_TREES + 1)
            for tid in tree_ids[:n_to_remove]:
                self._evict_tree(tid)
            logger.debug("Evicted %d trees (limit: %d)", n_to_remove, MAX_TREES)

        # Evict oldest trees if too many nodes total (>= to make room)
        while len(self.thought_nodes) >= MAX_NODES and self.thought_trees:
            oldest_tid = next(iter(self.thought_trees))
            self._evict_tree(oldest_tid)
            logger.debug("Evicted tree %s (node limit: %d)", oldest_tid, MAX_NODES)

    def _evict_tree(self, tree_id: str) -> None:
        """Remove an entire tree and all its nodes."""
        root_id = self.thought_trees.pop(tree_id, None)
        if root_id is None:
            return
        # BFS to find all nodes in this tree
        to_remove: list[str] = []
        visited: set[str] = set()
        queue = deque([root_id])
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = self.thought_nodes.get(nid)
            if node:
                to_remove.append(nid)
                queue.extend(node.children)
        for nid in to_remove:
            self.thought_nodes.pop(nid, None)
