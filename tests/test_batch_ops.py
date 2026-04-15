"""Tests for batch operations across tools (Phase 1 / M1)."""

from __future__ import annotations

import pytest

from aismartbuddy.tools.graph import (
    graph_create_session,
    graph_focus_summary,
    knowledge_batch,
)
from aismartbuddy.tools.score import score_evaluate, score_rubric


async def _create_graph_session() -> str:
    result = await graph_create_session()
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("session_id:"):
            return line[len("session_id:"):].strip()
    raise AssertionError(f"no session_id in {result!r}")


def _extract_sid_line(result: str) -> str:
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("session_id:"):
            return line[len("session_id:"):].strip()
    raise AssertionError(f"no session_id in {result!r}")


@pytest.mark.usefixtures("_init_session_manager")
class TestKnowledgeBatch:
    @pytest.mark.anyio
    async def test_nodes_only_batch(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "ATP", "entity_type": "concept", "confidence": 0.9},
                {"entity": "Mitochondria", "entity_type": "entity"},
                {"entity": "Glycolysis", "entity_type": "concept"},
            ],
        )
        assert "Nodes added: 3" in result
        assert "Relations added: 0" in result

    @pytest.mark.anyio
    async def test_nodes_plus_relations_batch(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "A"},
                {"entity": "B"},
                {"entity": "C"},
            ],
            relations=[
                {"from_name": "A", "to_name": "B", "relation": "supports"},
                {"from_name": "B", "to_name": "C", "relation": "causes"},
            ],
        )
        assert "Nodes added: 3" in result
        assert "Relations added: 2" in result

    @pytest.mark.anyio
    async def test_open_entity_type_is_accepted(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "Good", "entity_type": "concept"},
                {"entity": "Bad", "entity_type": "mechanism"},
            ],
        )
        assert "Nodes added: 2" in result

    @pytest.mark.anyio
    async def test_hypothesis_entity_type_alias_maps_to_question(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "Persistent Viral Trigger", "entity_type": "hypothesis"},
            ],
        )
        assert "Nodes added: 1" in result

    @pytest.mark.anyio
    async def test_missing_entity_aborts_batch(self):
        sid = await _create_graph_session()
        with pytest.raises(ValueError, match="missing 'entity'"):
            await knowledge_batch(
                session_id=sid,
                nodes=[{"entity_type": "concept"}],
            )

    @pytest.mark.anyio
    async def test_open_relation_is_accepted(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[{"entity": "A"}, {"entity": "B"}],
            relations=[
                {
                    "from_name": "A",
                    "to_name": "B",
                    "relation": "amplifies",
                },
            ],
        )
        assert "Relations added: 1" in result

    @pytest.mark.anyio
    async def test_empty_batch_rejected(self):
        sid = await _create_graph_session()
        with pytest.raises(ValueError, match="at least one"):
            await knowledge_batch(session_id=sid)


def _extract_field(result: str, prefix: str) -> str:
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix):].strip()
    return ""


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreEvaluateFindingBatch:
    """finding_batch applies N findings + emits the forcing-function warning."""

    @pytest.mark.anyio
    async def _setup(self) -> tuple[str, str]:
        rubric_result = await score_rubric(
            action="create",
            rubric_id="r1",
            description="test rubric",
            dimensions=[
                {"id": "correctness", "description": "correct", "weight": 1.0},
                {"id": "clarity", "description": "clear", "weight": 1.0},
            ],
        )
        sid = _extract_field(rubric_result, "Session:")
        start = await score_evaluate(
            action="start", session_id=sid, rubric_id="r1",
            context="testing",
        )
        eid = _extract_field(start, "Eval:")
        return sid, eid

    @pytest.mark.anyio
    async def test_three_findings_in_one_call(self):
        sid, eid = await self._setup()
        result = await score_evaluate(
            action="finding_batch",
            session_id=sid,
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "correctness", "severity": "moderate",
                    "description": "minor issue", "evidence": ["e1"],
                    "recommendation": "fix it",
                },
                {
                    "dimension": "clarity", "severity": "low",
                    "description": "style nit", "evidence": ["e2"],
                    "recommendation": "rename",
                },
                {
                    "dimension": "correctness", "severity": "high",
                    "description": "real bug", "evidence": ["e3"],
                    "recommendation": "fix urgently",
                },
            ],
        )
        assert "Batch: 3 findings applied" in result
        assert "Running scores:" in result
        assert "loses the incremental" in result.lower()

    @pytest.mark.anyio
    async def test_invalid_dimension_aborts_batch(self):
        sid, eid = await self._setup()
        with pytest.raises(ValueError, match="not in rubric"):
            await score_evaluate(
                action="finding_batch",
                session_id=sid,
                evaluation_id=eid,
                findings=[
                    {
                        "dimension": "BOGUS", "severity": "low",
                        "description": "x",
                    },
                ],
            )

    @pytest.mark.anyio
    async def test_empty_findings_rejected(self):
        sid, eid = await self._setup()
        with pytest.raises(ValueError, match="non-empty"):
            await score_evaluate(
                action="finding_batch",
                session_id=sid, evaluation_id=eid, findings=[],
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestUnifiedSession:
    """session_create returns a parent_id usable by every backend's tools."""

    @pytest.mark.anyio
    async def test_three_backend_unified_session(self):
        from aismartbuddy.tools.holon import holon_create
        from aismartbuddy.tools.infra import session_create
        from aismartbuddy.tools.sql import sql_query
        from aismartbuddy.tools.think import think_graph

        result = await session_create(backends=["sql", "graph", "think"])
        parent_id = _extract_sid_line(result)

        # SQL tool routes to sql backend
        sql_r = await sql_query(
            session_id=parent_id,
            query="CREATE TABLE t (id INTEGER);",
        )
        assert sql_r is not None  # Did not raise

        # Graph tool routes to graph backend
        graph_r = await knowledge_batch(
            session_id=parent_id,
            nodes=[{"entity": "X"}],
        )
        assert "Nodes added: 1" in graph_r

        # Think tool routes to think backend
        think_r = await think_graph(thought="hi", session_id=parent_id)
        assert "Status: added" in think_r

        # Holon (think backend) also routes correctly
        holon_r = await holon_create(
            name="Root", description="root", session_id=parent_id,
        )
        assert "Status: created" in holon_r

        assert f"parent_session_id: {parent_id}" in result
        assert "child_session_ids:" in result

    @pytest.mark.anyio
    async def test_missing_backend_raises_actionable_error(self):
        from aismartbuddy.tools.infra import session_create
        from aismartbuddy.tools.sql import sql_query

        # Create parent with only think backend
        result = await session_create(backends=["think"])
        parent_id = _extract_sid_line(result)

        # Calling a SQL tool should raise with actionable hint
        with pytest.raises(ValueError, match="no 'sql' backend"):
            await sql_query(session_id=parent_id, query="SELECT 1;")

    @pytest.mark.anyio
    async def test_backwards_compat_direct_session_id_still_works(self):
        from aismartbuddy.tools.graph import graph_create_session, graph_query

        # Create a single-backend graph session the old way
        gs = await graph_create_session()
        sid = _extract_sid_line(gs)
        # Direct child id still routes correctly
        result = await graph_query(
            session_id=sid,
            query="CREATE NODE TABLE T (id INT64 PRIMARY KEY);",
        )
        assert result is not None

    @pytest.mark.anyio
    async def test_graph_focus_summary_batches_multiple_neighbors(self):
        sid = await _create_graph_session()
        await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "A"},
                {"entity": "B"},
                {"entity": "C"},
            ],
            relations=[
                {"from_name": "A", "to_name": "B", "relation": "supports"},
                {"from_name": "B", "to_name": "C", "relation": "supports"},
            ],
        )
        result = await graph_focus_summary(
            session_id=sid,
            node_names=["A", "B"],
            node_type="KnowledgeNode",
            depth=1,
        )
        assert "## Graph Focus Summary" in result
        assert "### A" in result
        assert "### B" in result


