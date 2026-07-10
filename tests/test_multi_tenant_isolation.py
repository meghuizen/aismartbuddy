"""Multi-tenant isolation tests.

Verifies that sessions are properly isolated by (user_id, project_id),
that session_id is treated as a capability token, that ownership checks
prevent cross-user access, and that per-session locks serialize concurrent
access from multiple agents sharing the same session.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, cast

import pytest

from aismartbuddy.identity import resolve_identity, validate_identity
from aismartbuddy.session import SessionManager


@pytest.fixture
def mt_manager(tmp_path):
    """SessionManager configured for multi-tenant testing."""
    mgr = SessionManager(
        temp_base_dir=str(tmp_path),
        session_timeout=60,
        max_rows=100,
        max_chars=10000,
    )
    yield mgr
    mgr.cleanup_all()


# ── Identity resolution ──────────────────────────────────────


class TestIdentityResolution:
    def test_validate_identity_accepts_safe(self):
        validate_identity("alice", "user_id")
        validate_identity("my-project_2024", "project_id")
        validate_identity("a.b.c", "user_id")

    def test_validate_identity_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            validate_identity("../etc", "user_id")
        with pytest.raises(ValueError):
            validate_identity("a/b", "user_id")
        with pytest.raises(ValueError):
            validate_identity("..", "user_id")

    def test_validate_identity_rejects_empty_or_too_long(self):
        with pytest.raises(ValueError):
            validate_identity("", "user_id")
        with pytest.raises(ValueError):
            validate_identity("x" * 65, "user_id")

    def test_resolve_identity_param_fallback(self):
        user_id, project_id = resolve_identity(
            ctx=None, user_id="alice", project_id="acme"
        )
        assert user_id == "alice"
        assert project_id == "acme"

    def test_resolve_identity_defaults(self):
        user_id, project_id = resolve_identity(ctx=None)
        assert user_id == "default"
        assert project_id == "default"

    def test_resolve_identity_ctx_overrides_param(self):
        """Request metadata client_id wins when no bearer auth is present."""
        class FakeCtx:
            client_id = "authenticated_user"
        user_id, _ = resolve_identity(
            ctx=cast(Any, FakeCtx()),
            user_id="attacker_claim",
            project_id="p",
        )
        assert user_id == "authenticated_user"


# ── Session ownership ────────────────────────────────────────


class TestOwnership:
    def test_sessions_isolated_by_user(self, mt_manager):
        alice = mt_manager.create_session("sql", "alice", "acme")
        bob = mt_manager.create_session("sql", "bob", "acme")
        assert alice.session_id != bob.session_id
        assert alice.user_id == "alice"
        assert bob.user_id == "bob"

    def test_list_sessions_filters_by_user(self, mt_manager):
        mt_manager.create_session("sql", "alice", "acme")
        mt_manager.create_session("sql", "alice", "other")
        mt_manager.create_session("sql", "bob", "acme")
        alice_sessions = mt_manager.list_sessions(user_id="alice")
        assert len(alice_sessions) == 2
        assert all(s.user_id == "alice" for s in alice_sessions)

    def test_list_sessions_filters_by_project(self, mt_manager):
        mt_manager.create_session("sql", "alice", "acme")
        mt_manager.create_session("sql", "alice", "other")
        acme_sessions = mt_manager.list_sessions(
            user_id="alice", project_id="acme"
        )
        assert len(acme_sessions) == 1
        assert acme_sessions[0].project_id == "acme"

    def test_cross_user_access_rejected(self, mt_manager):
        alice = mt_manager.create_session("sql", "alice", "acme")
        # Bob tries to access alice's session
        with pytest.raises(ValueError, match="not found"):
            mt_manager.get_session(alice.session_id, user_id="bob", project_id="acme")

    def test_cross_project_access_rejected(self, mt_manager):
        alice = mt_manager.create_session("sql", "alice", "acme")
        # Same user, wrong project
        with pytest.raises(ValueError, match="not found"):
            mt_manager.get_session(alice.session_id, user_id="alice", project_id="other")

    def test_same_user_same_project_can_access(self, mt_manager):
        info = mt_manager.create_session("sql", "alice", "acme")
        # Same identity — should work
        fetched = mt_manager.get_session(
            info.session_id, user_id="alice", project_id="acme"
        )
        assert fetched.session_id == info.session_id

    def test_session_id_as_capability_without_ownership_check(self, mt_manager):
        """When user_id and project_id are None, session_id alone suffices."""
        info = mt_manager.create_session("sql", "alice", "acme")
        fetched = mt_manager.get_session(info.session_id)
        assert fetched.session_id == info.session_id

    def test_not_found_message_constant_time(self, mt_manager):
        """The error text for 'session doesn't exist' and 'session owned by
        someone else' must be identical to prevent enumeration."""
        alice = mt_manager.create_session("sql", "alice", "acme")

        # Case 1: truly missing
        try:
            mt_manager.get_session("00000000000000000000000000000000")
            pytest.fail("expected ValueError for missing session")
        except ValueError as e:
            missing_msg = str(e)

        # Case 2: exists but owned by alice
        try:
            mt_manager.get_session(alice.session_id, user_id="bob", project_id="acme")
            pytest.fail("expected ValueError for wrong-owner session")
        except ValueError as e:
            wrong_user_msg = str(e)

        # Both must start with the same "Session 'X' not found" template
        assert missing_msg.split("'")[2:] == wrong_user_msg.split("'")[2:]


# ── Temp directory layout ───────────────────────────────────


class TestTempLayout:
    def test_temp_dir_reflects_hierarchy(self, mt_manager, tmp_path):
        info = mt_manager.create_session("sql", "alice", "acme")
        expected = Path(tmp_path) / "aismartbuddy" / "alice" / "acme" / info.session_id
        assert Path(info.temp_dir) == expected
        assert expected.exists()

    def test_path_traversal_rejected(self, mt_manager):
        with pytest.raises(ValueError):
            mt_manager.create_session("sql", "../evil", "project")
        with pytest.raises(ValueError):
            mt_manager.create_session("sql", "user", "a/b")

    def test_destroy_removes_session_dir(self, mt_manager):
        info = mt_manager.create_session("sql", "alice", "acme")
        session_dir = Path(info.temp_dir)
        assert session_dir.exists()
        mt_manager.destroy_session(info.session_id, user_id="alice", project_id="acme")
        assert not session_dir.exists()

    def test_destroy_with_wrong_owner_rejected(self, mt_manager):
        info = mt_manager.create_session("sql", "alice", "acme")
        with pytest.raises(ValueError, match="not found"):
            mt_manager.destroy_session(info.session_id, user_id="bob", project_id="acme")
        # Session should still exist
        still_there = mt_manager.get_session(info.session_id)
        assert still_there.session_id == info.session_id


# ── Session ID entropy ──────────────────────────────────────


class TestSessionId:
    def test_session_id_is_128_bits(self, mt_manager):
        info = mt_manager.create_session("sql", "alice", "acme")
        assert len(info.session_id) == 32
        # All hex chars
        int(info.session_id, 16)

    def test_session_ids_unique(self, mt_manager):
        ids = set()
        for _ in range(20):
            info = mt_manager.create_session("think", "alice", "acme")
            ids.add(info.session_id)
        assert len(ids) == 20


# ── Per-session lock (multi-agent serialization) ─────────────


class TestPerSessionLock:
    def test_session_has_lock(self, mt_manager):
        info = mt_manager.create_session("sql", "alice", "acme")
        assert info.lock is not None
        # Can acquire and release
        with info.lock:
            pass

    def test_concurrent_access_serializes(self, mt_manager):
        """Two threads holding info.lock serialize their critical sections."""
        info = mt_manager.create_session("sql", "alice", "acme")
        order = []

        def worker(name, hold_ms):
            with info.lock:
                order.append(f"{name}-enter")
                time.sleep(hold_ms / 1000.0)
                order.append(f"{name}-exit")

        t1 = threading.Thread(target=worker, args=("A", 50))
        t2 = threading.Thread(target=worker, args=("B", 50))
        t1.start()
        time.sleep(0.01)  # ensure A starts first
        t2.start()
        t1.join()
        t2.join()

        # Either A-enter,A-exit,B-enter,B-exit or B first — but never interleaved
        assert order[0].endswith("-enter")
        assert order[1].startswith(order[0].split("-")[0])  # same one exits
        assert order[2].endswith("-enter")
        assert order[3].startswith(order[2].split("-")[0])

    def test_different_sessions_parallel(self, mt_manager):
        """Different sessions do NOT serialize against each other."""
        s1 = mt_manager.create_session("sql", "alice", "p1")
        s2 = mt_manager.create_session("sql", "alice", "p2")

        started = threading.Event()
        s1_acquired = threading.Event()

        def holder_s1():
            with s1.lock:
                s1_acquired.set()
                started.wait(timeout=1.0)

        def holder_s2():
            s1_acquired.wait(timeout=1.0)
            # s1.lock is held; we should still acquire s2.lock immediately
            with s2.lock:
                started.set()  # signals that s2 got its lock too

        t1 = threading.Thread(target=holder_s1)
        t2 = threading.Thread(target=holder_s2)
        t1.start()
        t2.start()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)
        # If we got here without timeout, lock contention is per-session only
        assert started.is_set()


# ── Engine isolation end-to-end ─────────────────────────────


class TestEngineIsolation:
    def test_sql_sessions_have_separate_files(self, mt_manager):
        alice = mt_manager.create_session("sql", "alice", "acme")
        bob = mt_manager.create_session("sql", "bob", "acme")
        # Alice creates a table
        alice.engine.execute("CREATE TABLE secret (msg VARCHAR)")
        alice.engine.execute("INSERT INTO secret VALUES ('hello from alice')")
        # Bob's engine has no such table
        cols, rows = bob.engine.execute("SHOW TABLES")
        table_names = [r[0] for r in rows]
        assert "secret" not in table_names

    def test_think_sessions_have_separate_state(self, mt_manager):
        alice = mt_manager.create_session("think", "alice", "acme")
        bob = mt_manager.create_session("think", "bob", "acme")
        assert alice.engine is not bob.engine
        assert alice.engine.thought_nodes is not bob.engine.thought_nodes


# ── Scoring memory limits ───────────────────────────────────


class TestScoringLimits:
    def test_rubric_limit_enforced(self, mt_manager):
        from aismartbuddy.engines.thinking_engine import MAX_RUBRICS, RubricRecord

        info = mt_manager.create_session("think", "alice", "acme")
        engine = info.engine
        # Create more rubrics than the limit
        for i in range(MAX_RUBRICS + 20):
            engine.upsert_rubric(RubricRecord(id=f"r{i}", dimensions={}))
        # Should never exceed the cap (actual value: MAX_RUBRICS -1 to MAX_RUBRICS)
        assert len(engine.rubrics) <= MAX_RUBRICS


# ── ThinkingEngine multi-agent safety ────────────────────────


class TestThinkingEngineConcurrency:
    def test_concurrent_add_node_does_not_corrupt(self, mt_manager):
        """Multiple threads adding thought nodes to the SAME session engine
        must not corrupt the internal dicts. _synchronized decorator on
        add_node enforces this."""
        from aismartbuddy.engines.thinking_engine import ThoughtNode

        info = mt_manager.create_session("think", "alice", "acme")
        engine = info.engine

        def worker(worker_id: int):
            for i in range(50):
                node = ThoughtNode(
                    id=f"w{worker_id}_n{i}",
                    tree_id=f"t{worker_id}",
                    content=f"worker {worker_id} node {i}",
                    action="think",
                )
                engine.add_node(node)

        threads = [threading.Thread(target=worker, args=(wid,)) for wid in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        # All 10 workers × 50 nodes = 500 expected nodes, all unique
        # (under memory cap — MAX_NODES=2000, well within)
        assert len(engine.thought_nodes) == 500
        # Each tree's root correctly registered
        assert len(engine.thought_trees) == 10
