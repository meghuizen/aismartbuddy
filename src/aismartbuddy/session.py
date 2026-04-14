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
class ParentSession:
    """A facade session that holds one or more single-backend child sessions.

    A parent_id is a capability token that routes per-tool to the appropriate
    backend's child session. Engines stay isolated — the parent is purely a
    facade. Backwards compat: existing single-backend sessions (created via
    sql_create_session, etc.) bypass this facade entirely.
    """

    parent_id: str
    user_id: str
    project_id: str
    children: dict[str, str]  # backend_name → child_session_id
    created_at: datetime
    last_accessed: datetime
    mode: str = "analyze"
    enforcement: str = "advisory"
    max_node_chars: int = 500


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
    mode: str = "analyze"
    enforcement: str = "advisory"
    max_node_chars: int = 500
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
        # parent_id → ParentSession (facade routing to backend children)
        self._parent_sessions: dict[str, ParentSession] = {}
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
        mode: str = "analyze",
        enforcement: str = "advisory",
        max_node_chars: int = 500,
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
            mode=mode,
            enforcement=enforcement,
            max_node_chars=max_node_chars,
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

    def create_parent_session(
        self,
        backends: list[str],
        user_id: str = "default",
        project_id: str = "default",
        mode: str = "analyze",
        enforcement: str = "advisory",
        max_node_chars: int = 500,
    ) -> ParentSession:
        """Create a parent session that holds one child session per backend.

        The returned parent_id routes to the appropriate child for each tool.
        Engines stay isolated — multi-backend just means one capability token
        unlocks SQL + graph + think operations on the same logical workspace.

        Args:
            backends: List of backend names. Allowed: "think", "graph", "sql".
            user_id, project_id: Multi-tenant identity (same as create_session).

        Returns:
            ParentSession with allocated children dict.

        Raises:
            ValueError: For invalid backend names, identity, or empty list.
        """
        if not backends:
            raise ValueError("backends must be a non-empty list")
        valid = {"think", "graph", "sql"}
        for b in backends:
            if b not in valid:
                raise ValueError(
                    f"Invalid backend {b!r}. Allowed: {sorted(valid)}"
                )
        if len(set(backends)) != len(backends):
            raise ValueError("backends must be unique")

        validate_identity(user_id, "user_id")
        validate_identity(project_id, "project_id")

        # Create child sessions sequentially. If any fails, roll back.
        children: dict[str, str] = {}
        try:
            for backend in backends:
                child = self.create_session(
                    backend,
                    user_id,
                    project_id,
                    mode=mode,
                    enforcement=enforcement,
                    max_node_chars=max_node_chars,
                )
                children[backend] = child.session_id
        except Exception:
            # Roll back any children already created
            for cid in children.values():
                try:
                    self.destroy_session(cid)
                except Exception:
                    pass
            raise

        parent_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        parent = ParentSession(
            parent_id=parent_id,
            user_id=user_id,
            project_id=project_id,
            children=children,
            mode=mode,
            enforcement=enforcement,
            max_node_chars=max_node_chars,
            created_at=now,
            last_accessed=now,
        )
        with self._lock:
            self._parent_sessions[parent_id] = parent
        logger.info(
            "Created parent session %s with backends=%s "
            "(user=%s project=%s)",
            parent_id, backends, user_id, project_id,
        )
        return parent

    def resolve_backend_session(
        self,
        session_id: str,
        backend: str,
    ) -> SessionInfo:
        """Resolve session_id (parent OR direct child) to a SessionInfo for a backend.

        - If session_id is a direct child session_id (single-backend): returns
          its SessionInfo unchanged. Backend type must match (else ValueError).
        - If session_id is a parent_id: looks up the child for `backend`. Raises
          ValueError if the parent has no child for that backend.

        Args:
            session_id: Either a direct child session_id or a parent_id.
            backend: The backend the caller's tool needs ("sql"|"graph"|"think").
        """
        # Try parent first
        with self._lock:
            parent = self._parent_sessions.get(session_id)
            if parent is not None:
                child_id = parent.children.get(backend)
                if child_id is None:
                    raise ValueError(
                        f"Parent session '{session_id}' has no '{backend}' "
                        "backend. Recreate with session_create("
                        f"backends=[..., '{backend}']) or use a "
                        f"{backend}_create_session."
                    )
                parent.last_accessed = datetime.now(timezone.utc)
                actual_session_id = child_id
            else:
                actual_session_id = session_id
        # Fall back to direct child lookup (also enforces session_type)
        info = self.get_session(actual_session_id)
        if info.session_type != backend:
            raise ValueError(
                f"Session '{actual_session_id}' is a {info.session_type} "
                f"session, not {backend}."
            )
        return info

    def destroy_parent_session(
        self,
        parent_id: str,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Destroy a parent session and all its child backends."""
        not_found = ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=parent_id))
        with self._lock:
            parent = self._parent_sessions.get(parent_id)
            if parent is None:
                raise not_found
            if user_id is not None and parent.user_id != user_id:
                raise not_found
            if project_id is not None and parent.project_id != project_id:
                raise not_found
            children_ids = list(parent.children.values())
            self._parent_sessions.pop(parent_id, None)
        # Destroy each child outside the parent lock
        for cid in children_ids:
            try:
                self.destroy_session(cid)
            except Exception:
                logger.exception("Error destroying child session %s", cid)
        logger.info("Destroyed parent session: %s", parent_id)

    def get_parent_session(self, parent_id: str) -> ParentSession:
        """Return a parent session by id."""
        with self._lock:
            parent = self._parent_sessions.get(parent_id)
            if parent is None:
                raise ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=parent_id))
            parent.last_accessed = datetime.now(timezone.utc)
            return parent

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
            # GC parent sessions whose children are all gone OR whose
            # last_accessed exceeds the timeout. Prevents unbounded growth
            # of _parent_sessions over long-running server lifetime.
            parents_to_drop: list[str] = []
            for pid, parent in self._parent_sessions.items():
                children_alive = any(
                    cid in self._sessions for cid in parent.children.values()
                )
                idle = (
                    now - parent.last_accessed
                ).total_seconds() > self._session_timeout
                if not children_alive or idle:
                    parents_to_drop.append(pid)
            for pid in parents_to_drop:
                self._parent_sessions.pop(pid, None)

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
            self._parent_sessions.clear()
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
