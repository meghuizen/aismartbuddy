"""Tests for extended thinking, session, and integration surfaces."""

from __future__ import annotations

import json

import pytest

from aismartbuddy.tools.graph import graph_knowledge_add, graph_query
from aismartbuddy.tools.infra import session_create
from aismartbuddy.tools.sql import sql_query
from aismartbuddy.tools.think import (
    think_argue,
    think_bridge,
    think_constraint,
    think_evidence,
    think_export_session,
    think_get_path,
    think_get_session_links,
    think_get_subtree,
    think_graph,
    think_graph_validate,
    think_hypothesis,
    think_link_sessions,
    think_model,
    think_monitor,
    think_science,
    think_set_active_session,
    think_summarize,
    think_topology,
)


def _extract_value(result: str, prefix: str) -> str:
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix) :].strip()
    raise AssertionError(f"missing prefix {prefix!r} in {result!r}")


@pytest.mark.usefixtures("_init_session_manager")
class TestOperationalThinkingSurface:
    @pytest.mark.anyio
    async def test_think_graph_batch_readback_and_validation(self):
        batch = await think_graph(
            thoughts=[
                {"thought": "Root design problem", "action": "branch"},
                {"thought": "Constraint branch", "parent_ref": 0},
                {"thought": "Evidence branch", "parent_ref": 0},
            ]
        )
        root_id = _extract_value(batch, "Node IDs:").split(",")[0].strip()

        subtree = await think_get_subtree(node_id=root_id)
        assert "Constraint branch" in subtree
        assert "Evidence branch" in subtree

        path = await think_get_path(node_id=root_id)
        assert "Path length: 1" in path

        exported = await think_export_session(format="json")
        payload = json.loads(exported)
        assert payload["trees"]

        verbose = await think_graph(
            thought="This node is too long, however it also mixes a second idea, additionally "
            "it keeps going long enough to trigger the granularity warning.",
            parent_id=root_id,
        )
        verbose_id = _extract_value(verbose, "Node:")
        validation = await think_graph_validate(
            node_id=verbose_id,
            auto_branch_on_warning=True,
        )
        assert "Status: warning" in validation
        assert "Auto-branch created:" in validation

    @pytest.mark.anyio
    async def test_active_parent_session_applies_to_sql_and_graph(self):
        parent = await session_create(backends=["think", "sql", "graph"], mode="analyze")
        sid = _extract_value(parent, "session_id:")
        await think_set_active_session(sid)

        sql_result = await sql_query(query="SELECT 1 AS value;")
        assert "value" in sql_result
        assert "1" in sql_result

        await graph_knowledge_add(entity="active-session-node", entity_type="entity")
        graph_result = await graph_query(
            query=(
                "MATCH (n:KnowledgeNode) "
                "WHERE n.name = 'active-session-node' "
                "RETURN n.name AS name;"
            )
        )
        assert "name" in graph_result
        assert "active-session-node" in graph_result

    @pytest.mark.anyio
    async def test_cross_session_linking(self):
        left = await think_graph(thought="Plan A root")
        left_sid = _extract_value(left, "Session:")
        left_node = _extract_value(left, "Node:")

        right = await think_graph(thought="Plan B root")
        right_sid = _extract_value(right, "Session:")
        right_node = _extract_value(right, "Node:")

        linked = await think_link_sessions(
            session_a=left_sid,
            node_a_id=left_node,
            session_b=right_sid,
            node_b_id=right_node,
            relationship="extends",
        )
        assert "--[extends]-->" in linked

        listed = await think_get_session_links(session_id=left_sid)
        assert "extends" in listed


@pytest.mark.usefixtures("_init_session_manager")
class TestReasoningExtensions:
    @pytest.mark.anyio
    async def test_hypothesis_constraint_evidence_and_bridge_flow(self):
        reg = await think_hypothesis(
            action="register",
            hypothesis_id="hyp_1",
            statement="Queue backpressure causes the latency spike",
            domain="systems",
            predictions=[{"observable": "queue_depth", "predicted_value": "high"}],
        )
        sid = _extract_value(reg, "Session:")
        assert "Status: registered" in reg

        evidence = await think_hypothesis(
            action="evidence",
            session_id=sid,
            hypothesis_id="hyp_1",
            evidence_text="Queue depth doubled during incident",
            direction="supports",
            strength=0.9,
            source_domain="observability",
        )
        assert "Posterior:" in evidence

        await think_constraint(
            action="register",
            session_id=sid,
            constraint_id="con_1",
            domain="resource",
            type="hard",
            statement="Queue depth cannot stay near zero if backpressure is the cause",
        )
        validated = await think_constraint(
            action="validate",
            session_id=sid,
            constraint_id="con_1",
            target_type="hypothesis",
            target_id="hyp_1",
            status="pass",
            note="Observed queue depth was elevated",
        )
        assert "Status: pass" in validated

        await think_evidence(
            action="register",
            session_id=sid,
            evidence_id="evi_1",
            content="Queue depth metric from incident timeline",
            source_type="measurement",
            confidence=0.9,
        )
        await think_evidence(
            action="chain",
            session_id=sid,
            from_id="evi_1",
            to_id="hyp_1",
            inference_type="inductive",
        )
        strength = await think_evidence(action="strength", session_id=sid, claim_id="hyp_1")
        assert "Evidence strength:" in strength

        bridge = await think_bridge(
            action="constraints_for_hypothesis",
            session_id=sid,
            hypothesis_id="hyp_1",
        )
        assert "con_1: pass" in bridge

        sweep = await think_constraint(
            action="check_all",
            session_id=sid,
            target_type="hypothesis",
        )
        assert "Constraint sweep:" in sweep
        assert "hypothesis targets" in sweep
        assert "status=pass" in sweep

    @pytest.mark.anyio
    async def test_topology_and_new_model_names(self):
        created = await think_topology(
            action="define",
            topology_id="topo_1",
            name="Control loop",
            source_domain="engineering",
            nodes=[
                {"id": "sensor", "role": "SENSOR"},
                {"id": "gate", "role": "GATE"},
            ],
            edges=[{"from": "sensor", "to": "gate", "type": "COUPLES"}],
        )
        sid = _extract_value(created, "Session:")
        assert "Status: defined" in created

        abstracted = await think_topology(
            action="abstract",
            session_id=sid,
            topology_id="topo_2",
            source_domain="software",
            source_description="A sensor detects health and a gate blocks requests",
        )
        assert "Status: abstracted" in abstracted

        compared = await think_topology(
            action="compare",
            session_id=sid,
            topology_a_id="topo_1",
            topology_b_id="topo_2",
        )
        assert "Shared roles:" in compared

        searched = await think_topology(
            action="search",
            session_id=sid,
            pattern="gate",
        )
        assert "Topologies:" in searched

        for model_name in ("kuba", "systems_dynamics", "inversion"):
            result = await think_model(
                session_id=sid,
                model_name=model_name,
                items=[
                    {
                        "id": f"{model_name}_item",
                        "problem": f"Analyze with {model_name}",
                        "steps": ["step 1"],
                        "reasoning": "structured reasoning",
                        "conclusion": "structured conclusion",
                    }
                ],
            )
            assert model_name in result

    @pytest.mark.anyio
    async def test_think_bridge_and_summarize_include_graph_context_when_available(self):
        parent = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_value(parent, "session_id:")
        await graph_knowledge_add(
            session_id=sid,
            entity="EntityA",
            entity_type="concept",
        )
        thought = await think_graph(
            session_id=sid,
            thought="EntityA is central to this branch",
            metadata={"knowledge_refs": ["EntityA"]},
        )
        node_id = _extract_value(thought, "Node:")

        bridge = await think_bridge(
            action="thoughts_for_entity",
            session_id=sid,
            entity_name="EntityA",
        )
        assert "Graph context:" in bridge
        assert "Graph companion:" in bridge

        full_context = await think_bridge(
            action="full_context",
            session_id=sid,
            target_id=node_id,
            target_type="thought",
        )
        assert "Graph context:" in full_context

        summary = await think_summarize(session_id=sid)
        assert "Cross-Backend Graph Context" in summary


@pytest.mark.usefixtures("_init_session_manager")
class TestPlanSparklingGrowingOrbit:
    """Covers the G1/G2/G3/G5 improvements from plans/sparkling-growing-orbit."""

    @pytest.mark.anyio
    async def test_long_single_thought_triggers_soft_warning(self):
        essay = "x" * 3000
        result = await think_graph(thought=essay)
        assert "consider action='branch'" in result
        assert "3000 chars" in result

    @pytest.mark.anyio
    async def test_short_thought_has_no_warning(self):
        result = await think_graph(thought="A concise claim about the system.")
        assert "consider action='branch'" not in result

    @pytest.mark.anyio
    async def test_long_thought_in_batch_triggers_warning(self):
        essay = "y" * 2000
        result = await think_graph(
            thoughts=[
                {"thought": "short root"},
                {"thought": essay, "parent_ref": 0},
            ]
        )
        assert "thoughts[1]" in result
        assert "consider action='branch'" in result

    @pytest.mark.anyio
    async def test_long_thought_in_children_triggers_warning(self):
        essay = "z" * 1800
        result = await think_graph(
            thought="Break this apart",
            action="branch",
            children=[
                {"thought": essay},
                {"thought": "short sibling"},
            ],
        )
        assert "children[0]" in result
        assert "consider action='branch'" in result

    @pytest.mark.anyio
    async def test_think_summarize_default_is_index(self):
        await think_graph(thought="Root insight for detail-level test")
        summary = await think_summarize()
        assert "detail=index" in summary

    @pytest.mark.anyio
    async def test_think_summarize_detail_levels_grow(self):
        # Seed a tree with branches long enough to exceed the synopsis-level
        # 200-char preview cap (so full reveals more than synopsis) while
        # staying under the 1500-char long-thought warning threshold.
        long_body = (
            "This branch discusses its angle at length, spanning multiple "
            "sentences so that the 200-character synopsis preview truncates "
            "but the 1200-character full preview does not. Additional filler "
            "text ensures we comfortably exceed the synopsis cap while "
            "remaining under the long-thought advisory threshold so the "
            "warning does not pollute the returned string."
        )
        assert len(long_body) > 200
        assert len(long_body) < 1500
        seed = await think_graph(
            thoughts=[
                {"thought": "Root of the analysis", "action": "branch"},
                {"thought": f"Branch A: {long_body}", "parent_ref": 0},
                {"thought": f"Branch B: {long_body}", "parent_ref": 0},
                {
                    "thought": f"Synthesis: {long_body}",
                    "action": "synthesize",
                    "parent_ref": 0,
                },
            ]
        )
        sid = _extract_value(seed, "Session:")

        index = await think_summarize(session_id=sid, detail_level="index")
        synopsis = await think_summarize(session_id=sid, detail_level="synopsis")
        full = await think_summarize(session_id=sid, detail_level="full")

        assert "detail=index" in index
        assert "detail=synopsis" in synopsis
        assert "detail=full" in full
        # Synopsis should carry more content than the terse index.
        assert len(synopsis) > len(index)
        # Full should strictly exceed synopsis once branches exceed the
        # synopsis preview cap.
        assert len(full) > len(synopsis)

    @pytest.mark.anyio
    async def test_think_summarize_invalid_detail_falls_back_to_index(self):
        await think_graph(thought="Invalid-detail test root")
        summary = await think_summarize(detail_level="nonsense")
        assert "detail=index" in summary

    @pytest.mark.anyio
    async def test_think_model_items_emits_compose_next_hint(self):
        result = await think_model(
            model_name="first_principles",
            items=[
                {
                    "id": "m_hint1",
                    "problem": "Test problem",
                    "steps": ["step 1"],
                    "reasoning": "reasoning",
                    "conclusion": "conclusion",
                }
            ],
        )
        assert "Suggested next: score_evaluate" in result
        assert '"m_hint1"' in result

    @pytest.mark.anyio
    async def test_think_science_items_emits_compose_next_hint(self):
        result = await think_science(
            items=[
                {
                    "id": "s_hint1",
                    "observation": "Observation text",
                    "question": "What causes X?",
                    "hypothesis": {
                        "statement": "X is caused by Y",
                        "variables": [
                            {"name": "Y", "role": "independent"},
                            {"name": "X", "role": "dependent"},
                        ],
                        "assumptions": ["Y is observable"],
                        "confidence": 0.6,
                        "falsifiability": (
                            "If removing Y does not change X, the hypothesis "
                            "is rejected outright."
                        ),
                    },
                }
            ],
        )
        assert "Suggested next: think_evidence" in result

    @pytest.mark.anyio
    async def test_think_monitor_items_emits_compose_next_hint(self):
        result = await think_monitor(
            items=[
                {
                    "id": "mon_hint1",
                    "task": "Assess plan",
                    "knowledge": {
                        "domain": "testing",
                        "level": "proficient",
                        "confidence": 0.7,
                        "limitations": ["small sample"],
                    },
                    "claims": [
                        {
                            "claim": "Tests cover the main path",
                            "status": "inference",
                            "confidence": 0.8,
                            "evidence": "test_think_extensions.py",
                        }
                    ],
                }
            ],
        )
        assert "Suggested next: think_validate" in result

    @pytest.mark.anyio
    async def test_think_argue_chain_emits_compose_next_hint(self):
        result = await think_argue(
            chain=[
                {
                    "argument_type": "thesis",
                    "claim": "The system is fast enough",
                    "premises": ["Latency p99 under budget"],
                    "conclusion": "No latency work needed",
                    "confidence": 0.7,
                },
                {
                    "argument_type": "antithesis",
                    "claim": "The system is not fast enough",
                    "premises": ["Tail latency spikes during failover"],
                    "conclusion": "Latency work is needed",
                    "confidence": 0.6,
                },
            ]
        )
        assert "Suggested next: think_monitor" in result

    @pytest.mark.anyio
    async def test_think_graph_synthesize_emits_compose_next_hint(self):
        seeded = await think_graph(
            thoughts=[
                {"thought": "root", "action": "branch"},
                {"thought": "child A", "parent_ref": 0},
                {"thought": "child B", "parent_ref": 0},
            ]
        )
        sid = _extract_value(seeded, "Session:")
        ids = _extract_value(seeded, "Node IDs:").split(",")
        root_id = ids[0].strip()

        synth = await think_graph(
            session_id=sid,
            thought="Combined conclusion across A and B",
            action="synthesize",
            parent_id=root_id,
        )
        assert "Suggested next: think_monitor" in synth

    @pytest.mark.anyio
    async def test_revise_rejects_empty_thought(self):
        # Regression: with `thought: str = ""` as default, the revise branch
        # must validate non-empty content or it silently blanks the node.
        seeded = await think_graph(thought="Initial claim")
        sid = _extract_value(seeded, "Session:")
        node_id = _extract_value(seeded, "Node:")
        with pytest.raises(ValueError, match="thought content is required"):
            await think_graph(
                session_id=sid,
                action="revise",
                node_id=node_id,
            )
