"""Tests for scoring/evaluation tools."""

from __future__ import annotations

import pytest

from aismartbuddy.tools.graph import graph_query
from aismartbuddy.tools.infra import session_create
from aismartbuddy.tools.refs import think_refs_query
from aismartbuddy.tools.score import (
    rubric_templates,
    score_evaluate,
    score_gate,
    score_rubric,
)
from aismartbuddy.tools.think import think_create_session, think_model, think_rules, think_validate


def _extract(result: str, prefix: str) -> str:
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix) :].strip()
    return ""


# ── Rubric tests ─────────────────────────────────────────────

PLAN_REVIEW_DIMS = [
    {"id": "feasibility", "description": "Can it be built?", "weight": 2.0, "required": True},
    {"id": "completeness", "description": "All steps covered?", "weight": 1.5, "required": True},
    {"id": "correctness", "description": "Will it work?", "weight": 1.5, "required": True},
    {"id": "integration", "description": "Modules connected?", "weight": 1.0, "required": False},
]


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
            action="create",
            rubric_id="test",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        r = await score_rubric(action="list", session_id=sid)
        assert "Rubrics (1)" in r
        assert "test" in r

    @pytest.mark.anyio
    async def test_update_rubric(self):
        created = await score_rubric(
            action="create",
            rubric_id="test-update",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(created, "Session:")
        updated = await score_rubric(
            action="update",
            session_id=sid,
            rubric_id="test-update",
            dimensions=[
                {"id": "d1", "weight": 1.0},
                {"id": "d2", "weight": 0.5},
            ],
        )
        assert "Status: updated" in updated
        assert "Dimensions: 2" in updated

    @pytest.mark.anyio
    async def test_invalid_strategy(self):
        with pytest.raises(ValueError, match="Invalid scoring_strategy"):
            await score_rubric(
                action="create",
                rubric_id="bad",
                dimensions=[{"id": "d1", "weight": 1.0}],
                scoring_strategy="magic",
            )

    @pytest.mark.anyio
    async def test_missing_dimension_fields(self):
        with pytest.raises(ValueError, match="must have"):
            await score_rubric(
                action="create",
                rubric_id="bad",
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
            action="start",
            session_id=sid,
            rubric_id=rid,
            context="Test plan v1",
        )
        assert "Eval:" in r
        assert "Status: active" in r
        assert "10/10" in r

    @pytest.mark.anyio
    async def test_start_with_rubric_creates_and_starts(self):
        r = await score_evaluate(
            action="start_with_rubric",
            session_id=None,
            rubric_id="combo-rubric",
            rubric_description="Combined start",
            dimensions=PLAN_REVIEW_DIMS,
            context="Combined path",
        )
        assert "Eval:" in r
        assert "Status: active" in r

    @pytest.mark.anyio
    async def test_finding_drops_score(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        r2 = await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="completeness",
            severity="high",
            description="Missing Sentry integration step",
        )
        assert "Finding:" in r2
        assert "completeness (high)" in r2
        # Score should have dropped from 10
        assert "Running score:" in r2
        # completeness should show a reduced score
        assert "completeness=8" in r2

    @pytest.mark.anyio
    async def test_finding_works_with_evaluation_id_only(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(r1, "Eval:")
        r2 = await score_evaluate(
            action="finding",
            evaluation_id=eid,
            dimension="correctness",
            severity="moderate",
            description="Evidence chain incomplete",
        )
        assert f"Eval: {eid}" in r2
        assert "correctness (moderate)" in r2

    @pytest.mark.anyio
    async def test_critical_required_auto_fail(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="feasibility",
            severity="critical",
            description="Requires unavailable API",
        )
        # Finalize — should fail due to auto_fail
        r = await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
            dimensions_reviewed=[
                "completeness",
                "correctness",
                "integration",
            ],
        )
        assert "FAIL" in r

    @pytest.mark.anyio
    async def test_blocking_finding(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        r2 = await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="correctness",
            severity="low",
            blocking=True,
            description="Blocks: data migration order wrong",
        )
        assert "Blocking: True" in r2

    @pytest.mark.anyio
    async def test_finalize_missing_required_dimension(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        # Only submit finding on one dimension — skip required ones
        await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="integration",
            severity="low",
            description="Minor style issue",
        )
        # Finalize without reviewing required dimensions
        r = await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
        )
        assert "CANNOT FINALIZE" in r
        assert "required dimensions not reviewed" in r

    @pytest.mark.anyio
    async def test_finalize_passes_with_all_required(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        # Submit one low finding
        await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="integration",
            severity="low",
            description="Minor issue",
        )
        # Finalize with all required marked as reviewed
        r = await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
            dimensions_reviewed=[
                "feasibility",
                "completeness",
                "correctness",
            ],
        )
        assert "PASS" in r
        assert "Final score:" in r

    @pytest.mark.anyio
    async def test_finding_on_finalized_eval_rejected(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
            dimensions_reviewed=[
                "feasibility",
                "completeness",
                "correctness",
            ],
        )
        with pytest.raises(ValueError, match="not active"):
            await score_evaluate(
                action="finding",
                session_id=sid,
                evaluation_id=eid,
                dimension="completeness",
                severity="low",
                description="Too late",
            )

    @pytest.mark.anyio
    async def test_invalid_dimension(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
        )
        eid = _extract(r1, "Eval:")
        with pytest.raises(ValueError, match="not in rubric"):
            await score_evaluate(
                action="finding",
                session_id=sid,
                evaluation_id=eid,
                dimension="nonexistent",
                severity="low",
                description="bad dim",
            )

    @pytest.mark.anyio
    async def test_review_shows_coverage_and_recent_ids(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(r1, "Eval:")
        await score_evaluate(
            action="finding",
            evaluation_id=eid,
            dimension="integration",
            severity="low",
            description="Minor integration issue",
        )
        review = await score_evaluate(action="review", evaluation_id=eid)
        assert "Covered dimensions:" in review
        assert "Uncovered dimensions:" in review
        assert "Recent finding IDs:" in review

    @pytest.mark.anyio
    async def test_batch_findings_and_alias_work(self):
        sid, rid = await self._setup_rubric()
        r1 = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(r1, "Eval:")
        batch = await score_evaluate(
            action="batch_findings",
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "feasibility",
                    "severity": "moderate",
                    "description": "Issue 1",
                },
                {
                    "dimension": "integration",
                    "severity": "low",
                    "description": "Issue 2",
                },
            ],
        )
        assert "Batch: 2 findings applied" in batch
        # Verbosity trim (Section 7): evaluation_id echo and Running scores
        # arrow chain are removed from batch_findings response. Per-finding
        # running_score lives in the Results JSON instead.
        assert "evaluation_id:" not in batch
        assert "Running scores:" not in batch
        assert "running_score" in batch  # in the Results: [...] JSON
        alias = await score_evaluate(
            action="finding_batch",
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "correctness",
                    "severity": "low",
                    "description": "Issue 3",
                }
            ],
        )
        assert "Batch: 1 findings applied" in alias

    @pytest.mark.anyio
    async def test_use_latest_resolves_when_unambiguous(self):
        sid, rid = await self._setup_rubric()
        await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        review = await score_evaluate(action="review", session_id=sid, use_latest=True)
        assert "Running score:" in review

    @pytest.mark.anyio
    async def test_use_latest_errors_when_ambiguous(self):
        sid, rid = await self._setup_rubric()
        await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        with pytest.raises(ValueError, match="No active evaluation found|ambiguous|Multiple"):
            await score_evaluate(action="review", use_latest=True)

    @pytest.mark.anyio
    async def test_analysis_refs_are_queryable(self):
        sid, rid = await self._setup_rubric()
        await think_model(
            session_id=sid,
            model_name="assumptions_xray",
            items=[
                {
                    "id": "claim_a",
                    "problem": "Check measurement boundary",
                    "steps": ["separate measured signal from mechanism"],
                    "reasoning": "Whole-blood transcriptomics is indirect for tissue-level claims.",
                    "conclusion": "Treat tissue claims as weak.",
                }
            ],
        )
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        await score_evaluate(
            action="finding",
            evaluation_id=eid,
            dimension="correctness",
            severity="moderate",
            description="Mechanistic overreach",
            analysis_refs=["claim_a"],
        )
        refs = await think_refs_query(entity_id="claim_a", session_id=sid)
        assert eid in refs

    @pytest.mark.anyio
    async def test_note_action_creates_lightweight_stub(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        note = await score_evaluate(
            action="note",
            evaluation_id=eid,
            dimension="feasibility",
            severity="low",
            description="Potential issue to revisit",
        )
        assert "Kind: note" in note

    @pytest.mark.anyio
    async def test_score_outputs_keep_decimal_precision_and_explicit_ids(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        assert f"evaluation_id: {eid}" in start

        finding = await score_evaluate(
            action="finding",
            evaluation_id=eid,
            dimension="feasibility",
            severity="low",
            description="Minor concern",
        )
        assert "feasibility=9.5" in finding
        assert f"evaluation_id: {eid}" in finding

        final = await score_evaluate(
            action="finalize",
            evaluation_id=eid,
            dimensions_reviewed=["completeness", "correctness"],
        )
        assert f"evaluation_id: {eid}" in final
        assert "feasibility: 9.5/10" in final

    @pytest.mark.anyio
    async def test_finalize_uses_bound_rule_profiles_and_hard_failures(self):
        sid, rid = await self._setup_rubric()
        await think_rules(
            action="create_profile",
            session_id=sid,
            profile_id="eval-rules",
            name="Evaluation Rules",
        )
        await think_rules(
            action="add_rules_batch",
            session_id=sid,
            profile_id="eval-rules",
            rules=[
                {
                    "id": "must-cover-threats",
                    "text": "Threat model coverage is mandatory",
                    "weight": 5.0,
                    "kind": "hard",
                }
            ],
        )
        start = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id=rid,
            rule_profile_ids=["eval-rules"],
        )
        eid = _extract(start, "Eval:")
        await think_validate(
            session_id=sid,
            subject_id=eid,
            subject_kind="evaluation",
            assessments=[
                {
                    "rule_id": "must-cover-threats",
                    "status": "violates",
                    "note": "Threat model section missing",
                }
            ],
            use_bound_profiles=True,
        )
        final = await score_evaluate(
            action="finalize",
            evaluation_id=eid,
            dimensions_reviewed=["feasibility", "completeness", "correctness"],
            use_bound_profiles=True,
        )
        assert "Pass: FAIL" in final
        assert "Rule validation:" in final
        assert "Hard failures: must-cover-threats" in final


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreGate:
    @pytest.mark.anyio
    async def test_gate_passing(self):
        r1 = await score_rubric(
            action="create",
            rubric_id="r1",
            dimensions=[
                {"id": "d1", "weight": 1.0, "required": True},
            ],
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id="r1",
        )
        eid = _extract(r2, "Eval:")
        await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
            dimensions_reviewed=["d1"],
        )
        r = await score_gate(
            action="gate",
            evaluation_id=eid,
        )
        assert "Pass: true" in r
        assert "finalized" in r

    @pytest.mark.anyio
    async def test_gate_active_eval(self):
        r1 = await score_rubric(
            action="create",
            rubric_id="r1",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id="r1",
        )
        eid = _extract(r2, "Eval:")
        r = await score_gate(
            action="gate",
            evaluation_id=eid,
        )
        assert "Pass: ?" in r
        assert "active" in r

    @pytest.mark.anyio
    async def test_list_evaluations(self):
        r1 = await score_rubric(
            action="create",
            rubric_id="r1",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id="r1",
        )
        eid = _extract(r2, "Eval:")
        await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
        )
        r = await score_gate(
            action="list",
            session_id=sid,
        )
        assert "Evaluations (1)" in r

    @pytest.mark.anyio
    async def test_gate_use_latest(self):
        r1 = await score_rubric(
            action="create",
            rubric_id="r2",
            dimensions=[{"id": "d1", "weight": 1.0}],
        )
        sid = _extract(r1, "Session:")
        await score_evaluate(action="start", session_id=sid, rubric_id="r2")
        r = await score_gate(action="gate", session_id=sid, use_latest=True)
        assert "Status: active" in r


@pytest.mark.usefixtures("_init_session_manager")
class TestScoringStrategies:
    @pytest.mark.anyio
    async def test_minimum_floor_caps_score(self):
        """Required dimension tanked should cap the total."""
        r1 = await score_rubric(
            action="create",
            rubric_id="floor-test",
            dimensions=[
                {"id": "required_dim", "weight": 1.0, "required": True},
                {"id": "good_dim", "weight": 1.0, "required": False},
            ],
            scoring_strategy="minimum_floor",
        )
        sid = _extract(r1, "Session:")
        r2 = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id="floor-test",
        )
        eid = _extract(r2, "Eval:")
        # Tank the required dimension with 3 high findings
        for _ in range(3):
            await score_evaluate(
                action="finding",
                session_id=sid,
                evaluation_id=eid,
                dimension="required_dim",
                severity="high",
                description="Issue",
            )
        r = await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
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
            action="start",
            session_id=sid,
            rubric_id="plan-review",
            context="Holonic tools implementation plan",
        )
        eid = _extract(r2, "Eval:")

        # Finding 1: completeness issue (high)
        r3 = await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="completeness",
            severity="high",
            description="Missing error handling for multi-membership edge case",
            evidence=["plan.md:45-50"],
            recommendation="Add explicit error handling step",
        )
        assert "below_threshold" in r3 or "above_threshold" in r3

        # Finding 2: integration issue (moderate)
        r4 = await score_evaluate(
            action="finding",
            session_id=sid,
            evaluation_id=eid,
            dimension="integration",
            severity="moderate",
            description="No mention of updating guide prompt",
        )
        assert "Running score:" in r4

        # Finalize
        r5 = await score_evaluate(
            action="finalize",
            session_id=sid,
            evaluation_id=eid,
            summary="Plan is mostly complete but has gaps",
            dimensions_reviewed=["feasibility", "correctness"],
        )
        assert "Final score:" in r5
        assert "Findings: 2" in r5
        assert "completeness:" in r5
        assert "integration:" in r5

        # Gate check
        r6 = await score_gate(
            action="gate",
            evaluation_id=eid,
        )
        assert "finalized" in r6

        # List evaluations
        r7 = await score_gate(
            action="list",
            session_id=sid,
            rubric_id="plan-review",
        )
        assert "Evaluations (1)" in r7


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreTemplatesAndGraph:
    @pytest.mark.anyio
    async def test_new_rubric_templates_are_listed(self):
        listed = await rubric_templates(action="list")
        assert "discovery_value" in listed
        assert "code_quality" in listed
        assert "agile_feature" in listed
        assert "agile_user_story" in listed
        assert "agile_task" in listed
        assert "research_hypothesis" in listed
        assert "omics_profile_quality" in listed
        assert "mechanistic_overreach" in listed
        assert "assay_boundary_review" in listed

    @pytest.mark.anyio
    async def test_new_rubric_template_can_be_loaded(self):
        sid = _extract(await think_create_session(), "session_id:")
        loaded = await rubric_templates(
            action="load",
            template_id="code_quality",
            session_id=sid,
        )
        assert "Rubric: code_quality" in loaded

    @pytest.mark.anyio
    async def test_scoring_materializes_graph_when_started_from_parent_session(self):
        parent = await session_create(backends=["think", "graph"], mode="analyze")
        sid = _extract(parent, "session_id:")
        await score_rubric(
            action="create",
            session_id=sid,
            rubric_id="graph-score",
            dimensions=[{"id": "logic", "weight": 1.0, "required": True}],
        )
        start = await score_evaluate(
            action="start",
            session_id=sid,
            rubric_id="graph-score",
            context="Graph-backed evaluation",
        )
        eid = _extract(start, "Eval:")
        await score_evaluate(
            action="finding",
            evaluation_id=eid,
            dimension="logic",
            severity="moderate",
            description="Missing counterevidence path",
            analysis_refs=["claim_x"],
        )
        result = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) "
                f"WHERE n.name = 'evaluation:{eid}' OR n.name = 'finding:{eid}:f-001' "
                "RETURN n.name;"
            ),
        )
        assert f"evaluation:{eid}" in result
        assert f"finding:{eid}:f-001" in result


# ── Section 6+7: auto_finalize + verbosity trim ──────────────


@pytest.mark.usefixtures("_init_session_manager")
class TestScoreEvaluateAutoFinalize:
    """Section 6 (auto_finalize) and Section 7 (verbosity trim)
    of plans/tool-call-efficiency-improvements.md.
    """

    async def _setup_rubric(self) -> tuple[str, str]:
        r = await score_rubric(
            action="create",
            rubric_id="auto-final-rubric",
            dimensions=PLAN_REVIEW_DIMS,
        )
        return _extract(r, "Session:"), "auto-final-rubric"

    @staticmethod
    def _extract_dim_lines(response: str) -> list[str]:
        """Pull out the per-dimension lines from a finalize-shaped block."""
        out: list[str] = []
        capture = False
        for line in response.splitlines():
            if line.strip() == "Dimension scores:":
                capture = True
                continue
            if capture:
                if not line.startswith("  "):
                    break
                out.append(line.rstrip())
        return out

    @pytest.mark.anyio
    async def test_batch_findings_auto_finalize_produces_same_outcome_as_two_calls(self):
        # Path A: traditional 2-call sequence (batch_findings then finalize).
        sid_a, rid = await self._setup_rubric()
        start_a = await score_evaluate(action="start", session_id=sid_a, rubric_id=rid)
        eid_a = _extract(start_a, "Eval:")
        findings_payload = [
            {
                "dimension": "feasibility",
                "severity": "moderate",
                "description": "Issue F",
            },
            {
                "dimension": "completeness",
                "severity": "low",
                "description": "Issue C",
            },
        ]
        await score_evaluate(
            action="batch_findings",
            evaluation_id=eid_a,
            findings=findings_payload,
        )
        final_a = await score_evaluate(
            action="finalize",
            evaluation_id=eid_a,
            summary="auto-finalize parity check",
            dimensions_reviewed=["correctness", "integration"],
        )

        # Path B: single batch_findings call with auto_finalize=True.
        sid_b, _ = await self._setup_rubric()
        start_b = await score_evaluate(action="start", session_id=sid_b, rubric_id=rid)
        eid_b = _extract(start_b, "Eval:")
        combined_b = await score_evaluate(
            action="batch_findings",
            evaluation_id=eid_b,
            findings=findings_payload,
            auto_finalize=True,
            summary="auto-finalize parity check",
            dimensions_reviewed=["correctness", "integration"],
        )

        # Final score must match.
        score_a = _extract(final_a, "Final score:").split("/")[0]
        score_b = _extract(combined_b, "Final score:").split("/")[0]
        assert score_a == score_b
        # Pass/fail verdict must match.
        verdict_a = _extract(final_a, "Pass:").split(" ")[0].rstrip("|").strip()
        verdict_b = _extract(combined_b, "Pass:").split(" ")[0].rstrip("|").strip()
        assert verdict_a == verdict_b
        # Per-dimension table content must match line-for-line.
        dim_a = self._extract_dim_lines(final_a)
        dim_b = self._extract_dim_lines(combined_b)
        assert dim_a == dim_b
        assert dim_a, "expected at least one dimension line"

    @pytest.mark.anyio
    async def test_batch_findings_auto_finalize_requires_summary(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        with pytest.raises(ValueError, match="summary"):
            await score_evaluate(
                action="batch_findings",
                evaluation_id=eid,
                findings=[
                    {
                        "dimension": "feasibility",
                        "severity": "low",
                        "description": "x",
                    }
                ],
                auto_finalize=True,
            )
        # Whitespace-only summary also rejected.
        with pytest.raises(ValueError, match="summary"):
            await score_evaluate(
                action="batch_findings",
                evaluation_id=eid,
                findings=[
                    {
                        "dimension": "feasibility",
                        "severity": "low",
                        "description": "x",
                    }
                ],
                auto_finalize=True,
                summary="   ",
            )

    @pytest.mark.anyio
    async def test_batch_findings_auto_finalize_missing_required_dims(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        # PLAN_REVIEW_DIMS has 3 required dims (feasibility/completeness/correctness).
        # Submit only one finding on a non-required dim and don't pass any
        # dimensions_reviewed — finalization should refuse.
        result = await score_evaluate(
            action="batch_findings",
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "integration",
                    "severity": "low",
                    "description": "Minor",
                }
            ],
            auto_finalize=True,
            summary="should not finalize",
        )
        assert "CANNOT FINALIZE" in result
        assert "required dimensions not reviewed" in result
        # The findings part of the response is still produced.
        assert "Batch: 1 findings applied" in result
        assert "Final:" in result

    @pytest.mark.anyio
    async def test_batch_findings_drops_running_scores_chain(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        result = await score_evaluate(
            action="batch_findings",
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "feasibility",
                    "severity": "low",
                    "description": "a",
                },
                {
                    "dimension": "completeness",
                    "severity": "low",
                    "description": "b",
                },
            ],
        )
        assert "Running scores:" not in result

    @pytest.mark.anyio
    async def test_batch_findings_drops_evaluation_id_echo(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        result = await score_evaluate(
            action="batch_findings",
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "feasibility",
                    "severity": "low",
                    "description": "a",
                }
            ],
        )
        assert "evaluation_id:" not in result

    @pytest.mark.anyio
    async def test_batch_findings_keeps_final_and_finding_ids(self):
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        result = await score_evaluate(
            action="batch_findings",
            evaluation_id=eid,
            findings=[
                {
                    "dimension": "feasibility",
                    "severity": "low",
                    "description": "a",
                }
            ],
        )
        assert "Final:" in result
        assert "Finding IDs:" in result

    @pytest.mark.anyio
    async def test_finding_action_unchanged(self):
        """Section 7 explicitly preserves the single-finding path. The
        evaluation_id echo at score.py:547 (start) and the per-finding
        echo around score.py:545 stay.
        """
        sid, rid = await self._setup_rubric()
        start = await score_evaluate(action="start", session_id=sid, rubric_id=rid)
        eid = _extract(start, "Eval:")
        finding = await score_evaluate(
            action="finding",
            evaluation_id=eid,
            dimension="feasibility",
            severity="low",
            description="single-finding path preserved",
        )
        # The single-finding response keeps the evaluation_id echo line.
        assert f"evaluation_id: {eid}" in finding
