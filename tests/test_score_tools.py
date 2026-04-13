"""Tests for scoring/evaluation tools."""

from __future__ import annotations

import pytest

from aismartbuddy.session import SessionManager
from aismartbuddy.tools.score import (
    score_evaluate,
    score_gate,
    score_rubric,
)


def _extract(result: str, prefix: str) -> str:
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix):].strip()
    return ""


# ── Rubric tests ─────────────────────────────────────────────

PLAN_REVIEW_DIMS = [
    {"id": "feasibility", "description": "Can it be built?",
     "weight": 2.0, "required": True},
    {"id": "completeness", "description": "All steps covered?",
     "weight": 1.5, "required": True},
    {"id": "correctness", "description": "Will it work?",
     "weight": 1.5, "required": True},
    {"id": "integration", "description": "Modules connected?",
     "weight": 1.0, "required": False},
]


@pytest.fixture
def _init_session_manager(session_manager: SessionManager):
    import aismartbuddy.session as session_mod

    session_mod.session_manager = session_manager
    yield
    session_mod.session_manager = None


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreRubric:
    @pytest.mark.anyio
    async def test_create_rubric(self):
        r = await score_rubric(
            action="create",
            rubric_id="plan-review",
            description="Validates plans",
            dimensions=PLAN_REVIEW_DIMS,
        )
        assert "Rubric: plan-review" in r
        assert "Dimensions: 4 (3 required)" in r
        assert "Threshold: 9.0/10" in r
        assert "Status: created" in r

    @pytest.mark.anyio
    async def test_list_rubrics(self):
        r1 = await score_rubric(
            action="create", rubric_id="test",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        r = await score_rubric(action="list", session_id=sid)
        assert "Rubrics (1)" in r
        assert "test" in r

    @pytest.mark.anyio
    async def test_invalid_strategy(self):
        with pytest.raises(ValueError, match="Invalid scoring_strategy"):
            await score_rubric(
                action="create", rubric_id="bad",
                dimensions=[{"id": "d1", "weight": 1.0}],
                scoring_strategy="magic",
            )

    @pytest.mark.anyio
    async def test_missing_dimension_fields(self):
        with pytest.raises(ValueError, match="must have"):
            await score_rubric(
                action="create", rubric_id="bad",
                dimensions=[{"description": "no id or weight"}],
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreEvaluate:
    async def _setup_rubric(self) -> tuple[str, str]:
        """Create rubric and return (session_id, rubric_id)."""
        r = await score_rubric(
            action="create",
            rubric_id="test-rubric",
            dimensions=PLAN_REVIEW_DIMS,
        )
        return _extract(r, "Session:"), "test-rubric"

    @pytest.mark.anyio
    async def test_start_evaluation(self):
        sid, rid = await self._setup_rubric()
        r = await score_evaluate(
            action="start", session_id=sid,
            rubric_id=rid, context="Test plan v1",
        )
        assert "Eval:" in r
        assert "Status: active" in r
        assert "10/10" in r

    @pytest.mark.anyio
    async def test_finding_drops_score(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        r2 = await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="completeness", severity="high",
            description="Missing Sentry integration step",
        )
        assert "Finding:" in r2
        assert "completeness (high)" in r2
        # Score should have dropped from 10
        assert "Running score:" in r2
        # completeness should show a reduced score
        assert "completeness=8" in r2

    @pytest.mark.anyio
    async def test_critical_required_auto_fail(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="feasibility", severity="critical",
            description="Requires unavailable API",
        )
        # Finalize — should fail due to auto_fail
        r = await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
            dimensions_reviewed=[
                "completeness", "correctness", "integration",
            ],
        )
        assert "FAIL" in r

    @pytest.mark.anyio
    async def test_blocking_finding(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        r2 = await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="correctness", severity="low",
            blocking=True,
            description="Blocks: data migration order wrong",
        )
        assert "Blocking: True" in r2

    @pytest.mark.anyio
    async def test_finalize_missing_required_dimension(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        # Only submit finding on one dimension — skip required ones
        await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="integration", severity="low",
            description="Minor style issue",
        )
        # Finalize without reviewing required dimensions
        r = await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
        )
        assert "CANNOT FINALIZE" in r
        assert "required dimensions not reviewed" in r

    @pytest.mark.anyio
    async def test_finalize_passes_with_all_required(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        # Submit one low finding
        await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="integration", severity="low",
            description="Minor issue",
        )
        # Finalize with all required marked as reviewed
        r = await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
            dimensions_reviewed=[
                "feasibility", "completeness", "correctness",
            ],
        )
        assert "PASS" in r
        assert "Final score:" in r

    @pytest.mark.anyio
    async def test_finding_on_finalized_eval_rejected(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
            dimensions_reviewed=[
                "feasibility", "completeness", "correctness",
            ],
        )
        with pytest.raises(ValueError, match="not active"):
            await score_evaluate(
                action="finding", session_id=sid, evaluation_id=eid,
                dimension="completeness", severity="low",
                description="Too late",
            )

    @pytest.mark.anyio
    async def test_invalid_dimension(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start", session_id=sid, rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        with pytest.raises(ValueError, match="not in rubric"):
            await score_evaluate(
                action="finding", session_id=sid, evaluation_id=eid,
                dimension="nonexistent", severity="low",
                description="bad dim",
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreGate:
    @pytest.mark.anyio
    async def test_gate_passing(self):
        r1 = await score_rubric(
            action="create", rubric_id="r1",
            dimensions=[
                {"id": "d1", "weight": 1.0, "required": True},
            ],
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start", session_id=sid, rubric_id="r1",
        )
        eid = _extract(r2, "Eval:")
        await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
            dimensions_reviewed=["d1"],
        )
        r = await score_gate(
            action="gate", session_id=sid, evaluation_id=eid,
        )
        assert "Pass: true" in r
        assert "finalized" in r

    @pytest.mark.anyio
    async def test_gate_active_eval(self):
        r1 = await score_rubric(
            action="create", rubric_id="r1",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start", session_id=sid, rubric_id="r1",
        )
        eid = _extract(r2, "Eval:")
        r = await score_gate(
            action="gate", session_id=sid, evaluation_id=eid,
        )
        assert "Pass: ?" in r
        assert "active" in r

    @pytest.mark.anyio
    async def test_list_evaluations(self):
        r1 = await score_rubric(
            action="create", rubric_id="r1",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start", session_id=sid, rubric_id="r1",
        )
        eid = _extract(r2, "Eval:")
        await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
        )
        r = await score_gate(
            action="list", session_id=sid,
        )
        assert "Evaluations (1)" in r


@pytest.mark.usefixtures("_init_session_manager")
class TestScoringStrategies:
    @pytest.mark.anyio
    async def test_minimum_floor_caps_score(self):
        """Required dimension tanked should cap the total."""
        r1 = await score_rubric(
            action="create", rubric_id="floor-test",
            dimensions=[
                {"id": "required_dim", "weight": 1.0, "required": True},
                {"id": "good_dim", "weight": 1.0, "required": False},
            ],
            scoring_strategy="minimum_floor",
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start", session_id=sid, rubric_id="floor-test",
        )
        eid = _extract(r2, "Eval:")
        # Tank the required dimension with 3 high findings
        for _ in range(3):
            await score_evaluate(
                action="finding", session_id=sid, evaluation_id=eid,
                dimension="required_dim", severity="high",
                description="Issue",
            )
        r = await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
            dimensions_reviewed=["good_dim"],
        )
        # good_dim is still 10, required_dim is 4
        # minimum_floor caps at min(required) = 4
        assert "FAIL" in r
        # Final score should be 4.0 (capped by floor), not 7.0 (average)
        assert "4.0/10" in r


@pytest.mark.usefixtures("_init_session_manager")
class TestEndToEnd:
    @pytest.mark.anyio
    async def test_full_plan_review_flow(self):
        """Complete flow: rubric → start → findings → finalize → gate."""
        # Create rubric
        r1 = await score_rubric(
            action="create",
            rubric_id="plan-review",
            description="Validates implementation plans",
            dimensions=PLAN_REVIEW_DIMS,
        )
        sid = _extract(r1, "Session:")

        # Start evaluation
        r2 = await score_evaluate(
            action="start", session_id=sid,
            rubric_id="plan-review",
            context="Holonic tools implementation plan",
        )
        eid = _extract(r2, "Eval:")

        # Finding 1: completeness issue (high)
        r3 = await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="completeness", severity="high",
            description="Missing error handling for multi-membership edge case",
            evidence=["plan.md:45-50"],
            recommendation="Add explicit error handling step",
        )
        assert "below_threshold" in r3 or "above_threshold" in r3

        # Finding 2: integration issue (moderate)
        r4 = await score_evaluate(
            action="finding", session_id=sid, evaluation_id=eid,
            dimension="integration", severity="moderate",
            description="No mention of updating guide prompt",
        )
        assert "Running score:" in r4

        # Finalize
        r5 = await score_evaluate(
            action="finalize", session_id=sid, evaluation_id=eid,
            summary="Plan is mostly complete but has gaps",
            dimensions_reviewed=["feasibility", "correctness"],
        )
        assert "Final score:" in r5
        assert "Findings: 2" in r5
        assert "completeness:" in r5
        assert "integration:" in r5

        # Gate check
        r6 = await score_gate(
            action="gate", session_id=sid, evaluation_id=eid,
        )
        assert "finalized" in r6

        # List evaluations
        r7 = await score_gate(
            action="list", session_id=sid, rubric_id="plan-review",
        )
        assert "Evaluations (1)" in r7
