from __future__ import annotations

import json

import pytest

from aismartbuddy.tools.graph import graph_query
from aismartbuddy.tools.infra import session_create
from aismartbuddy.tools.reasoning_v2 import (
    extract_findings_from_graph,
    extract_findings_from_sql,
    hypothesize,
    iterate,
    reason_get,
    reason_graph,
    reason_index,
    reason_refs,
    reason_trace,
    scaffold,
    self_assess,
    session_resume,
    synthesize_conclusion,
    think_debug,
    workflow_validate,
)
from aismartbuddy.tools.score import score_evaluate, score_rubric
from aismartbuddy.tools.sql import sql_query


def _extract_session_id(result: str) -> str:
    for line in result.splitlines():
        if line.startswith("session_id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"No session_id in {result!r}")


@pytest.mark.usefixtures("_init_session_manager")
class TestV2Reasoning:
    @pytest.mark.anyio
    async def test_session_create_with_mode_and_resume(self):
        result = await session_create(
            backends=["think", "graph", "sql"], mode="analyze", enforcement="strict"
        )
        sid = _extract_session_id(result)
        resumed = json.loads(await session_resume(sid))
        assert resumed["session"]["mode"] == "analyze"
        assert resumed["session"]["enforcement"] == "strict"
        assert sorted(resumed["session"]["backends"]) == ["graph", "sql", "think"]

    @pytest.mark.anyio
    async def test_scaffold_hypothesize_trace_and_synthesis(self):
        result = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(result)
        scaffold_result = await scaffold(
            model_name="first_principles",
            session_id=sid,
            items=[
                {
                    "id": "rna_1",
                    "problem": "Explain why pathway A matters.",
                    "steps": ["separate signal from noise"],
                    "reasoning": "Pathway A appears in the strongest signals and is upstream.",
                    "conclusion": "Pathway A is a plausible driver.",
                }
            ],
        )
        assert "Status: scaffolded" in scaffold_result
        hypo_result = await hypothesize(
            session_id=sid,
            items=[
                {
                    "id": "hyp_1",
                    "observation": "Marker X is elevated.",
                    "question": "What could cause this elevation?",
                    "hypothesis": "Inflammatory signaling is elevating marker X.",
                    "mechanism": "Cytokine cascade activates the measured pathway.",
                    "variables": [{"name": "marker_x", "role": "dependent"}],
                    "assumptions": ["The assay is valid."],
                    "falsifiability": (
                        "If the inflammatory pathway is blocked and marker X "
                        "stays high, the hypothesis is weakened."
                    ),
                    "expected_signals": ["other inflammatory markers increase"],
                    "connects_to": ["rna_1"],
                }
            ],
        )
        assert "Status: hypothesized" in hypo_result
        trace_result = await reason_trace(
            session_id=sid,
            target_ref="hyp_1",
            supporting_refs=["rna_1", "hyp_1"],
            reasoning_steps=["rna_1 established relevance", "hyp_1 proposed mechanism"],
        )
        assert "Status: traced" in trace_result
        synth_result = await synthesize_conclusion(
            session_id=sid,
            items=[
                {
                    "id": "syn_1",
                    "conclusion": (
                        "The inflammatory explanation is currently the best grounded explanation."
                    ),
                    "supporting_refs": ["rna_1", "hyp_1"],
                    "reason_trace_ref": trace_result.split("Trace: ", 1)[1].split(" | ", 1)[0],
                }
            ],
        )
        assert "Status: synthesized" in synth_result

    @pytest.mark.anyio
    async def test_reason_retrieval_tools(self):
        scaffold_result = await scaffold(
            model_name="design_review",
            items=[
                {
                    "id": "design_1",
                    "problem": "Review API design",
                    "steps": ["inspect state handling"],
                    "reasoning": "The API mixes transport and orchestration concerns.",
                    "conclusion": "Split orchestration from transport.",
                }
            ],
        )
        sid = scaffold_result.split("Session: ", 1)[1].split(" | ", 1)[0]
        index_payload = json.loads(await reason_index(sid))
        assert index_payload["count"] >= 1
        artifact_id = index_payload["items"][0]["id"]
        get_payload = json.loads(await reason_get(sid, artifact_id))
        assert get_payload["artifact"]["id"] == artifact_id
        refs_payload = json.loads(await reason_refs(sid, artifact_id))
        assert refs_payload["artifact_id"] == artifact_id

    @pytest.mark.anyio
    async def test_iterate_and_debug_items(self):
        session = await session_create(backends=["think"], mode="iterate")
        sid = _extract_session_id(session)
        iterate_result = await iterate(
            session_id=sid,
            goal="Improve win rate",
            items=[
                {
                    "approach": "v1",
                    "result": "0.51",
                    "learning": "need better filter",
                    "metric_name": "win_rate",
                    "metric_value": 0.51,
                },
                {
                    "approach": "v2",
                    "result": "0.55",
                    "learning": "better",
                    "metric_name": "win_rate",
                    "metric_value": 0.55,
                },
            ],
        )
        assert '"is_improvement":true' in iterate_result.lower()
        debug_result = await think_debug(
            session_id=sid,
            items=[
                {
                    "id": "dbg_1",
                    "issue": "regression in auth refresh",
                    "approach": "binary_search",
                    "steps": ["bisect commits"],
                    "findings": "regression introduced after token cache change",
                    "resolution": "revert token cache change",
                }
            ],
        )
        assert "Status: debugged" in debug_result

    @pytest.mark.anyio
    async def test_score_batch_and_workflow_validate(self):
        scaffold_result = await scaffold(
            model_name="pre_mortem",
            items=[
                {
                    "id": "risk_1",
                    "problem": "What could fail?",
                    "steps": ["inspect edge cases"],
                    "reasoning": "Concurrency is untested.",
                    "conclusion": "Concurrency risk is material.",
                }
            ],
        )
        sid = scaffold_result.split("Session: ", 1)[1].split(" | ", 1)[0]
        await score_rubric(
            action="create",
            session_id=sid,
            rubric_id="quality",
            dimensions=[{"id": "logic", "weight": 1.0, "required": True}],
        )
        start = await score_evaluate(
            action="start", session_id=sid, rubric_id="quality", context="analysis"
        )
        eid = start.split("Eval: ", 1)[1].split("\n", 1)[0].strip()
        batch = await score_evaluate(
            action="finding_batch",
            session_id=sid,
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "logic",
                    "severity": "moderate",
                    "description": "Missing concurrency tests",
                },
                {
                    "dimension": "logic",
                    "severity": "low",
                    "description": "Edge-case branch undocumented",
                },
            ],
        )
        assert '"finding_id"' in batch
        validation = json.loads(await workflow_validate(sid))
        assert "coverage" in validation

    @pytest.mark.anyio
    async def test_extract_findings_from_sql(self):
        session = await session_create(backends=["think", "sql"], mode="analyze")
        sid = _extract_session_id(session)
        await sql_query(session_id=sid, query="CREATE TABLE sales (id INTEGER, amount DOUBLE);")
        await sql_query(session_id=sid, query="INSERT INTO sales VALUES (1, 10.0), (2, 20.0);")
        extracted = await extract_findings_from_sql(
            session_id=sid,
            query="SELECT * FROM sales ORDER BY id",
            finding_kind="sales_row",
        )
        assert "Status: extracted" in extracted

    @pytest.mark.anyio
    async def test_extract_findings_from_graph(self):
        session = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(session)
        await graph_query(
            session_id=sid,
            query="CREATE NODE TABLE Signal (id INT64 PRIMARY KEY, name STRING);",
        )
        await graph_query(
            session_id=sid,
            query=(
                "CREATE (:Signal {id: 1, name: 'A'}); "
                "CREATE (:Signal {id: 2, name: 'B'});"
            ),
        )
        extracted = await extract_findings_from_graph(
            session_id=sid,
            query="MATCH (s:Signal) RETURN s.id AS id, s.name AS name ORDER BY id;",
            finding_kind="signal_row",
        )
        assert "Status: extracted" in extracted

    @pytest.mark.anyio
    async def test_reason_graph_node_limit_and_self_assess(self):
        session = await session_create(backends=["think"], mode="analyze", max_node_chars=500)
        sid = _extract_session_id(session)
        await self_assess(
            session_id=sid,
            items=[
                {
                    "id": "sa_1",
                    "task": "Assess current knowledge",
                    "knowledge_level": "familiar",
                    "known_knowns": ["dataset columns"],
                    "known_unknowns": ["causal direction"],
                    "limitations": ["no intervention data"],
                    "confidence": 0.5,
                    "recommended_next_step": "scaffold",
                }
            ],
        )
        with pytest.raises(ValueError):
            await reason_graph(session_id=sid, thought="x" * 501)

    @pytest.mark.anyio
    async def test_auto_graph_materializes_batched_nodes_and_edges(self):
        session = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract_session_id(session)
        result = await scaffold(
            model_name="first_principles",
            session_id=sid,
            items=[
                {
                    "id": "root_1",
                    "problem": "Root problem",
                    "steps": ["frame"],
                    "reasoning": "Primary context.",
                    "conclusion": "Start here.",
                },
                {
                    "id": "child_1",
                    "problem": "Child problem",
                    "steps": ["connect"],
                    "reasoning": "Depends on root.",
                    "conclusion": "Follow root.",
                    "connects_to": ["root_1"],
                },
            ],
        )
        assert "Graph:" in result

        node_rows = await graph_query(
            session_id=sid,
            query="MATCH (k:KnowledgeNode) RETURN k.name AS name ORDER BY name;",
        )
        edge_rows = await graph_query(
            session_id=sid,
            query=(
                "MATCH (a:KnowledgeNode)-[r:DerivedFrom]->(b:KnowledgeNode) "
                "RETURN a.name AS src, b.name AS dst ORDER BY src, dst;"
            ),
        )
        assert "child_1" in node_rows
        assert "root_1" in node_rows
        assert "child_1,root_1" in edge_rows.replace('"', "")

    @pytest.mark.anyio
    async def test_large_session_retrieval_paths(self):
        session = await session_create(backends=["think"], mode="analyze")
        sid = _extract_session_id(session)

        await scaffold(
            model_name="first_principles",
            session_id=sid,
            items=[
                {
                    "id": "anchor",
                    "problem": "Anchor problem",
                    "steps": ["seed"],
                    "reasoning": "Creates a common reference target.",
                    "conclusion": "Anchor artifact.",
                }
            ],
        )

        for batch_start in range(0, 1200, 200):
            await scaffold(
                model_name="design_review",
                session_id=sid,
                items=[
                    {
                        "id": f"bulk_{i}",
                        "problem": f"Problem {i}",
                        "steps": ["inspect"],
                        "reasoning": f"Reasoning {i}",
                        "conclusion": f"Conclusion {i}",
                        "connects_to": ["anchor"] if i % 3 == 0 else [],
                    }
                    for i in range(batch_start, batch_start + 200)
                ],
            )

        index_payload = json.loads(await reason_index(sid, kind="scaffold", limit=5))
        refs_payload = json.loads(await reason_refs(sid, "anchor"))
        resume_payload = json.loads(await session_resume(sid))
        workflow_payload = json.loads(await workflow_validate(sid))

        assert index_payload["count"] >= 1201
        assert len(index_payload["items"]) == 5
        assert refs_payload["count"] >= 400
        assert "artifact_summary" in resume_payload
        assert "coverage" in workflow_payload
