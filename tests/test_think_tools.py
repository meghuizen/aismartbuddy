"""Tests for structured thinking tools (Layer 1 — ephemeral, in-memory)."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.thinking_engine import (
    MAX_NODES,
    MAX_TREES,
    ArgRecord,
    CollabRecord,
    DebugRecord,
    DecisionRecord,
    DiagramRecord,
    InquiryRecord,
    ModelRecord,
    MonitorRecord,
    ThinkingEngine,
    ThoughtNode,
)
from aismartbuddy.session import SessionManager
from aismartbuddy.tools.think import (
    think_argue,
    think_collaborate,
    think_debug,
    think_decide,
    think_destroy_session,
    think_graph,
    think_graph_delegate,
    think_graph_validate,
    think_interfere,
    think_interfere_state,
    think_model,
    think_monitor,
    think_science,
    think_summarize,
    think_visualize,
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
        engine.add_node(ThoughtNode(
            id="c1", tree_id="t1", content="Child", parent_id="r1", depth=1
        ))
        engine.add_node(ThoughtNode(
            id="g1", tree_id="t1", content="Grand", parent_id="c1", depth=2
        ))
        assert engine.get_node_count() == 3
        assert "c1" in engine.get_node("r1").children
        assert "g1" in engine.get_node("c1").children

    def test_hierarchical_branching(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(
            id="r1", tree_id="t1", content="Problem", action="branch"
        ))
        for i in range(3):
            engine.add_node(ThoughtNode(
                id=f"b{i}", tree_id="t1", content=f"Branch {i}",
                parent_id="r1", depth=1,
            ))
        assert len(engine.get_node("r1").children) == 3

    def test_get_subtree(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r", tree_id="t1", content="Root"))
        engine.add_node(ThoughtNode(
            id="a", tree_id="t1", content="A", parent_id="r", depth=1
        ))
        engine.add_node(ThoughtNode(
            id="b", tree_id="t1", content="B", parent_id="r", depth=1
        ))
        engine.add_node(ThoughtNode(
            id="a1", tree_id="t1", content="A1", parent_id="a", depth=2
        ))
        assert len(engine.get_subtree_nodes("r")) == 4
        assert len(engine.get_subtree_nodes("a")) == 2

    def test_get_path_to_root(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(id="r", tree_id="t1", content="Root"))
        engine.add_node(ThoughtNode(
            id="c", tree_id="t1", content="Child", parent_id="r", depth=1
        ))
        engine.add_node(ThoughtNode(
            id="g", tree_id="t1", content="Grand", parent_id="c", depth=2
        ))
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
            engine.add_node(ThoughtNode(
                id=f"r{t}", tree_id=tid, content=f"Root {t}"
            ))
            for n in range(1, nodes_per_tree):
                engine.add_node(ThoughtNode(
                    id=f"n{t}_{n}", tree_id=tid, content=f"Node {n}",
                    parent_id=f"r{t}", depth=1,
                ))
        assert engine.get_node_count() <= MAX_NODES

    def test_memory_limit_trees(self, engine: ThinkingEngine):
        for t in range(MAX_TREES + 10):
            engine.add_node(ThoughtNode(
                id=f"r{t}", tree_id=f"t{t}", content=f"Root {t}"
            ))
        assert len(engine.get_tree_ids()) <= MAX_TREES

    def test_add_model(self, engine: ThinkingEngine):
        engine.add_model(ModelRecord(
            model_name="first_principles", problem="test"
        ))
        assert len(engine.models) == 1

    def test_upsert_decision(self, engine: ThinkingEngine):
        d = DecisionRecord(decision_id="d1", statement="Choose DB")
        engine.upsert_decision(d)
        assert engine.get_decision("d1") is not None
        d2 = DecisionRecord(
            decision_id="d1", statement="v2", stage="criteria"
        )
        engine.upsert_decision(d2)
        assert engine.get_decision("d1").stage == "criteria"

    def test_add_debug(self, engine: ThinkingEngine):
        engine.add_debug(DebugRecord(
            approach_name="binary_search", issue="test issue"
        ))
        assert len(engine.debugs) == 1

    def test_argumentation_chain(self, engine: ThinkingEngine):
        engine.add_argument(
            "chain1", ArgRecord(argument_id="a1", claim="Claim 1")
        )
        engine.add_argument(
            "chain1", ArgRecord(argument_id="a2", claim="Counter 1")
        )
        assert len(engine.get_arg_chain("chain1")) == 2

    def test_collaboration(self, engine: ThinkingEngine):
        engine.upsert_collaboration(CollabRecord(
            session_id="c1", topic="Design review"
        ))
        assert engine.get_collaboration("c1") is not None

    def test_inquiry(self, engine: ThinkingEngine):
        engine.upsert_inquiry(InquiryRecord(
            inquiry_id="i1", stage="observation"
        ))
        assert engine.get_inquiry("i1").stage == "observation"

    def test_monitor(self, engine: ThinkingEngine):
        engine.upsert_monitor(MonitorRecord(
            monitoring_id="m1", task="Test task"
        ))
        assert engine.get_monitor("m1").task == "Test task"

    def test_diagram(self, engine: ThinkingEngine):
        engine.upsert_diagram(DiagramRecord(
            diagram_id="d1", diagram_type="flowchart",
            elements=[{"id": "n1", "type": "node", "properties": {}}],
        ))
        assert engine.get_diagram("d1") is not None

    def test_summary_empty(self, engine: ThinkingEngine):
        assert "Empty thinking session" in engine.get_summary()

    def test_summary_with_content(self, engine: ThinkingEngine):
        engine.add_node(ThoughtNode(
            id="r1", tree_id="t1", content="Test thought"
        ))
        engine.add_model(ModelRecord(
            model_name="pareto_principle", problem="test"
        ))
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


@pytest.fixture
def _init_session_manager(session_manager: SessionManager):
    """Wire up the module-level singleton so tools can find it."""
    import aismartbuddy.session as session_mod

    session_mod.session_manager = session_manager
    yield
    session_mod.session_manager = None


def _extract_field(result: str, prefix: str) -> str:
    """Extract a value from compact text output after a prefix."""
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix):].strip()
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

        r2 = await think_graph(
            thought="Building on that...", parent_id=nid1, session_id=sid
        )
        assert "Depth: 1" in r2
        nid2 = _extract_field(r2, "Node:")

        r3 = await think_graph(
            thought="Therefore...", parent_id=nid2, session_id=sid
        )
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

        await think_graph(
            thought="Branch A", parent_id=nid, session_id=sid
        )
        r3 = await think_graph(
            thought="Branch B", parent_id=nid, session_id=sid
        )
        assert "Siblings: 1" in r3  # Branch B has 1 sibling (Branch A)

    @pytest.mark.anyio
    async def test_revise_node(self):
        r1 = await think_graph(thought="Original thought")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        r2 = await think_graph(
            thought="Revised insight", action="revise",
            node_id=nid, session_id=sid,
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
            action="synthesize", parent_id=branch_id, session_id=sid,
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
            session_id=sid, depends_on=[node_a],
        )
        assert "Status: added" in r2

    @pytest.mark.anyio
    async def test_validate_dependencies(self):
        r1 = await think_graph(thought="Task A")
        sid = _extract_field(r1, "Session:")
        node_a = _extract_field(r1, "Node:")

        r2 = await think_graph(
            thought="Task B", session_id=sid, depends_on=[node_a],
        )
        node_b = _extract_field(r2, "Node:")

        r = await think_graph_validate(
            session_id=sid, target_id=node_b,
            check_type="dependencies", result="pass",
            details="All dependencies exist and are acyclic.",
        )
        assert "dependencies = pass" in r


@pytest.mark.usefixtures("_init_session_manager")
class TestThoughtGraphValidate:
    @pytest.mark.anyio
    async def test_validate_coverage(self):
        r1 = await think_graph(thought="Root problem")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        r = await think_graph_validate(
            session_id=sid, target_id=nid,
            check_type="coverage", result="pass",
            details="Children cover all aspects of the problem.",
        )
        assert "Validation: coverage = pass" in r
        assert "Total checks on node: 1" in r

    @pytest.mark.anyio
    async def test_validate_multiple_checks(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        await think_graph_validate(
            session_id=sid, target_id=nid,
            check_type="coverage", result="pass", details="OK",
        )
        r = await think_graph_validate(
            session_id=sid, target_id=nid,
            check_type="gaps", result="warning",
            details="Missing edge case analysis.",
            suggestions=["Add error handling branch"],
        )
        assert "Total checks on node: 2" in r

    @pytest.mark.anyio
    async def test_invalid_check_type(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        with pytest.raises(ValueError, match="Invalid check_type"):
            await think_graph_validate(
                session_id=sid, target_id=nid,
                check_type="vibes", result="pass", details="nope",
            )

    @pytest.mark.anyio
    async def test_invalid_result(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        with pytest.raises(ValueError, match="Invalid result"):
            await think_graph_validate(
                session_id=sid, target_id=nid,
                check_type="coverage", result="maybe", details="hmm",
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThoughtGraphDelegate:
    @pytest.mark.anyio
    async def test_package_subtree(self):
        r1 = await think_graph(thought="Root problem")
        sid = _extract_field(r1, "Session:")
        root_id = _extract_field(r1, "Node:")

        r2 = await think_graph(
            thought="Delegatable subtask", parent_id=root_id, session_id=sid
        )
        child_id = _extract_field(r2, "Node:")

        r = await think_graph_delegate(
            session_id=sid, node_id=child_id, action="package"
        )
        assert "Delegation: packaged" in r
        assert "Delegation Package" in r
        assert "Root problem" in r
        assert "[THIS NODE]" in r

    @pytest.mark.anyio
    async def test_receive_result(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")
        nid = _extract_field(r1, "Node:")

        await think_graph_delegate(
            session_id=sid, node_id=nid, action="package"
        )
        r = await think_graph_delegate(
            session_id=sid, node_id=nid, action="receive",
            result="Subagent found the answer: 42",
        )
        assert "Delegation: completed" in r

    @pytest.mark.anyio
    async def test_package_includes_ancestry(self):
        r1 = await think_graph(thought="Level 0")
        sid = _extract_field(r1, "Session:")
        nid0 = _extract_field(r1, "Node:")

        r2 = await think_graph(
            thought="Level 1", parent_id=nid0, session_id=sid
        )
        nid1 = _extract_field(r2, "Node:")

        r3 = await think_graph(
            thought="Level 2", parent_id=nid1, session_id=sid
        )
        nid2 = _extract_field(r3, "Node:")

        r = await think_graph_delegate(
            session_id=sid, node_id=nid2, action="package"
        )
        assert "Context depth: 3 nodes" in r
        assert "Level 0" in r
        assert "Level 1" in r
        assert "Level 2" in r

    @pytest.mark.anyio
    async def test_delegate_nonexistent_node(self):
        r1 = await think_graph(thought="Root")
        sid = _extract_field(r1, "Session:")

        with pytest.raises(ValueError, match="not found"):
            await think_graph_delegate(
                session_id=sid, node_id="nonexistent", action="package"
            )


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
                decision_statement="test", options=[],
                analysis_type="invalid", stage="options",
                decision_id="x", iteration=0, next_stage_needed=False,
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
            model_name="first_principles", problem="Why is the build slow?",
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


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkDebugTool:
    @pytest.mark.anyio
    async def test_debug_approach(self):
        result = await think_debug(
            approach_name="binary_search", issue="Performance regression",
            steps=["Bisect commits"], resolution="Found commit X.",
        )
        assert "Approach: binary_search" in result

    @pytest.mark.anyio
    async def test_invalid_approach(self):
        with pytest.raises(ValueError, match="Invalid approach_name"):
            await think_debug(approach_name="magic", issue="test")


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkArgueTool:
    @pytest.mark.anyio
    async def test_argumentation_chain(self):
        result = await think_argue(
            claim="DuckDB is better", premises=["Column-oriented"],
            conclusion="Choose DuckDB.", argument_type="thesis",
            confidence=0.8, next_argument_needed=True,
        )
        assert "Type: thesis" in result

    @pytest.mark.anyio
    async def test_invalid_argument_type(self):
        with pytest.raises(ValueError, match="Invalid argument_type"):
            await think_argue(
                claim="test", premises=[], conclusion="",
                argument_type="invalid", confidence=0.5,
                next_argument_needed=False,
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkCollaborateTool:
    @pytest.mark.anyio
    async def test_collaboration(self):
        result = await think_collaborate(
            topic="API design review",
            personas=[{
                "id": "arch", "name": "Architect",
                "expertise": ["API"], "background": "10y",
                "perspective": "Clean", "biases": [],
                "communication": {"style": "technical", "tone": "analytical"},
            }],
            contributions=[{
                "personaId": "arch", "content": "Surface too large.",
                "type": "concern", "confidence": 0.8,
            }],
            stage="critique", active_persona_id="arch",
            collaboration_id="r-1", iteration=1,
            next_contribution_needed=True,
        )
        assert "Collab: r-1" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkScienceTool:
    @pytest.mark.anyio
    async def test_scientific_inquiry(self):
        result = await think_science(
            stage="hypothesis", inquiry_id="perf-test",
            iteration=1, next_stage_needed=True,
            hypothesis={"statement": "Index will fix it", "variables": []},
        )
        assert "Inquiry: perf-test" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkMonitorTool:
    @pytest.mark.anyio
    async def test_metacognitive_monitoring(self):
        result = await think_monitor(
            task="Code review", stage="knowledge-assessment",
            overall_confidence=0.7, monitoring_id="rm",
            iteration=1, next_assessment_needed=True,
            uncertainty_areas=["Coverage", "Edge cases"],
        )
        assert "Confidence: 0.70" in result
        assert "Uncertainties: 2" in result

    @pytest.mark.anyio
    async def test_knowledge_assessment(self):
        result = await think_monitor(
            task="Evaluate Python", stage="knowledge-assessment",
            overall_confidence=0.85, monitoring_id="ka-1",
            iteration=1, next_assessment_needed=False,
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
                task="t", stage="knowledge-assessment",
                overall_confidence=0.5, monitoring_id="x",
                iteration=0, next_assessment_needed=False,
                knowledge_assessment={
                    "domain": "t", "knowledgeLevel": "god-tier",
                },
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkVisualizeTool:
    @pytest.mark.anyio
    async def test_create_diagram(self):
        result = await think_visualize(
            operation="create", diagram_id="arch",
            diagram_type="flowchart", iteration=1,
            next_operation_needed=True,
            elements=[{"id": "n1", "type": "node", "properties": {}}],
        )
        assert "Diagram: arch" in result

    @pytest.mark.anyio
    async def test_delete_diagram(self):
        r1 = await think_visualize(
            operation="create", diagram_id="tmp",
            diagram_type="graph", iteration=1,
            next_operation_needed=True,
        )
        sid = _extract_field(r1, "Session:")
        r2 = await think_visualize(
            operation="delete", diagram_id="tmp",
            diagram_type="graph", iteration=2,
            next_operation_needed=False, session_id=sid,
        )
        assert "Deleted" in r2


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkSummarizeTool:
    @pytest.mark.anyio
    async def test_summarize(self):
        r = await think_graph(thought="Test thought")
        sid = _extract_field(r, "Session:")
        summary = await think_summarize(sid)
        assert "Thought Graphs" in summary

    @pytest.mark.anyio
    async def test_summarize_wrong_session_type(
        self, session_manager: SessionManager
    ):
        info = session_manager.create_session("sql")
        with pytest.raises(ValueError, match="not a thinking session"):
            await think_summarize(info.session_id)


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkDestroyTool:
    @pytest.mark.anyio
    async def test_destroy(self):
        r = await think_graph(thought="Test")
        sid = _extract_field(r, "Session:")
        result = await think_destroy_session(sid)
        assert "Destroyed" in result

    @pytest.mark.anyio
    async def test_destroy_wrong_session_type(
        self, session_manager: SessionManager
    ):
        info = session_manager.create_session("sql")
        with pytest.raises(ValueError, match="not a thinking session"):
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
            action="add_frame", session_id=sid, protocol_id=pid,
            frame="Data is passive; queries are active",
        )

        for dom, law_, iso in [
            ("Holography", "Every fragment encodes the whole",
             "Both have local parts with global info"),
            ("Immunology", "Identity without central controller",
             "Both maintain coherence without coordination"),
            ("Holarchy", "Every level is whole and part",
             "Both have recursive self-similar structure"),
        ]:
            r = await think_interfere(
                action="add_source", session_id=sid, protocol_id=pid,
                source_domain=dom, law=law_, isomorphism=iso,
            )
        assert "Sources: 3" in r

        for i in range(5):
            r = await think_interfere(
                action="add_fragment", session_id=sid, protocol_id=pid,
                fragment=f"Fragment {i}: It would have to...",
            )
        assert "Phase: saturated" in r

        r = await think_interfere(
            action="crystallize", session_id=sid, protocol_id=pid,
            name="Holographic Compute Substrate",
            properties=[
                {"text": "Node is data+query+processor",
                 "novel": True, "source_laws": [0, 2]},
                {"text": "Consistency from resonance",
                 "novel": True, "source_laws": [0, 1]},
                {"text": "No observer boundary",
                 "novel": True, "source_laws": [1, 2]},
            ],
        )
        assert "Phase: crystallized" in r

        r = await think_interfere(
            action="add_necessity", session_id=sid, protocol_id=pid,
            conclusion="Local stateless computation",
            prerequisites=[
                {"claim": "Prereq 1", "status": "untested"},
                {"claim": "Prereq 2", "status": "untested"},
            ],
        )
        assert "Phase: necessities_derived" in r

        r = await think_interfere(
            action="stress_test", session_id=sid, protocol_id=pid,
            audit_type="first_principles",
            audit_result="No violations found.",
        )
        assert "Audits: 1/4" in r

        r = await think_interfere(
            action="finalize", session_id=sid, protocol_id=pid,
            verdict="survives",
        )
        assert "Phase: stress_tested" in r

        r = await think_interfere(
            action="recurse", session_id=sid, protocol_id=pid,
            new_domain="distributed consensus",
            concept_as_law="Nodes store+query+compute without coordination",
        )
        assert "Iter: 2" in r

    @pytest.mark.anyio
    async def test_reject_fragment_before_2_sources(self):
        r = await think_interfere(
            action="set_domain", target_domain="test"
        )
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        await think_interfere(
            action="add_source", session_id=sid, protocol_id=pid,
            source_domain="A", law="law A", isomorphism="iso A",
        )
        r = await think_interfere(
            action="add_fragment", session_id=sid, protocol_id=pid,
            fragment="test",
        )
        assert "REJECTED" in r

    @pytest.mark.anyio
    async def test_reject_mashup_not_emergence(self):
        r = await think_interfere(
            action="set_domain", target_domain="test"
        )
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        for d in ["A", "B"]:
            await think_interfere(
                action="add_source", session_id=sid, protocol_id=pid,
                source_domain=d, law=f"{d} law", isomorphism=f"iso {d}",
            )
        for i in range(5):
            await think_interfere(
                action="add_fragment", session_id=sid, protocol_id=pid,
                fragment=f"Fragment {i}",
            )
        r = await think_interfere(
            action="crystallize", session_id=sid, protocol_id=pid,
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
        r = await think_interfere(
            action="set_domain", target_domain="test"
        )
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        for d in ["A", "B"]:
            await think_interfere(
                action="add_source", session_id=sid, protocol_id=pid,
                source_domain=d, law=f"{d} law", isomorphism=f"iso {d}",
            )
        for i in range(5):
            await think_interfere(
                action="add_fragment", session_id=sid, protocol_id=pid,
                fragment=f"Fragment {i}",
            )
        await think_interfere(
            action="crystallize", session_id=sid, protocol_id=pid,
            name="Concept",
            properties=[
                {"text": "P1", "novel": True, "source_laws": [0, 1]},
                {"text": "P2", "novel": True, "source_laws": [0, 1]},
            ],
        )
        await think_interfere(
            action="add_necessity", session_id=sid, protocol_id=pid,
            conclusion="Test",
            prerequisites=[
                {"claim": "A", "status": "untested"},
                {"claim": "B", "status": "untested"},
            ],
        )
        await think_interfere(
            action="update_necessity", session_id=sid, protocol_id=pid,
            chain_index=0, prereq_index=0, new_status="fails",
        )
        r = await think_interfere(
            action="update_necessity", session_id=sid, protocol_id=pid,
            chain_index=0, prereq_index=1, new_status="fails",
        )
        assert "CHAIN BROKEN" in r

    @pytest.mark.anyio
    async def test_state_query(self):
        r = await think_interfere(
            action="set_domain", target_domain="test domain",
        )
        sid = _extract_field(r, "Session:")
        pid = _extract_field(r, "Protocol:")
        await think_interfere(
            action="add_source", session_id=sid, protocol_id=pid,
            source_domain="Physics", law="E=mc2",
            isomorphism="Both are energy systems",
        )
        state = await think_interfere_state(session_id=sid, protocol_id=pid)
        assert "test domain" in state
        assert "Physics" in state

    @pytest.mark.anyio
    async def test_multi_protocol_isolation(self):
        r1 = await think_interfere(
            action="set_domain", target_domain="domain A",
        )
        sid = _extract_field(r1, "Session:")
        pid1 = _extract_field(r1, "Protocol:")
        r2 = await think_interfere(
            action="set_domain", target_domain="domain B",
            session_id=sid,
        )
        pid2 = _extract_field(r2, "Protocol:")
        assert pid1 != pid2
        await think_interfere(
            action="add_frame", session_id=sid, protocol_id=pid1,
            frame="Frame for A only",
        )
        state2 = await think_interfere_state(session_id=sid, protocol_id=pid2)
        assert "Frame for A only" not in state2
