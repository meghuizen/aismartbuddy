"""Tests for session management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aismartbuddy.session import SessionManager


def test_create_sql_session(session_manager: SessionManager):
    info = session_manager.create_session("sql")
    assert info.session_id
    assert info.session_type == "sql"
    assert info.engine is not None
    assert "data.duckdb" in info.db_path


def test_create_graph_session(session_manager: SessionManager):
    info = session_manager.create_session("graph")
    assert info.session_id
    assert info.session_type == "graph"
    assert info.engine is not None
    assert "graph.lbug" in info.db_path


def test_get_session(session_manager: SessionManager):
    info = session_manager.create_session("sql")
    retrieved = session_manager.get_session(info.session_id)
    assert retrieved.session_id == info.session_id
    assert retrieved.session_type == "sql"


def test_get_session_not_found(session_manager: SessionManager):
    with pytest.raises(ValueError, match="not found"):
        session_manager.get_session("nonexistent")


def test_destroy_session(session_manager: SessionManager):
    info = session_manager.create_session("sql")
    session_manager.destroy_session(info.session_id)
    with pytest.raises(ValueError, match="not found"):
        session_manager.get_session(info.session_id)


def test_destroy_nonexistent_session(session_manager: SessionManager):
    with pytest.raises(ValueError, match="not found"):
        session_manager.destroy_session("nonexistent")


def test_list_sessions(session_manager: SessionManager):
    session_manager.create_session("sql")
    session_manager.create_session("graph")
    sessions = session_manager.list_sessions()
    assert len(sessions) == 2
    types = {s.session_type for s in sessions}
    assert types == {"sql", "graph"}


def test_cleanup_expired(tmp_path):
    mgr = SessionManager(temp_base_dir=str(tmp_path), session_timeout=1, max_rows=100)
    info = mgr.create_session("sql")
    # Force the session to be expired
    info.last_accessed = datetime.now(timezone.utc) - timedelta(seconds=10)
    removed = mgr.cleanup_expired()
    assert removed == 1
    assert len(mgr.list_sessions()) == 0


def test_cleanup_all(session_manager: SessionManager):
    session_manager.create_session("sql")
    session_manager.create_session("graph")
    session_manager.cleanup_all()
    assert len(session_manager.list_sessions()) == 0


def test_invalid_session_type(session_manager: SessionManager):
    with pytest.raises(ValueError, match="Invalid session_type"):
        session_manager.create_session("nosql")
