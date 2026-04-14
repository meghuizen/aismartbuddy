"""Scoring and evaluation tools.

Separates AI judgment from mechanical scoring. The AI submits findings
one at a time; the server computes running scores after each, preventing
post-hoc rationalization. Required dimensions must be reviewed or
finalization fails.
"""

from __future__ import annotations

import json
import uuid

import anyio
from mcp.server.fastmcp import Context

from aismartbuddy.engines.thinking_engine import (
    EvaluationRecord,
    FindingRecord,
    RubricRecord,
)
from aismartbuddy.tools.think import (
    _engine,
    _get_or_create_think_session,
    _require_think_session,
    _validate_enum,
)

# ── Validation constants ─────────────────────────────────────

_SCORE_RUBRIC_ACTIONS = frozenset({"create", "list"})
_SCORE_EVALUATE_ACTIONS = frozenset(
    {"start", "finding", "finding_batch", "finalize"}
)
_SCORE_GATE_ACTIONS = frozenset({"gate", "list"})
_SCORING_STRATEGIES = frozenset({
    "weighted_deduction",
    "minimum_floor",
})
_DEFAULT_SEVERITY_DEDUCTIONS: dict[str, float] = {
    "critical": 3.0,
    "high": 2.0,
    "moderate": 1.0,
    "low": 0.5,
}
_DEFAULT_SEVERITY_LEVELS = list(_DEFAULT_SEVERITY_DEDUCTIONS.keys())


# ── Tool: score_rubric ───────────────────────────────────────


async def score_rubric(
    action: str,
    session_id: str | None = None,
    rubric_id: str | None = None,
    description: str | None = None,
    dimensions: list[dict] | None = None,
    severity_levels: list[str] | None = None,
    severity_deductions: dict[str, float] | None = None,
    pass_threshold: float = 9.0,
    scale_min: int = 1,
    scale_max: int = 10,
    scoring_strategy: str = "weighted_deduction",
    ctx: Context | None = None,
) -> str:
    """Create or list scoring rubrics.

    A rubric defines the scoring framework: dimensions with weights,
    severity levels, deduction amounts, pass threshold, and strategy.
    Rubrics are reusable across evaluations.

    Actions:
        create: Define a new rubric. Requires rubric_id, dimensions.
        list: Show all rubrics in the session.

    Args:
        action: create or list.
        session_id: Thinking session ID. Omit to auto-create.
        rubric_id: Unique rubric identifier (for create).
        description: What this rubric evaluates (for create).
        dimensions: List of scoring dimensions (for create).
            Each: {id, description, weight (float), required (bool)}.
        severity_levels: Ordered severity levels.
            Default: [critical, high, moderate, low].
        severity_deductions: Score deduction per severity.
            Default: {critical: 3.0, high: 2.0, moderate: 1.0, low: 0.5}.
        pass_threshold: Score needed to pass. Default: 9.0.
        scale_min: Minimum score. Default: 1.
        scale_max: Maximum score. Default: 10.
        scoring_strategy: weighted_deduction (start at max, deduct
            per finding) or minimum_floor (capped by worst required
            dimension). Default: weighted_deduction.

    Returns:
        Compact status with rubric details.
    """
    _validate_enum(action, _SCORE_RUBRIC_ACTIONS, "action")

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)
    sid = info.session_id

    if action == "create":
        if not rubric_id:
            raise ValueError("rubric_id is required for create")
        if not dimensions:
            raise ValueError("dimensions is required for create")
        _validate_enum(
            scoring_strategy, _SCORING_STRATEGIES, "scoring_strategy"
        )
        # Validate dimensions structure + uniqueness
        dim_ids_seen: set[str] = set()
        for i, dim in enumerate(dimensions):
            if "id" not in dim or "weight" not in dim:
                raise ValueError(
                    f"Dimension {i} must have 'id' and 'weight'"
                )
            if dim["id"] in dim_ids_seen:
                raise ValueError(
                    f"Duplicate dimension id: '{dim['id']}'"
                )
            dim_ids_seen.add(dim["id"])

        # Resolve severity levels and deductions
        effective_levels = severity_levels or _DEFAULT_SEVERITY_LEVELS
        effective_deductions = (
            severity_deductions or dict(_DEFAULT_SEVERITY_DEDUCTIONS)
        )
        # Validate all severity levels have deduction entries
        missing = set(effective_levels) - set(effective_deductions.keys())
        if missing:
            raise ValueError(
                f"severity_deductions missing entries for: "
                f"{', '.join(sorted(missing))}"
            )

        record = RubricRecord(
            id=rubric_id,
            description=description or "",
            dimensions=dimensions,
            severity_levels=effective_levels,
            severity_deductions=effective_deductions,
            pass_threshold=pass_threshold,
            scale_min=scale_min,
            scale_max=scale_max,
            scoring_strategy=scoring_strategy,
        )
        engine.upsert_rubric(record)

        required = sum(1 for d in dimensions if d.get("required", False))
        return (
            f"Session: {sid} | Rubric: {rubric_id}\n"
            f"Dimensions: {len(dimensions)} ({required} required)"
            f" | Threshold: {pass_threshold}/{scale_max}\n"
            f"Strategy: {scoring_strategy}\n"
            "Status: created"
        )

    # action == "list"
    rubrics = engine.get_rubrics()
    if not rubrics:
        return f"Session: {sid}\nNo rubrics defined."
    lines = [f"Session: {sid}", f"Rubrics ({len(rubrics)}):"]
    for r in rubrics:
        req = sum(1 for d in r.dimensions if d.get("required", False))
        lines.append(
            f"  {r.id}: {len(r.dimensions)} dims ({req} req)"
            f" | threshold={r.pass_threshold}/{r.scale_max}"
            f" | {r.scoring_strategy}"
        )
    return "\n".join(lines)


# ── Tool: score_evaluate ─────────────────────────────────────


_TEMPLATES_DIR = (
    __import__("pathlib").Path(__file__).parent.parent / "templates" / "rubrics"
)
_TEMPLATE_IDS = frozenset({
    "security_review", "architecture_review", "code_review",
    "research_quality", "hypothesis_strength", "documentation_completeness",
})


async def rubric_templates(
    action: str,
    template_id: str | None = None,
    session_id: str | None = None,
    ctx: Context | None = None,
) -> str:
    """List or load pre-built scoring rubrics.

    Templates ship with the server: security_review, architecture_review,
    code_review, research_quality, hypothesis_strength, documentation_completeness.
    Loading a template is equivalent to calling score_rubric(action="create",
    ...) with the template's pre-configured fields.

    Args:
        action: list | load.
        template_id: Required for load.
        session_id: Required for load — where to install the rubric.

    Returns:
        Template list or load confirmation.
    """
    import json

    if action not in ("list", "load"):
        raise ValueError(f"action must be list|load, got {action!r}")

    if action == "list":
        out = ["Available rubric templates:"]
        for tid in sorted(_TEMPLATE_IDS):
            path = _TEMPLATES_DIR / f"{tid}.json"
            if path.exists():
                try:
                    payload = json.loads(path.read_text())
                    out.append(f"- {tid}: {payload.get('description', '')}")
                except Exception:
                    out.append(f"- {tid}: (parse error)")
        return "\n".join(out)

    # load
    if not template_id:
        raise ValueError("template_id is required for load")
    if template_id not in _TEMPLATE_IDS:
        raise ValueError(
            f"Unknown template '{template_id}'. "
            f"Valid: {sorted(_TEMPLATE_IDS)}"
        )
    path = _TEMPLATES_DIR / f"{template_id}.json"
    if not path.exists():
        raise ValueError(f"Template file missing: {path}")
    payload = json.loads(path.read_text())
    return await score_rubric(
        action="create",
        session_id=session_id,
        rubric_id=payload["rubric_id"],
        description=payload.get("description"),
        dimensions=payload["dimensions"],
        severity_levels=payload.get("severity_levels"),
        severity_deductions=payload.get("severity_deductions"),
        pass_threshold=payload.get("pass_threshold", 9.0),
        scale_min=payload.get("scale_min", 1),
        scale_max=payload.get("scale_max", 10),
        scoring_strategy=payload.get("scoring_strategy", "weighted_deduction"),
        ctx=ctx,
    )


async def score_evaluate(
    action: str,
    session_id: str,
    evaluation_id: str | None = None,
    rubric_id: str | None = None,
    context: str | None = None,
    dimension: str | None = None,
    severity: str | None = None,
    blocking: bool = False,
    description: str | None = None,
    evidence: list[str] | None = None,
    recommendation: str | None = None,
    summary: str | None = None,
    dimensions_reviewed: list[str] | None = None,
    findings: list[dict] | None = None,
) -> str:
    """Start an evaluation, submit findings, or finalize.

    The key design: findings are submitted individually. The server
    computes the running score after each, preventing the AI from
    listing problems then giving a contradictory high score.

    Actions:
        start: Begin evaluation against a rubric. Returns eval ID.
        finding: Submit a single finding. Returns running score.
        finding_batch: Submit N findings in one call. **WARNING**: this
            loses the incremental self-assessment forcing function — all
            findings are committed before any score is seen. Use only when
            iterative scoring isn't feasible (e.g., bulk import). The output
            includes a reminder to prefer action="finding" when possible.
        finalize: Close evaluation. Checks required dimensions.

    Args:
        action: start, finding, or finalize.
        session_id: Thinking session ID.
        evaluation_id: Eval ID (auto-generated on start, required after).
        rubric_id: Which rubric to evaluate against (for start).
        context: What's being evaluated (for start).
        dimension: Which dimension this finding affects (for finding).
        severity: Finding severity — must match rubric's levels
            (for finding).
        blocking: If true, evaluation cannot pass (for finding).
        description: What was found (for finding).
        evidence: Where the finding was observed (for finding).
        recommendation: How to fix it (for finding).
        summary: Overall evaluation summary (for finalize).
        dimensions_reviewed: Extra dimensions reviewed with no
            findings (for finalize).

    Returns:
        Compact status with running/final score.
    """
    _validate_enum(action, _SCORE_EVALUATE_ACTIONS, "action")
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    # ── start ────────────────────────────────────────────
    if action == "start":
        if not rubric_id:
            raise ValueError("rubric_id is required for start")
        rubric = engine.get_rubric(rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{rubric_id}' not found")

        eid = evaluation_id or uuid.uuid4().hex[:12]
        dim_scores = {
            d["id"]: float(rubric.scale_max) for d in rubric.dimensions
        }
        ev = EvaluationRecord(
            id=eid,
            rubric_id=rubric_id,
            context=context or "",
            dimension_scores=dim_scores,
            running_score=float(rubric.scale_max),
        )
        engine.upsert_evaluation(ev)

        return (
            f"Session: {session_id} | Eval: {eid}\n"
            f"Rubric: {rubric_id} | All dimensions at"
            f" {rubric.scale_max}/{rubric.scale_max}\n"
            "Status: active"
        )

    # ── finding ──────────────────────────────────────────
    if action == "finding":
        if not evaluation_id:
            raise ValueError("evaluation_id is required for finding")
        ev = engine.get_evaluation(evaluation_id)
        if ev is None:
            raise ValueError(f"Evaluation '{evaluation_id}' not found")
        if ev.status != "active":
            raise ValueError(
                f"Evaluation '{evaluation_id}' is {ev.status},"
                " not active"
            )
        if not dimension or not severity or not description:
            raise ValueError(
                "dimension, severity, and description are "
                "required for finding"
            )
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{ev.rubric_id}' not found")

        # Validate dimension exists in rubric
        dim_ids = {d["id"] for d in rubric.dimensions}
        if dimension not in dim_ids:
            raise ValueError(
                f"Dimension '{dimension}' not in rubric. "
                f"Valid: {', '.join(sorted(dim_ids))}"
            )
        # Validate severity
        if severity not in rubric.severity_levels:
            raise ValueError(
                f"Severity '{severity}' not in rubric. "
                f"Valid: {', '.join(rubric.severity_levels)}"
            )

        # id assigned inside apply_finding (under lock) to prevent
        # concurrent-submission collisions.
        finding = FindingRecord(
            id="",
            dimension=dimension,
            severity=severity,
            blocking=blocking,
            description=description,
            evidence=evidence or [],
            recommendation=recommendation or "",
        )
        running = engine.apply_finding(evaluation_id, finding)
        fid = finding.id

        # Build dimension score display
        dim_parts = []
        for d in rubric.dimensions:
            score = ev.dimension_scores.get(d["id"])
            if d["id"] in ev.dimensions_reviewed:
                dim_parts.append(f"{d['id']}={score:.0f}")
            else:
                dim_parts.append(f"{d['id']}=?")

        threshold_status = (
            "above_threshold"
            if running >= rubric.pass_threshold
            else "below_threshold"
        )

        return (
            f"Session: {session_id} | Eval: {evaluation_id}"
            f" | Finding: {fid}\n"
            f"Dimension: {dimension} ({severity})"
            f" | Blocking: {blocking}\n"
            f"Running score: {running}/{rubric.scale_max}"
            f" | Status: {threshold_status}\n"
            f"Dimension scores: {', '.join(dim_parts)}"
        )

    # ── finding_batch ────────────────────────────────────
    if action == "finding_batch":
        if not evaluation_id:
            raise ValueError("evaluation_id is required for finding_batch")
        if not findings:
            raise ValueError("findings list must be non-empty")
        ev = engine.get_evaluation(evaluation_id)
        if ev is None:
            raise ValueError(f"Evaluation '{evaluation_id}' not found")
        if ev.status != "active":
            raise ValueError(
                f"Evaluation '{evaluation_id}' is {ev.status}, not active"
            )
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{ev.rubric_id}' not found")
        dim_ids = {d["id"] for d in rubric.dimensions}

        # Validate all findings up-front
        for i, f in enumerate(findings):
            if not f.get("dimension"):
                raise ValueError(
                    f"findings[{i}] missing 'dimension'"
                )
            if f["dimension"] not in dim_ids:
                raise ValueError(
                    f"findings[{i}].dimension '{f['dimension']}' "
                    f"not in rubric. Valid: {', '.join(sorted(dim_ids))}"
                )
            if not f.get("severity"):
                raise ValueError(f"findings[{i}] missing 'severity'")
            if f["severity"] not in rubric.severity_levels:
                raise ValueError(
                    f"findings[{i}].severity '{f['severity']}' not in rubric. "
                    f"Valid: {', '.join(rubric.severity_levels)}"
                )
            if not f.get("description"):
                raise ValueError(f"findings[{i}] missing 'description'")

        # Apply sequentially under the engine RLock; collect running scores
        running_scores: list[float] = []
        finding_ids: list[str] = []
        result_rows: list[str] = []
        with engine.state_lock:
            for f in findings:
                fr = FindingRecord(
                    id="",
                    dimension=f["dimension"],
                    severity=f["severity"],
                    blocking=bool(f.get("blocking", False)),
                    description=f["description"],
                    evidence=list(f.get("evidence") or []),
                    recommendation=f.get("recommendation", "") or "",
                )
                rs = engine.apply_finding(evaluation_id, fr)
                running_scores.append(rs)
                finding_ids.append(fr.id)
                result_rows.append(
                    json.dumps(
                        {
                            "finding_id": fr.id,
                            "running_score": rs,
                            "dimension_score": ev.dimension_scores.get(
                                f["dimension"], rubric.scale_max
                            ),
                        },
                        separators=(",", ":"),
                    )
                )

        running_str = " → ".join(f"{s}" for s in running_scores)
        final_running = running_scores[-1]
        threshold_status = (
            "above_threshold"
            if final_running >= rubric.pass_threshold
            else "below_threshold"
        )
        return (
            f"Session: {session_id} | Eval: {evaluation_id}"
            f" | Batch: {len(findings)} findings applied\n"
            f"Results: [{', '.join(result_rows)}]\n"
            f"Running scores: {running_str}\n"
            f"Final: {final_running}/{rubric.scale_max}"
            f" (threshold {rubric.pass_threshold}) | {threshold_status}\n"
            f"Finding IDs: {', '.join(finding_ids)}\n"
            "⚠ finding_batch loses the incremental self-assessment "
            "forcing function. Each finding was committed before seeing "
            'its running score. Prefer action="finding" for iterative '
            "scoring when feasible."
        )

    # ── finalize ─────────────────────────────────────────
    if not evaluation_id:
        raise ValueError("evaluation_id is required for finalize")

    # Atomic finalize — engine.finalize_evaluation is @_synchronized so
    # concurrent calls from multiple agents sharing the session cannot
    # both succeed on the same evaluation.
    missing, ev = engine.finalize_evaluation(
        evaluation_id, dimensions_reviewed, summary or ""
    )
    if missing:
        return (
            f"Session: {session_id} | Eval: {evaluation_id}\n"
            f"CANNOT FINALIZE: required dimensions not reviewed: "
            f"{', '.join(missing)}\n"
            "Submit findings or include in dimensions_reviewed."
        )
    rubric = engine.get_rubric(ev.rubric_id)

    # Severity counts
    sev_counts: dict[str, int] = {}
    for f in ev.findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    # Dimension detail
    dim_lines = []
    for d in rubric.dimensions:
        did = d["id"]
        score = ev.dimension_scores.get(did, rubric.scale_max)
        n_findings = sum(1 for f in ev.findings if f.dimension == did)
        dim_lines.append(
            f"  {did}: {score:.0f}/{rubric.scale_max}"
            f" ({n_findings} findings)"
        )

    sev_str = ", ".join(
        f"{s}={sev_counts.get(s, 0)}" for s in rubric.severity_levels
    )
    pass_str = "PASS" if ev.passed else "FAIL"

    lines = [
        f"Session: {session_id} | Eval: {evaluation_id}",
        (
            f"Final score: {ev.final_score}/{rubric.scale_max}"
            f" | Pass: {pass_str}"
        ),
        (
            f"Threshold: {rubric.pass_threshold}"
            f" | Strategy: {rubric.scoring_strategy}"
        ),
        f"Findings: {len(ev.findings)} ({sev_str})",
        "Dimension scores:",
    ]
    lines.extend(dim_lines)
    return "\n".join(lines)


# ── Tool: score_gate ─────────────────────────────────────────


async def score_gate(
    action: str,
    session_id: str,
    evaluation_id: str | None = None,
    rubric_id: str | None = None,
    limit: int = 10,
) -> str:
    """Check scoring gates or list evaluation history.

    Actions:
        gate: Lightweight pass/fail check for hooks. Returns
            pass boolean, score, threshold. If evaluation is not
            finalized, returns pass=? (indeterminate).
        list: Show evaluation history, optionally filtered by rubric.

    Args:
        action: gate or list.
        session_id: Thinking session ID.
        evaluation_id: Which evaluation to check (for gate).
        rubric_id: Filter by rubric (for list).
        limit: Max evaluations to return (for list).

    Returns:
        Gate check result or evaluation list.
    """
    _validate_enum(action, _SCORE_GATE_ACTIONS, "action")
    _, info = _require_think_session(session_id)
    engine = _engine(info)

    if action == "gate":
        if not evaluation_id:
            raise ValueError("evaluation_id is required for gate")
        ev = engine.get_evaluation(evaluation_id)
        if ev is None:
            raise ValueError(
                f"Evaluation '{evaluation_id}' not found"
            )
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(
                f"Rubric '{ev.rubric_id}' referenced by "
                f"evaluation '{evaluation_id}' not found"
            )
        threshold = rubric.pass_threshold

        if ev.status == "finalized":
            pass_str = "true" if ev.passed else "false"
            score_str = f"{ev.final_score}/{rubric.scale_max}"
            return (
                f"Session: {session_id} | Eval: {evaluation_id}\n"
                f"Pass: {pass_str} | Score: {score_str}"
                f" | Threshold: {threshold}\n"
                f"Blocking: {sum(1 for f in ev.findings if f.blocking)}"
                f" | Status: finalized"
            )
        else:
            score_str = f"{ev.running_score}/{rubric.scale_max}"
            return (
                f"Session: {session_id} | Eval: {evaluation_id}\n"
                f"Pass: ? | Score: {score_str} (running)"
                f" | Threshold: {threshold}\n"
                "Status: active (not finalized)"
            )

    # action == "list"
    evals = engine.get_evaluations(rubric_id)
    evals.sort(key=lambda e: e.created_at, reverse=True)
    evals = evals[:limit]

    rubric_label = rubric_id or "all"
    lines = [
        f"Session: {session_id} | Rubric: {rubric_label}",
        f"Evaluations ({len(evals)}):",
    ]
    for ev in evals:
        if ev.status == "finalized":
            pass_str = "PASS" if ev.passed else "FAIL"
            score = ev.final_score or 0
        else:
            pass_str = "ACTIVE"
            score = ev.running_score
        date_str = ev.created_at.strftime("%Y-%m-%d")
        lines.append(
            f"  {ev.id}: {score:.1f} {pass_str}"
            f" ({len(ev.findings)} findings) — {date_str}"
        )
    if not evals:
        lines.append("  No evaluations found.")
    return "\n".join(lines)
