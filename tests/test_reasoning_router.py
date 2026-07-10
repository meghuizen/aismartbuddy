from __future__ import annotations

import pytest

from aismartbuddy.engines.thinking_engine import ThinkingEngine
from aismartbuddy.framework_catalog import framework_catalog, render_catalog
from aismartbuddy.server import get_reasoning_framework
from aismartbuddy.tools.meta import suggest_reasoning
from aismartbuddy.tools.think import _MODEL_GUIDANCE, _MODEL_NAMES, think_model


def _value(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split(prefix, 1)[1].strip().split(" | ", 1)[0]
    raise AssertionError(f"Missing {prefix!r} in {text}")


def test_every_accepted_model_has_guidance():
    assert _MODEL_NAMES <= set(_MODEL_GUIDANCE)


def test_framework_catalog_lists_installable_guidance():
    specs = framework_catalog.list()
    assert len(specs) == 16
    assert "strategic-resolution" in {spec.id for spec in specs}
    assert "suggest_reasoning" in render_catalog()
    guidance = framework_catalog.guidance("strategic-resolution")
    assert "Strategic Resolution" in guidance


def test_router_is_deterministic_and_depth_changes_route():
    quick = framework_catalog.recommend(
        "Decide between two architecture options under uncertainty",
        intent="auto",
        depth="quick",
    )
    deep = framework_catalog.recommend(
        "Decide between two architecture options under uncertainty",
        intent="auto",
        depth="deep",
    )
    assert quick.intent == "make_decision"
    assert quick.steps[0].tool == "think_decide"
    assert len(deep.steps) > len(quick.steps)
    assert deep.steps[-1].tool == "think_monitor"


@pytest.mark.usefixtures("_init_session_manager")
class TestReasoningRouteProgress:
    @pytest.mark.anyio
    async def test_suggest_reasoning_stores_and_advances_route(self):
        route = await suggest_reasoning(
            "Diagnose the root cause of repeated deployment failures",
            intent="solve_problem",
            depth="standard",
        )
        assert "Entry tool: think_model" in route

        first = await think_model(
            model_name="root_cause",
            items=[
                {
                    "id": "root_model",
                    "problem": "Deployments repeatedly fail",
                    "steps": ["Separate symptoms from causes"],
                    "reasoning": "The failure starts before deployment completes.",
                    "conclusion": "Test pipeline and environment causes independently.",
                }
            ],
        )
        sid = _value(first, "Session:")
        stored = await suggest_reasoning(
            "Diagnose the root cause of repeated deployment failures",
            session_id=sid,
            intent="solve_problem",
            depth="standard",
        )
        assert f"Stored in session: {sid}" in stored

        await think_model(
            model_name="root_cause",
            session_id=sid,
            items=[
                {
                    "id": "root_model_2",
                    "problem": "Deployments repeatedly fail",
                    "steps": ["Test the first causal hypothesis"],
                    "reasoning": "The pipeline failure is independently observable.",
                    "conclusion": "Continue with competing hypotheses.",
                }
            ],
        )
        from aismartbuddy.tools import get_session_manager

        info = get_session_manager().resolve_backend_session(sid, "think")
        assert isinstance(info.engine, ThinkingEngine)
        progress = info.engine.get_reasoning_progress()
        assert progress is not None
        assert progress.completed_tools == ["think_model"]
        assert progress.next_tool == "think_hypothesis"


@pytest.mark.anyio
async def test_framework_resource_returns_full_guidance():
    resource = await get_reasoning_framework("redteam")
    assert resource.startswith("# Red Team")
    assert "failure" in resource.lower()
