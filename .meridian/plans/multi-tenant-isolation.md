# AISmartBuddy Multi-Tenant Isolation Plan

## Verbatim Requirements

### Original Request
> make sure that information, loops, thinking graphs, multiple thinking steps and for each tool, the information for a user and for a session doesnt bleed into another session or user. make sure it's multi threaded, multi user, multi project and can even handle multiple sessions and agents from the same user on the same project. Not only from the MCP scaffolding, but also into the backend database structure. Only when things are intentionally shared with other sessions, you are allowed

### Clarifications

**Q:** How should user identity be established?
**A:** Both — token when present, parameter fallback

**Q:** How should a project be scoped within a user?
**A:** Explicit tool parameter (session-creating tools accept project_id; session_id alone is enough for subsequent calls)

**Q:** What deployment models must this support?
**A:** Local stdio (one process per client), Shared streamable-http (SaaS-like), Single-user multi-project stdio. NOT persistent across restarts.

**Q:** What must be shareable across sessions when intentional?
**A:** Whole sessions (multi-agent collaboration). Specific data (tables, graphs, thought artifacts) — user later clarified: "nah, let the AI agents in context create subagents if they need to copy content over, no internal python mechanisms for this"

**Q:** When multiple agents share a session, how should concurrent writes be handled?
**A:** Per-session lock — serialize all calls

**Q:** How should a second agent attach to an existing shared session?
**A:** Just pass session_id (existing behavior)

**Q:** Within the same user_id, how should session access work across different clients/processes?
**A:** Same user_id = full access

---

## Context

AISmartBuddy currently has **zero multi-tenant isolation**. All sessions live in a global `SessionManager._sessions` dict keyed only by session_id. Any client that knows a session_id can access it. The `aismartbuddy://sessions` resource exposes all sessions to any caller (enumeration attack). The ThinkingEngine is explicitly **not thread-safe internally** — its 15 in-memory state dicts rely on "one client per session" as an undocumented assumption. Under streamable-http with multiple concurrent clients, this collapses.

This plan adds a proper multi-tenant ownership model: sessions are bound to `(user_id, project_id)` at creation, each session gets a `threading.Lock` for multi-agent serialization, identity is sourced from MCP Bearer tokens when configured (or explicit parameters as fallback), session IDs are upgraded to full 128-bit entropy, the sessions resource is filtered by caller, and the temp directory layout mirrors the ownership hierarchy so disk layout matches logical layout.

**Scope boundary**: This plan does NOT add export/import tools. When an AI needs to copy content between sessions, it spawns a subagent that reads from one session and writes to the other. No new Python scaffolding for cross-session data transfer.

---

## Current State (grounded in code)

### What's already isolated (keep as-is)
| Location | Isolation mechanism |
|---|---|
| `engines/duckdb_engine.py` | Each session has its own `DuckDBPyConnection` + `.duckdb` file |
| `engines/ladybug_engine.py` | Each session has its own `lb.Database` + `.lbug` file |
| `engines/thinking_engine.py:304-320` | All 15 state dicts are instance-level on the engine |
| `engines/__init__.py:27-30` | `_cursors` dict + `_cursor_lock` per engine instance |
| `session.py:64-73` | Per-session `temp_dir` (UUID subdirectory) |
| `tools/*.py` module scope | All module-level constants are immutable (frozenset/dict) |

### Critical gaps
| Location | Problem |
|---|---|
| `session.py:24-35` (SessionInfo) | No `user_id`, `project_id`, or `lock` field |
| `session.py:102` | `session_id = uuid.uuid4().hex[:16]` — only 64 bits entropy |
| `session.py:152-166` (get_session) | Returns session to anyone who knows session_id; no ownership check |
| `server.py:573-590` (list_sessions resource) | Unfiltered — any client sees all sessions |
| `engines/thinking_engine.py:298-301` (docstring) | "Not thread-safe internally" — breaks with multi-agent on one session |
| `tools/*/_require_*_session()` | Only validates session exists + type; no ownership check |
| `tools/think.py:150-168` (auto-session) | Creates sessions with no ownership binding |

### Current session lifecycle (single-tenant)
```
sql_create_session()
  → SessionManager.create_session("sql")
  → uuid.uuid4().hex[:16]
  → /tmp/aismartbuddy/{session_id}/data.duckdb
  → SessionInfo(session_id, session_type="sql", ...)
  → _sessions[session_id] = info   (no owner)
```

### Target session lifecycle (multi-tenant)
```
sql_create_session(user_id="alice", project_id="acme", ctx=Context)
  → identity = resolve_identity(ctx, user_id, project_id)
      (ctx.client_id overrides user_id if Bearer auth configured)
  → SessionManager.create_session("sql", user_id="alice", project_id="acme")
  → uuid.uuid4().hex     # full 32 char = 128 bits
  → /tmp/aismartbuddy/{user_id}/{project_id}/{session_id}/data.duckdb
  → SessionInfo(session_id, session_type="sql", user_id, project_id, lock=Lock(), ...)
  → _sessions[session_id] = info
```

---

## TIER 1 — Core Multi-Tenancy

### 1.1 Extend SessionInfo with ownership + lock

**File: `src/aismartbuddy/session.py`**

Add to the `SessionInfo` dataclass (currently lines 24-35):
- `user_id: str` — owner identity (required, no default)
- `project_id: str` — project binding (required, no default)
- `lock: threading.Lock` — per-session serialization lock (field with default_factory)

**Rationale:**
- `user_id` and `project_id` become first-class attributes of every session.
- The lock lives on SessionInfo (not the engine) because it serializes the WHOLE session's tool execution, including SessionManager operations that the engine doesn't know about.

**Acceptance:**
- `SessionInfo(session_id=..., session_type=..., user_id="alice", project_id="acme", ...)` constructs correctly
- `info.lock` is a `threading.Lock` instance, not a stub
- Existing tests fail loudly if they construct SessionInfo without owner fields (signals where they need updating)

---

### 1.2 Upgrade session_id entropy

**File: `src/aismartbuddy/session.py:102`**

Change:
- Current: `session_id = uuid.uuid4().hex[:16]` — 64 bits
- New: `session_id = uuid.uuid4().hex` — full 32-char hex, 128 bits

**Rationale:** Session IDs act as capabilities (anyone with the ID can access the session within their user/project). 64 bits is guessable in adversarial settings; 128 bits is not.

**Acceptance:**
- `len(info.session_id) == 32`
- All existing tests pass (they don't depend on session_id length beyond "string")

---

### 1.3 Update SessionManager signatures for ownership

**File: `src/aismartbuddy/session.py`**

Modify these methods:

- `create_session(session_type: str, user_id: str, project_id: str) -> SessionInfo`
  - Records `user_id`, `project_id` on SessionInfo at creation.
  - Creates lock via `threading.Lock()` and assigns to SessionInfo.
  - Temp directory becomes `{base_dir}/aismartbuddy/{user_id}/{project_id}/{session_id}/` (new hierarchical layout).

- `get_session(session_id: str, user_id: str | None = None, project_id: str | None = None) -> SessionInfo`
  - If both `user_id` and `project_id` are provided: verify session matches BOTH. Mismatch raises same `ValueError("Session 'X' not found")` as missing session (constant-time reject to prevent enumeration by presence).
  - If neither provided (internal calls, e.g., background cleanup): return session without ownership check.
  - `session_id` alone is enough — but per the design, tools will always pass (user_id, project_id) when they have them from ctx or parameters.

- `list_sessions(user_id: str | None = None, project_id: str | None = None) -> list[SessionInfo]`
  - Filter: if user_id given, return only sessions where `info.user_id == user_id`. Same for project_id.
  - If both `None`, return all (used by admin/internal paths only).

- `destroy_session(session_id: str, user_id: str | None = None, project_id: str | None = None)`
  - Same ownership check as `get_session`.

- `cleanup_expired()` — unchanged internally (iterates all sessions regardless of owner).

**Temp directory layout change:**

Current:
```
/tmp/aismartbuddy/
  {session_id}/
    data.duckdb  (or graph.lbug)
```

New:
```
/tmp/aismartbuddy/
  {user_id}/
    {project_id}/
      {session_id}/
        data.duckdb  (or graph.lbug)
```

Path validation: `user_id` and `project_id` must match `^[A-Za-z0-9_.-]{1,64}$` to prevent path traversal (e.g., `../../etc/passwd`). New helper `_validate_path_component()` in SessionManager.

**Acceptance:**
- `create_session("sql", "alice", "acme")` creates `/tmp/aismartbuddy/alice/acme/{sid}/data.duckdb`
- `get_session(sid, "alice", "acme")` returns session
- `get_session(sid, "bob", "acme")` raises `ValueError` with same message as a truly-missing session
- `list_sessions("alice")` returns only alice's sessions
- Invalid user_id like `../etc` raises `ValueError` at create time

---

### 1.4 Identity resolution helper

**New file: `src/aismartbuddy/identity.py`**

Defines a helper used by every session-creating tool:

- `resolve_identity(ctx: Context | None, user_id: str | None, project_id: str | None) -> tuple[str, str]`
  - Priority order for `user_id`:
    1. `ctx.client_id` if present and non-empty (Bearer token path).
    2. Explicit `user_id` parameter if provided.
    3. Env var `AISMARTBUDDY_DEFAULT_USER_ID` if set.
    4. Literal `"default"`.
  - Priority order for `project_id`:
    1. Explicit `project_id` parameter if provided.
    2. Env var `AISMARTBUDDY_DEFAULT_PROJECT_ID` if set.
    3. Literal `"default"`.
  - Validates both match the path-component regex before returning.
  - Raises `ValueError` if the resolved values fail validation.

- `get_identity_from_session(session_id: str) -> tuple[str, str]`
  - Looks up `(user_id, project_id)` from SessionInfo using SessionManager.
  - Used by tools that have a `session_id` but not ctx (e.g., `sql_query`).
  - Raises if session not found.

**Rationale:** Centralizes the auth logic. Tools don't need to know about Bearer tokens vs parameters vs env vars. Also makes it trivial to change the priority order later.

**Integration with RuntimeConfig:** Add `default_user_id: str = "default"` and `default_project_id: str = "default"` fields to RuntimeConfig (src/aismartbuddy/config.py) plus CLI flags + envvar bindings following the existing pattern.

**Acceptance:**
- With ctx having `client_id="alice"` and no parameter → returns `("alice", "default")`
- With ctx=None and `user_id="bob"` → returns `("bob", "default")`
- With both → ctx.client_id wins
- With env var `AISMARTBUDDY_DEFAULT_USER_ID=test` and nothing else → returns `("test", "default")`

---

### 1.5 Session-creating tools accept ownership parameters

**Files to modify:**
- `src/aismartbuddy/tools/sql.py` — `sql_create_session`
- `src/aismartbuddy/tools/graph.py` — `graph_create_session`
- `src/aismartbuddy/tools/think.py` — every tool that auto-creates a think session via `_get_or_create_think_session`
- `src/aismartbuddy/tools/holon.py` — `holon_create` (auto-creates think session when session_id omitted)

**Pattern for session-creating tools:**

Current signature:
```
async def sql_create_session() -> str
```

New signature:
```
async def sql_create_session(
    user_id: str | None = None,
    project_id: str | None = None,
    ctx: Context | None = None,
) -> str
```

Body: call `resolve_identity(ctx, user_id, project_id)` → pass `(user_id, project_id)` to `SessionManager.create_session(...)`. Response includes the resolved user_id and project_id so the client can confirm what was used.

**Tool description updates:**
- Document `user_id` and `project_id` parameters with the priority order explanation.
- Include "See also: aismartbuddy://sessions/{user_id}/{project_id} resource to list your sessions" where relevant.
- Note: `ctx: Context` parameter is auto-injected by FastMCP; documenting it would confuse users, so it stays undocumented in the description text (but is in the signature for type checking).

**Auto-session creation for think tools** (`_get_or_create_think_session`):
- When `session_id` is None, resolve identity from ctx + params and create a new session bound to that (user_id, project_id).
- When `session_id` is provided, call `get_session(session_id, user_id, project_id)` with the resolved identity to validate ownership.

**Acceptance:**
- `sql_create_session()` on stdio → creates session with `user_id="default"`, `project_id="default"`
- `sql_create_session(user_id="alice", project_id="acme")` → creates session bound to alice/acme
- Under Bearer auth with client_id="alice", `sql_create_session(project_id="acme")` → alice/acme (user_id param ignored)

---

### 1.6 Per-session serialization lock

**File: `src/aismartbuddy/tools/__init__.py`**

The shared execute helpers `execute_and_format()` and `fetch_next_and_format()` already exist (from Tier 1 of the prior plan). Extend them plus create new utilities:

- Add a `with_session_lock(info, fn)` helper that wraps a lambda call in `with info.lock:`.
- Update `execute_and_format()` to acquire `info.lock` before calling `info.engine.execute_arrow(...)` (or the paginated equivalent). Note: `anyio.to_thread.run_sync` moves the call off the event loop, so the lock must be acquired INSIDE the sync function, not awaited.
- Update `fetch_next_and_format()` likewise.

**For tools that don't go through the shared helpers** (think tools, holon tools, score tools — they call engine methods directly):
- Each of their engine calls must be wrapped in `with info.lock:` under the `anyio.to_thread.run_sync` boundary.
- Create a small helper in `tools/__init__.py`: `async def run_with_lock(info, sync_fn)` that does the lock+thread dispatch in one call.

**ThinkingEngine invariant change:**
- Update docstring at `engines/thinking_engine.py:298-301`: "Thread-safe via SessionInfo.lock held by the tool dispatch layer. Engine methods assume single-threaded entry guaranteed by the caller."
- No internal locking needed on ThinkingEngine.

**Cursor cleanup and session lock:**
- Background `cleanup_expired()` currently calls `engine.cleanup_expired_cursors(timeout)` INSIDE SessionManager._lock (see `session.py:197-203`). This must change to mirror the existing pattern where slow I/O happens outside the manager lock (`session.py:206-208` already does this for `_close_session`).
- **Restructure `cleanup_expired()`:**
  1. Inside `self._lock`: collect expired sessions (existing logic) AND collect the list of `(session_info, engine)` pairs that need cursor cleanup.
  2. Exit `self._lock`.
  3. For each active session outside the manager lock: try-acquire `info.lock` with 1s timeout. If acquired, run `engine.cleanup_expired_cursors(timeout)` and release. If not acquired (tool in flight), skip — next cycle will retry.
- This preserves the existing "heavy work outside the manager lock" invariant.

**Session destroy and session lock (prevents engine-closed-underneath-call race):**
- `destroy_session(session_id, user_id, project_id)` flow:
  1. Inside `self._lock`: validate ownership, pop session from `_sessions`. (This prevents new callers from looking up the session.)
  2. Exit `self._lock`.
  3. Acquire `info.lock` (blocking — wait for any in-flight tool call to finish).
  4. Call `engine.close_all_cursors()` and `engine.close()` while holding `info.lock`.
  5. Release `info.lock`; rmtree temp dir.
- `cleanup_expired()` same pattern: after popping expired sessions out of `_sessions`, acquire each `info.lock` before `_close_session`.
- Rationale: once the session is popped from the manager dict, no new tool calls can find it. But a call that already looked it up might still be executing with `info.lock` held. We wait for that to finish before tearing down the engine.

**Acceptance:**
- Two concurrent tool calls on the same session_id execute SEQUENTIALLY (second waits for first's lock release).
- Two concurrent tool calls on DIFFERENT session_ids execute IN PARALLEL.
- Under load, no data corruption in ThinkingEngine dicts (verified by new stress test).
- Background cleanup never blocks tool execution for more than 1 second.

---

### 1.7 Replace sessions resource with scoped template

**File: `src/aismartbuddy/server.py:573-590`**

Current resource:
```
@mcp.resource("aismartbuddy://sessions")
async def list_sessions() -> str:
    ...  # exposes all sessions
```

Replace with TWO resources:

1. **Scoped template** `aismartbuddy://sessions/{user_id}/{project_id}`:
   - Parameters matched to function args (per MCP SDK resource templates).
   - Internally calls `session_manager.list_sessions(user_id=user_id, project_id=project_id)`.
   - Returns only sessions owned by that `(user_id, project_id)` tuple.
   - If user_id/project_id don't match regex, returns error message (no crash).

2. **Current-user resource** `aismartbuddy://sessions` (keep URI, change semantics):
   - Accepts `ctx: Context` (FastMCP injects).
   - If `ctx.client_id` is set (Bearer auth), use it as `user_id` and filter to that user's sessions across all projects.
   - If no auth and no identity available: return empty list with a message like "Identity required — use aismartbuddy://sessions/{user_id}/{project_id} or authenticate".

**Acceptance:**
- `aismartbuddy://sessions/alice/acme` → only alice's acme sessions
- `aismartbuddy://sessions/bob/acme` → only bob's acme sessions (empty if bob has none)
- Under auth with client_id=alice, `aismartbuddy://sessions` → alice's sessions across all projects
- Without auth, `aismartbuddy://sessions` → helpful error, not a data leak

---

### 1.8 destroy_session and get_session from tools

**Files:**
- `src/aismartbuddy/tools/sql.py:_require_sql_session` (and graph/think/holon equivalents)
- `src/aismartbuddy/tools/graph.py:_require_graph_session_pair` (two-session helper used by graph_compare, graph_cross_reference — validates BOTH sessions' ownership independently via two get_session calls)
- `src/aismartbuddy/tools/sql.py:sql_destroy_session` (and equivalents)

**Current pattern:**
```
def _require_sql_session(session_id: str):
    mgr = get_session_manager()
    info = mgr.get_session(session_id)
    if info.session_type != "sql":
        raise ValueError(...)
    return mgr, info
```

**New pattern:**
```
def _require_sql_session(session_id, user_id, project_id):
    mgr = get_session_manager()
    info = mgr.get_session(session_id, user_id, project_id)  # ownership check
    if info.session_type != "sql":
        raise ValueError(...)
    return mgr, info
```

The calling tool now looks like:
```
async def sql_query(session_id, query, ..., ctx=None):
    user_id, project_id = resolve_identity(ctx, None, None)
    mgr, info = _require_sql_session(session_id, user_id, project_id)
    return await execute_and_format(info, mgr, query, ...)
```

**Alternative simpler approach chosen:** Tools that operate on an existing session (sql_query, graph_query, think_*) do NOT need user_id/project_id parameters (the user explicitly said "session_id alone is enough"). Instead:
- `get_session(session_id)` without ownership args returns the session (session_id is unguessable, acts as capability).
- We still derive (user_id, project_id) from ctx if available, and if it disagrees with session.user_id AND session.project_id, we reject.
- If no ctx identity, we don't check (the session_id proves authorization).

**Two-session tools (graph_compare, graph_cross_reference) — deadlock prevention:**

`_require_graph_session_pair(session_id_a, session_id_b)` at `tools/graph.py:27-34` calls `get_session` twice. Under the new design:
- Both sessions have their ownership checked independently (each call validates identity).
- Both sessions have their own `info.lock`. Acquiring both locks in different orders by different callers would ABBA-deadlock.
- **Fix:** Acquire locks in lexicographic order of `session_id`. Helper in `tools/__init__.py`:
  - `async def with_two_session_locks(info_a, info_b, sync_fn)` — orders locks by `min(a.session_id, b.session_id)` first.
- Only two tools use pairs: `graph_compare` and `graph_cross_reference`. Both go through the helper.

**Final resolved policy (what gets implemented):**

```
Policy: session_id is a capability. Ownership is verified only when identity is available from ctx.

Scenarios:
1. Bearer auth configured, token's client_id = alice; session owned by alice:
   sql_query(session_id=X) → verifies session.user_id == "alice" → OK
2. Bearer auth configured, token's client_id = bob; session owned by alice:
   sql_query(session_id=X) → verifies session.user_id == "alice" != "bob" → ValueError
3. No auth (stdio), no ctx identity; session owned by anyone:
   sql_query(session_id=X) → session_id acts as capability, returns session → OK
4. No auth, explicit user_id parameter on session-creating tool only; no per-call parameter:
   sql_query(session_id=X) → no ctx, no param, session_id as capability → OK
```

This keeps the capability model (session_id is unguessable) while adding defense-in-depth when auth is configured.

**Acceptance:**
- Under auth, cross-user session access via leaked session_id is rejected.
- Without auth, session_id is the only capability (explicit design choice, documented).

---

## TIER 2 — Hardening

### 2.1 Orphaned session cleanup on failed creation

**File: `src/aismartbuddy/session.py`**

Currently `create_session` does:
1. Create `session_dir`
2. Instantiate engine
3. `engine.connect()` — can fail
4. On connect failure (already fixed in prior tier): rm `session_dir`.

Extend: also add a try/except around engine instantiation itself (step 2), cleaning up `session_dir` on any exception during steps 2-3. Also wrap the whole creation in a catch that removes the temp `user_id/project_id/session_id` tree but leaves `user_id/project_id/` intact (they're cheap to recreate; shared with other sessions).

**Acceptance:** Injected engine.connect() failure leaves no orphaned directory at any level of the new hierarchy.

---

### 2.2 Enforce MAX_RUBRICS and MAX_EVALUATIONS in ThinkingEngine

**File: `src/aismartbuddy/engines/thinking_engine.py`**

The audit found these constants defined at lines 289-290 but never enforced. Add:
- `_cleanup_scoring_memory()` method that evicts oldest rubrics/evaluations when limits reached.
- Call it in `upsert_rubric()` and `upsert_evaluation()` (lines 710, 728).

Pattern follows the existing `_cleanup_graph_memory()` and `_cleanup_holon_memory()` approach. These limits exist as instance attributes (not module constants) to support per-session tuning later; read from RuntimeConfig if available, fall back to defaults.

**Acceptance:** 150 rubrics created in a session → only newest 100 remain. No unbounded memory growth.

---

### 2.3 Error messages don't leak existence

**Files:** `src/aismartbuddy/session.py`, all `tools/*.py`

Unify "session not found" messages:
- Current session-missing: `"Session 'abc' not found. Use sql_create_session, graph_create_session, or a think_* tool to create one."`
- Current wrong-type: `"Session 'X' is a think session, not SQL."`
- Current (new) ownership mismatch: will use same message as session-missing.

**Invariant:** The exact same error string is returned for (a) session doesn't exist and (b) session exists but not owned by caller. Prevents presence enumeration via error-channel timing or text.

Wrong-type messages are kept as-is (you can't discover someone else's session type without already being able to access it).

**Acceptance:** Given a valid session_id owned by alice, bob's request for it produces the exact same error text as an invalid session_id.

---

### 2.4 Path-component validation and safe rmtree

**File: `src/aismartbuddy/session.py`**

Add `_validate_path_component(value: str, label: str)` helper:
- Regex: `^[A-Za-z0-9_.-]{1,64}$`
- Reject empty, paths, `..`, `/`, `\`, null bytes.

Applied to `user_id` and `project_id` at SessionManager.create_session entry.

Also: the existing `shutil.rmtree(info.temp_dir, ignore_errors=True)` at `_close_session` is safe because it operates on a fully validated, internal-only path. Document this invariant as a comment.

**Acceptance:** `create_session("sql", "../evil", "project")` → ValueError before any filesystem operation.

---

## TIER 3 — Transport Auth Documentation

### 3.1 Document how to enable Bearer token auth + architecture update

**File: `CLAUDE.md`**

Update the Architecture section to include `identity.py`:
```
__main__.py (Click CLI) → server.py (FastMCP + lifespan)
  ├── identity.py (resolve_identity from ctx/params/env)  ←── NEW node
  ├── tools/sql.py    → engines/duckdb_engine.py    ─┐
  ├── tools/graph.py  → engines/ladybug_engine.py    │
  ...
```

Add a new section "Multi-Tenant Model":
- Sessions bound to (user_id, project_id) at creation.
- Per-session `threading.Lock` serializes multi-agent tool calls.
- Session_id is a capability token (128-bit entropy); ownership verified when ctx.client_id is available (Bearer auth path).
- Temp directory layout: `{base}/aismartbuddy/{user_id}/{project_id}/{session_id}/`.

Add a new section "Authentication (optional)":
- How to configure `FastMCP(token_verifier=MyVerifier(), auth=AuthSettings(...))` in server.py.
- Sample `TokenVerifier` implementation pattern (JWT HS256 or similar — reference external).
- Which deployment models it applies to (streamable-http and SSE only; stdio does not support Bearer tokens).
- That `ctx.client_id` becomes the authoritative user_id when auth is configured.

**No executable code change** — this is documentation of an existing SDK capability.

**File: `src/aismartbuddy/server.py`** — add a block comment near the `mcp = FastMCP(...)` instantiation explaining how to wire auth; currently unused.

**Acceptance:** A developer can read CLAUDE.md and know exactly what to configure for Bearer auth.

---

### 3.2 Document identity resolution priority in aismartbuddy-guide prompt

**File: `src/aismartbuddy/server.py:198-347`** (the `aismartbuddy-guide` prompt)

Add a section "## User and Project Isolation":
- Describe user_id/project_id parameters on session-creating tools.
- Document priority: ctx.client_id (Bearer auth) > parameter > env > "default".
- Explain that session_id is a capability; treat it as secret.
- Document the new `aismartbuddy://sessions/{user_id}/{project_id}` resource template.

**Acceptance:** An AI agent reading this prompt knows to pass user_id/project_id when creating sessions and that session_ids are secrets.

---

## TIER 4 — Testing

### 4.1 Isolation test matrix

**New file: `tests/test_multi_tenant_isolation.py`**

Test cases (each is one `@pytest.mark.anyio async def test_...`):

1. **Different users cannot see each other's sessions**
   - Create session as alice; create session as bob.
   - list_sessions("alice") returns only alice's session; "bob" returns only bob's.

2. **Same user, different projects cannot see each other's sessions**
   - Create session as alice/acme and alice/other.
   - list_sessions("alice", "acme") returns only the acme one.

3. **Session access via mismatched ownership is rejected**
   - Create as alice/acme, try to `get_session(sid, "bob", "acme")` → ValueError.
   - Error message matches the "not found" pattern (enumeration resistance).

4. **Same user + project from different agents can share a session**
   - Create as alice/acme, get the session_id.
   - Two concurrent tasks call `sql_query(sid)` — both succeed, no errors, results correct.
   - Under the lock, calls serialize (verified by timing: two concurrent 200ms queries take ~400ms, not ~200ms).

5. **Path traversal attempts are blocked**
   - `create_session("sql", "../etc", "foo")` → ValueError.
   - `create_session("sql", "ok", "a/b")` → ValueError.

6. **ThinkingEngine does not corrupt state under multi-agent load**
   - Create think session.
   - Spawn 10 concurrent tasks each adding 50 thought nodes to the same session.
   - After all complete, total nodes == 500, all have unique IDs, no orphans.

7. **Auto-session creation for think tools respects identity**
   - Without session_id, call think_graph with `user_id="alice"`.
   - Verify session's user_id == "alice" and project_id == "default".
   - Second call without session_id creates a DIFFERENT session (not reuse).

8. **Temp directory layout mirrors identity**
   - Create session as alice/acme.
   - Verify `{temp_base}/aismartbuddy/alice/acme/{session_id}/` exists.
   - Destroy session; verify session_id dir removed but alice/acme/ may remain.

9. **list_sessions resource returns scoped results via template**
   - Create sessions for alice/acme, alice/other, bob/acme.
   - Read resource `aismartbuddy://sessions/alice/acme` → only the alice/acme session.

10. **Constant-time error for missing vs wrong-user session**
    - Both return the same error text (string equality check).

**Fixture helpers:** extend `conftest.py` with a `make_session(user_id, project_id, session_type)` helper.

---

### 4.2 Verify existing tests still pass

All existing tests currently construct sessions via `session_manager.create_session("sql")` without user_id/project_id. Two options:

**Option A (picked): default parameters in the existing SessionManager method**
- Keep `create_session(session_type, user_id: str = "default", project_id: str = "default")` so existing callers without identity still work.
- All existing tests behave identically (they get `user_id="default"`, `project_id="default"` sessions).

This is cleaner than modifying every test file.

**Acceptance:** `uv run pytest -v` passes 206 existing tests + ~10 new tests.

---

## Files Modified / Created

| File | Action | Tier |
|---|---|---|
| `src/aismartbuddy/session.py` | Modify: SessionInfo fields, SessionManager signatures, temp layout, path validation | 1.1, 1.2, 1.3, 2.1, 2.3, 2.4 |
| `src/aismartbuddy/identity.py` | **Create** — identity resolution helper | 1.4 |
| `src/aismartbuddy/config.py` | Modify: add default_user_id, default_project_id fields | 1.4 |
| `src/aismartbuddy/__main__.py` | Modify: new CLI options + envvar bindings | 1.4 |
| `src/aismartbuddy/tools/__init__.py` | Modify: lock-aware execute helpers, new run_with_lock helper | 1.6 |
| `src/aismartbuddy/tools/sql.py` | Modify: sql_create_session signature, ctx plumbing, use lock helpers | 1.5, 1.6, 1.8 |
| `src/aismartbuddy/tools/graph.py` | Modify: graph_create_session signature, ctx plumbing, lock helpers | 1.5, 1.6, 1.8 |
| `src/aismartbuddy/tools/think.py` | Modify: auto-session creates with identity, lock helpers | 1.5, 1.6, 1.8 |
| `src/aismartbuddy/tools/holon.py` | Modify: auto-session with identity, lock helpers | 1.5, 1.6, 1.8 |
| `src/aismartbuddy/tools/score.py` | Modify: lock helpers | 1.6 |
| `src/aismartbuddy/server.py` | Modify: replace sessions resource, lifespan passes defaults, auth docs comment, update prompt | 1.7, 3.1, 3.2 |
| `src/aismartbuddy/engines/thinking_engine.py` | Modify: docstring update, MAX_RUBRICS/MAX_EVALUATIONS enforcement | 1.6, 2.2 |
| `tests/test_multi_tenant_isolation.py` | **Create** — isolation matrix tests | 4.1 |
| `tests/conftest.py` | Modify: add make_session helper | 4.1 |
| `CLAUDE.md` | Modify: document multi-tenant model, auth configuration, new layout | 3.1 |

---

## Verification

After Tier 1:
```
uv run pytest tests/test_multi_tenant_isolation.py -v    # new tests pass
uv run pytest -v                                          # all 206+ existing tests still pass
uv run pyright                                            # type check clean
uv run ruff check src/ tests/                             # lint clean
```

Manual check — multi-tenant scenario:
```
uv run python -c "
from aismartbuddy.session import SessionManager
mgr = SessionManager(temp_base_dir='/tmp/mt-test', session_timeout=60)
alice_sess = mgr.create_session('sql', 'alice', 'acme')
bob_sess = mgr.create_session('sql', 'bob', 'acme')
# Alice sees only her session
print('alice:', [s.session_id for s in mgr.list_sessions('alice')])
print('bob:', [s.session_id for s in mgr.list_sessions('bob')])
# Cross-user access blocked
try:
    mgr.get_session(alice_sess.session_id, 'bob', 'acme')
    print('FAIL: bob got alice session')
except ValueError as e:
    print('OK: bob rejected:', e)
mgr.cleanup_all()
"
```

After Tier 2:
```
# Under concurrent load, no data corruption
uv run python -c "
# Spawn 50 threads adding thought nodes to shared session, verify count
"
```

After Tier 3:
```
# Documentation review — grep for TODO/FIXME/stub in CLAUDE.md
grep -n 'TODO\|FIXME\|stub' CLAUDE.md
```

---

## Non-Goals (explicit out-of-scope)

- **Export/import tools** — User rejected: "nah, let the AI agents in context create subagents if they need to copy content over". If cross-session data transfer is needed, agents orchestrate it themselves via existing tools.
- **Persistent projects across restarts** — User did not select this option. Sessions stay ephemeral (temp-based), wiped on server restart.
- **Fine-grained engine locks** — User chose per-session lock (serialize). Fine-grained parallelism within a single session is explicitly out of scope.
- **ACL / permission rules beyond user+project** — No groups, no roles, no share-with-specific-user. Trust boundary is (user_id, project_id); within that pair, full access.
- **Full OAuth issuer implementation** — Documentation-only. This plan shows HOW to configure MCP SDK's existing Bearer auth; does not ship a TokenVerifier implementation.
- **Rate limiting / quota per user** — Out of scope. Can be layered later if needed.
- **Session encryption at rest** — Files on disk remain plaintext. If the threat model changes, DuckDB/LadybugDB support encryption, but that's a separate initiative.

---

## TLDR

Bind every session to `(user_id, project_id)` at creation time, add a per-session `threading.Lock` to serialize multi-agent access, upgrade session_id entropy to 128 bits, replace the global sessions resource with a scoped template, and source identity from MCP Bearer tokens when configured (falling back to explicit parameters and env defaults). Backward compatible via `"default"` user/project fallbacks so existing single-tenant usage keeps working. Multi-agent sharing is implicit: any caller who resolves to the same `(user_id, project_id)` and holds the session_id can access the session. No new export/import plumbing — AI agents orchestrate cross-session copies themselves via existing tools.
