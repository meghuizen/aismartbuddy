from __future__ import annotations

import json
from pathlib import Path

from aismartbuddy.framework_catalog import framework_catalog


def test_reasoning_quality_corpus_is_complete_and_routes_as_expected():
    path = Path(__file__).resolve().parents[1] / "evals" / "reasoning_quality.json"
    tasks = json.loads(path.read_text(encoding="utf-8"))
    assert len(tasks) == 16
    assert len({task["id"] for task in tasks}) == 16
    categories = {task["category"] for task in tasks}
    assert {
        "diagnosis",
        "evidence_synthesis",
        "decision",
        "systems_reasoning",
        "adversarial_review",
        "novelty",
        "knowledge_retrieval",
        "data_supported_learning",
    } <= categories
    for task in tasks:
        route = framework_catalog.recommend(task["task"], intent="auto", depth="standard")
        assert route.intent == task["expected_intent"], task["id"]
        assert route.steps[0].tool == task["expected_entry_tool"], task["id"]
        assert task["quality_dimensions"]
