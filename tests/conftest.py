"""Shared test fixtures for AISmartBuddy tests."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.duckdb_engine import DuckDBEngine
from aismartbuddy.session import SessionManager


@pytest.fixture
def session_manager(tmp_path):
    """Create a SessionManager using a temp directory."""
    mgr = SessionManager(
        temp_base_dir=str(tmp_path),
        session_timeout=60,
        max_rows=100,
        max_chars=10000,
    )
    yield mgr
    mgr.cleanup_all()


@pytest.fixture
def _init_session_manager(session_manager: SessionManager):
    """Wire the `session_manager` fixture into the module-level singleton
    that tools read. Shared via conftest so test files don't duplicate."""
    import aismartbuddy.session as session_mod

    session_mod.session_manager = session_manager
    yield
    session_mod.session_manager = None


@pytest.fixture
def duckdb_engine(tmp_path):
    """Create a DuckDB engine with a temp database."""
    db_path = str(tmp_path / "test.duckdb")
    engine = DuckDBEngine(db_path, max_rows=100, max_chars=10000)
    engine.connect()
    yield engine
    engine.close()
