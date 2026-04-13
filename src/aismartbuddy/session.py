"""Session management for AISmartBuddy database sessions.

Multi-tenant model:
- Every session is bound to (user_id, project_id) at creation.
- Session_id acts as a capability token (128-bit entropy, unguessable).
- When identity is known via ctx.client_id (Bearer auth), ownership is verified.
- Per-session threading.Lock serializes concurrent tool calls from multiple agents
  sharing the same session, preventing ThinkingEngine state corruption.
- Temp directory layout: {base}/aismartbuddy/{user_id}/{project_id}/{session_id}/
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Union

from aismartbuddy.identity import validate_identity

if TYPE_CHECKING:
    from aismartbuddy.engines.duckdb_engine import DuckDBEngine
    from aismartbuddy.engines.ladybug_engine import LadybugEngine
    from aismartbuddy.engines.thinking_engine import ThinkingEngine

logger = logging.getLogger("aismartbuddy.session")

# Consistent "not found" message — returned for both truly-missing sessions AND
# sessions the caller doesn't own. Prevents enumeration by error channel.
_NOT_FOUND_MSG_TMPL = (
    "Session '{session_id}' not found. "
    "Use sql_create_session, graph_create_session, or a think_* tool to create one."
)


@dataclass
class SessionInfo:
    """Metadata for an active database session.

    user_id + project_id form the ownership tuple. session_id alone is the
    capability token (sufficient to look up the session in this process).
    lock serializes tool calls that share a session across multiple agents.
    """

    session_id: str
    session_type: str  # "sql", "graph", or "think"
    user_id: str
    project_id: str
    db_path: str
    temp_dir: str
    created_at: datetime
    last_accessed: datetime
    engine: Union[DuckDBEngine, LadybugEngine, ThinkingEngine, None] = field(
        default=None, repr=False
    )
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class SessionManager:
    """Manages lifecycle of temporary database sessions.

    Thread-safe: mutations to _sessions are guarded by _lock. Per-session
    tool execution is guarded by each SessionInfo.lock. Heavy I/O (engine
    close, filesystem cleanup) happens outside _lock to avoid blocking
    lookups.
    """

    def __init__(
        self,
        temp_base_dir: str | None = None,
        session_timeout: int = 3600,
        cursor_timeout: int = 300,
        max_rows: int = 1000,
        max_chars: int = 50000,
        duckdb_threads: int = 0,
        duckdb_memory_limit: str = "256MB",
        ladybug_buffer_pool_size: int = 256 * 1024 * 1024,
        ladybug_max_threads: int = 0,
    ) -> None:
        self._session_timeout = session_timeout
        self._cursor_timeout = cursor_timeout
        self._max_rows = max_rows
        self._max_chars = max_chars
        self._duckdb_threads = duckdb_threads
        self._duckdb_memory_limit = duckdb_memory_limit
        self._ladybug_buffer_pool_size = ladybug_buffer_pool_size
        self._ladybug_max_threads = ladybug_max_threads
        self._sessions: dict[str, SessionInfo] = {}
        self._lock = threading.Lock()

        if temp_base_dir:
            self._base_dir = Path(temp_base_dir) / "aismartbuddy"
        else:
            self._base_dir = Path(tempfile.gettempdir()) / "aismartbuddy"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Session temp directory: %s", self._base_dir)

    @property
    def max_rows(self) -> int:
        return self._max_rows

    @property
    def max_chars(self) -> int:
        return self._max_chars

    @property
    def cursor_timeout(self) -> int:
        return self._cursor_timeout

    def create_session(
        self,
        session_type: str,
        user_id: str = "default",
        project_id: str = "default",
    ) -> SessionInfo:
        """Create a new database session bound to (user_id, project_id).

        Args:
            session_type: "sql" (DuckDB), "graph" (LadybugDB), or "think".
            user_id: Owner identity. Defaults to "default" for backward compat
                and single-tenant stdio use.
            project_id: Project scope within the user's data. Defaults to "default".

        Returns:
            SessionInfo with session_id and connected engine.

        Raises:
            ValueError: For invalid session_type, user_id, or project_id.
        """
        # Opportunistic cleanup of expired sessions
        self.cleanup_expired()

        if session_type not in ("sql", "graph", "think"):
            raise ValueError(
                f"Invalid session_type: {session_type!r}. Must be 'sql', 'graph', or 'think'."
            )

        validate_identity(user_id, "user_id")
        validate_identity(project_id, "project_id")

        # Full UUID for capability-grade entropy (128 bits)
        session_id = uuid.uuid4().hex
        session_dir = self._base_dir / user_id / project_id / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)

        if session_type == "sql":
            db_path = str(session_dir / "data.duckdb")
            from aismartbuddy.engines.duckdb_engine import DuckDBEngine

            engine = DuckDBEngine(
                db_path, self._max_rows, self._max_chars,
                threads=self._duckdb_threads,
                memory_limit=self._duckdb_memory_limit,
            )
        elif session_type == "graph":
            db_path = str(session_dir / "graph.lbug")
            from aismartbuddy.engines.ladybug_engine import LadybugEngine

            engine = LadybugEngine(
                db_path, self._max_rows, self._max_chars,
                buffer_pool_size=self._ladybug_buffer_pool_size,
                max_threads=self._ladybug_max_threads,
            )
        else:  # think
            db_path = ""
            from aismartbuddy.engines.thinking_engine import ThinkingEngine

            engine = ThinkingEngine()

        try:
            engine.connect()
        except Exception:
            shutil.rmtree(str(session_dir), ignore_errors=True)
            raise

        info = SessionInfo(
            session_id=session_id,
            session_type=session_type,
            user_id=user_id,
            project_id=project_id,
            db_path=db_path,
            temp_dir=str(session_dir),
            created_at=now,
            last_accessed=now,
            engine=engine,
        )
        with self._lock:
            self._sessions[session_id] = info
        logger.info(
            "Created %s session: %s (user=%s project=%s)",
            session_type, session_id, user_id, project_id,
        )
        return info

    def get_session(
        self,
        session_id: str,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> SessionInfo:
        """Look up an active session by ID, optionally enforcing ownership.

        If both user_id and project_id are provided, the session's owner
        must match; otherwise the same "not found" error is raised (constant
        error text prevents presence enumeration).

        If user_id and project_id are None, session_id acts as a capability
        token — possession is sufficient. Used by internal callers that
        already validated the caller out-of-band.

        Raises:
            ValueError: If session_id is not found OR ownership doesn't match.
        """
        not_found = ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=session_id))
        with self._lock:
            info = self._sessions.get(session_id)
            if info is None:
                raise not_found
            if user_id is not None and info.user_id != user_id:
                raise not_found
            if project_id is not None and info.project_id != project_id:
                raise not_found
            info.last_accessed = datetime.now(timezone.utc)
        return info

    def destroy_session(
        self,
        session_id: str,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Destroy a session after verifying ownership.

        Pop-then-lock protocol:
        1. Remove from _sessions under _lock (no new lookups can find it).
        2. Acquire info.lock to wait for any in-flight tool call to finish.
        3. Tear down engine while holding info.lock.
        4. Release and rmtree.
        """
        not_found = ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=session_id))
        with self._lock:
            info = self._sessions.get(session_id)
            if info is None:
                raise not_found
            if user_id is not None and info.user_id != user_id:
                raise not_found
            if project_id is not None and info.project_id != project_id:
                raise not_found
            self._sessions.pop(session_id, None)
        # Wait for any in-flight tool call on this session to finish
        with info.lock:
            self._close_session(info)
        logger.info("Destroyed session: %s", session_id)

    def list_sessions(
        self,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> list[SessionInfo]:
        """Return sessions filtered by owner.

        With no args: returns ALL sessions (admin/internal only — used
        by cleanup_all and tests).
        With user_id: only sessions owned by that user.
        With user_id and project_id: only sessions owned by that (user, project).
        """
        with self._lock:
            all_sessions = list(self._sessions.values())
        if user_id is None and project_id is None:
            return all_sessions
        return [
            s for s in all_sessions
            if (user_id is None or s.user_id == user_id)
            and (project_id is None or s.project_id == project_id)
        ]

    def cleanup_expired(self) -> int:
        """Remove expired sessions and stale cursors.

        Restructured so heavy work (engine close, cursor cleanup) happens
        OUTSIDE _lock, matching the existing _close_session pattern.

        Returns count of sessions removed.
        """
        now = datetime.now(timezone.utc)
        to_close: list[SessionInfo] = []
        active_sessions: list[SessionInfo] = []
        with self._lock:
            expired = [
                sid
                for sid, info in self._sessions.items()
                if (now - info.last_accessed).total_seconds() > self._session_timeout
            ]
            for sid in expired:
                info = self._sessions.pop(sid, None)
                if info is not None:
                    to_close.append(info)
            # Snapshot still-active sessions for cursor cleanup outside _lock
            active_sessions = list(self._sessions.values())

        # Close expired sessions (waits for any in-flight call first)
        for info in to_close:
            with info.lock:
                self._close_session(info)
            logger.info("Expired session cleaned up: %s", info.session_id)

        # Cursor cleanup on active sessions (try-acquire with short timeout;
        # skip if tool call is active — next cycle will retry)
        for info in active_sessions:
            if info.engine is None or not hasattr(info.engine, "cleanup_expired_cursors"):
                continue
            # threading.Lock.acquire(timeout=1) is non-blocking enough
            got = info.lock.acquire(timeout=1.0)
            if not got:
                continue
            try:
                info.engine.cleanup_expired_cursors(self._cursor_timeout)
            except Exception:
                logger.debug("Error cleaning cursors for %s", info.session_id)
            finally:
                info.lock.release()

        return len(to_close)

    def cleanup_all(self) -> None:
        """Destroy all sessions. Called on server shutdown."""
        with self._lock:
            all_sessions = list(self._sessions.values())
            self._sessions.clear()
        for info in all_sessions:
            # Waits for any in-flight tool call to finish
            with info.lock:
                self._close_session(info)
        logger.info("All sessions cleaned up")

    def _close_session(self, info: SessionInfo) -> None:
        """Close engine (including cursors) and remove temp directory.

        MUST be called while holding info.lock to prevent engine teardown
        racing with an in-flight tool call.
        """
        if info.engine is not None:
            try:
                if hasattr(info.engine, "close_all_cursors"):
                    info.engine.close_all_cursors()
                info.engine.close()
            except Exception:
                logger.exception("Error closing engine for session %s", info.session_id)
        try:
            shutil.rmtree(info.temp_dir, ignore_errors=True)
        except Exception:
            logger.exception("Error removing temp dir for session %s", info.session_id)


# Module-level singleton — initialized by server lifespan
session_manager: SessionManager | None = None
