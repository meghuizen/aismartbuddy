"""iterate — ITERATE-mode lightweight build-test-learn cycle tracker.

3 fields per attempt (approach/result/learning). Optional metric_value
enables ratcheting + stagnation detection (M5 — already wired here).
"""

from __future__ import annotations

import uuid

import anyio
from mcp.server.fastmcp import Context as _MCPContext

from aismartbuddy.engines.thinking_engine import (
    IterationRecord,
    ThinkingEngine,
)
from aismartbuddy.tools.think import _get_or_create_think_session

_ACTIONS = frozenset({"start", "attempt", "status", "conclude"})
_STAGNATION_WINDOW = 3


def _engine(info) -> ThinkingEngine:
    assert isinstance(info.engine, ThinkingEngine)
    return info.engine


async def iterate(
    action: str,
    session_id: str | None = None,
    iteration_id: str | None = None,
    goal: str | None = None,
    attempt: dict | None = None,
    conclusion: str | None = None,
    higher_is_better: bool = True,
    ctx: _MCPContext | None = None,
) -> str:
    """[ELABORATE] Track a build-test-learn cycle. Lightweight by design.

    Actions:
        start: Begin a new iteration. Requires goal. Returns iteration_id.
        attempt: Record one attempt. Requires attempt={approach, result,
            learning}. Optional metric_name + metric_value enable ratcheting:
            server tracks best_so_far, marks improvements, detects stagnation
            (last N attempts all worse than best).
        status: Show full attempt history with trend + stagnation flag.
        conclude: Mark iteration complete. Optional conclusion text.

    Args:
        action: start | attempt | status | conclude.
        session_id: Thinking session ID. Omit to auto-create.
        iteration_id: Required for attempt | status | conclude.
        goal: Required for start.
        attempt: Required for action=attempt. Dict with approach, result,
            learning (all required) and optional metric_name, metric_value.
        conclusion: Optional summary text for conclude.
        higher_is_better: Direction for metric ratchet (True = maximize).
            Set on first metric attempt.

    Returns:
        Compact status with trend + (if metric) best_metric.
    """
    if action not in _ACTIONS:
        raise ValueError(
            f"action must be one of {sorted(_ACTIONS)}, got {action!r}"
        )

    _, info = await anyio.to_thread.run_sync(
        lambda: _get_or_create_think_session(session_id, ctx)
    )
    engine = _engine(info)

    # ── start ──────────────────────────────────────────────
    if action == "start":
        if not goal:
            raise ValueError("start requires 'goal'")
        iid = uuid.uuid4().hex[:10]
        rec = IterationRecord(iteration_id=iid, goal=goal)
        with engine.state_lock:
            engine.iterations[iid] = rec
        return (
            f"Session: {info.session_id} | Iteration: {iid}\n"
            f"Goal: {goal[:80]}\n"
            "Status: started"
        )

    if not iteration_id:
        raise ValueError(
            f"action={action} requires 'iteration_id' "
            "(returned by action='start')"
        )
    rec = engine.iterations.get(iteration_id)
    if rec is None:
        raise ValueError(f"Iteration '{iteration_id}' not found")

    # ── attempt ────────────────────────────────────────────
    if action == "attempt":
        if not isinstance(attempt, dict):
            raise ValueError("attempt must be a dict")
        for f in ("approach", "result", "learning"):
            if not attempt.get(f):
                raise ValueError(f"attempt missing required '{f}'")

        with engine.state_lock:
            attempt_no = len(rec.attempts) + 1
            entry = {
                "attempt_no": attempt_no,
                "approach": attempt["approach"],
                "result": attempt["result"],
                "learning": attempt["learning"],
            }
            metric_name = attempt.get("metric_name")
            metric_value = attempt.get("metric_value")
            is_improvement = False
            stagnation = False
            if metric_value is not None:
                mv = float(metric_value)
                entry["metric_name"] = metric_name
                entry["metric_value"] = mv
                # Initialize ratchet on first metric attempt
                if rec.metric_name is None:
                    rec.metric_name = metric_name or "metric"
                    rec.higher_is_better = higher_is_better
                    rec.best_metric = mv
                    is_improvement = True
                else:
                    if rec.higher_is_better:
                        is_improvement = mv > (rec.best_metric or float("-inf"))
                    else:
                        is_improvement = mv < (rec.best_metric or float("inf"))
                    if is_improvement:
                        rec.best_metric = mv
                rec.metric_history.append(mv)
                # Stagnation: last N attempts all worse than best
                window = rec.metric_history[-_STAGNATION_WINDOW:]
                if len(window) >= _STAGNATION_WINDOW:
                    if rec.higher_is_better:
                        stagnation = all(
                            v < (rec.best_metric or float("-inf"))
                            for v in window
                        )
                    else:
                        stagnation = all(
                            v > (rec.best_metric or float("inf"))
                            for v in window
                        )
            entry["is_improvement"] = is_improvement
            rec.attempts.append(entry)

        parts = [
            f"Session: {info.session_id} | Iteration: {iteration_id}"
            f" | Attempt: {attempt_no}",
            f"Approach: {attempt['approach'][:80]}",
            f"Result: {attempt['result'][:80]}",
            f"Learning: {attempt['learning'][:80]}",
        ]
        if metric_value is not None:
            parts.append(
                f"Metric: {rec.metric_name}={metric_value} | "
                f"Best: {rec.best_metric} | "
                f"Improvement: {is_improvement}"
            )
            if stagnation:
                parts.append(
                    "⚠ Stagnation: last 3 attempts all below best — "
                    "consider radical change or conclude."
                )
        parts.append("Status: recorded")
        return "\n".join(parts)

    # ── status ─────────────────────────────────────────────
    if action == "status":
        n = len(rec.attempts)
        parts = [
            f"Session: {info.session_id} | Iteration: {iteration_id}",
            f"Goal: {rec.goal[:80]} | Attempts: {n}"
            f" | Complete: {rec.is_complete}",
        ]
        if rec.metric_name:
            parts.append(
                f"Metric: {rec.metric_name} | Best: {rec.best_metric}"
                f" | History: {rec.metric_history}"
            )
        if n > 0:
            parts.append("Recent attempts:")
            for entry in rec.attempts[-5:]:
                line = (
                    f"  #{entry['attempt_no']}: {entry['approach'][:60]} "
                    f"→ {entry['result'][:60]}"
                )
                if "metric_value" in entry:
                    line += f" [m={entry['metric_value']}]"
                parts.append(line)
        return "\n".join(parts)

    # ── conclude ───────────────────────────────────────────
    with engine.state_lock:
        rec.is_complete = True
        if conclusion:
            rec.conclusion = conclusion
    return (
        f"Session: {info.session_id} | Iteration: {iteration_id}\n"
        f"Attempts: {len(rec.attempts)}"
        + (f" | Best metric: {rec.best_metric}"
           if rec.metric_name else "")
        + f"\nConclusion: {(conclusion or '')[:80]}\n"
        "Status: concluded"
    )
