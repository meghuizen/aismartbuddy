"""Tests for performance guards: timeouts, size limits, depth bounds.

Covers Phase 0 (M0) items: P2 bounded computation, P4 response size.
"""

from __future__ import annotations

import pytest

from aismartbuddy.tools.graph import graph_create_session, graph_query


async def _extract_sid(create_fn) -> str:
    """Parse session_id from a *_create_session tool response."""
    result = await create_fn()
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("session_id:"):
            return line[len("session_id:"):].strip()
    raise AssertionError(f"no session_id in {result!r}")


@pytest.mark.usefixtures("_init_session_manager")
class TestGraphQueryTimeout:
    @pytest.mark.anyio
    async def test_timeout_parameter_accepted(self, session_manager):
        """graph_query accepts timeout_ms parameter without crashing."""
        sid = await _extract_sid(graph_create_session)
        # Any valid positive timeout_ms is accepted; normal-speed queries finish well under it.
        result = await graph_query(
            session_id=sid,
            query="CREATE NODE TABLE X (id INT64 PRIMARY KEY);",
            timeout_ms=5000,
        )
        assert "timed out" not in result.lower()

    @pytest.mark.anyio
    async def test_timeout_disabled_when_zero(self, session_manager):
        """timeout_ms=0 disables the deadline — fast queries still succeed."""
        sid = await _extract_sid(graph_create_session)
        # Create a trivial node to query against
        await graph_query(
            session_id=sid,
            query="CREATE NODE TABLE Item (id INT64 PRIMARY KEY, name STRING);",
            timeout_ms=0,
        )
        result = await graph_query(
            session_id=sid,
            query="MATCH (n:Item) RETURN n.id LIMIT 10;",
            timeout_ms=0,
        )
        # No timeout error path taken; result is normal query output
        assert "timed out" not in result.lower()

    @pytest.mark.anyio
    async def test_default_timeout_10s_allows_normal_queries(self, session_manager):
        """Default timeout (10s) does not interfere with normal-speed queries."""
        sid = await _extract_sid(graph_create_session)
        await graph_query(
            session_id=sid,
            query="CREATE NODE TABLE T (id INT64 PRIMARY KEY);",
        )
        result = await graph_query(
            session_id=sid, query="MATCH (n:T) RETURN n.id LIMIT 5;",
        )
        assert "timed out" not in result.lower()


@pytest.mark.usefixtures("_init_session_manager")
class TestMinNodesGuard:
    @pytest.mark.anyio
    async def test_infer_rejects_small_graph(self):
        from aismartbuddy.tools.graph import (
            graph_knowledge_infer,
            knowledge_batch,
        )

        sid = await _extract_sid(graph_create_session)
        # Add only 3 nodes — below default min_nodes_override=10
        await knowledge_batch(
            session_id=sid,
            nodes=[{"entity": f"n{i}"} for i in range(3)],
        )
        result = await graph_knowledge_infer(
            session_id=sid, inference_type="chains",
        )
        assert "Minimum" in result and "recommended" in result.lower()

    @pytest.mark.anyio
    async def test_infer_runs_when_above_threshold(self):
        from aismartbuddy.tools.graph import (
            graph_knowledge_infer,
            knowledge_batch,
        )

        sid = await _extract_sid(graph_create_session)
        await knowledge_batch(
            session_id=sid,
            nodes=[{"entity": f"n{i}"} for i in range(5)],
        )
        # Lower the threshold for the call
        result = await graph_knowledge_infer(
            session_id=sid, inference_type="clusters",
            min_nodes_override=3,
        )
        # Doesn't reject — runs the actual inference
        assert "Minimum" not in result


class TestSizeGuarded:
    """size_guarded decorator truncates oversized responses with a hint."""

    @pytest.mark.anyio
    async def test_truncates_above_500kb(self):
        from aismartbuddy.tools import size_guarded

        @size_guarded
        async def fake_tool() -> str:
            # 600KB single-byte string — exceeds 500KB cap
            return "a" * (600 * 1024)

        result = await fake_tool()
        assert "truncated" in result.lower()
        assert "500kb" in result.lower()
        # Result is bounded near the 500KB cap (plus the truncation hint)
        assert len(result.encode("utf-8")) < 600 * 1024

    @pytest.mark.anyio
    async def test_passes_through_under_threshold(self):
        from aismartbuddy.tools import size_guarded

        @size_guarded
        async def fake_tool() -> str:
            return "small response"

        result = await fake_tool()
        assert result == "small response"

    @pytest.mark.anyio
    async def test_warn_threshold_does_not_truncate(self):
        from aismartbuddy.tools import size_guarded

        @size_guarded
        async def fake_tool() -> str:
            # 60KB — over warn (50KB) but under truncate (500KB)
            return "x" * (60 * 1024)

        result = await fake_tool()
        # Returned in full, no truncation message
        assert "truncated" not in result.lower()
        assert len(result) == 60 * 1024
