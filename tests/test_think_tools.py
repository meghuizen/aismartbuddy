"""Tests for structured thinking tools (Layer 1 — ephemeral, in-memory)."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.thinking_engine import (
    MAX_NODES,
    MAX_TREES,
    ArgRecord,
    DebugRecord,
    DecisionRecord,
    InquiryRecord,
    ModelRecord,
    MonitorRecord,
    ThinkingEngine,
    ThoughtNode,
)
from aismartbuddy.session import SessionManager
from aismartbuddy.tools.refs import think_refs_query
from aismartbuddy.tools.think import (
    think_argue,
    think_debug,
    think_decide,
    think_destroy_session,
    think_graph,
    think_graph_delegate,
    think_interfere,
    think_interfere_state,
    think_model,
    think_monitor,
    think_rules,
    think_science,
    think_summarize,
    think_validate,
)

# ── ThinkingEngine unit tests ────────────────────────────────


class TestThinkingEngine:
    @pytest.fixture
    def engine(self):
        e = ThinkingEngine()
        e.connect()
        yield e
        e.close()

    def test_connect_close(self, engine: ThinkingEngine):
        assert engine.thought_nodes == {}
        engine.close()
        assert engine.thought_nodes == {}

    def test_add_node(self, engine: ThinkingEngine):
        node = ThoughtNode(id="n1", tree_id="t1", content="First thought")
        engine.add_node(node)
        assert engine.get_node_count() == 1
        assert engine.get_node("n1") is not None
        assert "t1" in engine.get_tree_ids()

    def test_node_chain(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r1", tree_id="t1", content="Root"))
        engine.add_node(
            ThoughtNode(id="c1", tree_id="t1", content="Child", parent_id="r1", depth=1)
        )
        engine.add_node(
            ThoughtNode(id="g1", tree_id="t1", content="Grand", parent_id="c1", depth=2)
        )
        assert engine.get_node_count() == 3
        assert "c1" in engine.get_node("r1").children
        assert "g1" in engine.get_node("c1").children

    def test_hierarchical_branching(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r1", tree_id="t1", content="Problem", action="branch"))
        for i in range(3):
            engine.add_node(
                ThoughtNode(
                    id=f"b{i}",
                    tree_id="t1",
                    content=f"Branch {i}",
                    parent_id="r1",
                    depth=1,
                )
            )
        assert len(engine.get_node("r1").children) == 3

    def test_get_subtree(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r", tree_id="t1", content="Root"))
        engine.add_node(ThoughtNode(id="a", tree_id="t1", content="A", parent_id="r", depth=1))
        engine.add_node(ThoughtNode(id="b", tree_id="t1", content="B", parent_id="r", depth=1))
        engine.add_node(ThoughtNode(id="a1", tree_id="t1", content="A1", parent_id="a", depth=2))
        assert len(engine.get_subtree_nodes("r")) == 4
        assert len(engine.get_subtree_nodes("a")) == 2

    def test_get_path_to_root(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r", tree_id="t1", content="Root"))
        engine.add_node(ThoughtNode(id="c", tree_id="t1", content="Child", parent_id="r", depth=1))
        engine.add_node(ThoughtNode(id="g", tree_id="t1", content="Grand", parent_id="c", depth=2))
        path = engine.get_path_to_root("g")
        assert [n.id for n in path] == ["g", "c", "r"]

    def test_revise_node(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="n1", tree_id="t1", content="Original"))
        revised = engine.revise_node("n1", "Updated content")
        assert revised is not None
        assert revised.content == "Updated content"
        assert revised.revision_history == ["Original"]

    def test_multi_tree_forest(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r1", tree_id="t1", content="Tree 1"))
        engine.add_node(ThoughtNode(id="r2", tree_id="t2", content="Tree 2"))
        assert len(engine.get_tree_ids()) == 2

    def test_memory_limit_nodes(self, engine: ThinkingEngine):
        nodes_per_tree = 10
        n_trees = (MAX_NODES // nodes_per_tree) + 5
        for t in range(n_trees):
            tid = f"t{t}"
            engine.add_node(ThoughtNode(id=f"r{t}", tree_id=tid, content=f"Root {t}"))
            for n in range(1, nodes_per_tree):
                engine.add_node(
                    ThoughtNode(
                        id=f"n{t}_{n}",
                        tree_id=tid,
                        content=f"Node {n}",
                        parent_id=f"r{t}",
                        depth=1,
                    )
                )
        assert engine.get_node_count() <= MAX_NODES

    def test_memory_limit_trees(self, engine: ThinkingEngine):
        for t in range(MAX_TREES + 10):
            engine.add_node(ThoughtNode(id=f"r{t}", tree_id=f"t{t}", content=f"Root {t}"))
        assert len(engine.get_tree_ids()) <= MAX_TREES

    def test_add_model(self, engine: ThinkingEngine):
        engine.add_model(ModelRecord(model_name="first_principles", problem="test"))
        assert len(engine.models) == 1

    def test_upsert_decision(self, engine: ThinkingEngine):
        d = DecisionRecord(decision_id="d1", statement="Choose DB")
        engine.upsert_decision(d)
        assert engine.get_decision("d1") is not None
        d2 = DecisionRecord(decision_id="d1", statement="v2", stage="criteria")
        engine.upsert_decision(d2)
        assert engine.get_decision("d1").stage == "criteria"

    def test_add_debug(self, engine: ThinkingEngine):
        engine.add_debug(DebugRecord(approach_name="binary_search", issue="test issue"))
        assert len(engine.debugs) == 1

    def test_argumentation_chain(self, engine: ThinkingEngine):
        engine.add_argument("chain1", ArgRecord(argument_id="a1", claim="Claim 1"))
        engine.add_argument("chain1", ArgRecord(argument_id="a2", claim="Counter 1"))
        assert len(engine.get_arg_chain("chain1")) == 2

    def test_inquiry(self, engine: ThinkingEngine):
        engine.upsert_inquiry(InquiryRecord(inquiry_id="i1", stage="observation"))
        assert engine.get_inquiry("i1").stage == "observation"

    def test_monitor(self, engine: ThinkingEngine):
        engine.upsert_monitor(MonitorRecord(monitoring_id="m1", task="Test task"))
        assert engine.get_monitor("m1").task == "Test task"

    def test_summary_empty(self, engine: ThinkingEngine):
        assert "Empty thinking session" in engine.get_summary()

    def test_summary_with_content(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r1", tree_id="t1", content="Test thought"))
        engine.add_model(ModelRecord(model_name="pareto_principle", problem="test"))
        summary = engine.get_summary()
        assert "Thought Graphs" in summary
        assert "Mental Models" in summary


# ── Session integration tests ────────────────────────────────


class TestThinkSessionIntegration:
    def test_create_think_session(self, session_manager: SessionManager):
        info = session_manager.create_session("think")
        assert info.session_id
        assert info.session_type == "think"
        assert isinstance(info.engine, ThinkingEngine)
        assert info.db_path == ""

    def test_get_think_session(self, session_manager: SessionManager):
        info = session_manager.create_session("think")
        retrieved = session_manager.get_session(info.session_id)
        assert retrieved.session_type == "think"

    def test_destroy_think_session(self, session_manager: SessionManager):
        info = session_manager.create_session("think")
        session_manager.destroy_session(info.session_id)
        with pytest.raises(ValueError, match="not found"):
            session_manager.get_session(info.session_id)

    def test_multi_session_isolation(self, session_manager: SessionManager):
        s1 = session_manager.create_session("think")
        s2 = session_manager.create_session("think")
        e1 = s1.engine
        e2 = s2.engine
        assert isinstance(e1, ThinkingEngine)
        assert isinstance(e2, ThinkingEngine)
        e1.add_node(ThoughtNode(id="n1", tree_id="t1", content="S1 only"))
        assert e1.get_node_count() == 1
        assert e2.get_node_count() == 0

    def test_invalid_session_type(self, session_manager: SessionManager):
        with pytest.raises(ValueError, match="Invalid session_type"):
            session_manager.create_session("invalid")


# ── Tool-level integration tests (async) ─────────────────────


def _extract_field(result: str, prefix: str) -> str:
    """Extract a value from compact text output after a prefix."""
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix) :].strip()
    return ""


# ── Thought Graph tool tests ─────────────────────────────────


@pytest.mark.usefixtures("_init_session_manager")
class TestThoughtGraph:
    @pytest.mark.anyio
    async def test_simple_sequential_chain(self):
        r1 = await think_graph(thought="First insight")
        assert "Session:" in r1
        assert "Action: think" in r1
        assert "Depth: 0" in r1
        sid = _extract_field(r1, "Session:")
        nid1 = _extract_field(r1, "Node:")

        r2 = await think_graph(thought="Building on that...", parent_id=nid1, session_id=sid)
        assert "Depth: 1" in r2
        nid2 = _extract_field(r2, "Node:")

        r3 = await think_graph(thought="Therefore...", parent_id=nid2, session_id=sid)
        assert "Depth: 2" in r3

    @pytest.mark.anyio
    async def test_new_tree_root(self):
        r = await think_graph(thought="New root")
        assert "Tree:" in r
        assert "Depth: 0" in r
        assert "Status: added" in r

    @pytest.mark.anyio
    async def test_hierarchical_branching(self):
        r1 = await think_graph(thought="Decompose this", action="branch")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")
        assert "Action: branch" in r1

        await think_graph(thought="Branch A", parent_id=nid, session_id=sid)
        r3 = await think_graph(thought="Branch B", parent_id=nid, session_id=sid)
        assert "Siblings: 1" in r3  # Branch B has 1 sibling (Branch A)

    @pytest.mark.anyio
    async def test_revise_node(self):
        r1 = await think_graph(thought="Original thought")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        r2 = await think_graph(
            thought="Revised insight",
            action="revise",
            node_id=nid,
            session_id=sid,
        )
        assert "Action: revise" in r2
        assert "Revisions: 1" in r2
        assert "Status: revised" in r2

    @pytest.mark.anyio
    async def test_synthesize(self):
        r1 = await think_graph(thought="Problem", action="branch")
        sid = _extract_field(r1, "Session:")
        branch_id = _extract_field(r1, "Node:")

        await think_graph(thought="Part A", parent_id=branch_id, session_id=sid)
        await think_graph(thought="Part B", parent_id=branch_id, session_id=sid)
        r = await think_graph(
            thought="Combined conclusion",
            action="synthesize",
            parent_id=branch_id,
            session_id=sid,
        )
        assert "Action: synthesize" in r

    @pytest.mark.anyio
    async def test_multi_tree_forest(self):
        r1 = await think_graph(thought="Tree 1 root")
        sid = _extract_field(r1, "Session:")
        tree1 = _extract_field(r1, "Tree:")

        r2 = await think_graph(thought="Tree 2 root", session_id=sid)
        tree2 = _extract_field(r2, "Tree:")
        assert tree1 != tree2

    @pytest.mark.anyio
    async def test_auto_session_creation(self):
        r = await think_graph(thought="Auto session")
        assert "Session:" in r
        assert "Node:" in r

    @pytest.mark.anyio
    async def test_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            await think_graph(thought="test", action="explode")

    @pytest.mark.anyio
    async def test_revise_missing_node_id(self):
        with pytest.raises(ValueError, match="node_id is required"):
            await think_graph(thought="test", action="revise")

    @pytest.mark.anyio
    async def test_nonexistent_parent(self):
        with pytest.raises(ValueError, match="not found"):
            await think_graph(thought="test", parent_id="nonexistent")

    @pytest.mark.anyio
    async def test_depends_on(self):
        r1 = await think_graph(thought="Task A: Design API")
        sid = _extract_field(r1, "Session:")
        node_a = _extract_field(r1, "Node:")

        r2 = await think_graph(
            thought="Task B: Implement API (depends on design)",
            session_id=sid,
            depends_on=[node_a],
        )
        assert "Status: added" in r2


@pytest.mark.usefixtures("_init_session_manager")
class TestThoughtGraphDelegate:
    @pytest.mark.anyio
    async def test_package_subtree(self):
        r1 = await think_graph(thought="Root problem")
        sid = _extract_field(r1, "Session:")
        root_id = _extract_field(r1, "Node:")

        r2 = await think_graph(thought="Delegatable subtask", parent_id=root_id, session_id=sid)
        child_id = _extract_field(r2, "Node:")

        r = await think_graph_delegate(session_id=sid, node_id=child_id, action="package")
        assert "Delegation: packaged" in r
        assert "Delegation Package" in r
        assert "Root problem" in r
        assert "[THIS NODE]" in r

    @pytest.mark.anyio
    async def test_receive_result(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        await think_graph_delegate(session_id=sid, node_id=nid, action="package")
        r = await think_graph_delegate(
            session_id=sid,
            node_id=nid,
            action="receive",
            result="Subagent found the answer: 42",
        )
        assert "Delegation: completed" in r

    @pytest.mark.anyio
    async def test_package_includes_ancestry(self):
        r1 = await think_graph(thought="Level 0")
        sid = _extract_field(r1, "Session:")
        nid0 = _extract_field(r1, "Node:")

        r2 = await think_graph(thought="Level 1", parent_id=nid0, session_id=sid)
        nid1 = _extract_field(r2, "Node:")

        r3 = await think_graph(thought="Level 2", parent_id=nid1, session_id=sid)
        nid2 = _extract_field(r3, "Node:")

        r = await think_graph_delegate(session_id=sid, node_id=nid2, action="package")
        assert "Context depth: 3 nodes" in r
        assert "Level 0" in r
        assert "Level 1" in r
        assert "Level 2" in r

    @pytest.mark.anyio
    async def test_delegate_nonexistent_node(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")

        with pytest.raises(ValueError, match="not found"):
            await think_graph_delegate(session_id=sid, node_id="nonexistent", action="package")


# ── Decision tool tests ──────────────────────────────────────


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkDecideTool:
    @pytest.mark.anyio
    async def test_decision_flow(self):
        result = await think_decide(
            decision_statement="Choose a database",
            options=[
                {"id": "a", "name": "DuckDB", "description": "SQL"},
                {"id": "b", "name": "LadybugDB", "description": "Graph"},
            ],
            analysis_type="multi-criteria",
            stage="problem-definition",
            decision_id="db-choice",
            iteration=1,
            next_stage_needed=True,
        )
        assert "Decision: db-choice" in result
        assert "Status: analyzing" in result

    @pytest.mark.anyio
    async def test_decision_with_recommendation(self):
        result = await think_decide(
            decision_statement="Choose a database",
            options=[{"id": "a", "name": "DuckDB", "description": "SQL"}],
            analysis_type="multi-criteria",
            stage="recommendation",
            decision_id="db-choice",
            iteration=2,
            next_stage_needed=False,
            recommendation="Use DuckDB for tabular analytics.",
        )
        assert "Status: decided" in result
        assert "Recommendation:" in result

    @pytest.mark.anyio
    async def test_invalid_analysis_type(self):
        with pytest.raises(ValueError, match="Invalid analysis_type"):
            await think_decide(
                decision_statement="test",
                options=[],
                analysis_type="invalid",
                stage="options",
                decision_id="x",
                iteration=0,
                next_stage_needed=False,
            )

    # ── items[] strict batch form ────────────────────────────

    @pytest.mark.anyio
    async def test_items_batch(self):
        r = await think_decide(
            items=[
                {
                    "id": "d1",
                    "decision_statement": "Adopt new build tool?",
                    "options": [
                        {"name": "keep", "description": "stay with maven"},
                        {"name": "switch", "description": "move to bazel"},
                    ],
                    "criteria": [{"name": "speed", "weight": 0.7}],
                    "recommendation": "switch — bazel is 3x faster",
                },
            ]
        )
        assert "Decisions: 1" in r and "d1" in r

    @pytest.mark.anyio
    async def test_items_options_too_few_rejected(self):
        with pytest.raises(ValueError, match="at least 2 options"):
            await think_decide(
                items=[
                    {
                        "id": "x",
                        "decision_statement": "test",
                        "options": [{"name": "only", "description": "one"}],
                        "criteria": [{"name": "c", "weight": 1.0}],
                        "recommendation": "r",
                    },
                ]
            )

    @pytest.mark.anyio
    async def test_items_criteria_missing_weight_rejected(self):
        with pytest.raises(ValueError, match="missing 'weight'"):
            await think_decide(
                items=[
                    {
                        "id": "x",
                        "decision_statement": "test",
                        "options": [
                            {"name": "a", "description": "a"},
                            {"name": "b", "description": "b"},
                        ],
                        "criteria": [{"name": "c"}],
                        "recommendation": "r",
                    },
                ]
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkModelTool:
    @pytest.mark.anyio
    async def test_apply_model(self):
        result = await think_model(
            model_name="first_principles",
            problem="Why is the build slow?",
            steps=["Identify bottleneck", "Measure", "Optimize"],
            conclusion="Compilation is the bottleneck.",
        )
        assert "Model: first_principles" in result
        assert "Conclusion:" in result

    @pytest.mark.anyio
    async def test_first_principles_guidance(self):
        result = await think_model(
            model_name="first_principles",
            problem="Why is the build slow?",
        )
        assert "First Principles Thinking" in result
        assert "framework loaded" in result

    @pytest.mark.anyio
    async def test_invalid_model(self):
        with pytest.raises(ValueError, match="Invalid model_name"):
            await think_model(model_name="nonexistent", problem="test")

    @pytest.mark.anyio
    async def test_assumptions_xray_guidance(self):
        result = await think_model(
            model_name="assumptions_xray",
            problem="Chronic cortisol causes mitochondrial dysfunction",
        )
        assert "Assumption X-Ray" in result
        assert "hidden assumptions" in result
        assert "falsification" in result

    @pytest.mark.anyio
    async def test_fishbone_guidance(self):
        result = await think_model(
            model_name="fishbone",
            problem="Why is Complex I activity reduced?",
        )
        assert "Fishbone" in result
        assert "categories" in result

    @pytest.mark.anyio
    async def test_value_of_info_guidance(self):
        result = await think_model(
            model_name="value_of_info",
            problem="Should we sequence RNA or measure metabolites first?",
        )
        assert "Value of Information" in result
        assert "uncertainties" in result

    @pytest.mark.anyio
    async def test_swot_guidance(self):
        result = await think_model(
            model_name="swot",
            problem="Using GR antagonists for ME/CFS treatment",
        )
        assert "SWOT" in result
        assert "Strengths" in result
        assert "Threats" in result

    @pytest.mark.anyio
    async def test_pre_mortem_guidance(self):
        result = await think_model(
            model_name="pre_mortem",
            problem="Replacing think_step with thought graph",
        )
        assert "Pre-Mortem" in result
        assert "failure modes" in result

    @pytest.mark.anyio
    async def test_design_review_guidance(self):
        result = await think_model(
            model_name="design_review",
            problem="Multi-membership holonic data model",
        )
        assert "Design Review" in result
        assert "state machine" in result.lower() or "State machine" in result

    @pytest.mark.anyio
    async def test_complexity_guidance(self):
        result = await think_model(
            model_name="complexity",
            problem="think_interfere function with 23 parameters",
        )
        assert "Complexity" in result
        assert "Cyclomatic" in result or "cyclomatic" in result

    @pytest.mark.anyio
    async def test_root_cause_guidance(self):
        result = await think_model(
            model_name="root_cause",
            problem="Why does the build fail intermittently?",
        )
        assert "Root Cause" in result
        assert "Why" in result

    # ── items[] strict batch form ────────────────────────────

    @pytest.mark.anyio
    async def test_items_batch_three(self):
        items = [
            {
                "id": f"p{i}",
                "problem": f"sub-problem {i}",
                "steps": [f"step {i}.1"],
                "reasoning": "because",
                "conclusion": f"therefore {i}",
            }
            for i in range(3)
        ]
        r = await think_model(model_name="first_principles", items=items)
        assert "Items: 3" in r
        for i in range(3):
            assert f"p{i}" in r

    @pytest.mark.anyio
    async def test_items_missing_required_rejected(self):
        with pytest.raises(ValueError, match="missing required 'reasoning'"):
            await think_model(
                model_name="first_principles",
                items=[
                    {
                        "id": "x",
                        "problem": "p",
                        "steps": ["s"],
                        "conclusion": "c",
                    }
                ],
            )

    @pytest.mark.anyio
    async def test_items_empty_steps_rejected(self):
        with pytest.raises(ValueError, match="missing required 'steps'"):
            await think_model(
                model_name="first_principles",
                items=[
                    {
                        "id": "x",
                        "problem": "p",
                        "steps": [],
                        "reasoning": "r",
                        "conclusion": "c",
                    }
                ],
            )

    @pytest.mark.anyio
    async def test_items_duplicate_id_rejected(self):
        with pytest.raises(ValueError, match="duplicate id 'dup'"):
            await think_model(
                model_name="first_principles",
                items=[
                    {
                        "id": "dup",
                        "problem": "p1",
                        "steps": ["s"],
                        "reasoning": "r",
                        "conclusion": "c",
                    },
                    {
                        "id": "dup",
                        "problem": "p2",
                        "steps": ["s"],
                        "reasoning": "r",
                        "conclusion": "c",
                    },
                ],
            )

    @pytest.mark.anyio
    async def test_items_auto_graph_auto_creates_session_with_graph(self):
        # auto-create now provisions think+graph backends so auto_graph works
        # without an explicit session_create call.
        result = await think_model(
            model_name="first_principles",
            items=[
                {
                    "id": "x",
                    "problem": "p",
                    "steps": ["s"],
                    "reasoning": "r",
                    "conclusion": "c",
                }
            ],
            auto_graph=True,
        )
        assert "Graph nodes created:" in result

    @pytest.mark.anyio
    async def test_items_auto_graph_with_unified_session(self):
        from aismartbuddy.tools.infra import session_create

        r1 = await session_create(backends=["think", "graph"])
        sid = ""
        for line in r1.split("\n"):
            line = line.strip()
            if line.startswith("session_id:"):
                sid = line[len("session_id:") :].strip()
                break
        assert sid

        r2 = await think_model(
            model_name="first_principles",
            session_id=sid,
            auto_graph=True,
            items=[
                {
                    "id": "concept_a",
                    "problem": "P A",
                    "steps": ["s1"],
                    "reasoning": "because",
                    "conclusion": "therefore A",
                },
                {
                    "id": "concept_b",
                    "problem": "P B",
                    "steps": ["s1"],
                    "reasoning": "because",
                    "conclusion": "therefore B",
                    "connects_to": ["concept_a"],
                },
            ],
        )
        assert "Items: 2" in r2
        assert "Graph nodes created: 2" in r2


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkDebugTool:
    @pytest.mark.anyio
    async def test_debug_approach(self):
        result = await think_debug(
            approach_name="binary_search",
            issue="Performance regression",
            steps=["Bisect commits"],
            resolution="Found commit X.",
        )
        assert "Approach: binary_search" in result

    @pytest.mark.anyio
    async def test_invalid_approach(self):
        with pytest.raises(ValueError, match="Invalid approach_name"):
            await think_debug(approach_name="magic", issue="test")

    # ── items[] strict batch form ────────────────────────────

    @pytest.mark.anyio
    async def test_items_batch(self):
        r = await think_debug(
            items=[
                {
                    "id": "bug1",
                    "approach": "binary_search",
                    "issue": "auth fails on token refresh",
                    "steps": ["bisect commits"],
                    "findings": "regression in commit abc",
                    "resolution": "revert abc, retry",
                },
            ]
        )
        assert "Debugs: 1" in r and "bug1" in r

    @pytest.mark.anyio
    async def test_items_invalid_approach_rejected(self):
        with pytest.raises(ValueError, match="invalid"):
            await think_debug(
                items=[
                    {
                        "id": "x",
                        "approach": "magic",
                        "issue": "i",
                        "steps": ["s"],
                        "findings": "f",
                        "resolution": "r",
                    },
                ]
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkArgueTool:
    @pytest.mark.anyio
    async def test_argumentation_chain(self):
        result = await think_argue(
            claim="DuckDB is better",
            premises=["Column-oriented"],
            conclusion="Choose DuckDB.",
            argument_type="thesis",
            confidence=0.8,
            next_argument_needed=True,
        )
        assert "Type: thesis" in result

    @pytest.mark.anyio
    async def test_invalid_argument_type(self):
        with pytest.raises(ValueError, match="Invalid argument_type"):
            await think_argue(
                claim="test",
                premises=[],
                conclusion="",
                argument_type="invalid",
                confidence=0.5,
                next_argument_needed=False,
            )


def _good_hyp_item(id_: str = "h1") -> dict:
    return {
        "id": id_,
        "observation": "X correlates with Y in 80% of trials.",
        "question": "Does X cause Y?",
        "hypothesis": {
            "statement": "X causes Y via mechanism M",
            "variables": [
                {"name": "X", "role": "independent"},
                {"name": "Y", "role": "dependent"},
            ],
            "assumptions": ["M is reproducible across labs"],
            "confidence": 0.6,
            "falsifiability": (
                "If suppressing X with antagonist Z still produces Y in "
                ">50% of trials, the hypothesis is falsified."
            ),
        },
    }


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkScienceTool:
    @pytest.mark.anyio
    async def test_scientific_inquiry(self):
        result = await think_science(
            stage="hypothesis",
            inquiry_id="perf-test",
            iteration=1,
            next_stage_needed=True,
            hypothesis={"statement": "Index will fix it", "variables": []},
        )
        assert "Inquiry: perf-test" in result

    @pytest.mark.anyio
    async def test_items_batch(self):
        items = [_good_hyp_item(f"h{i}") for i in range(3)]
        r = await think_science(items=items)
        assert "Hypotheses: 3" in r
        for i in range(3):
            assert f"h{i}" in r

    @pytest.mark.anyio
    async def test_items_short_falsifiability_rejected(self):
        bad = _good_hyp_item()
        bad["hypothesis"]["falsifiability"] = "N/A"
        with pytest.raises(ValueError, match="≥ 20 chars"):
            await think_science(items=[bad])

    @pytest.mark.anyio
    async def test_items_invalid_variable_role_rejected(self):
        bad = _good_hyp_item()
        bad["hypothesis"]["variables"][0]["role"] = "guess"
        with pytest.raises(
            ValueError,
            match="independent.dependent.controlled",
        ):
            await think_science(items=[bad])

    @pytest.mark.anyio
    async def test_items_empty_assumptions_rejected(self):
        bad = _good_hyp_item()
        bad["hypothesis"]["assumptions"] = []
        with pytest.raises(ValueError, match="assumptions"):
            await think_science(items=[bad])


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkMonitorTool:
    @pytest.mark.anyio
    async def test_metacognitive_monitoring(self):
        result = await think_monitor(
            task="Code review",
            stage="knowledge-assessment",
            overall_confidence=0.7,
            monitoring_id="rm",
            iteration=1,
            next_assessment_needed=True,
            uncertainty_areas=["Coverage", "Edge cases"],
        )
        assert "Confidence: 0.70" in result
        assert "Uncertainties: 2" in result

    @pytest.mark.anyio
    async def test_knowledge_assessment(self):
        result = await think_monitor(
            task="Evaluate Python",
            stage="knowledge-assessment",
            overall_confidence=0.85,
            monitoring_id="ka-1",
            iteration=1,
            next_assessment_needed=False,
            knowledge_assessment={
                "domain": "Python async",
                "knowledgeLevel": "proficient",
                "confidenceScore": 0.9,
                "supportingEvidence": "Built async systems",
                "knownLimitations": ["Limited uvloop"],
            },
        )
        assert "Knowledge: Python async=proficient" in result

    @pytest.mark.anyio
    async def test_invalid_knowledge_level(self):
        with pytest.raises(ValueError, match="Invalid knowledgeLevel"):
            await think_monitor(
                task="t",
                stage="knowledge-assessment",
                overall_confidence=0.5,
                monitoring_id="x",
                iteration=0,
                next_assessment_needed=False,
                knowledge_assessment={
                    "domain": "t",
                    "knowledgeLevel": "god-tier",
                },
            )

    # ── items[] strict batch form ────────────────────────────

    GOOD_K = {
        "domain": "RNA biology",
        "level": "familiar",
        "confidence": 0.6,
        "limitations": [
            "No hands-on lab experience",
            "Recent literature beyond cutoff is unknown",
        ],
    }
    GOOD_CLAIMS = [
        {
            "claim": "rRNA is the most abundant RNA",
            "status": "fact",
            "confidence": 0.95,
            "evidence": "textbook",
        },
        {
            "claim": "X causes Y",
            "status": "speculation",
            "confidence": 0.4,
            "evidence": "weak correlation",
        },
    ]

    @pytest.mark.anyio
    async def test_items_basic(self):
        r = await think_monitor(
            items=[
                {
                    "id": "a1",
                    "task": "Analyze RNA pathways",
                    "knowledge": self.GOOD_K,
                    "claims": self.GOOD_CLAIMS,
                },
            ]
        )
        assert "Assessments: 1" in r
        assert "a1" in r

    @pytest.mark.anyio
    async def test_items_empty_limitations_rejected(self):
        bad_k = {**self.GOOD_K, "limitations": []}
        with pytest.raises(ValueError, match="non-empty"):
            await think_monitor(
                items=[
                    {
                        "id": "x",
                        "task": "t",
                        "knowledge": bad_k,
                        "claims": self.GOOD_CLAIMS,
                    },
                ]
            )

    @pytest.mark.anyio
    async def test_items_invalid_level_rejected(self):
        bad_k = {**self.GOOD_K, "level": "wizard"}
        with pytest.raises(ValueError, match="level must be one of"):
            await think_monitor(
                items=[
                    {
                        "id": "x",
                        "task": "t",
                        "knowledge": bad_k,
                        "claims": self.GOOD_CLAIMS,
                    },
                ]
            )

    @pytest.mark.anyio
    async def test_items_invalid_claim_status_rejected(self):
        bad_claims = [
            {"claim": "c", "status": "guess", "confidence": 0.5, "evidence": "e"},
        ]
        with pytest.raises(ValueError, match="status must be one of"):
            await think_monitor(
                items=[
                    {
                        "id": "x",
                        "task": "t",
                        "knowledge": self.GOOD_K,
                        "claims": bad_claims,
                    },
                ]
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkGraphBatch:
    """think_graph(children=[...]) creates parent + N children atomically."""

    @pytest.mark.anyio
    async def test_branch_with_three_children(self):
        r = await think_graph(
            thought="IPM vs GO coherence",
            action="branch",
            children=[
                {"thought": "TENSION 1: scoping"},
                {"thought": "TENSION 2: interaction"},
                {"thought": "TENSION 3: inheritance"},
            ],
        )
        assert "Batch: 3 children created" in r
        # All three children IDs returned
        children_line = next((ln for ln in r.split("\n") if ln.startswith("Children: ")), "")
        cids = [c.strip() for c in children_line[len("Children: ") :].split(",")]
        assert len(cids) == 3
        # Each ID is a 10-char hex
        for cid in cids:
            assert len(cid) == 10

    @pytest.mark.anyio
    async def test_empty_children_field_rejected(self):
        with pytest.raises(ValueError, match="non-empty 'thought'"):
            await think_graph(
                thought="parent",
                children=[{"thought": ""}],
            )

    @pytest.mark.anyio
    async def test_expected_children_warning_on_synthesize_mismatch(self):
        # Create branch with expected_children=4
        r = await think_graph(
            thought="branch root",
            action="branch",
            expected_children=4,
        )
        sid = _extract_field(r, "Session:")
        parent_id = _extract_field(r, "Node:")
        # Add only 2 children
        await think_graph(
            thought="child A",
            parent_id=parent_id,
            session_id=sid,
        )
        await think_graph(
            thought="child B",
            parent_id=parent_id,
            session_id=sid,
        )
        # Synthesize — should warn about 2 != 4
        synth = await think_graph(
            thought="synth conclusion",
            action="synthesize",
            parent_id=parent_id,
            session_id=sid,
        )
        assert "expected 4 children" in synth
        assert "found 3" in synth  # 2 + the synthesize itself = 3


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkArgueChain:
    """think_argue(chain=[...]) submits full dialectic in one call."""

    @pytest.mark.anyio
    async def test_thesis_antithesis_synthesis_chain(self):
        from aismartbuddy.tools.think import think_argue

        r = await think_argue(
            chain=[
                {
                    "type": "thesis",
                    "claim": "X is good",
                    "premises": ["evidence A"],
                    "conclusion": "Adopt X",
                    "confidence": 0.7,
                },
                {
                    "type": "antithesis",
                    "claim": "X is bad",
                    "premises": ["evidence B"],
                    "conclusion": "Reject X",
                    "confidence": 0.6,
                    "responds_to_index": 0,
                },
                {
                    "type": "synthesis",
                    "claim": "Adopt X with caveat",
                    "premises": ["combine A and B"],
                    "conclusion": "Adopt X under condition Y",
                    "confidence": 0.8,
                    "responds_to_index": 1,
                },
            ],
        )
        assert "Batch: 3 arguments" in r
        assert "Chain: " in r

    @pytest.mark.anyio
    async def test_chain_responds_to_invalid_index_rejected(self):
        from aismartbuddy.tools.think import think_argue

        with pytest.raises(ValueError, match="must reference a prior"):
            await think_argue(
                chain=[
                    {
                        "type": "thesis",
                        "claim": "c",
                        "premises": ["p"],
                        "conclusion": "x",
                        "responds_to_index": 5,
                    },
                ],
            )

    @pytest.mark.anyio
    async def test_chain_missing_premises_rejected(self):
        from aismartbuddy.tools.think import think_argue

        with pytest.raises(ValueError, match="premises"):
            await think_argue(
                chain=[
                    {
                        "type": "thesis",
                        "claim": "c",
                        "conclusion": "x",
                    },
                ],
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkSummarizeTool:
    @pytest.mark.anyio
    async def test_summarize(self):
        r = await think_graph(thought="Test thought")
        sid = _extract_field(r, "Session:")
        summary = await think_summarize(sid)
        assert "Thought Graphs" in summary

    @pytest.mark.anyio
    async def test_summarize_wrong_session_type(self, session_manager: SessionManager):
        info = session_manager.create_session("sql")
        with pytest.raises(ValueError, match="not think"):
            await think_summarize(info.session_id)

    @pytest.mark.anyio
    async def test_summarize_caps_items_per_category(self):
        """Creating >cap thought trees collapses excess to '... (N more)'."""
        from aismartbuddy.tools.think import think_graph

        r = await think_graph(thought="Tree 0", action="branch")
        sid = _extract_field(r, "Session:")
        # Create 25 more branch trees so we exceed the cap of 5
        for i in range(1, 26):
            await think_graph(
                thought=f"Tree {i}",
                action="branch",
                session_id=sid,
            )
        summary = await think_summarize(sid, max_items_per_category=5)
        assert "Thought Graphs" in summary
        # Count lines inside Thought Graphs section beginning with "- "
        sections = summary.split("\n\n")
        graphs_section = next((s for s in sections if "Thought Graphs" in s), "")
        item_lines = [ln for ln in graphs_section.split("\n") if ln.startswith("- ")]
        # 5 shown + 1 "... (N more)" footer = 6 total
        assert len(item_lines) <= 6, item_lines
        assert any("more)" in ln for ln in item_lines)


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkDestroyTool:
    @pytest.mark.anyio
    async def test_destroy(self):
        r = await think_graph(thought="Test")
        sid = _extract_field(r, "Session:")
        result = await think_destroy_session(sid)
        assert "Destroyed" in result

    @pytest.mark.anyio
    async def test_destroy_wrong_session_type(self, session_manager: SessionManager):
        info = session_manager.create_session("sql")
        with pytest.raises(ValueError, match="not think"):
            await think_destroy_session(info.session_id)


@pytest.mark.usefixtures("_init_session_manager")
class TestCompactTextFormat:
    @pytest.mark.anyio
    async def test_no_json_in_output(self):
        result = await think_graph(thought="test")
        assert "{" not in result
        assert "}" not in result
        assert "|" in result
        assert "Session:" in result


# ── Interference Protocol tests ──────────────────────────────


@pytest.mark.usefixtures("_init_session_manager")
class TestInterferenceProtocol:
    @pytest.mark.anyio
    async def test_full_happy_path(self):
        r = await think_interfere(
            action="set_domain",
            target_domain="biological data systems",
        )
        assert "Phase: domain_set" in r
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")

        await think_interfere(
            action="add_frame",
            session_id=sid,
            protocol_id=pid,
            frame="Data is passive; queries are active",
        )

        for dom, law_, iso in [
            (
                "Holography",
                "Every fragment encodes the whole",
                "Both have local parts with global info",
            ),
            (
                "Immunology",
                "Identity without central controller",
                "Both maintain coherence without coordination",
            ),
            (
                "Holarchy",
                "Every level is whole and part",
                "Both have recursive self-similar structure",
            ),
        ]:
            r = await think_interfere(
                action="add_source",
                session_id=sid,
                protocol_id=pid,
                source_domain=dom,
                law=law_,
                isomorphism=iso,
            )
        assert "Sources: 3" in r

        for i in range(5):
            r = await think_interfere(
                action="add_fragment",
                session_id=sid,
                protocol_id=pid,
                fragment=f"Fragment {i}: It would have to...",
            )
        assert "Phase: saturated" in r

        r = await think_interfere(
            action="crystallize",
            session_id=sid,
            protocol_id=pid,
            name="Holographic Compute Substrate",
            properties=[
                {"text": "Node is data+query+processor", "novel": True, "source_laws": [0, 2]},
                {"text": "Consistency from resonance", "novel": True, "source_laws": [0, 1]},
                {"text": "No observer boundary", "novel": True, "source_laws": [1, 2]},
            ],
        )
        assert "Phase: crystallized" in r

        r = await think_interfere(
            action="add_necessity",
            session_id=sid,
            protocol_id=pid,
            conclusion="Local stateless computation",
            prerequisites=[
                {"claim": "Prereq 1", "status": "untested"},
                {"claim": "Prereq 2", "status": "untested"},
            ],
        )
        assert "Phase: necessities_derived" in r

        r = await think_interfere(
            action="stress_test",
            session_id=sid,
            protocol_id=pid,
            audit_type="first_principles",
            audit_result="No violations found.",
        )
        assert "Audits: 1/4" in r

        r = await think_interfere(
            action="finalize",
            session_id=sid,
            protocol_id=pid,
            verdict="survives",
        )
        assert "Phase: stress_tested" in r

        r = await think_interfere(
            action="recurse",
            session_id=sid,
            protocol_id=pid,
            new_domain="distributed consensus",
            concept_as_law="Nodes store+query+compute without coordination",
        )
        assert "Iter: 2" in r

    @pytest.mark.anyio
    async def test_reject_fragment_before_2_sources(self):
        r = await think_interfere(action="set_domain", target_domain="test")
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        await think_interfere(
            action="add_source",
            session_id=sid,
            protocol_id=pid,
            source_domain="A",
            law="law A",
            isomorphism="iso A",
        )
        r = await think_interfere(
            action="add_fragment",
            session_id=sid,
            protocol_id=pid,
            fragment="test",
        )
        assert "REJECTED" in r

    @pytest.mark.anyio
    async def test_reject_mashup_not_emergence(self):
        r = await think_interfere(action="set_domain", target_domain="test")
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        for d in ["A", "B"]:
            await think_interfere(
                action="add_source",
                session_id=sid,
                protocol_id=pid,
                source_domain=d,
                law=f"{d} law",
                isomorphism=f"iso {d}",
            )
        for i in range(5):
            await think_interfere(
                action="add_fragment",
                session_id=sid,
                protocol_id=pid,
                fragment=f"Fragment {i}",
            )
        r = await think_interfere(
            action="crystallize",
            session_id=sid,
            protocol_id=pid,
            name="Mashup",
            properties=[
                {"text": "P1", "novel": True, "source_laws": [0]},
                {"text": "P2", "novel": True, "source_laws": [1]},
            ],
        )
        assert "REJECTED" in r

    @pytest.mark.anyio
    async def test_reject_invalid_action(self):
        with pytest.raises(ValueError, match="Invalid action"):
            await think_interfere(action="explode")

    @pytest.mark.anyio
    async def test_necessity_chain_broken(self):
        r = await think_interfere(action="set_domain", target_domain="test")
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        for d in ["A", "B"]:
            await think_interfere(
                action="add_source",
                session_id=sid,
                protocol_id=pid,
                source_domain=d,
                law=f"{d} law",
                isomorphism=f"iso {d}",
            )
        for i in range(5):
            await think_interfere(
                action="add_fragment",
                session_id=sid,
                protocol_id=pid,
                fragment=f"Fragment {i}",
            )
        await think_interfere(
            action="crystallize",
            session_id=sid,
            protocol_id=pid,
            name="Concept",
            properties=[
                {"text": "P1", "novel": True, "source_laws": [0, 1]},
                {"text": "P2", "novel": True, "source_laws": [0, 1]},
            ],
        )
        await think_interfere(
            action="add_necessity",
            session_id=sid,
            protocol_id=pid,
            conclusion="Test",
            prerequisites=[
                {"claim": "A", "status": "untested"},
                {"claim": "B", "status": "untested"},
            ],
        )
        await think_interfere(
            action="update_necessity",
            session_id=sid,
            protocol_id=pid,
            chain_index=0,
            prereq_index=0,
            new_status="fails",
        )
        r = await think_interfere(
            action="update_necessity",
            session_id=sid,
            protocol_id=pid,
            chain_index=0,
            prereq_index=1,
            new_status="fails",
        )
        assert "CHAIN BROKEN" in r

    @pytest.mark.anyio
    async def test_state_query(self):
        r = await think_interfere(
            action="set_domain",
            target_domain="test domain",
        )
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        await think_interfere(
            action="add_source",
            session_id=sid,
            protocol_id=pid,
            source_domain="Physics",
            law="E=mc2",
            isomorphism="Both are energy systems",
        )
        state = await think_interfere_state(session_id=sid, protocol_id=pid)
        assert "test domain" in state
        assert "Physics" in state

    @pytest.mark.anyio
    async def test_multi_protocol_isolation(self):
        r1 = await think_interfere(
            action="set_domain",
            target_domain="domain A",
        )
        sid = _extract_field(r1, "Session:")
        pid1 = _extract_field(r1, "Protocol:")
        r2 = await think_interfere(
            action="set_domain",
            target_domain="domain B",
            session_id=sid,
        )
        pid2 = _extract_field(r2, "Protocol:")
        assert pid1 != pid2
        await think_interfere(
            action="add_frame",
            session_id=sid,
            protocol_id=pid1,
            frame="Frame for A only",
        )
        state2 = await think_interfere_state(session_id=sid, protocol_id=pid2)
        assert "Frame for A only" not in state2


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkGraphMinChildren:
    @pytest.mark.anyio
    async def test_below_min_children_rejected(self):
        with pytest.raises(ValueError, match="min_children=5"):
            await think_graph(
                thought="root",
                action="branch",
                children=[{"thought": "c1"}, {"thought": "c2"}],
                min_children=5,
            )

    @pytest.mark.anyio
    async def test_at_min_children_succeeds(self):
        r = await think_graph(
            thought="root",
            action="branch",
            children=[{"thought": f"c{i}"} for i in range(5)],
            min_children=5,
        )
        assert "Batch: 5 children created" in r


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkRefsQuery:
    @pytest.mark.anyio
    async def test_returns_no_refs_for_unknown_id(self):
        from aismartbuddy.tools.refs import think_refs_query

        r = await think_refs_query(entity_id="nonexistent_id_xyz")
        assert "Total refs: 0" in r
        assert "No records reference this id" in r

    @pytest.mark.anyio
    async def test_finds_thought_node_with_ref(self):
        from aismartbuddy.tools.refs import think_refs_query

        r1 = await think_graph(
            thought="leaf",
            refs=["scaffold_item_42"],
        )
        sid = _extract_field(r1, "Session:")
        r = await think_refs_query(
            entity_id="scaffold_item_42",
            session_id=sid,
        )
        assert "Total refs: 1" in r
        assert "thought_nodes" in r


@pytest.mark.usefixtures("_init_session_manager")
class TestRuleRegistryAndValidation:
    @pytest.mark.anyio
    async def test_rule_profile_lifecycle_and_validation(self):
        created = await think_rules(
            action="create_profile",
            profile_id="security-rules",
            name="Security Rules",
            description="High-priority security constraints",
        )
        sid = _extract_field(created, "Session:")
        assert "Status: created" in created

        added = await think_rules(
            action="add_rules_batch",
            session_id=sid,
            profile_id="security-rules",
            rules=[
                {
                    "id": "encrypt-data",
                    "text": "Encryption at rest is required",
                    "weight": 5.0,
                    "kind": "hard",
                    "conflicts_with": ["debug-logging"],
                },
                {
                    "id": "debug-logging",
                    "text": "Verbose plaintext debug logging is required",
                    "weight": 1.0,
                    "kind": "soft",
                    "conflicts_with": ["encrypt-data"],
                },
            ],
        )
        assert "Rules added: 2" in added

        updated = await think_rules(
            action="update_weights_batch",
            session_id=sid,
            profile_id="security-rules",
            updates=[{"rule_id": "debug-logging", "weight": 2.5}],
        )
        assert "Weights updated: 1" in updated

        shown = await think_rules(
            action="show_profile",
            session_id=sid,
            profile_id="security-rules",
        )
        assert "debug-logging: [soft] w=2.5" in shown

        scaffold = await think_model(
            session_id=sid,
            model_name="design_review",
            items=[
                {
                    "id": "plan_a",
                    "problem": "Design an auth subsystem",
                    "steps": ["define trust boundaries"],
                    "reasoning": "Need security review coverage.",
                    "conclusion": "Proceed with explicit security controls.",
                }
            ],
            rule_profile_ids=["security-rules"],
        )
        assert "plan_a" in scaffold

        validation = await think_validate(
            session_id=sid,
            subject_id="plan_a",
            subject_kind="model",
            assessments=[
                {
                    "rule_id": "encrypt-data",
                    "status": "violates",
                    "note": "Storage layer still plaintext",
                },
                {
                    "rule_id": "debug-logging",
                    "status": "uncertain",
                    "note": "Logging mode not fully decided yet",
                },
            ],
            use_bound_profiles=True,
        )
        assert "Hard gates: FAIL" in validation
        assert "Conflicts: conflict-" in validation
        assert "Nuance:" in validation

        refs = await think_refs_query(entity_id="security-rules", session_id=sid)
        assert "models" in refs
        assert "rule_profiles" in refs
        assert "validations" in refs

        summary = await think_summarize(sid)
        assert "Rule Validation" in summary
        assert "security-rules" in summary

    @pytest.mark.anyio
    async def test_pinned_snapshot_stays_stable_after_weight_changes(self):
        created = await think_rules(
            action="create_profile",
            profile_id="design-rules",
            name="Design Rules",
        )
        sid = _extract_field(created, "Session:")
        await think_rules(
            action="add_rules_batch",
            session_id=sid,
            profile_id="design-rules",
            rules=[
                {
                    "id": "nuance",
                    "text": "Preserve nuance for high-risk decisions",
                    "weight": 4.0,
                    "kind": "soft",
                }
            ],
        )
        graph_r = await think_graph(
            thought="Review the original architecture plan",
            session_id=sid,
        )
        node_id = _extract_field(graph_r, "Node:")
        pin = await think_rules(
            action="pin_snapshot",
            session_id=sid,
            profile_id="design-rules",
            subject_id=node_id,
            subject_kind="thought",
            label="baseline",
        )
        snapshot_id = _extract_field(pin, "Snapshot:")
        assert snapshot_id.startswith("design-rules-snap-")

        await think_rules(
            action="update_weights_batch",
            session_id=sid,
            profile_id="design-rules",
            updates=[{"rule_id": "nuance", "weight": 9.0}],
        )
        validation = await think_validate(
            session_id=sid,
            subject_id=node_id,
            subject_kind="thought",
            assessments=[{"rule_id": "nuance", "status": "violates"}],
        )
        assert "Weighted gaps: nuance[violates]:4.0" in validation

        profile = await think_rules(
            action="show_profile",
            session_id=sid,
            profile_id="design-rules",
        )
        assert "w=9.0" in profile

    @pytest.mark.anyio
    async def test_rule_bound_subjects_materialize_graph_nodes_and_links(self):
        from aismartbuddy.tools.graph import graph_query
        from aismartbuddy.tools.infra import session_create

        parent = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_field(parent, "session_id:")
        await think_rules(
            action="create_profile",
            session_id=sid,
            profile_id="arch-rules",
            name="Architecture Rules",
        )
        await think_rules(
            action="add_rules_batch",
            session_id=sid,
            profile_id="arch-rules",
            rules=[
                {
                    "id": "least-privilege",
                    "text": "Use least privilege everywhere",
                    "weight": 3.0,
                    "kind": "soft",
                }
            ],
        )
        result = await think_model(
            session_id=sid,
            model_name="design_review",
            items=[
                {
                    "id": "plan_graph",
                    "problem": "Model the API gateway",
                    "steps": ["review trust zones"],
                    "reasoning": "Needs rule-aware graph links.",
                    "conclusion": "Gateway must preserve least privilege.",
                }
            ],
            rule_profile_ids=["arch-rules"],
        )
        assert "plan_graph" in result

        graph = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) "
                "WHERE n.name IN ["
                "'model:plan_graph', "
                "'rule_profile:arch-rules', "
                "'rule:least-privilege'] "
                "RETURN n.name;"
            ),
        )
        assert "model:plan_graph" in graph
        assert "rule_profile:arch-rules" in graph
        assert "rule:least-privilege" in graph


# ── auto_graph wirings on think_graph / think_decide / think_argue / think_validate ──


def _extract_session_id(result: str) -> str:
    for line in result.splitlines():
        line = line.strip()
        if line.startswith("session_id:"):
            return line[len("session_id:") :].strip()
    raise AssertionError(f"No session_id in {result!r}")


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkGraphAutoGraph:
    """think_graph(thoughts=[...], auto_graph=True) materialises BranchOf KG."""

    @pytest.mark.anyio
    async def test_auto_graph_default_false_byte_identical(self):
        """auto_graph=False (default) MUST produce byte-for-byte identical
        response to an explicit auto_graph=False call."""
        thoughts = [
            {"thought": "First insight"},
            {"thought": "Building", "parent_ref": 0},
            {"thought": "Conclusion", "parent_ref": 1},
        ]
        r_default = await think_graph(thoughts=list(thoughts))
        r_explicit = await think_graph(thoughts=list(thoughts), auto_graph=False)

        def _normalize(s: str) -> str:
            lines = []
            for line in s.split("\n"):
                if line.startswith("Session:"):
                    if " | Batch nodes created:" in line:
                        _, rhs = line.split(" | ", 1)
                        lines.append(f"Session: <SID> | {rhs}")
                    else:
                        lines.append("Session: <SID>")
                elif line.startswith("Node IDs:"):
                    lines.append("Node IDs: <IDS>")
                elif line.startswith("Trees:"):
                    lines.append("Trees: <TIDS>")
                else:
                    lines.append(line)
            return "\n".join(lines)

        assert _normalize(r_default) == _normalize(r_explicit)
        assert "Graph nodes created:" not in r_default
        assert "Graph nodes created:" not in r_explicit

    @pytest.mark.anyio
    async def test_auto_graph_no_graph_backend_raises(self):
        """auto_graph=True against a think-only session raises canonical error."""
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think"])
        sid = _extract_session_id(sess)
        with pytest.raises(ValueError, match="auto_graph requires a graph backend"):
            await think_graph(
                session_id=sid,
                auto_graph=True,
                thoughts=[{"thought": "root"}],
            )

    @pytest.mark.anyio
    async def test_auto_graph_creates_nodes_and_branchof_edges(self):
        """N thoughts → N KnowledgeNode rows + correct BranchOf edges."""
        from aismartbuddy.tools.graph import graph_query
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(sess)

        result = await think_graph(
            session_id=sid,
            auto_graph=True,
            thoughts=[
                {"thought": "Root insight"},
                {"thought": "Builds on root", "parent_ref": 0},
                {"thought": "Sibling of B", "parent_ref": 0},
                {"thought": "Conclusion", "parent_ref": 1},
            ],
        )
        assert "Batch nodes created: 4" in result
        assert "Graph nodes created: 4" in result

        # Extract assigned node ids from "Node IDs: <id1>, <id2>, ..."
        node_ids: list[str] = []
        for line in result.split("\n"):
            if line.startswith("Node IDs:"):
                payload = line[len("Node IDs:") :].strip()
                node_ids = [p.strip() for p in payload.split(",") if p.strip()]
                break
        assert len(node_ids) == 4

        et_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (k:KnowledgeNode) "
                "RETURN k.entity_type AS et, count(*) AS n "
                "ORDER BY et;"
            ),
        )
        assert "thought" in et_csv
        assert ",4" in et_csv.replace('"', "")

        edges_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (a:KnowledgeNode)-[r:BranchOf]->(b:KnowledgeNode) "
                "RETURN a.name AS src, b.name AS dst ORDER BY src, dst;"
            ),
        )
        normalized = edges_csv.replace('"', "")
        # 3 BranchOf edges from index 1, 2, 3 to assigned ids 0, 0, 1
        assert f"{node_ids[1]},{node_ids[0]}" in normalized
        assert f"{node_ids[2]},{node_ids[0]}" in normalized
        assert f"{node_ids[3]},{node_ids[1]}" in normalized


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkDecideAutoGraph:
    """think_decide(items=[...], auto_graph=True) materialises DerivedFrom KG."""

    @pytest.mark.anyio
    async def test_auto_graph_default_false_byte_identical(self):
        items = [
            {
                "id": "d1",
                "decision_statement": "Pick stack",
                "options": ["A", "B"],
                "criteria": [{"name": "cost", "weight": 1.0}],
                "recommendation": "A",
            },
        ]
        r_default = await think_decide(items=items)
        r_explicit = await think_decide(items=items, auto_graph=False)

        def _normalize(s: str) -> str:
            return "\n".join(
                "Session: <SID>" if line.startswith("Session:") else line
                for line in s.split("\n")
            )

        assert _normalize(r_default) == _normalize(r_explicit)
        assert "Graph nodes created:" not in r_default
        assert "Graph nodes created:" not in r_explicit

    @pytest.mark.anyio
    async def test_auto_graph_no_graph_backend_raises(self):
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think"])
        sid = _extract_session_id(sess)
        with pytest.raises(ValueError, match="auto_graph requires a graph backend"):
            await think_decide(
                session_id=sid,
                auto_graph=True,
                items=[
                    {
                        "id": "d1",
                        "decision_statement": "x",
                        "options": ["a", "b"],
                        "criteria": [{"name": "c", "weight": 1.0}],
                        "recommendation": "a",
                    }
                ],
            )

    @pytest.mark.anyio
    async def test_auto_graph_creates_nodes_and_derivedfrom_edges(self):
        from aismartbuddy.tools.graph import graph_query
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(sess)

        result = await think_decide(
            session_id=sid,
            auto_graph=True,
            items=[
                {
                    "id": "dec_a",
                    "decision_statement": "Pick A",
                    "options": ["x", "y"],
                    "criteria": [{"name": "cost", "weight": 1.0}],
                    "recommendation": "x",
                },
                {
                    "id": "dec_b",
                    "decision_statement": "Pick B",
                    "options": ["p", "q"],
                    "criteria": [{"name": "speed", "weight": 1.0}],
                    "recommendation": "p",
                    "connects_to": ["dec_a"],
                },
            ],
        )
        assert "Decisions: 2" in result
        assert "Graph nodes created: 2" in result

        et_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (k:KnowledgeNode {entity_type: 'decision'}) "
                "RETURN count(*) AS n;"
            ),
        )
        assert "2" in et_csv

        edges_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (a:KnowledgeNode)-[r:DerivedFrom]->(b:KnowledgeNode) "
                "RETURN a.name AS src, b.name AS dst ORDER BY src, dst;"
            ),
        )
        normalized = edges_csv.replace('"', "")
        assert "dec_b,dec_a" in normalized


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkArgueAutoGraph:
    """think_argue(chain=[...], auto_graph=True) materialises RespondsTo KG."""

    @pytest.mark.anyio
    async def test_auto_graph_default_false_byte_identical(self):
        chain = [
            {
                "type": "thesis",
                "claim": "X",
                "premises": ["p1"],
                "conclusion": "y",
                "argument_id": "a1",
            },
            {
                "type": "antithesis",
                "claim": "Not X",
                "premises": ["p2"],
                "conclusion": "z",
                "argument_id": "a2",
                "responds_to_index": 0,
            },
        ]
        r_default = await think_argue(chain=[dict(c) for c in chain])
        r_explicit = await think_argue(
            chain=[dict(c) for c in chain], auto_graph=False
        )

        def _normalize(s: str) -> str:
            lines = []
            for line in s.split("\n"):
                if line.startswith("Session:"):
                    # strip Session id and chain id (random per call)
                    if " | Batch:" in line:
                        _, rhs = line.split(" | Batch:", 1)
                        lines.append(f"Session: <SID> | Chain: <CID> | Batch:{rhs}")
                    else:
                        lines.append("Session: <SID>")
                else:
                    lines.append(line)
            return "\n".join(lines)

        assert _normalize(r_default) == _normalize(r_explicit)
        assert "Graph nodes created:" not in r_default
        assert "Graph nodes created:" not in r_explicit

    @pytest.mark.anyio
    async def test_auto_graph_no_graph_backend_raises(self):
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think"])
        sid = _extract_session_id(sess)
        with pytest.raises(ValueError, match="auto_graph requires a graph backend"):
            await think_argue(
                session_id=sid,
                auto_graph=True,
                chain=[
                    {
                        "type": "thesis",
                        "claim": "x",
                        "premises": ["p"],
                        "conclusion": "y",
                    }
                ],
            )

    @pytest.mark.anyio
    async def test_auto_graph_creates_nodes_and_respondsto_edges(self):
        from aismartbuddy.tools.graph import graph_query
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(sess)

        result = await think_argue(
            session_id=sid,
            auto_graph=True,
            chain=[
                {
                    "type": "thesis",
                    "claim": "Use Postgres",
                    "premises": ["mature"],
                    "conclusion": "go pg",
                    "argument_id": "arg_t",
                },
                {
                    "type": "antithesis",
                    "claim": "Use SQLite",
                    "premises": ["simple"],
                    "conclusion": "go sqlite",
                    "argument_id": "arg_a",
                    "responds_to_index": 0,
                },
                {
                    "type": "synthesis",
                    "claim": "Use both per env",
                    "premises": ["context"],
                    "conclusion": "split deploy",
                    "argument_id": "arg_s",
                    "responds_to_index": 1,
                },
            ],
        )
        assert "Batch: 3 arguments" in result
        assert "Graph nodes created: 3" in result

        et_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (k:KnowledgeNode {entity_type: 'argument'}) "
                "RETURN count(*) AS n;"
            ),
        )
        assert "3" in et_csv

        edges_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (a:KnowledgeNode)-[r:RespondsTo]->(b:KnowledgeNode) "
                "RETURN a.name AS src, b.name AS dst ORDER BY src, dst;"
            ),
        )
        normalized = edges_csv.replace('"', "")
        assert "arg_a,arg_t" in normalized
        assert "arg_s,arg_a" in normalized


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkValidateAutoGraph:
    """think_validate(items=[...], auto_graph=True) materialises Validates KG."""

    @pytest.mark.anyio
    async def test_auto_graph_default_false_byte_identical(self):
        # Use shared session so both calls reference the same materialised subject.
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think"])
        sid = _extract_session_id(sess)
        # Materialise two decisions to validate against (one per call).
        await think_decide(
            session_id=sid,
            items=[
                {
                    "id": "subj1",
                    "decision_statement": "x",
                    "options": ["a", "b"],
                    "criteria": [{"name": "c", "weight": 1.0}],
                    "recommendation": "a",
                },
                {
                    "id": "subj2",
                    "decision_statement": "y",
                    "options": ["a", "b"],
                    "criteria": [{"name": "c", "weight": 1.0}],
                    "recommendation": "a",
                },
            ],
        )
        r_default = await think_validate(
            session_id=sid,
            items=[{"id": "v1", "subject_id": "subj1"}],
        )
        r_explicit = await think_validate(
            session_id=sid,
            auto_graph=False,
            items=[{"id": "v2", "subject_id": "subj2"}],
        )

        def _normalize(s: str) -> str:
            lines = []
            for line in s.split("\n"):
                if line.startswith("Session:"):
                    if " | Validations:" in line:
                        _, rhs = line.split(" | ", 1)
                        lines.append(f"Session: <SID> | {rhs}")
                    else:
                        lines.append("Session: <SID>")
                elif line.startswith("IDs:"):
                    lines.append("IDs: <IDS>")
                else:
                    lines.append(line)
            return "\n".join(lines)

        assert _normalize(r_default) == _normalize(r_explicit)
        assert "Graph nodes created:" not in r_default
        assert "Graph nodes created:" not in r_explicit

    @pytest.mark.anyio
    async def test_auto_graph_no_graph_backend_raises(self):
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think"])
        sid = _extract_session_id(sess)
        # Materialise a real decision to validate against.
        await think_decide(
            session_id=sid,
            items=[
                {
                    "id": "subj_x",
                    "decision_statement": "x",
                    "options": ["a", "b"],
                    "criteria": [{"name": "c", "weight": 1.0}],
                    "recommendation": "a",
                }
            ],
        )
        with pytest.raises(ValueError, match="auto_graph requires a graph backend"):
            await think_validate(
                session_id=sid,
                auto_graph=True,
                items=[{"id": "v1", "subject_id": "subj_x"}],
            )

    @pytest.mark.anyio
    async def test_auto_graph_creates_nodes_and_validates_edges(self):
        """Validations materialise as KnowledgeNodes; the Validates edge lands
        only on a subject already in the KG (chained from think_decide with
        auto_graph)."""
        from aismartbuddy.tools.graph import graph_query
        from aismartbuddy.tools.infra import session_create

        sess = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(sess)

        # Materialise two decisions: subject_x lands in KG (auto_graph=True),
        # subject_skip lands in the engine but NOT in the KG.
        await think_decide(
            session_id=sid,
            auto_graph=True,
            items=[
                {
                    "id": "subject_x",
                    "decision_statement": "Pick stack",
                    "options": ["a", "b"],
                    "criteria": [{"name": "cost", "weight": 1.0}],
                    "recommendation": "a",
                },
            ],
        )
        await think_decide(
            session_id=sid,
            items=[
                {
                    "id": "subject_skip",
                    "decision_statement": "Other",
                    "options": ["a", "b"],
                    "criteria": [{"name": "c", "weight": 1.0}],
                    "recommendation": "a",
                }
            ],
        )

        result = await think_validate(
            session_id=sid,
            auto_graph=True,
            items=[
                {
                    "id": "v_a",
                    "validation_id": "val_a",
                    "subject_id": "subject_x",
                    "rationale": "passed soft rules",
                },
                {
                    "id": "v_b",
                    "validation_id": "val_b",
                    "subject_id": "subject_skip",  # not a KnowledgeNode → edge skipped
                    "rationale": "checks against missing-in-KG",
                },
            ],
        )
        assert "Validations: 2" in result
        assert "Graph nodes created: 2" in result

        # Pull the engine-assigned validation ids from the response.
        validation_ids: list[str] = []
        for line in result.split("\n"):
            if line.startswith("IDs:"):
                payload = line[len("IDs:") :].strip()
                validation_ids = [p.strip() for p in payload.split(",") if p.strip()]
                break
        assert len(validation_ids) == 2

        et_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (k:KnowledgeNode {entity_type: 'validation'}) "
                "RETURN count(*) AS n;"
            ),
        )
        assert "2" in et_csv

        edges_csv = await graph_query(
            session_id=sid,
            query=(
                "MATCH (a:KnowledgeNode)-[r:Validates]->(b:KnowledgeNode) "
                "RETURN a.name AS src, b.name AS dst ORDER BY src, dst;"
            ),
        )
        normalized = edges_csv.replace('"', "")
        # Only the first validation has a real KG subject (subject_x); the
        # second is silently skipped because subject_skip was not auto_graphed.
        assert f"{validation_ids[0]},subject_x" in normalized
        # No edge from the second validation (skipped target).
        assert f"{validation_ids[1]}," not in normalized


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkMonitorDensity:
    """think_monitor(action='density') returns session load stats."""

    @pytest.mark.anyio
    async def test_think_monitor_density_empty_session(self):
        result = await think_monitor(action="density")
        # response includes a "nodes: N" line (node_count rendered as 'nodes')
        # plus an entity_refs/export_token_estimate/recommendation block.
        assert "nodes: 0" in result
        assert "export_token_estimate:" in result
        assert "recommendation: continue" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkBridgeBundle:
    """think_bridge bundle action — multi-backend context assembly."""

    @pytest.mark.anyio
    async def test_think_bridge_bundle_no_companion(self):
        from aismartbuddy.tools.think import think_bridge

        result = await think_bridge(action="bundle", entity_ids=["x"])
        # No companion graph/SQL, but think section may or may not match — at
        # minimum we expect no error and the canonical session header.
        assert result.startswith("Session:") or "## Think" in result

    @pytest.mark.anyio
    async def test_think_bridge_bundle_missing_entity_ids(self):
        from aismartbuddy.tools.think import think_bridge

        with pytest.raises(ValueError, match="bundle requires entity_ids"):
            await think_bridge(action="bundle", entity_ids=[])
        with pytest.raises(ValueError, match="bundle requires entity_ids"):
            await think_bridge(action="bundle", entity_ids=None)


@pytest.mark.usefixtures("_init_session_manager")
class TestThoughtsForEntity:
    """think_bridge(action='thoughts_for_entity') registration + text fallback."""

    @pytest.mark.anyio
    async def test_unknown_entity_returns_none(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_graph(thought="totally unrelated content")
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="thoughts_for_entity",
            entity_name="NLRX1",
            session_id=sid,
        )
        assert "Thought matches: 0" in result

    @pytest.mark.anyio
    async def test_text_fallback_when_no_knowledge_refs(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_graph(
            thought="NLRX1 mitochondrial reactive oxygen species pathway"
        )
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="thoughts_for_entity",
            entity_name="NLRX1",
            session_id=sid,
        )
        assert "Thought matches: 1" in result
        assert "(text match)" in result

    @pytest.mark.anyio
    async def test_prefers_knowledge_refs_over_text(self):
        from aismartbuddy.tools.think import think_bridge

        # Two thoughts: one tagged via entity_refs, one with text-only match.
        r1 = await think_graph(
            thoughts=[
                {
                    "thought": "First insight tagged via entity_refs",
                    "entity_refs": ["NLRX1"],
                },
                {"thought": "Second mentions NLRX1 in body text only"},
            ],
        )
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="thoughts_for_entity",
            entity_name="NLRX1",
            session_id=sid,
        )
        # Only the registered match counts; text fallback is suppressed when
        # we already have a knowledge_refs hit.
        assert "Thought matches: 1" in result
        assert "(text match)" not in result

    @pytest.mark.anyio
    async def test_entity_refs_register_to_knowledge_refs(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_graph(
            thoughts=[
                {
                    "thought": "Thought referencing NLRX1 structurally",
                    "entity_refs": ["NLRX1"],
                }
            ],
        )
        sid = _extract_field(r1, "Session:")
        # Verify lookup finds the node WITHOUT relying on text content.
        result = await think_bridge(
            action="thoughts_for_entity",
            entity_name="NLRX1",
            session_id=sid,
        )
        assert "Thought matches: 1" in result
        assert "(text match)" not in result


@pytest.mark.usefixtures("_init_session_manager")
class TestDomainContext:
    """think_bridge(action='domain_context') aggregates by domain tag."""

    @pytest.mark.anyio
    async def test_domain_context_for_think_model(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_model(
            model_name="first_principles",
            items=[
                {
                    "id": "m_metab_1",
                    "problem": "Mitochondrial ROS",
                    "steps": ["s1"],
                    "reasoning": "first principles",
                    "conclusion": "ROS drives signal",
                    "domain": "metabolism",
                }
            ],
        )
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="domain_context",
            domain="metabolism",
            session_id=sid,
        )
        assert "domain: metabolism" in result
        assert "models: 1" in result
        assert "m_metab_1" in result

    @pytest.mark.anyio
    async def test_domain_context_for_think_science(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_science(
            items=[
                {
                    "id": "inq_inf_1",
                    "observation": "elevated cytokine levels",
                    "question": "what drives this",
                    "hypothesis": {
                        "statement": "NLRX1 modulates response",
                        "variables": [
                            {"name": "NLRX1_level", "role": "independent"},
                            {"name": "cytokine", "role": "dependent"},
                        ],
                        "assumptions": ["assay sensitivity sufficient"],
                        "confidence": 0.6,
                        "falsifiability": (
                            "Knockout NLRX1 and observe no change in cytokine levels"
                        ),
                    },
                    "domain": "inflammation",
                }
            ],
        )
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="domain_context",
            domain="inflammation",
            session_id=sid,
        )
        assert "domain: inflammation" in result
        assert "inquiries: 1" in result
        assert "inq_inf_1" in result

    @pytest.mark.anyio
    async def test_domain_context_empty_domain_message(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_graph(thought="some unrelated thought")
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="domain_context",
            domain="frontend",
            session_id=sid,
        )
        assert "(no records found for domain 'frontend')" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestDomainConnections:
    """think_bridge(action='domain_connections') cross-domain inspection."""

    @pytest.mark.anyio
    async def test_missing_domain_b_raises(self):
        from aismartbuddy.tools.think import think_bridge

        with pytest.raises(
            ValueError, match="domain_connections requires both domain and domain_b"
        ):
            await think_bridge(action="domain_connections", domain="a")

    @pytest.mark.anyio
    async def test_same_domain_returns_note(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_graph(thought="anchor")
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="domain_connections",
            domain="x",
            domain_b="x",
            session_id=sid,
        )
        assert "same domain" in result

    @pytest.mark.anyio
    async def test_no_graph_companion_think_side_only(self):
        from aismartbuddy.tools.infra import session_create
        from aismartbuddy.tools.think import think_bridge

        # Explicit think-only session (no graph backend) so domain_connections
        # returns think-side shared entities without a "## Graph connections" block.
        sess = await session_create(backends=["think"])
        sid = _extract_field(sess, "session_id:")
        await think_graph(
            session_id=sid,
            thoughts=[
                {
                    "thought": "frontend thought referencing user_login",
                    "entity_refs": ["user_login"],
                    "domain": "frontend",
                },
                {
                    "thought": "backend thought referencing user_login",
                    "entity_refs": ["user_login"],
                    "domain": "backend",
                },
            ],
        )
        result = await think_bridge(
            action="domain_connections",
            domain="frontend",
            domain_b="backend",
            session_id=sid,
        )
        assert "## Shared entities" in result
        assert "user_login" in result
        # No graph backend → no "## Graph connections" header
        assert "## Graph connections" not in result

    @pytest.mark.anyio
    async def test_empty_shared_entities(self):
        from aismartbuddy.tools.think import think_bridge

        # Two thoughts with non-overlapping entity_refs — intersection is empty.
        r1 = await think_graph(
            thoughts=[
                {
                    "thought": "frontend thought",
                    "entity_refs": ["login_form"],
                    "domain": "frontend",
                },
                {
                    "thought": "backend thought",
                    "entity_refs": ["db_pool"],
                    "domain": "backend",
                },
            ],
        )
        sid = _extract_field(r1, "Session:")
        result = await think_bridge(
            action="domain_connections",
            domain="frontend",
            domain_b="backend",
            session_id=sid,
        )
        assert "## Shared entities: (none)" in result

    @pytest.mark.anyio
    async def test_whitespace_only_domain_raises(self):
        from aismartbuddy.tools.think import think_bridge

        r1 = await think_graph(thought="anchor")
        sid = _extract_field(r1, "Session:")
        with pytest.raises(ValueError, match="domain_connections requires"):
            await think_bridge(
                action="domain_connections",
                domain="   ",
                domain_b="backend",
                session_id=sid,
            )

    @pytest.mark.anyio
    async def test_graph_mode_shows_cross_domain_edges(self):
        from aismartbuddy.tools.graph import graph_knowledge_add, graph_knowledge_relate
        from aismartbuddy.tools.infra import session_create
        from aismartbuddy.tools.think import think_bridge

        r1 = await session_create(backends=["think", "graph"])
        sid = ""
        for line in r1.split("\n"):
            line = line.strip()
            if line.startswith("session_id:"):
                sid = line[len("session_id:"):].strip()
                break
        assert sid

        # Create two graph nodes in different domains, then link them.
        await graph_knowledge_add(
            session_id=sid,
            entity="CPT1A",
            entity_type="gene",
            domain="metabolism",
        )
        await graph_knowledge_add(
            session_id=sid,
            entity="IL6",
            entity_type="cytokine",
            domain="inflammation",
        )
        await graph_knowledge_relate(
            session_id=sid,
            from_name="CPT1A",
            to_name="IL6",
            relation="activates",
        )

        # domain_connections should surface the cross-domain edge.
        result = await think_bridge(
            action="domain_connections",
            domain="metabolism",
            domain_b="inflammation",
            session_id=sid,
        )
        assert "## Graph connections" in result
        assert "CPT1A" in result
        assert "IL6" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkScienceRefs:
    """think_science items[] refs population from connects_to."""

    @pytest.mark.anyio
    async def test_connects_to_populates_refs(self):
        _hyp = lambda stmt: {  # noqa: E731
            "statement": stmt,
            "variables": [
                {"name": "x", "role": "independent"},
                {"name": "y", "role": "dependent"},
            ],
            "assumptions": ["baseline"],
            "confidence": 0.5,
            "falsifiability": "Specific predicted result that would refute it",
        }
        # Build anchor record first.
        r1 = await think_science(
            items=[
                {
                    "id": "inq_anchor",
                    "observation": "obs",
                    "question": "q",
                    "hypothesis": _hyp("h"),
                }
            ],
        )
        sid = _extract_field(r1, "Session:")
        # Second record connects_to the first.
        await think_science(
            items=[
                {
                    "id": "inq_dep",
                    "observation": "obs2",
                    "question": "q2",
                    "hypothesis": _hyp("h2"),
                    "connects_to": ["inq_anchor"],
                }
            ],
            session_id=sid,
        )
        rows = await think_refs_query(entity_id="inq_anchor", session_id=sid)
        # Expect at least one inquiry referencing inq_anchor.
        assert "inq_dep" in rows or "inquiry" in rows
