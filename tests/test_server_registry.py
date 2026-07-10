from __future__ import annotations

import pytest

from aismartbuddy import config as cfg
from aismartbuddy.server import _build_tool_specs, aismartbuddy_guide
from aismartbuddy.tool_catalog import ToolSpec
from aismartbuddy.tools.graph import graph_import
from aismartbuddy.tools.sql import sql_import, sql_import_batch


def _tool_names(specs: list[ToolSpec]) -> set[str]:
    return {spec.name for spec in specs}


def test_default_registry_hides_legacy_reasoning_surface():
    names = _tool_names(_build_tool_specs(False))
    assert "think_model" in names
    assert "think_rules" in names
    assert "think_validate" in names
    assert "extract_findings_from_sql" in names
    assert "brainstorm" in names
    assert "scaffold" not in names
    assert "hypothesize" not in names
    assert "reason_graph" not in names
    assert "reason_index" not in names


def test_legacy_registry_can_be_reenabled():
    names = _tool_names(_build_tool_specs(True))
    assert "scaffold" in names
    assert "hypothesize" in names
    assert "reason_graph" in names
    assert "reason_index" in names


@pytest.mark.anyio
async def test_guide_uses_think_first_language():
    original = cfg.runtime_config.expose_legacy_reasoning_tools
    cfg.runtime_config.expose_legacy_reasoning_tools = False
    try:
        guide = await aismartbuddy_guide()
    finally:
        cfg.runtime_config.expose_legacy_reasoning_tools = original
    assert "Migration map for older reasoning concepts" in guide
    assert "think_rules(...)" in guide
    assert "think_validate(...)" in guide
    assert (
        "extract_findings_from_sql / extract_findings_from_graph stay public as bridge tools"
        in guide
    )
    assert 'score_evaluate(action="review", evaluation_id)' in guide


def test_import_docstrings_include_general_shapes():
    assert "entity-score table" in (sql_import.__doc__ or "")
    assert "data_profile" in (sql_import.__doc__ or "")
    assert "wide matrix" in (sql_import_batch.__doc__ or "")
    assert "edge list" in (graph_import.__doc__ or "")
