from __future__ import annotations

import pytest

from aismartbuddy.engines.thinking_engine import ThinkingEngine
from aismartbuddy.tools import get_session_manager
from aismartbuddy.tools.graph import (
    graph_create_session,
    graph_knowledge_add,
    graph_knowledge_relate,
    knowledge_batch,
)
from aismartbuddy.tools.infra import session_create
from aismartbuddy.tools.meta import suggest_reasoning
from aismartbuddy.tools.reasoning_v2 import extract_findings_from_sql
from aismartbuddy.tools.sql import sql_query
from aismartbuddy.tools.think import (
    think_bridge,
    think_create_session,
    think_hypothesis,
    think_model,
    think_monitor,
    think_summarize,
)


def _value(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split(prefix, 1)[1].strip().split(" | ", 1)[0]
    raise AssertionError(f"Missing {prefix!r} in {text}")


@pytest.mark.usefixtures("_init_session_manager")
class TestThinkingQualityViews:
    @pytest.mark.anyio
    async def test_audit_reports_epistemic_gaps(self):
        monitor = await think_monitor(
            monitoring_id="audit_source",
            task="Assess an unsupported conclusion",
            claims=[{"claim": "The change is safe", "status": "fact", "confidence": 0.95}],
        )
        sid = _value(monitor, "Session:")
        await think_hypothesis(
            action="register",
            session_id=sid,
            hypothesis_id="untested_hypothesis",
            statement="A hidden dependency causes the failure",
        )

        audit = await think_monitor(action="audit_session", session_id=sid)
        assert "unsupported_claims: 1" in audit
        assert "overconfident_claims: 1" in audit
        assert "untested_hypotheses: 1" in audit

        bridge = await think_bridge(action="integrity", session_id=sid)
        assert "Epistemic audit" in bridge
        assert "untested_hypothesis" in bridge

    @pytest.mark.anyio
    async def test_handoff_contains_route_progress_and_honors_budget(self):
        first = await think_model(
            model_name="root_cause",
            items=[
                {
                    "id": "handoff_model",
                    "problem": "A release repeatedly fails",
                    "steps": ["Separate pipeline and environment causes"],
                    "reasoning": "The failure is visible before deployment.",
                    "conclusion": "Test competing causes independently.",
                }
            ],
        )
        sid = _value(first, "Session:")
        await suggest_reasoning(
            "Diagnose repeated release failures",
            session_id=sid,
            intent="solve_problem",
            constraints=["Do not reduce test coverage"],
        )
        await think_model(
            model_name="root_cause",
            session_id=sid,
            items=[
                {
                    "id": "handoff_model_2",
                    "problem": "A release repeatedly fails",
                    "steps": ["Test the first cause"],
                    "reasoning": "Pipeline evidence is independently observable.",
                    "conclusion": "Compare competing hypotheses next.",
                }
            ],
        )

        handoff = await think_summarize(
            session_id=sid,
            detail_level="handoff",
            max_chars=2_500,
        )
        assert len(handoff) <= 2_500
        assert "## Handoff" in handoff
        assert "Intent: solve_problem" in handoff
        assert "Next tool: think_hypothesis" in handoff
        assert "Quality Gaps" in handoff

    @pytest.mark.anyio
    async def test_bridge_can_audit_multiple_sessions(self):
        first_session = await think_create_session()
        sid_one = _value(first_session, "session_id:")
        first = await think_monitor(
            session_id=sid_one,
            monitoring_id="one",
            task="First",
            claims=[{"claim": "One", "status": "fact", "confidence": 0.9}],
        )
        assert _value(first, "Session:") == sid_one
        second_session = await think_create_session()
        sid_two = _value(second_session, "session_id:")
        second = await think_monitor(
            session_id=sid_two,
            monitoring_id="two",
            task="Second",
            claims=[{"claim": "Two", "status": "fact", "confidence": 0.9}],
        )
        assert _value(second, "Session:") == sid_two
        result = await think_bridge(
            action="integrity",
            session_id=sid_one,
            session_ids=[sid_two],
            max_chars=3_000,
        )
        assert f"## Session {sid_one}" in result
        assert f"## Session {sid_two}" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestKnowledgeIntegrity:
    @pytest.mark.anyio
    async def test_relationship_reports_zero_when_endpoint_is_missing(self):
        created = await graph_create_session()
        sid = _value(created, "session_id:")
        await graph_knowledge_add(session_id=sid, entity="present")
        result = await graph_knowledge_relate(
            session_id=sid,
            from_name="present",
            to_name="missing",
            relation="supports",
        )
        assert "Matched endpoints: from=1 to=0" in result
        assert "Relationships created: 0" in result

    @pytest.mark.anyio
    async def test_batch_reference_validation_happens_before_writes(self):
        created = await graph_create_session()
        sid = _value(created, "session_id:")
        with pytest.raises(ValueError, match="missing endpoints: absent"):
            await knowledge_batch(
                session_id=sid,
                nodes=[{"entity": "new-node"}],
                relations=[
                    {
                        "from_name": "new-node",
                        "to_name": "absent",
                        "relation": "supports",
                    }
                ],
                validate_refs=True,
            )
        result = await knowledge_batch(session_id=sid, nodes=[{"entity": "after-failure"}])
        assert "Nodes added: 1" in result

    @pytest.mark.anyio
    async def test_auto_graph_reports_skipped_references(self):
        session = await session_create(backends=["think", "graph"])
        sid = _value(session, "session_id:")
        result = await think_model(
            model_name="first_principles",
            session_id=sid,
            auto_graph=True,
            items=[
                {
                    "id": "graph_item",
                    "problem": "Find fundamentals",
                    "steps": ["List assumptions"],
                    "reasoning": "One reference is external.",
                    "conclusion": "Continue after checking it.",
                    "connects_to": ["missing_target"],
                }
            ],
        )
        assert "skipped refs: 1" in result

    @pytest.mark.anyio
    async def test_extracted_findings_retain_query_provenance(self):
        session = await session_create(backends=["think", "sql"])
        sid = _value(session, "session_id:")
        await sql_query(query="CREATE TABLE facts(value INTEGER);", session_id=sid)
        await sql_query(query="INSERT INTO facts VALUES (7);", session_id=sid)
        extracted = await extract_findings_from_sql(sid, "SELECT value FROM facts;")
        artifact_id = _value(extracted, "Item IDs:").split(",", 1)[0]
        info = get_session_manager().resolve_backend_session(sid, "think")
        assert isinstance(info.engine, ThinkingEngine)
        artifact = info.engine.get_artifact(artifact_id)
        assert artifact is not None
        assert artifact.provenance == {
            "backend": "sql",
            "query": "SELECT value FROM facts;",
        }
