from __future__ import annotations

import inspect
import json

import pytest

from aismartbuddy.server import _build_tool_specs, mcp
from aismartbuddy.tool_catalog import TOOL_DESCRIPTIONS, description_for


def test_default_catalog_keeps_existing_tools_and_adds_only_router():
    specs = _build_tool_specs(False)
    names = {spec.name for spec in specs}
    assert len(specs) == 75
    assert "suggest_reasoning" in names
    assert len(names - {"suggest_reasoning"}) == 74


def test_every_tool_uses_explicit_concise_copy_not_its_docstring():
    specs = _build_tool_specs(True)
    assert {spec.name for spec in specs} <= set(TOOL_DESCRIPTIONS)
    for spec in specs:
        assert spec.description == description_for(spec.name)
        assert spec.description.strip()
        assert spec.description != (inspect.getdoc(spec.implementation) or "")
        assert len(spec.description) <= 600
        for forbidden in ("Args:", "Returns:", "```", "|---", "Example:"):
            assert forbidden not in spec.description


@pytest.mark.anyio
async def test_serialized_catalog_stays_within_context_budgets():
    rows = [tool.model_dump(mode="json", exclude_none=True) for tool in await mcp.list_tools()]
    descriptions = sum(len(row.get("description") or "") for row in rows)
    serialized = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    assert descriptions <= 22_000
    assert len(serialized) <= 110_000


@pytest.mark.anyio
async def test_input_field_descriptions_are_short_when_present():
    rows = [tool.model_dump(mode="json", exclude_none=True) for tool in await mcp.list_tools()]
    field_descriptions: list[str] = []

    def collect(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "description" and isinstance(child, str):
                    field_descriptions.append(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for row in rows:
        collect(row.get("input_schema", {}))
    assert all(len(value) <= 160 for value in field_descriptions)
