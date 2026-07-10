from __future__ import annotations

import pytest

from aismartbuddy.tools.graph import graph_query
from aismartbuddy.tools.infra import session_create, session_destroy
from aismartbuddy.tools.sql import sql_query
from aismartbuddy.tools.think import (
    think_get_session_links,
    think_graph,
    think_summarize,
)


def _value(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line.split(prefix, 1)[1].strip().split(" | ", 1)[0]
    raise AssertionError(f"Missing {prefix!r} in {text}")


def test_shared_handle_reuses_engine_lock_and_reference_counts(session_manager):
    source = session_manager.create_session("think", "u", "p")
    alias = session_manager.create_shared_session(source.session_id, "think", "u", "p")
    assert alias.engine is source.engine
    assert alias.lock is source.lock
    assert {item.session_id for item in session_manager.list_shared_members(source.session_id)} == {
        alias.session_id
    }

    session_manager.destroy_session(source.session_id)
    assert session_manager.get_session(alias.session_id).engine is alias.engine
    session_manager.destroy_session(alias.session_id)


def test_shared_handle_rejects_different_project(session_manager):
    source = session_manager.create_session("think", "u", "p1")
    with pytest.raises(ValueError, match="same user_id and project_id"):
        session_manager.create_shared_session(source.session_id, "think", "u", "p2")


@pytest.mark.usefixtures("_init_session_manager")
class TestSharedUnifiedSessions:
    @pytest.mark.anyio
    async def test_all_backends_are_mutable_and_survive_source_close(self):
        source_text = await session_create(backends=["think", "sql", "graph"])
        source = _value(source_text, "session_id:")

        await think_graph(thought="Shared reasoning root", session_id=source)
        await sql_query(
            query="CREATE TABLE shared_values(id INTEGER, value VARCHAR);",
            session_id=source,
        )
        await sql_query(
            query="INSERT INTO shared_values VALUES (1, 'visible');",
            session_id=source,
        )
        await graph_query(
            query="CREATE NODE TABLE SharedNode(id INT64 PRIMARY KEY, name STRING);",
            session_id=source,
        )
        await graph_query(
            query="CREATE (:SharedNode {id: 1, name: 'visible'});",
            session_id=source,
        )

        clone_text = await session_create(
            backends=["think", "sql", "graph"],
            share_from_session_id=source,
            share_backends=["think", "sql", "graph"],
        )
        clone = _value(clone_text, "session_id:")

        assert "Shared reasoning root" in await think_summarize(
            session_id=clone, detail_level="synopsis"
        )
        assert "visible" in await sql_query(
            query="SELECT value FROM shared_values;", session_id=clone
        )
        assert "visible" in await graph_query(
            query="MATCH (n:SharedNode) RETURN n.name;", session_id=clone
        )
        links = await think_get_session_links(session_id=clone)
        assert "Shared mutable members" in links

        await session_destroy(source)
        assert "visible" in await sql_query(
            query="SELECT value FROM shared_values;", session_id=clone
        )
        await think_graph(thought="Clone continues", session_id=clone)
        assert "Clone continues" in await think_summarize(session_id=clone, detail_level="synopsis")
        await session_destroy(clone)
