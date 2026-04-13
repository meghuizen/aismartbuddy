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
    validation_results: list[dict] = field(default_factory=list)
    depth: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


@dataclass
class ModelRecord:
    """Application of a mental model to a problem."""

    model_name: str
    problem: str
    steps: list[str] = field(default_factory=list)
    reasoning: str = ""
    conclusion: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DecisionRecord:
    """State for a multi-stage decision analysis."""

    decision_id: str
    statement: str
    options: list[dict] = field(default_factory=list)
    analysis_type: str = "multi-criteria"
    stage: str = "problem-definition"
    iteration: int = 0
    criteria: list[dict] = field(default_factory=list)
    evaluations: list[dict] = field(default_factory=list)
    recommendation: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DebugRecord:
    """Application of a debugging approach to an issue."""

    approach_name: str
    issue: str
    steps: list[str] = field(default_factory=list)
    findings: str = ""
    resolution: str = ""
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
class CollabRecord:
    """State for a collaborative reasoning session."""

    session_id: str
    topic: str
    personas: list[dict] = field(default_factory=list)
    contributions: list[dict] = field(default_factory=list)
    stage: str = "problem-definition"
    iteration: int = 0
    active_persona_id: str = ""
    consensus_points: list[str] = field(default_factory=list)
    disagreements: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InquiryRecord:
    """State for a scientific method inquiry."""

    inquiry_id: str
    stage: str = "observation"
    iteration: int = 0
    observation: str = ""
    question: str = ""
    hypothesis: dict | None = None
    experiment: dict | None = None
    analysis: str = ""
    conclusion: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MonitorRecord:
    """State for metacognitive monitoring."""

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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DiagramRecord:
    """State for a visual reasoning diagram."""

    diagram_id: str
    diagram_type: str = "graph"
    elements: list[dict] = field(default_factory=list)
    operations_log: list[dict] = field(default_factory=list)
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
    stale_projections: list[str] = field(default_factory=list)
    description_stale: bool = False
    analytical_lenses: list[dict] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    children_by_holarchy: dict[str, list[str]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


MAX_HOLONS = 1000
MAX_HOLARCHIES = 30


@dataclass
class FindingRecord:
    """A single finding in a scored evaluation."""

    id: str
    dimension: str
    severity: str
    blocking: bool = False
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finalized_at: datetime | None = None


MAX_RUBRICS = 100
MAX_EVALUATIONS = 100


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
        self.collaborations: dict[str, CollabRecord] = {}
        self.inquiries: dict[str, InquiryRecord] = {}
        self.monitors: dict[str, MonitorRecord] = {}
        self.diagrams: dict[str, DiagramRecord] = {}
        self.interferences: dict[str, InterferenceRecord] = {}
        self.holon_nodes: dict[str, HolonNode] = {}
        self.holon_holarchies: dict[str, str] = {}  # holarchy_id → root_id
        self.rubrics: dict[str, RubricRecord] = {}
        self.evaluations: dict[str, EvaluationRecord] = {}

    @property
    def state_lock(self):
        """Expose the internal RLock so tool-layer code can hold it during
        multi-step read-modify-write sequences on engine-owned dataclasses
        (e.g. holon_update, propagate_up/down, think_graph_validate).

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
        self.collaborations.clear()
        self.inquiries.clear()
        self.monitors.clear()
        self.diagrams.clear()
        self.interferences.clear()
        self.holon_nodes.clear()
        self.holon_holarchies.clear()
        self.rubrics.clear()
        self.evaluations.clear()

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

    # ── Mental models ────────────────────────────────────

    @_synchronized
    def add_model(self, record: ModelRecord) -> None:
        self.models.append(record)

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

    # ── Collaborative reasoning ──────────────────────────

    @_synchronized
    def upsert_collaboration(self, record: CollabRecord) -> None:
        self.collaborations[record.session_id] = record

    def get_collaboration(self, session_id: str) -> CollabRecord | None:
        return self.collaborations.get(session_id)

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

    # ── Visual reasoning ─────────────────────────────────

    @_synchronized
    def upsert_diagram(self, record: DiagramRecord) -> None:
        self.diagrams[record.diagram_id] = record

    def get_diagram(self, diagram_id: str) -> DiagramRecord | None:
        return self.diagrams.get(diagram_id)

    @_synchronized
    def delete_diagram(self, diagram_id: str) -> bool:
        """Remove a diagram. Returns True if it existed."""
        return self.diagrams.pop(diagram_id, None) is not None

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
        node.memberships.append({
            "holarchy_id": holarchy_id,
            "parent_id": parent_id,
            "role_in_parent": role,
            "level": level,
        })
        if parent_id in self.holon_nodes:
            parent = self.holon_nodes[parent_id]
            children = parent.children_by_holarchy.setdefault(holarchy_id, [])
            if holon_id not in children:
                children.append(holon_id)
        return node

    def get_holon(self, holon_id: str) -> HolonNode | None:
        return self.holon_nodes.get(holon_id)

    def get_holon_children(
        self, holon_id: str, holarchy_id: str
    ) -> list[HolonNode]:
        node = self.holon_nodes.get(holon_id)
        if node is None:
            return []
        child_ids = node.children_by_holarchy.get(holarchy_id, [])
        return [
            self.holon_nodes[cid]
            for cid in child_ids
            if cid in self.holon_nodes
        ]

    def get_holon_parent(
        self, holon_id: str, holarchy_id: str
    ) -> HolonNode | None:
        node = self.holon_nodes.get(holon_id)
        if node is None:
            return None
        for m in node.memberships:
            if m["holarchy_id"] == holarchy_id:
                pid = m.get("parent_id")
                if pid:
                    return self.holon_nodes.get(pid)
        return None

    def get_holon_siblings(
        self, holon_id: str, holarchy_id: str
    ) -> list[HolonNode]:
        parent = self.get_holon_parent(holon_id, holarchy_id)
        if parent is None:
            return []
        return [
            c for c in self.get_holon_children(parent.id, holarchy_id)
            if c.id != holon_id
        ]

    def get_holon_ancestry(
        self, holon_id: str, holarchy_id: str
    ) -> list[HolonNode]:
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

    def find_bridge(
        self, from_id: str, to_id: str
    ) -> list[HolonNode]:
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
                return [
                    self.holon_nodes[pid]
                    for pid in path
                    if pid in self.holon_nodes
                ]

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
            node.memberships = [
                m for m in node.memberships
                if m["holarchy_id"] != holarchy_id
            ]
            # Remove children tracking for this holarchy
            node.children_by_holarchy.pop(holarchy_id, None)
            # Remove projections/stale for this holarchy
            node.projections.pop(holarchy_id, None)
            node.stale_projections = [
                s for s in node.stale_projections
                if s != holarchy_id
            ]
            # Mark for deletion if no memberships remain
            if not node.memberships:
                to_delete.append(hid)
        for hid in to_delete:
            self.holon_nodes.pop(hid, None)

    # ── Scoring ──────────────────────────────────────────

    def _cleanup_scoring_memory(self) -> None:
        """Evict oldest rubrics / evaluations when MAX limits are exceeded.

        Never evicts rubrics referenced by active evaluations. Never evicts
        active evaluations (only finalized ones).
        """
        # Evict oldest finalized evaluations if over limit
        if len(self.evaluations) >= MAX_EVALUATIONS:
            finalized = [
                eid for eid, e in self.evaluations.items()
                if e.status != "active"
            ]
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
            e for e in self.evaluations.values()
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

    def get_evaluations(
        self, rubric_id: str | None = None
    ) -> list[EvaluationRecord]:
        evals = list(self.evaluations.values())
        if rubric_id:
            evals = [e for e in evals if e.rubric_id == rubric_id]
        return evals

    @_synchronized
    def apply_finding(
        self, eval_id: str, finding: FindingRecord
    ) -> float:
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
        highest_severity = (
            rubric.severity_levels[0] if rubric.severity_levels else "critical"
        )
        if (
            finding.severity == highest_severity
            and dim_info
            and dim_info.get("required", False)
        ):
            ev.auto_fail = True

        # Compute running score
        ev.running_score = self._compute_score(ev, rubric)
        return ev.running_score

    def _compute_score(
        self, ev: EvaluationRecord, rubric: RubricRecord
    ) -> float:
        """Compute score based on rubric strategy."""
        dims = rubric.dimensions
        if not dims:
            return float(rubric.scale_max)

        total_weight = sum(d["weight"] for d in dims)
        if total_weight == 0:
            return float(rubric.scale_max)

        weighted_sum = sum(
            ev.dimension_scores.get(d["id"], rubric.scale_max) * d["weight"]
            for d in dims
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

        required = {
            d["id"] for d in rubric.dimensions if d.get("required", False)
        }
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
            raise ValueError(
                f"Evaluation '{eval_id}' is already {ev.status}"
            )
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

    def get_summary(self) -> str:
        """Return a token-optimized summary of all thinking activity."""
        lines: list[str] = ["## Thinking Session Summary"]

        # Thought Graphs
        if self.thought_nodes:
            n_trees = len(self.thought_trees)
            n_nodes = len(self.thought_nodes)
            lines.append(f"\n### Thought Graphs: {n_trees} trees, {n_nodes} nodes")
            for tid, root_id in self.thought_trees.items():
                root = self.thought_nodes.get(root_id)
                if root:
                    subtree = self.get_subtree_nodes(root_id)
                    max_depth = max((n.depth for n in subtree), default=0)
                    delegated = sum(
                        1 for n in subtree if n.delegation_state
                    )
                    root_preview = root.content[:40]
                    line = (
                        f"- {tid}: \"{root_preview}\" — "
                        f"{len(subtree)} nodes, depth {max_depth}"
                    )
                    if delegated:
                        line += f", {delegated} delegated"
                    lines.append(line)

        # Models
        if self.models:
            lines.append(f"\n### Mental Models: {len(self.models)} applied")
            for m in self.models:
                conclusion_preview = m.conclusion[:100] if m.conclusion else "(no conclusion)"
                lines.append(f"- {m.model_name}: {conclusion_preview}")

        # Decisions
        if self.decisions:
            lines.append(f"\n### Decisions: {len(self.decisions)}")
            for d in self.decisions.values():
                rec_preview = d.recommendation[:100] if d.recommendation else f"stage={d.stage}"
                lines.append(f"- {d.decision_id}: {rec_preview}")

        # Debugs
        if self.debugs:
            lines.append(f"\n### Debugging: {len(self.debugs)} approaches")
            for d in self.debugs:
                res_preview = d.resolution[:100] if d.resolution else "(in progress)"
                lines.append(f"- {d.approach_name} on '{d.issue[:60]}': {res_preview}")

        # Arguments
        if self.args:
            total_args = sum(len(chain) for chain in self.args.values())
            lines.append(f"\n### Argumentation: {len(self.args)} chains, {total_args} arguments")

        # Collaborations
        if self.collaborations:
            lines.append(f"\n### Collaborations: {len(self.collaborations)}")
            for c in self.collaborations.values():
                lines.append(
                    f"- {c.topic[:60]}: {len(c.contributions)} contributions, stage={c.stage}"
                )

        # Inquiries
        if self.inquiries:
            lines.append(f"\n### Scientific Inquiries: {len(self.inquiries)}")
            for inq in self.inquiries.values():
                lines.append(f"- {inq.inquiry_id}: stage={inq.stage}, iter={inq.iteration}")

        # Monitors
        if self.monitors:
            lines.append(f"\n### Metacognitive Monitors: {len(self.monitors)}")
            for mon in self.monitors.values():
                mon_line = (
                    f"- {mon.task[:60]}: confidence={mon.overall_confidence:.2f}, "
                    f"stage={mon.stage}"
                )
                if mon.knowledge_assessment:
                    domain = mon.knowledge_assessment.get("domain", "?")
                    level = mon.knowledge_assessment.get("knowledgeLevel", "?")
                    mon_line += f", knowledge={domain}({level})"
                lines.append(mon_line)

        # Diagrams
        if self.diagrams:
            lines.append(f"\n### Diagrams: {len(self.diagrams)}")
            for diag in self.diagrams.values():
                lines.append(
                    f"- {diag.diagram_id} ({diag.diagram_type}): "
                    f"{len(diag.elements)} elements"
                )

        # Interference Protocols
        if self.interferences:
            lines.append(
                f"\n### Interference Protocols: {len(self.interferences)}"
            )
            for ip in self.interferences.values():
                ip_line = (
                    f"- {ip.protocol_id}: phase={ip.phase}, "
                    f"iter={ip.iteration}, domain={ip.target_domain[:40]}"
                )
                if ip.emergent_name:
                    ip_line += f", concept={ip.emergent_name}"
                ip_line += (
                    f", sources={len(ip.source_laws)}, "
                    f"fragments={len(ip.fragments)}"
                )
                lines.append(ip_line)

        # Holonic Workspaces
        if self.holon_nodes:
            n_holarchies = len(self.holon_holarchies)
            n_holons = len(self.holon_nodes)
            multi = sum(
                1 for h in self.holon_nodes.values()
                if len(h.memberships) > 1
            )
            stale = sum(
                len(h.stale_projections) for h in self.holon_nodes.values()
            )
            lines.append(
                f"\n### Holonic Workspaces: {n_holarchies} holarchies, "
                f"{n_holons} holons"
            )
            if multi:
                lines.append(f"Multi-membership holons: {multi}")
            if stale:
                lines.append(f"Stale projections: {stale}")
            for hid, root_id in self.holon_holarchies.items():
                root = self.holon_nodes.get(root_id)
                if root:
                    lines.append(f"- {hid}: \"{root.name}\" (root)")

        # Scoring
        if self.rubrics or self.evaluations:
            active = sum(
                1 for e in self.evaluations.values()
                if e.status == "active"
            )
            finalized = sum(
                1 for e in self.evaluations.values()
                if e.status == "finalized"
            )
            lines.append(
                f"\n### Scoring: {len(self.rubrics)} rubrics, "
                f"{len(self.evaluations)} evaluations "
                f"({active} active, {finalized} finalized)"
            )

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
            logger.debug(
                "Evicted %d trees (limit: %d)", n_to_remove, MAX_TREES
            )

        # Evict oldest trees if too many nodes total (>= to make room)
        while len(self.thought_nodes) >= MAX_NODES and self.thought_trees:
            oldest_tid = next(iter(self.thought_trees))
            self._evict_tree(oldest_tid)
            logger.debug(
                "Evicted tree %s (node limit: %d)", oldest_tid, MAX_NODES
            )

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
