"""Tests for new mode tools that survived the redesign:

- iterate (lightweight build-test-learn cycles)
- data_profile / data_anomalies (DuckDB shortcuts)
- brainstorm (DIVERGE — quantity before quality)

Removed in S3a/S3b/S3c: scaffold, hypothesize, self_assess, session_export,
session_snapshot, workflow tests. Their behaviour is being absorbed into
upgraded think_model / think_science / think_monitor (see steps S2a–S2d).
"""

from __future__ import annotations

import pytest


def _extract_sid(result: str) -> str:
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("session_id:"):
            return line[len("session_id:"):].strip()
        if line.startswith("Session:"):
            for part in line.split(" | "):
                part = part.strip()
                if part.startswith("Session:"):
                    return part[len("Session:"):].strip()
    raise AssertionError(f"no session_id in {result!r}")


@pytest.mark.usefixtures("_init_session_manager")
class TestIterate:
    @staticmethod
    def _iter_id(start_response: str) -> str:
        for line in start_response.split("\n"):
            for part in line.split(" | "):
                part = part.strip()
                if part.startswith("Iteration:"):
                    return part[len("Iteration:"):].strip()
        raise AssertionError(f"no iteration_id in {start_response!r}")

    @pytest.mark.anyio
    async def test_full_cycle(self):
        from aismartbuddy.tools.iterate import iterate

        r1 = await iterate(action="start", goal="Tune RSI threshold")
        sid = _extract_sid(r1)
        iid = self._iter_id(r1)

        r2 = await iterate(
            action="attempt", session_id=sid, iteration_id=iid,
            attempt={
                "approach": "RSI=14",
                "result": "win rate 51%",
                "learning": "try shorter period",
            },
        )
        assert "Attempt: 1" in r2

        r3 = await iterate(
            action="status", session_id=sid, iteration_id=iid,
        )
        assert "Attempts: 1" in r3

        r4 = await iterate(
            action="conclude",
            session_id=sid, iteration_id=iid,
            conclusion="RSI=14 was the best of 1 attempt",
        )
        assert "Status: concluded" in r4

    @pytest.mark.anyio
    async def test_metric_ratchet_improvement(self):
        from aismartbuddy.tools.iterate import iterate

        r1 = await iterate(action="start", goal="Maximize win rate")
        sid = _extract_sid(r1)
        iid = self._iter_id(r1)

        await iterate(
            action="attempt", session_id=sid, iteration_id=iid,
            attempt={
                "approach": "v1", "result": "ok", "learning": "next",
                "metric_name": "win_rate", "metric_value": 0.51,
            },
        )
        r2 = await iterate(
            action="attempt", session_id=sid, iteration_id=iid,
            attempt={
                "approach": "v2", "result": "better",
                "learning": "keep going",
                "metric_name": "win_rate", "metric_value": 0.55,
            },
        )
        assert "Improvement: True" in r2
        assert "Best: 0.55" in r2

    @pytest.mark.anyio
    async def test_stagnation_detected(self):
        from aismartbuddy.tools.iterate import iterate

        r1 = await iterate(action="start", goal="Maximize")
        sid = _extract_sid(r1)
        iid = self._iter_id(r1)

        await iterate(
            action="attempt", session_id=sid, iteration_id=iid,
            attempt={
                "approach": "a", "result": "ok", "learning": "x",
                "metric_value": 10.0,
            },
        )
        r = ""
        for v in (5.0, 6.0, 7.0):
            r = await iterate(
                action="attempt", session_id=sid, iteration_id=iid,
                attempt={
                    "approach": "a", "result": "ok", "learning": "x",
                    "metric_value": v,
                },
            )
        assert "Stagnation" in r

    @pytest.mark.anyio
    async def test_attempt_missing_field_rejected(self):
        from aismartbuddy.tools.iterate import iterate

        r1 = await iterate(action="start", goal="g")
        sid = _extract_sid(r1)
        iid = self._iter_id(r1)
        with pytest.raises(ValueError, match="missing required 'learning'"):
            await iterate(
                action="attempt", session_id=sid, iteration_id=iid,
                attempt={"approach": "a", "result": "r"},
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestDataExplore:
    async def _setup_table(self) -> str:
        from aismartbuddy.tools.sql import sql_create_session, sql_query

        sid = _extract_sid(await sql_create_session())
        await sql_query(
            session_id=sid,
            query="CREATE TABLE sales (id INTEGER, amount DOUBLE, region VARCHAR);",
        )
        rows = [f"({i}, {100.0 + i}, 'east')" for i in range(10)]
        rows.append("(99, 99999.0, 'west')")  # outlier
        await sql_query(
            session_id=sid,
            query=f"INSERT INTO sales VALUES {', '.join(rows)};",
        )
        return sid

    @pytest.mark.anyio
    async def test_data_profile_returns_summary(self):
        from aismartbuddy.tools.sql import data_profile

        sid = await self._setup_table()
        r = await data_profile(session_id=sid, table="sales")
        assert "column_name" in r or "amount" in r

    @pytest.mark.anyio
    async def test_data_anomalies_zscore_finds_outlier(self):
        from aismartbuddy.tools.sql import data_anomalies

        sid = await self._setup_table()
        r = await data_anomalies(
            session_id=sid, table="sales", columns=["amount"],
            method="zscore", threshold=2.0,
        )
        assert "99999" in r

    @pytest.mark.anyio
    async def test_data_anomalies_isolation_forest_not_implemented(self):
        from aismartbuddy.tools.sql import data_anomalies

        sid = await self._setup_table()
        with pytest.raises(NotImplementedError, match="external library"):
            await data_anomalies(
                session_id=sid, table="sales", columns=["amount"],
                method="isolation_forest",
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestBrainstorm:
    @pytest.mark.anyio
    async def test_below_min_ideas_rejected(self):
        from aismartbuddy.tools.brainstorm import brainstorm

        ideas = [{"idea": f"idea {i}", "spark": "thinking"} for i in range(3)]
        with pytest.raises(ValueError, match="min_ideas=10"):
            await brainstorm(topic="x", ideas=ideas)

    @pytest.mark.anyio
    async def test_at_min_ideas_succeeds(self):
        from aismartbuddy.tools.brainstorm import brainstorm

        ideas = [
            {"idea": f"a wild idea about {i}", "spark": "what if X"}
            for i in range(10)
        ]
        r = await brainstorm(
            topic="campaign names", ideas=ideas, style="wild",
        )
        assert "Ideas: 10" in r

    @pytest.mark.anyio
    async def test_clustering_groups_shared_keywords(self):
        from aismartbuddy.tools.brainstorm import brainstorm

        ideas = [
            {"idea": "mitochondria support energy production",
             "spark": "biology"},
            {"idea": "energy mitochondria can be optimized via diet",
             "spark": "fitness"},
            {"idea": "mitochondria energy decline with age",
             "spark": "aging research"},
            {"idea": "marketing pitch about coffee", "spark": "branding"},
            {"idea": "marketing pitch about tea", "spark": "branding"},
        ] + [{"idea": f"random idea {i}", "spark": "x"} for i in range(5)]
        r = await brainstorm(topic="random", ideas=ideas, style="wild")
        assert "cluster_0:" in r

    @pytest.mark.anyio
    async def test_missing_spark_rejected(self):
        from aismartbuddy.tools.brainstorm import brainstorm

        ideas = [{"idea": f"idea {i}"} for i in range(10)]
        with pytest.raises(ValueError, match="missing 'spark'"):
            await brainstorm(topic="t", ideas=ideas)

    @pytest.mark.anyio
    async def test_invalid_style_rejected(self):
        from aismartbuddy.tools.brainstorm import brainstorm

        with pytest.raises(ValueError, match="style must be one of"):
            await brainstorm(
                topic="t", style="invalid",
                ideas=[
                    {"idea": f"i{i}", "spark": "s"} for i in range(10)
                ],
            )
