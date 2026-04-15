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
from aismartbuddy.tools import get_session_manager
from aismartbuddy.tools.think import (
    _engine,
    _format_rule_validation_summary,
    _get_or_create_think_session,
    _materialize_subject_rule_bindings,
    _require_think_session,
    _rule_bindings_from_profile_ids,
    _validate_enum,
)

# ── Validation constants ─────────────────────────────────────

_SCORE_RUBRIC_ACTIONS = frozenset({"create", "list"})
_SCORE_EVALUATE_ACTIONS = frozenset(
    {
        "start",
        "start_with_rubric",
        "finding",
        "note",
        "batch_findings",
        "finding_batch",
        "review",
        "finalize",
    }
)
_SCORE_GATE_ACTIONS = frozenset({"gate", "list"})
_SCORING_STRATEGIES = frozenset(
    {
        "weighted_deduction",
        "minimum_floor",
    }
)
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

    _, info = await anyio.to_thread.run_sync(lambda: _get_or_create_think_session(session_id, ctx))
    engine = _engine(info)
    sid = info.session_id

    if action == "create":
        if not rubric_id:
            raise ValueError("rubric_id is required for create")
        if not dimensions:
            raise ValueError("dimensions is required for create")
        _validate_enum(scoring_strategy, _SCORING_STRATEGIES, "scoring_strategy")
        # Validate dimensions structure + uniqueness
        dim_ids_seen: set[str] = set()
        for i, dim in enumerate(dimensions):
            if "id" not in dim or "weight" not in dim:
                raise ValueError(f"Dimension {i} must have 'id' and 'weight'")
            if dim["id"] in dim_ids_seen:
                raise ValueError(f"Duplicate dimension id: '{dim['id']}'")
            dim_ids_seen.add(dim["id"])

        # Resolve severity levels and deductions
        effective_levels = severity_levels or _DEFAULT_SEVERITY_LEVELS
        effective_deductions = severity_deductions or dict(_DEFAULT_SEVERITY_DEDUCTIONS)
        # Validate all severity levels have deduction entries
        missing = set(effective_levels) - set(effective_deductions.keys())
        if missing:
            raise ValueError(
                f"severity_deductions missing entries for: {', '.join(sorted(missing))}"
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


_TEMPLATES_DIR = __import__("pathlib").Path(__file__).parent.parent / "templates" / "rubrics"
_TEMPLATE_IDS = frozenset(
    {
        "security_review",
        "architecture_review",
        "code_review",
        "research_quality",
        "hypothesis_strength",
        "documentation_completeness",
        "omics_profile_quality",
        "mechanistic_overreach",
        "assay_boundary_review",
    }
)


def _extract_parent_session_id(session_id: str | None) -> str | None:
    """Return the caller-provided session id only when it's a parent facade id."""
    if not session_id:
        return None
    mgr = get_session_manager()
    if session_id in getattr(mgr, "_parent_sessions", {}):
        return session_id
    return None


def _find_evaluation_session(
    evaluation_id: str | None = None,
    *,
    session_id: str | None = None,
    use_latest: bool = False,
):
    """Resolve an evaluation handle to (SessionInfo, ThinkingEngine, EvaluationRecord).

    Resolution order:
    - explicit session_id + evaluation_id/use_latest within that session scope
    - global search by evaluation_id across active think sessions
    - global latest active evaluation when use_latest=True
    """
    mgr = get_session_manager()

    if session_id:
        _, info = _require_think_session(session_id)
        engine = _engine(info)
        if use_latest and not evaluation_id:
            active = [e for e in engine.get_evaluations() if e.status == "active"]
            if not active:
                raise ValueError("No active evaluation found in this session")
            if len(active) > 1:
                raise ValueError(
                    "Multiple active evaluations found in this session. "
                    "Pass evaluation_id to disambiguate."
                )
            return info, engine, active[0]
        if not evaluation_id:
            raise ValueError("evaluation_id is required unless use_latest=true")
        ev = engine.get_evaluation(evaluation_id)
        if ev is None:
            raise ValueError(f"Evaluation '{evaluation_id}' not found")
        return info, engine, ev

    candidates = []
    for info in mgr.list_sessions():
        if info.session_type != "think" or info.engine is None:
            continue
        engine = _engine(info)
        if evaluation_id:
            ev = engine.get_evaluation(evaluation_id)
            if ev is not None:
                candidates.append((info, engine, ev))
        elif use_latest:
            for ev in engine.get_evaluations():
                if ev.status == "active":
                    candidates.append((info, engine, ev))

    if evaluation_id:
        if not candidates:
            raise ValueError(f"Evaluation '{evaluation_id}' not found")
        if len(candidates) > 1:
            raise ValueError(
                f"Evaluation '{evaluation_id}' is ambiguous across sessions. "
                "Pass session_id to disambiguate."
            )
        return candidates[0]

    if use_latest:
        if not candidates:
            raise ValueError("No active evaluation found")
        if len(candidates) > 1:
            raise ValueError(
                "Multiple active evaluations found. "
                "Pass session_id or evaluation_id to disambiguate."
            )
        return candidates[0]

    raise ValueError("evaluation_id is required unless use_latest=true")


async def _materialize_evaluation_graph(
    ev: EvaluationRecord, finding: FindingRecord | None = None
) -> None:
    """Best-effort graph materialization for evaluations started from parent sessions."""
    if not ev.parent_session_id:
        return
    try:
        from aismartbuddy.tools.graph import graph_knowledge_add, graph_knowledge_relate

        await graph_knowledge_add(
            session_id=ev.parent_session_id,
            entity=f"evaluation:{ev.id}",
            entity_type="insight",
            properties={
                "rubric_id": ev.rubric_id,
                "context": ev.context,
                "status": ev.status,
                "session_id": ev.session_id,
            },
            confidence=1.0,
            source="score_evaluate",
        )
        if finding is not None:
            await graph_knowledge_add(
                session_id=ev.parent_session_id,
                entity=f"finding:{ev.id}:{finding.id}",
                entity_type="fact",
                properties={
                    "dimension": finding.dimension,
                    "severity": finding.severity,
                    "kind": finding.kind,
                    "blocking": finding.blocking,
                    "description": finding.description,
                },
                confidence=1.0,
                source="score_evaluate",
            )
            await graph_knowledge_relate(
                session_id=ev.parent_session_id,
                from_name=f"finding:{ev.id}:{finding.id}",
                to_name=f"evaluation:{ev.id}",
                relation="part_of",
                weight=1.0,
                justification="scoring finding belongs to evaluation",
                source="score_evaluate",
            )
            for ref in finding.refs:
                try:
                    await graph_knowledge_relate(
                        session_id=ev.parent_session_id,
                        from_name=f"finding:{ev.id}:{finding.id}",
                        to_name=ref,
                        relation="derived_from",
                        weight=1.0,
                        justification="analysis_refs",
                        source="score_evaluate",
                    )
                except Exception:
                    continue
        if ev.rule_bindings:
            _, info = _require_think_session(ev.session_id)
            engine = _engine(info)
            await _materialize_subject_rule_bindings(
                engine,
                ev.parent_session_id,
                subject_kind="evaluation",
                subject_id=ev.id,
                subject_label=ev.context or ev.id,
                bindings=ev.rule_bindings,
                source="score_evaluate",
            )
    except Exception:
        # Optional integration — never fail the scoring action if graph writes fail.
        return


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
        raise ValueError(f"Unknown template '{template_id}'. Valid: {sorted(_TEMPLATE_IDS)}")
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
    session_id: str | None = None,
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
    use_latest: bool = False,
    analysis_refs: list[str] | None = None,
    rule_profile_ids: list[str] | None = None,
    use_bound_profiles: bool = False,
    rubric_description: str | None = None,
    dimensions: list[dict] | None = None,
    severity_levels: list[str] | None = None,
    severity_deductions: dict[str, float] | None = None,
    pass_threshold: float = 9.0,
    scale_min: int = 1,
    scale_max: int = 10,
    scoring_strategy: str = "weighted_deduction",
    ctx: Context | None = None,
) -> str:
    """Start an evaluation, submit findings, or finalize.

    The key design: findings are submitted individually. The server
    computes the running score after each, preventing the AI from
    listing problems then giving a contradictory high score.

    Actions:
        start: Begin evaluation against a rubric. Returns eval ID.
        start_with_rubric: Create rubric + evaluation in one call.
        finding: Submit a single finding. Returns running score.
        note: Submit a lightweight finding stub (minimal payload).
        batch_findings: Submit N findings in one call; server applies them
            sequentially and returns the running score after each.
        finding_batch: Compatibility alias of batch_findings.
        review: Show current score, coverage, blocking findings, and recent IDs.
        finalize: Close evaluation. Checks required dimensions.

    Args:
        action: scoring action.
        session_id: Thinking session ID. Required for start/start_with_rubric
            and list-style actions; optional once evaluation_id exists.
        evaluation_id: Eval ID (auto-generated on start, primary handle after start).
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
        use_latest: Resolve the latest active evaluation in scope when
            evaluation_id is omitted.
        analysis_refs: IDs from think_* or extracted findings to keep an audit trail.
        rule_profile_ids: Optional bound rule profiles to carry into the evaluation.
        use_bound_profiles: On review/finalize, include rule validation context
            from profiles bound to this evaluation.

    Returns:
        Compact status with running/final score.
    """
    _validate_enum(action, _SCORE_EVALUATE_ACTIONS, "action")

    # ── start ────────────────────────────────────────────
    if action == "start":
        _, info = await anyio.to_thread.run_sync(
            lambda: _get_or_create_think_session(session_id, ctx)
        )
        engine = _engine(info)
        if not rubric_id:
            raise ValueError("rubric_id is required for start")
        rubric = engine.get_rubric(rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{rubric_id}' not found")

        eid = evaluation_id or uuid.uuid4().hex[:12]
        dim_scores = {d["id"]: float(rubric.scale_max) for d in rubric.dimensions}
        ev = EvaluationRecord(
            id=eid,
            rubric_id=rubric_id,
            session_id=info.session_id,
            parent_session_id=_extract_parent_session_id(session_id),
            context=context or "",
            dimension_scores=dim_scores,
            running_score=float(rubric.scale_max),
            refs=list(dict.fromkeys(list(analysis_refs or []))),
            rule_bindings=_rule_bindings_from_profile_ids(engine, rule_profile_ids),
        )
        engine.upsert_evaluation(ev)
        await _materialize_evaluation_graph(ev)

        return (
            f"Session: {info.session_id} | Eval: {eid}\n"
            f"evaluation_id: {eid}\n"
            f"Rubric: {rubric_id} | All dimensions at"
            f" {rubric.scale_max}/{rubric.scale_max}\n"
            "Status: active"
        )

    if action == "start_with_rubric":
        if not rubric_id:
            raise ValueError("rubric_id is required for start_with_rubric")
        if not dimensions:
            raise ValueError("dimensions is required for start_with_rubric")
        _, info = await anyio.to_thread.run_sync(
            lambda: _get_or_create_think_session(session_id, ctx)
        )
        resolved_session_id = info.session_id
        await score_rubric(
            action="create",
            session_id=resolved_session_id,
            rubric_id=rubric_id,
            description=rubric_description,
            dimensions=dimensions,
            severity_levels=severity_levels,
            severity_deductions=severity_deductions,
            pass_threshold=pass_threshold,
            scale_min=scale_min,
            scale_max=scale_max,
            scoring_strategy=scoring_strategy,
            ctx=ctx,
        )
        return await score_evaluate(
            action="start",
            session_id=session_id or resolved_session_id,
            evaluation_id=evaluation_id,
            rubric_id=rubric_id,
            context=context,
            analysis_refs=analysis_refs,
            rule_profile_ids=rule_profile_ids,
            ctx=ctx,
        )

    # ── finding ──────────────────────────────────────────
    if action in {"finding", "note"}:
        info, engine, ev = _find_evaluation_session(
            evaluation_id, session_id=session_id, use_latest=use_latest
        )
        if ev.status != "active":
            raise ValueError(f"Evaluation '{ev.id}' is {ev.status}, not active")
        if not dimension or not severity or not description:
            raise ValueError(f"dimension, severity, and description are required for {action}")
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{ev.rubric_id}' not found")

        # Validate dimension exists in rubric
        dim_ids = {d["id"] for d in rubric.dimensions}
        if dimension not in dim_ids:
            raise ValueError(
                f"Dimension '{dimension}' not in rubric. Valid: {', '.join(sorted(dim_ids))}"
            )
        # Validate severity
        if severity not in rubric.severity_levels:
            raise ValueError(
                f"Severity '{severity}' not in rubric. Valid: {', '.join(rubric.severity_levels)}"
            )

        # id assigned inside apply_finding (under lock) to prevent
        # concurrent-submission collisions.
        finding = FindingRecord(
            id="",
            dimension=dimension,
            severity=severity,
            kind=action,
            blocking=blocking,
            description=description,
            evidence=evidence or [],
            recommendation=recommendation or "",
            refs=list(dict.fromkeys(list(analysis_refs or []))),
        )
        running = engine.apply_finding(ev.id, finding)
        fid = finding.id
        await _materialize_evaluation_graph(ev, finding)

        # Build dimension score display
        dim_parts = []
        for d in rubric.dimensions:
            score = ev.dimension_scores.get(d["id"])
            if d["id"] in ev.dimensions_reviewed:
                dim_parts.append(f"{d['id']}={score:.1f}")
            else:
                dim_parts.append(f"{d['id']}=?")

        threshold_status = (
            "above_threshold" if running >= rubric.pass_threshold else "below_threshold"
        )

        return (
            f"Session: {info.session_id} | Eval: {ev.id}"
            f" | Finding: {fid}\n"
            f"evaluation_id: {ev.id}\n"
            f"Dimension: {dimension} ({severity}) | Kind: {action}"
            f" | Blocking: {blocking}\n"
            f"Running score: {running}/{rubric.scale_max}"
            f" | Status: {threshold_status}\n"
            f"Dimension scores: {', '.join(dim_parts)}"
        )

    # ── batch_findings / finding_batch ───────────────────
    if action in {"batch_findings", "finding_batch"}:
        if not findings:
            raise ValueError("findings list must be non-empty")
        info, engine, ev = _find_evaluation_session(
            evaluation_id, session_id=session_id, use_latest=use_latest
        )
        if ev.status != "active":
            raise ValueError(f"Evaluation '{ev.id}' is {ev.status}, not active")
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{ev.rubric_id}' not found")
        dim_ids = {d["id"] for d in rubric.dimensions}

        # Validate all findings up-front
        for i, f in enumerate(findings):
            if not f.get("dimension"):
                raise ValueError(f"findings[{i}] missing 'dimension'")
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
                    kind=f.get("kind", "finding"),
                    blocking=bool(f.get("blocking", False)),
                    description=f["description"],
                    evidence=list(f.get("evidence") or []),
                    recommendation=f.get("recommendation", "") or "",
                    refs=list(
                        dict.fromkeys(
                            list(f.get("analysis_refs") or []) + list(analysis_refs or [])
                        )
                    ),
                )
                rs = engine.apply_finding(ev.id, fr)
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
                            "kind": fr.kind,
                        },
                        separators=(",", ":"),
                    )
                )
        for finding_id in finding_ids:
            finding = next((f for f in ev.findings if f.id == finding_id), None)
            if finding is not None:
                await _materialize_evaluation_graph(ev, finding)

        running_str = " -> ".join(f"{s}" for s in running_scores)
        final_running = running_scores[-1]
        threshold_status = (
            "above_threshold" if final_running >= rubric.pass_threshold else "below_threshold"
        )
        response = (
            f"Session: {info.session_id} | Eval: {ev.id}"
            f" | Batch: {len(findings)} findings applied\n"
            f"evaluation_id: {ev.id}\n"
            f"Results: [{', '.join(result_rows)}]\n"
            f"Running scores: {running_str}\n"
            f"Final: {final_running}/{rubric.scale_max}"
            f" (threshold {rubric.pass_threshold}) | {threshold_status}\n"
            f"Finding IDs: {', '.join(finding_ids)}"
        )
        if action == "finding_batch":
            response += (
                "\n⚠ finding_batch loses the incremental self-assessment "
                'forcing function. Prefer action="batch_findings" or '
                "single finding calls when feasible."
            )
        return response

    if action == "review":
        info, engine, ev = _find_evaluation_session(
            evaluation_id, session_id=session_id, use_latest=use_latest
        )
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(f"Rubric '{ev.rubric_id}' not found")
        dim_ids = [d["id"] for d in rubric.dimensions]
        covered = sorted(ev.dimensions_reviewed)
        uncovered = [did for did in dim_ids if did not in ev.dimensions_reviewed]
        recent = [f.id for f in ev.findings[-5:]]
        blocking_count = sum(1 for f in ev.findings if f.blocking)
        status = (
            "above_threshold" if ev.running_score >= rubric.pass_threshold else "below_threshold"
        )
        return (
            f"Session: {info.session_id} | Eval: {ev.id}\n"
            f"evaluation_id: {ev.id}\n"
            f"Rubric: {ev.rubric_id} | Status: {ev.status}\n"
            f"Running score: {ev.running_score}/{rubric.scale_max}"
            f" | Threshold: {rubric.pass_threshold} | {status}\n"
            f"Findings so far: {len(ev.findings)} | Blocking: {blocking_count}\n"
            f"Covered dimensions: {', '.join(covered) if covered else '(none)'}\n"
            f"Uncovered dimensions: {', '.join(uncovered) if uncovered else '(none)'}\n"
            f"Recent finding IDs: {', '.join(recent) if recent else '(none)'}"
            + (
                "\n"
                + _format_rule_validation_summary(
                    engine.subject_rule_validation_summary(ev.id, "evaluation")
                )
                if use_bound_profiles or ev.rule_bindings
                else ""
            )
        )

    # ── finalize ─────────────────────────────────────────
    info, engine, ev = _find_evaluation_session(
        evaluation_id, session_id=session_id, use_latest=use_latest
    )

    # Atomic finalize — engine.finalize_evaluation is @_synchronized so
    # concurrent calls from multiple agents sharing the session cannot
    # both succeed on the same evaluation.
    missing, ev = engine.finalize_evaluation(ev.id, dimensions_reviewed, summary or "")
    if missing:
        return (
            f"Session: {info.session_id} | Eval: {evaluation_id or '(latest)'}\n"
            f"evaluation_id: {evaluation_id or '(latest)'}\n"
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
        dim_lines.append(f"  {did}: {score:.1f}/{rubric.scale_max} ({n_findings} findings)")

    sev_str = ", ".join(f"{s}={sev_counts.get(s, 0)}" for s in rubric.severity_levels)
    pass_str = "PASS" if ev.passed else "FAIL"

    rule_summary = None
    if use_bound_profiles or ev.rule_bindings:
        latest_rule_validation = engine.get_latest_validation(ev.id, "evaluation")
        if latest_rule_validation is None:
            latest_rule_validation = engine.validate_subject(
                ev.id,
                "evaluation",
                [],
                use_bound_profiles=True,
                validation_id=uuid.uuid4().hex[:10],
                refs=analysis_refs,
            )
        rule_summary = engine.subject_rule_validation_summary(ev.id, "evaluation")
        if latest_rule_validation and not latest_rule_validation.passed_hard_gates:
            ev.passed = False
            pass_str = "FAIL"

    lines = [
        f"Session: {info.session_id} | Eval: {ev.id}",
        f"evaluation_id: {ev.id}",
        (f"Final score: {ev.final_score}/{rubric.scale_max} | Pass: {pass_str}"),
        (f"Threshold: {rubric.pass_threshold} | Strategy: {rubric.scoring_strategy}"),
        f"Findings: {len(ev.findings)} ({sev_str})",
        "Dimension scores:",
    ]
    lines.extend(dim_lines)
    if rule_summary is not None:
        lines.append(_format_rule_validation_summary(rule_summary))
    return "\n".join(lines)


# ── Tool: score_gate ─────────────────────────────────────────


async def score_gate(
    action: str,
    session_id: str | None = None,
    evaluation_id: str | None = None,
    rubric_id: str | None = None,
    limit: int = 10,
    use_latest: bool = False,
) -> str:
    """Check scoring gates or list evaluation history.

    Actions:
        gate: Lightweight pass/fail check for hooks. Returns
            pass boolean, score, threshold. If evaluation is not
            finalized, returns pass=? (indeterminate).
        list: Show evaluation history, optionally filtered by rubric.

    Args:
        action: gate or list.
        session_id: Thinking session ID. Required for list.
        evaluation_id: Which evaluation to check (for gate).
        rubric_id: Filter by rubric (for list).
        limit: Max evaluations to return (for list).

    Returns:
        Gate check result or evaluation list.
    """
    _validate_enum(action, _SCORE_GATE_ACTIONS, "action")

    if action == "gate":
        info, engine, ev = _find_evaluation_session(
            evaluation_id, session_id=session_id, use_latest=use_latest
        )
        rubric = engine.get_rubric(ev.rubric_id)
        if rubric is None:
            raise ValueError(
                f"Rubric '{ev.rubric_id}' referenced by evaluation '{ev.id}' not found"
            )
        threshold = rubric.pass_threshold

        if ev.status == "finalized":
            pass_str = "true" if ev.passed else "false"
            score_str = f"{ev.final_score}/{rubric.scale_max}"
            return (
                f"Session: {info.session_id} | Eval: {ev.id}\n"
                f"Pass: {pass_str} | Score: {score_str}"
                f" | Threshold: {threshold}\n"
                f"Blocking: {sum(1 for f in ev.findings if f.blocking)}"
                f" | Status: finalized"
            )
        else:
            score_str = f"{ev.running_score}/{rubric.scale_max}"
            return (
                f"Session: {info.session_id} | Eval: {ev.id}\n"
                f"Pass: ? | Score: {score_str} (running)"
                f" | Threshold: {threshold}\n"
                "Status: active (not finalized)"
            )

    # action == "list"
    if not session_id:
        raise ValueError("session_id is required for list")
    _, info = _require_think_session(session_id)
    engine = _engine(info)
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
            f"  {ev.id}: {score:.1f} {pass_str} ({len(ev.findings)} findings) — {date_str}"
        )
    if not evals:
        lines.append("  No evaluations found.")
    return "\n".join(lines)
