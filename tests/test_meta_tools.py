"""Tests for meta tools (suggest_database)."""

from __future__ import annotations

import pytest

from aismartbuddy.tools.meta import suggest_database


@pytest.mark.asyncio
async def test_suggest_sql_for_analytics():
    result = await suggest_database("analyze sales trends over time with aggregations")
    assert "SQL" in result
    assert "sql_create_session" in result


@pytest.mark.asyncio
async def test_suggest_graph_for_relationships():
    result = await suggest_database("find shortest path between users in a social network")
    assert "Graph" in result
    assert "graph_create_session" in result


@pytest.mark.asyncio
async def test_suggest_with_ambiguous_input():
    result = await suggest_database("process some data")
    # Should return a valid recommendation regardless
    assert "SQL" in result or "Graph" in result or "Both" in result


@pytest.mark.asyncio
async def test_suggest_graph_for_hierarchy():
    result = await suggest_database("model organizational hierarchy and find ancestors")
    assert "Graph" in result


@pytest.mark.asyncio
async def test_suggest_sql_for_csv():
    result = await suggest_database("import CSV file and calculate statistics")
    assert "SQL" in result
