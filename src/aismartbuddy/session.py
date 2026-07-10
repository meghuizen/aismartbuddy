"""Session management for AISmartBuddy database sessions.

Multi-tenant model:
- Every session is bound to (user_id, project_id) at creation.
- Session_id acts as a capability token (128-bit entropy, unguessable).
- When identity is known via MCP v2 bearer auth context, ownership is verified.
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
    auto_graph: bool = False
    reasoning_intent: str | None = None
    reasoning_depth: str | None = None
    output_budget_chars: int | None = None


@dataclass
class SessionLink:
    """Cross-session link between two session-scoped nodes/artifacts."""

    id: str
    session_a: str
    node_a_id: str
    session_b: str
    node_b_id: str
    relationship: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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
    reasoning_intent: str | None = None
    reasoning_depth: str | None = None
    output_budget_chars: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass
class SharedBackendHandle:
    """Own one engine, lock, backing directory, and its session aliases."""

    id: str
    session_type: str
    user_id: str
    project_id: str
    db_path: str
    temp_dir: str
    engine: Union[DuckDBEngine, LadybugEngine, ThinkingEngine, None] = field(
        default=None, repr=False
    )
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    members: set[str] = field(default_factory=set)

    @property
    def ref_count(self) -> int:
        return len(self.members)


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
        self._backend_handles: dict[str, SharedBackendHandle] = {}
        self._handle_id_by_session: dict[str, str] = {}
        # parent_id → ParentSession (facade routing to backend children)
        self._parent_sessions: dict[str, ParentSession] = {}
        self._active_session_id: str | None = None
        self._idempotency_results: dict[tuple[str, str], str] = {}
        self._session_links: dict[str, SessionLink] = {}
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
        reasoning_intent: str | None = None,
        reasoning_depth: str | None = None,
        output_budget_chars: int | None = None,
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
                db_path,
                self._max_rows,
                self._max_chars,
                threads=self._duckdb_threads,
                memory_limit=self._duckdb_memory_limit,
            )
        elif session_type == "graph":
            db_path = str(session_dir / "graph.lbug")
            from aismartbuddy.engines.ladybug_engine import LadybugEngine

            engine = LadybugEngine(
                db_path,
                self._max_rows,
                self._max_chars,
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

        handle = SharedBackendHandle(
            id=uuid.uuid4().hex,
            session_type=session_type,
            user_id=user_id,
            project_id=project_id,
            db_path=db_path,
            temp_dir=str(session_dir),
            engine=engine,
            members={session_id},
        )
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
            reasoning_intent=reasoning_intent,
            reasoning_depth=reasoning_depth,
            output_budget_chars=output_budget_chars,
            engine=engine,
            lock=handle.lock,
        )
        with self._lock:
            self._sessions[session_id] = info
            self._backend_handles[handle.id] = handle
            self._handle_id_by_session[session_id] = handle.id
            if self._active_session_id is None:
                self._active_session_id = session_id
        logger.info(
            "Created %s session: %s (user=%s project=%s)",
            session_type,
            session_id,
            user_id,
            project_id,
        )
        return info

    def _handle_for_session_locked(self, info: SessionInfo) -> SharedBackendHandle:
        """Return or adopt the handle for a session while ``self._lock`` is held."""

        handle_id = self._handle_id_by_session.get(info.session_id)
        handle = self._backend_handles.get(handle_id or "")
        if handle is not None:
            return handle
        handle = SharedBackendHandle(
            id=uuid.uuid4().hex,
            session_type=info.session_type,
            user_id=info.user_id,
            project_id=info.project_id,
            db_path=info.db_path,
            temp_dir=info.temp_dir,
            engine=info.engine,
            lock=info.lock,
            members={info.session_id},
        )
        self._backend_handles[handle.id] = handle
        self._handle_id_by_session[info.session_id] = handle.id
        return handle

    def create_shared_session(
        self,
        source_session_id: str,
        session_type: str,
        user_id: str,
        project_id: str,
        *,
        mode: str | None = None,
        enforcement: str | None = None,
        max_node_chars: int | None = None,
        reasoning_intent: str | None = None,
        reasoning_depth: str | None = None,
        output_budget_chars: int | None = None,
    ) -> SessionInfo:
        """Create a distinct session ID over an existing mutable backend."""

        source = self.resolve_backend_session(source_session_id, session_type)
        if source.user_id != user_id or source.project_id != project_id:
            raise ValueError("Shared sessions must have the same user_id and project_id")

        alias_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        with self._lock:
            # Re-check that the source was not destroyed after resolution.
            current = self._sessions.get(source.session_id)
            if current is None:
                raise ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=source_session_id))
            handle = self._handle_for_session_locked(current)
            handle.members.add(alias_id)
            info = SessionInfo(
                session_id=alias_id,
                session_type=session_type,
                user_id=user_id,
                project_id=project_id,
                db_path=handle.db_path,
                temp_dir=handle.temp_dir,
                created_at=now,
                last_accessed=now,
                engine=handle.engine,
                mode=mode if mode is not None else source.mode,
                enforcement=enforcement if enforcement is not None else source.enforcement,
                max_node_chars=(
                    max_node_chars if max_node_chars is not None else source.max_node_chars
                ),
                reasoning_intent=(
                    reasoning_intent
                    if reasoning_intent is not None
                    else source.reasoning_intent
                ),
                reasoning_depth=(
                    reasoning_depth if reasoning_depth is not None else source.reasoning_depth
                ),
                output_budget_chars=(
                    output_budget_chars
                    if output_budget_chars is not None
                    else source.output_budget_chars
                ),
                lock=handle.lock,
            )
            self._sessions[alias_id] = info
            self._handle_id_by_session[alias_id] = handle.id
        logger.info(
            "Created shared %s session %s from %s (members=%d)",
            session_type,
            alias_id,
            source.session_id,
            handle.ref_count,
        )
        return info

    def list_shared_members(self, session_id: str) -> list[SessionInfo]:
        """Return other session aliases sharing the same mutable backend."""

        info = self.get_session(session_id)
        with self._lock:
            handle_id = self._handle_id_by_session.get(info.session_id)
            handle = self._backend_handles.get(handle_id or "")
            if handle is None:
                return []
            member_ids = [value for value in handle.members if value != info.session_id]
            return [self._sessions[value] for value in member_ids if value in self._sessions]

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
            close_backend = self._detach_handle_locked(session_id)
            if self._active_session_id == session_id:
                self._active_session_id = None
            self._drop_session_aux_state(session_id)
        # Wait for any in-flight tool call on this session to finish
        with info.lock:
            if close_backend:
                self._close_session(info)
        logger.info("Destroyed session: %s", session_id)

    def _detach_handle_locked(self, session_id: str) -> bool:
        """Detach one alias; return True when its backend must be closed."""

        handle_id = self._handle_id_by_session.pop(session_id, None)
        if handle_id is None:
            return True  # legacy or test-created SessionInfo
        handle = self._backend_handles.get(handle_id)
        if handle is None:
            return True
        handle.members.discard(session_id)
        if handle.members:
            return False
        self._backend_handles.pop(handle_id, None)
        return True

    def create_parent_session(
        self,
        backends: list[str],
        user_id: str = "default",
        project_id: str = "default",
        mode: str = "analyze",
        enforcement: str = "advisory",
        max_node_chars: int = 500,
        auto_graph: bool = False,
        reasoning_intent: str | None = None,
        reasoning_depth: str | None = None,
        output_budget_chars: int | None = None,
        share_from_session_id: str | None = None,
        share_backends: list[str] | None = None,
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
                raise ValueError(f"Invalid backend {b!r}. Allowed: {sorted(valid)}")
        if len(set(backends)) != len(backends):
            raise ValueError("backends must be unique")

        validate_identity(user_id, "user_id")
        validate_identity(project_id, "project_id")

        requested_shared = set(share_backends or (backends if share_from_session_id else []))
        if requested_shared - set(backends):
            raise ValueError("share_backends must be a subset of backends")
        if share_backends and not share_from_session_id:
            raise ValueError("share_from_session_id is required when share_backends is set")
        if share_from_session_id:
            source_parent = self.resolve_to_parent(share_from_session_id)
            if source_parent is not None:
                source_user = source_parent.user_id
                source_project = source_parent.project_id
            else:
                source_info = self.get_session(share_from_session_id)
                source_user = source_info.user_id
                source_project = source_info.project_id
            if source_user != user_id or source_project != project_id:
                raise ValueError("Shared sessions must have the same user_id and project_id")

        # Create child sessions sequentially. If any fails, roll back.
        children: dict[str, str] = {}
        try:
            for backend in backends:
                if share_from_session_id and backend in requested_shared:
                    try:
                        child = self.create_shared_session(
                            share_from_session_id,
                            backend,
                            user_id,
                            project_id,
                            mode=mode,
                            enforcement=enforcement,
                            max_node_chars=max_node_chars,
                            reasoning_intent=reasoning_intent,
                            reasoning_depth=reasoning_depth,
                            output_budget_chars=output_budget_chars,
                        )
                    except ValueError:
                        if share_backends is not None:
                            raise
                        child = self.create_session(
                            backend,
                            user_id,
                            project_id,
                            mode=mode,
                            enforcement=enforcement,
                            max_node_chars=max_node_chars,
                            reasoning_intent=reasoning_intent,
                            reasoning_depth=reasoning_depth,
                            output_budget_chars=output_budget_chars,
                        )
                else:
                    child = self.create_session(
                        backend,
                        user_id,
                        project_id,
                        mode=mode,
                        enforcement=enforcement,
                        max_node_chars=max_node_chars,
                        reasoning_intent=reasoning_intent,
                        reasoning_depth=reasoning_depth,
                        output_budget_chars=output_budget_chars,
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
            auto_graph=auto_graph,
            reasoning_intent=reasoning_intent,
            reasoning_depth=reasoning_depth,
            output_budget_chars=output_budget_chars,
            created_at=now,
            last_accessed=now,
        )
        with self._lock:
            self._parent_sessions[parent_id] = parent
            self._active_session_id = parent_id
        logger.info(
            "Created parent session %s with backends=%s (user=%s project=%s)",
            parent_id,
            backends,
            user_id,
            project_id,
        )
        return parent

    def resolve_backend_session(
        self,
        session_id: str | None,
        backend: str,
    ) -> SessionInfo:
        """Resolve session_id (parent OR direct child) to a SessionInfo for a backend.

        Three resolution paths:
        1. parent_id → returns the child for `backend` (raises if parent has no
           child of that backend type).
        2. direct child_id matching `backend` → returns it unchanged.
        3. direct child_id of WRONG backend type that belongs to a unified
           parent → walks up to the parent and returns the sibling child for
           `backend`. This makes the documented "pass the returned session_id
           to all tools" contract work transparently when the user holds a
           think child ID but is calling a graph tool (or vice versa).

        Falls through to ValueError only when (a) no parent exists OR (b) the
        parent has no sibling for the requested backend.

        Args:
            session_id: Either a direct child session_id or a parent_id.
            backend: The backend the caller's tool needs ("sql"|"graph"|"think").
        """
        if not session_id:
            session_id = self.get_active_session_id()
            if not session_id:
                raise ValueError(
                    f"No active session set for backend '{backend}'. "
                    "Create a session first or call think_set_active_session(session_id)."
                )

        # Resolve to the target backend child in one locked block. Three
        # paths considered atomically so a concurrent destroy_parent_session
        # cannot create a stale-reference window between the type check and
        # the sibling lookup:
        #   1. session_id is a parent_id → use parent.children[backend]
        #   2. session_id is a child of some parent → walk up, then dispatch
        #      to the sibling for `backend`
        #   3. session_id is a standalone session of the requested backend
        #      → fall through to validation
        actual_session_id: str
        wrong_type_seen: str | None = None
        with self._lock:
            parent = self._parent_sessions.get(session_id)
            if parent is None:
                # Could be a child of a unified parent — search children index
                # (linear over parents; small N in practice, single-pass).
                for candidate in self._parent_sessions.values():
                    if session_id in candidate.children.values():
                        parent = candidate
                        break
            if parent is not None:
                child_id = parent.children.get(backend)
                if child_id is None:
                    raise ValueError(
                        f"Parent session '{parent.parent_id}' has no '{backend}' "
                        "backend. Recreate with session_create("
                        f"backends=[..., '{backend}']) or use a "
                        f"{backend}_create_session."
                    )
                parent.last_accessed = datetime.now(timezone.utc)
                actual_session_id = child_id
            else:
                actual_session_id = session_id
                # Peek session_type to surface the same wrong-backend error
                # message as before when no parent linkage exists.
                peek = self._sessions.get(actual_session_id)
                if peek is not None and peek.session_type != backend:
                    wrong_type_seen = peek.session_type
        if wrong_type_seen is not None:
            raise ValueError(
                f"Session '{actual_session_id}' is a {wrong_type_seen} session, not {backend}."
            )
        # Direct child lookup (also enforces session_type for the resolved id)
        info = self.get_session(actual_session_id)
        if info.session_type != backend:
            raise ValueError(
                f"Session '{actual_session_id}' is a {info.session_type} session, not {backend}."
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
            if self._active_session_id == parent_id:
                self._active_session_id = None
            self._drop_session_aux_state(parent_id)
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
            s
            for s in all_sessions
            if (user_id is None or s.user_id == user_id)
            and (project_id is None or s.project_id == project_id)
        ]

    def set_active_session(self, session_id: str) -> str:
        """Set the implicit active session (parent or direct child)."""
        with self._lock:
            if session_id in self._parent_sessions or session_id in self._sessions:
                self._active_session_id = session_id
                return session_id
        raise ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=session_id))

    def get_active_session_id(self) -> str | None:
        """Return the current implicit active session id, if any."""
        with self._lock:
            if self._active_session_id in self._parent_sessions:
                return self._active_session_id
            if self._active_session_id in self._sessions:
                return self._active_session_id
            return None

    def find_parent_for_child(self, child_session_id: str) -> ParentSession | None:
        """Return the parent facade containing a child session, if any."""
        with self._lock:
            for parent in self._parent_sessions.values():
                if child_session_id in parent.children.values():
                    return parent
        return None

    def resolve_to_parent(self, session_id: str | None) -> ParentSession | None:
        """Return the parent for a session_id, whether it IS a parent_id or
        a child of one. Returns None if no parent linkage exists.

        Use this in tools that need parent-aware behavior without caring
        whether the caller passed the parent's own id or a child id. Replaces
        the ``parents.get(sid) or find_parent_for_child(sid)`` pattern that
        previously reached into ``_parent_sessions`` from multiple call sites.
        """
        if not session_id:
            return None
        with self._lock:
            parent = self._parent_sessions.get(session_id)
            if parent is not None:
                return parent
            for candidate in self._parent_sessions.values():
                if session_id in candidate.children.values():
                    return candidate
        return None

    def find_companion_session(self, child_session_id: str, backend: str) -> str | None:
        """Return a sibling backend session for a child session, if available."""
        parent = self.find_parent_for_child(child_session_id)
        if parent is None:
            return None
        return parent.children.get(backend)

    def add_backend(self, parent_id: str, backend: str) -> str:
        """Attach a new backend child to an existing parent session.

        Internal use only — not exposed as an MCP tool.
        Returns the new child session_id.
        Raises ValueError if parent not found or backend already exists.

        Concurrency: we drop the lock to call create_session (which acquires
        info.lock and may take non-trivial time to spin up an engine). To
        prevent two racing add_backend calls from both creating a child and
        the second one orphaning the first, we re-check `backend in
        parent.children` under the lock after creation and destroy our own
        child on conflict.
        """
        with self._lock:
            parent = self._parent_sessions.get(parent_id)
            if parent is None:
                raise ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=parent_id))
            if backend in parent.children:
                raise ValueError(f"Parent session '{parent_id}' already has a '{backend}' backend.")
            # Snapshot the fields create_session needs so we don't dereference
            # a possibly-destroyed parent outside the lock.
            user_id = parent.user_id
            project_id = parent.project_id
            mode = parent.mode
            enforcement = parent.enforcement
            max_node_chars = parent.max_node_chars
            reasoning_intent = parent.reasoning_intent
            reasoning_depth = parent.reasoning_depth
            output_budget_chars = parent.output_budget_chars
        child = self.create_session(
            backend,
            user_id,
            project_id,
            mode=mode,
            enforcement=enforcement,
            max_node_chars=max_node_chars,
            reasoning_intent=reasoning_intent,
            reasoning_depth=reasoning_depth,
            output_budget_chars=output_budget_chars,
        )
        cleanup_child: str | None = None
        conflict = False
        with self._lock:
            parent = self._parent_sessions.get(parent_id)
            if parent is None:
                cleanup_child = child.session_id
            elif backend in parent.children:
                # Lost a race against another add_backend for the same backend.
                cleanup_child = child.session_id
                conflict = True
            else:
                parent.children[backend] = child.session_id
        if cleanup_child is not None:
            self.destroy_session(cleanup_child)
            if conflict:
                raise ValueError(f"Parent session '{parent_id}' already has a '{backend}' backend.")
            raise ValueError(_NOT_FOUND_MSG_TMPL.format(session_id=parent_id))
        logger.info(
            "Added '%s' backend to parent session %s (child=%s)",
            backend,
            parent_id,
            child.session_id,
        )
        return child.session_id

    def get_idempotent_result(self, session_id: str, idempotency_key: str) -> str | None:
        """Return a stored idempotent result if this write already completed."""
        with self._lock:
            return self._idempotency_results.get((session_id, idempotency_key))

    def store_idempotent_result(self, session_id: str, idempotency_key: str, result: str) -> None:
        """Persist the first successful result for an idempotent write."""
        with self._lock:
            self._idempotency_results.setdefault((session_id, idempotency_key), result)

    def add_session_link(
        self,
        session_a: str,
        node_a_id: str,
        session_b: str,
        node_b_id: str,
        relationship: str,
    ) -> SessionLink:
        """Create and store a cross-session link between two nodes/artifacts."""
        if not relationship:
            raise ValueError("relationship is required")
        # Existence check resolves parent/direct child capability tokens.
        left = self.resolve_backend_session(session_a, "think")
        right = self.resolve_backend_session(session_b, "think")
        if left.user_id != right.user_id or left.project_id != right.project_id:
            raise ValueError("Linked sessions must have the same user_id and project_id")
        link = SessionLink(
            id=uuid.uuid4().hex[:12],
            session_a=session_a,
            node_a_id=node_a_id,
            session_b=session_b,
            node_b_id=node_b_id,
            relationship=relationship,
        )
        with self._lock:
            self._session_links[link.id] = link
        return link

    def list_session_links(self, session_id: str) -> list[SessionLink]:
        """Return all cross-session links involving the session."""
        with self._lock:
            return [
                link
                for link in self._session_links.values()
                if link.session_a == session_id or link.session_b == session_id
            ]

    def cleanup_expired(self) -> int:
        """Remove expired sessions and stale cursors.

        Restructured so heavy work (engine close, cursor cleanup) happens
        OUTSIDE _lock, matching the existing _close_session pattern.

        Returns count of sessions removed.
        """
        now = datetime.now(timezone.utc)
        to_close: list[tuple[SessionInfo, bool]] = []
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
                    to_close.append((info, self._detach_handle_locked(sid)))
            # Snapshot still-active sessions for cursor cleanup outside _lock
            active_sessions = list(self._sessions.values())
            # GC parent sessions whose children are all gone OR whose
            # last_accessed exceeds the timeout. Prevents unbounded growth
            # of _parent_sessions over long-running server lifetime.
            parents_to_drop: list[str] = []
            for pid, parent in self._parent_sessions.items():
                children_alive = any(cid in self._sessions for cid in parent.children.values())
                idle = (now - parent.last_accessed).total_seconds() > self._session_timeout
                if not children_alive or idle:
                    parents_to_drop.append(pid)
            for pid in parents_to_drop:
                self._parent_sessions.pop(pid, None)
                if self._active_session_id == pid:
                    self._active_session_id = None
                self._drop_session_aux_state(pid)

        # Close expired sessions (waits for any in-flight call first)
        for info, close_backend in to_close:
            with info.lock:
                if close_backend:
                    self._close_session(info)
            logger.info("Expired session cleaned up: %s", info.session_id)

        # Cursor cleanup on active sessions (try-acquire with short timeout;
        # skip if tool call is active — next cycle will retry)
        for info in active_sessions:
            cleanup_cursors = getattr(info.engine, "cleanup_expired_cursors", None)
            if not callable(cleanup_cursors):
                continue
            # threading.Lock.acquire(timeout=1) is non-blocking enough
            got = info.lock.acquire(timeout=1.0)
            if not got:
                continue
            try:
                cleanup_cursors(self._cursor_timeout)
            except Exception:
                logger.debug("Error cleaning cursors for %s", info.session_id)
            finally:
                info.lock.release()

        return len(to_close)

    def cleanup_all(self) -> None:
        """Destroy all sessions. Called on server shutdown."""
        with self._lock:
            all_sessions = list(self._sessions.values())
            handles = list(self._backend_handles.values())
            self._sessions.clear()
            self._backend_handles.clear()
            self._handle_id_by_session.clear()
            self._parent_sessions.clear()
            self._active_session_id = None
            self._idempotency_results.clear()
            self._session_links.clear()
        if handles:
            handled_ids: set[str] = set()
            for handle in handles:
                with handle.lock:
                    representative = next(
                        (
                            info
                            for info in all_sessions
                            if info.session_id in handle.members
                        ),
                        None,
                    )
                    if representative is not None:
                        self._close_session(representative)
                        handled_ids.update(handle.members)
            for info in all_sessions:
                if info.session_id in handled_ids:
                    continue
                with info.lock:
                    self._close_session(info)
        else:
            for info in all_sessions:
                # Legacy or test-created sessions without registered handles.
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
                close_cursors = getattr(info.engine, "close_all_cursors", None)
                if callable(close_cursors):
                    close_cursors()
                info.engine.close()
            except Exception:
                logger.exception("Error closing engine for session %s", info.session_id)
        try:
            shutil.rmtree(info.temp_dir, ignore_errors=True)
        except Exception:
            logger.exception("Error removing temp dir for session %s", info.session_id)

    def _drop_session_aux_state(self, session_id: str) -> None:
        """Drop idempotency/link state tied to a removed session."""
        doomed = [k for k in self._idempotency_results if k[0] == session_id]
        for key in doomed:
            self._idempotency_results.pop(key, None)
        for link_id, link in list(self._session_links.items()):
            if link.session_a == session_id or link.session_b == session_id:
                self._session_links.pop(link_id, None)


# Module-level singleton — initialized by server lifespan
session_manager: SessionManager | None = None
