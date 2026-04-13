# AISmartBuddy MCP Server — Architectural Audit & Improvement Plan

## Verbatim Requirements

### Original Request
> load in the mcp server creation skill. Go through the whole MCP server, as an architect and analyze the code an structure, performance multi threaded, buffer sizes, use polars dataframe with arrow for duckdb and ladybugdb, stream size. remote and local. token efficient outputs. look at tool description for clarity and the ability for correctly oneshot use by letting the description give clarity on use cases. use clear-thought look for missing implementation. look for improvement opportunities

### Clarifications
**Q:** (from plan review)
**A:** > when having limit, the ability for paging needs to be available to get all data

## Context

AISmartBuddy is a Python MCP server (45 tools, 5 prompts, 1 resource) providing AI assistants with temporary SQL (DuckDB), graph (LadybugDB/Cypher), and structured thinking sessions. The server is functional but leaves significant performance and capability on the table: both DuckDB and LadybugDB expose Arrow/Polars APIs that are completely unused, the data pipeline materializes everything through slow Python tuples and csv.writer, the MCP SDK's progress reporting and streamable-http transport are unavailable, and several reliability gaps exist (silent background task failure, orphaned temp dirs). This plan addresses all findings from a comprehensive architectural audit.

---

## Current Architecture (As-Is)

```
CLI (__main__.py)
  → config.py (RuntimeConfig)
  → server.py (FastMCP + lifespan)
      ├── tools/sql.py    → engines/duckdb_engine.py    ─┐
      ├── tools/graph.py  → engines/ladybug_engine.py     ├── session.py (SessionManager)
      ├── tools/think.py  → engines/thinking_engine.py    │
      ├── tools/holon.py  → engines/thinking_engine.py    │
      ├── tools/score.py  → engines/thinking_engine.py    │
      └── tools/meta.py                                   │
          formatting.py (CSV/table via csv.writer) ────────┘

Data flow: engine.execute() → list[tuple] → csv.writer(StringIO) → str → MCP response
```

---

## TIER 1 — Arrow/Polars Data Pipeline + Engine Tuning + Reliability Fixes

### 1.1 Replace tuple-based data flow with Arrow/Polars

**Problem:** All query results pass through Python `list[tuple]` and `csv.writer` — the slowest possible path. Both engines expose Arrow/Polars APIs that enable zero-copy interchange and 10-100x faster CSV serialization.

**Target architecture:**
```
DuckDB:    conn.execute(sql).fetch_arrow_table()  → pyarrow.Table
LadybugDB: conn.execute(cypher).get_as_arrow()    → pyarrow.Table
                         ↓
              polars.from_arrow(table)             → polars.DataFrame
                         ↓
              df.head(max_rows).write_csv()        → str (formatted output)
```

**Files to modify:**

- **`pyproject.toml`** — Add dependencies:
  - `polars >= 1.0` (DataFrame ops + fast CSV)
  - `pyarrow >= 17.0` (Arrow interchange, already a transitive dep of duckdb)

- **`engines/__init__.py`** (BaseEngine):
  - Change `execute()` abstract signature: `→ tuple[list[str], list[tuple]]` stays as the return type for backward compat
  - Add new abstract method `execute_arrow(query: str) → pyarrow.Table | None` with default implementation that falls back to `execute()` and converts
  - Add `_arrow_to_tuples(table: pa.Table) → tuple[list[str], list[tuple]]` utility for backward compat where needed

- **`engines/duckdb_engine.py`** (DuckDBEngine):
  - `execute()` — Keep as-is for backward compat (tests, simple cases)
  - Add `execute_arrow(sql: str) → pa.Table | None`:
    ```python
    result = conn.execute(sql)
    if result.description is None:
        return None
    return result.fetch_arrow_table()
    ```
  - `connect()` — Add config dict:
    ```python
    self._conn = duckdb.connect(self._db_path, config={
        'threads': self._threads,
        'memory_limit': self._memory_limit,
        'temp_directory': self._session_dir,
    })
    ```
  - Constructor: accept `threads: int = 0` (auto-detect), `memory_limit: str = '256MB'`

- **`engines/ladybug_engine.py`** (LadybugEngine):
  - Add `execute_arrow(cypher: str) → pa.Table | None`:
    ```python
    result = conn.execute(cypher)
    if isinstance(result, list):
        result = result[-1] if result else None
    if result is None:
        return None
    try:
        return result.get_as_arrow()
    except (AttributeError, RuntimeError):
        return None
    ```
  - `connect()` — Add buffer/thread config:
    ```python
    self._db = lb.Database(
        self._db_path,
        buffer_pool_size=self._buffer_pool_size,
        max_num_threads=self._max_threads,
    )
    ```
  - Constructor: accept `buffer_pool_size: int = 256 * 1024 * 1024` (256MB), `max_threads: int = 0`

- **`formatting.py`** — Major refactor:
  - Add `format_arrow_as_csv(table: pa.Table, max_rows, max_chars) → str`:
    ```python
    import polars as pl
    df = pl.from_arrow(table).head(max_rows)
    csv_str = df.write_csv()
    # Apply max_chars truncation
    ...
    meta = f"# {table.num_rows} rows x {table.num_columns} columns"
    return meta + "\n" + csv_str
    ```
  - Add `format_arrow_as_table(table: pa.Table, max_rows, max_chars) → str`:
    - Use `polars.from_arrow(table).head(max_rows)` then tabulate on `.to_pandas()` or `.rows()`
  - Add `format_arrow_result(table: pa.Table | None, max_rows, max_chars, output_format) → str`:
    - Handles None (DDL/DML), empty table, delegates to csv/table formatter
  - Keep existing `format_result()` as fallback for non-Arrow paths (thinking tools)

- **`tools/sql.py`** — Use Arrow path:
  - `sql_query()`: Call `info.engine.execute_arrow(query)` → `format_arrow_result()`
  - Fall back to `execute()` + `format_result()` if Arrow unavailable

- **`tools/graph.py`** — Use Arrow path:
  - `graph_query()`: Call `info.engine.execute_arrow(query)` → `format_arrow_result()`
  - Same fallback pattern

**Acceptance criteria:**
- All SQL/graph query results flow through Arrow → Polars → CSV
- Existing tests pass without modification (backward compat via fallback)
- CSV output is identical in format (header + data rows + metadata comment)
- New benchmark: 10K row query formatted in < 100ms (vs current ~500ms+)

---

### 1.2 Result pagination — page through full datasets

**Problem:** When results exceed `max_rows`, the current server silently truncates — the AI has no way to fetch the remaining data. With a 1000-row limit and a 50K-row table, 98% of data is inaccessible.

**Design — Two complementary pagination mechanisms:**

```
Mechanism 1: Explicit offset/limit (SQL-level, re-executes query)
  sql_query(sid, "SELECT * FROM big_table", offset=0, limit=500)    → rows 0-499
  sql_query(sid, "SELECT * FROM big_table", offset=500, limit=500)  → rows 500-999

Mechanism 2: Cursor-based paging (Arrow streaming, single query execution)
  sql_query(sid, "SELECT * FROM big_table", paginate=true)  → page 1 + cursor_id
  sql_query_next(sid, cursor_id)                             → page 2
  sql_query_next(sid, cursor_id)                             → page 3 (or "end of results")
```

**Why both:**
- Offset/limit is simple and works for random access (jump to page 5)
- Cursor paging is efficient for sequential scan (the Arrow `RecordBatchReader` from DuckDB streams batches without re-executing the query — critical for large results)

**Files to modify:**

- **`engines/__init__.py`** (BaseEngine):
  - Add `_cursors: dict[str, pa.RecordBatchReader]` dict for active cursors
  - Add `execute_paged(query, page_size) → tuple[str, pa.Table]` — returns cursor_id + first page
  - Add `fetch_next_page(cursor_id) → pa.Table | None` — returns next page or None if exhausted
  - Add `close_cursor(cursor_id)` — cleanup

- **`engines/duckdb_engine.py`** (DuckDBEngine):
  - `execute_paged()`: Use `conn.execute(sql).fetch_arrow_reader(rows_per_batch=page_size)`
    - Store the `RecordBatchReader` in `_cursors[cursor_id]`
    - Return first batch as Arrow table
  - `fetch_next_page()`: Call `reader.read_next_batch()` on stored reader
    - Return None when exhausted, auto-cleanup cursor

- **`engines/ladybug_engine.py`** (LadybugEngine):
  - `execute_paged()`: Use `get_as_arrow()` then chunk manually via Polars `DataFrame.iter_slices(page_size)`
    - LadybugDB doesn't have streaming Arrow reader, so materialize + slice
    - Store iterator in `_cursors`
  - `fetch_next_page()`: Get next slice from iterator

- **`tools/sql.py`**:
  - `sql_query()` — Add `offset: int | None = None` and `limit: int | None = None` params:
    - When provided, override max_rows with limit, skip offset rows via Polars `.slice(offset, limit)`
    - Include pagination metadata in response: `# Page: rows {offset}-{offset+limit} of {total}`
  - `sql_query()` — Add `paginate: bool = False` param:
    - When True, use `execute_paged()`, return first page + cursor_id
    - Response includes: `cursor_id: {id} | has_more: true | page: 1`
  - New tool `sql_query_next(session_id, cursor_id)`:
    - Fetches next page from stored cursor
    - Returns formatted page + `has_more: true/false`
    - Auto-closes cursor when exhausted

- **`tools/graph.py`** — Same pattern:
  - `graph_query()` — Add `offset`, `limit`, `paginate` params
  - New tool `graph_query_next(session_id, cursor_id)`

- **`server.py`** — Register new tools:
  - `sql_query_next` with `_READONLY` annotations
  - `graph_query_next` with `_READONLY` annotations

- **`session.py`** — Cursor cleanup:
  - `_close_session()` — Close all active cursors for the session
  - Periodic cleanup — Close cursors that have been idle too long

**Response format with pagination:**
```
# 50000 rows x 5 columns (page 1, rows 0-999, cursor: abc123)
col1,col2,col3,col4,col5
...1000 rows...
# has_more: true | cursor_id: abc123 | next: sql_query_next(session_id, "abc123")
```

**Acceptance criteria:**
- `sql_query(sid, q, offset=1000, limit=500)` returns rows 1000-1499
- `sql_query(sid, q, paginate=true)` returns first page + cursor_id
- `sql_query_next(sid, cursor_id)` returns subsequent pages
- Last page returns `has_more: false` and auto-closes cursor
- Cursors cleaned up on session destroy
- Cursor timeout after 5 minutes of inactivity (tracked via `last_accessed` timestamp stored alongside each cursor in `_cursors: dict[str, tuple[Any, datetime]]`; checked by `_periodic_cleanup` in server.py alongside session expiration; `cursor_timeout` configurable in RuntimeConfig, default 300s)
- Graph tools have identical pagination support
- Guide prompts updated: `aismartbuddy-guide`, `sql-guide`, `graph-guide` in server.py include pagination examples and new tool docs

---

### 1.3 DuckDB and LadybugDB connection tuning (was 1.2)

**Problem:** Both engines use bare `connect()` calls with zero configuration. DuckDB doesn't set threads, memory limits, or temp directory. LadybugDB doesn't set buffer pool size or thread count.

**Files to modify:**

- **`config.py`** — Add new RuntimeConfig fields:
  ```
  duckdb_threads: int = 0          # 0 = auto-detect
  duckdb_memory_limit: str = '256MB'
  ladybug_buffer_pool_size: int = 256 * 1024 * 1024  # 256MB
  ladybug_max_threads: int = 0     # 0 = auto-detect
  ```

- **`__main__.py`** — Add CLI options:
  ```
  --duckdb-threads, --duckdb-memory-limit
  --ladybug-buffer-size, --ladybug-threads
  ```
  Add `envvar=` to ALL Click options for Docker/env var config.

- **`session.py`** — Pass new config values to engine constructors:
  - `DuckDBEngine(db_path, max_rows, max_chars, threads=rc.duckdb_threads, memory_limit=rc.duckdb_memory_limit)`
  - `LadybugEngine(db_path, max_rows, max_chars, buffer_pool_size=rc.ladybug_buffer_pool_size, max_threads=rc.ladybug_max_threads)`

**Acceptance criteria:**
- DuckDB `PRAGMA threads` returns configured value
- LadybugDB uses configured buffer pool
- All existing tests pass
- CLI `--help` shows new options with sensible defaults

---

### 1.4 Reliability fixes — silent failures and resource leaks

**Problem A:** `_periodic_cleanup` (server.py:19-30) has no error handling — if `cleanup_expired()` raises, the background task dies silently and sessions never get cleaned up again.

**Fix in `server.py`:**
```python
async def _periodic_cleanup(interval: int = 300) -> None:
    from aismartbuddy import session as session_mod
    while True:
        await anyio.sleep(interval)
        try:
            if session_mod.session_manager is not None:
                count = await anyio.to_thread.run_sync(
                    session_mod.session_manager.cleanup_expired
                )
                if count > 0:
                    logger.info("Periodic cleanup removed %d expired sessions", count)
        except Exception:
            logger.exception("Error in periodic cleanup")
```

**Problem B:** `create_session()` (session.py:92-94) creates `session_dir` before `engine.connect()`. If connect fails, orphaned empty directories accumulate.

**Fix in `session.py`:**
```python
try:
    engine.connect()
except Exception:
    shutil.rmtree(str(session_dir), ignore_errors=True)
    raise
```

**Acceptance criteria:**
- Background cleanup survives exceptions and logs them
- Failed `create_session()` leaves no orphaned directories
- Add tests for both error paths

---

### 1.5 Documentation update — Tier 1

Update `CLAUDE.md` to reflect Tier 1 changes:
- Architecture diagram: change data flow from `engine.execute() → list[tuple] → csv.writer → str` to `engine.execute_arrow() → pa.Table → polars.DataFrame → write_csv() → str`
- Add new tools to tool count: `sql_query_next`, `graph_query_next` (45 → 47 tools)
- Document pagination in "Key patterns" section
- Document new CLI options (`--duckdb-threads`, `--duckdb-memory-limit`, `--ladybug-buffer-size`, `--ladybug-threads`)
- Update `server.py` guide prompts (`aismartbuddy-guide`, `sql-guide`, `graph-guide`) to document pagination patterns

---

## TIER 2 — Transport, Progress Reporting, Tool Descriptions

### 2.1 Add streamable-http transport

**Problem:** Only stdio and SSE transports are available. The MCP SDK (v1.27.0) recommends streamable-http over SSE (which is deprecated). No health check endpoint exists for production monitoring.

**Files to modify:**

- **`__main__.py`**:
  - Add `"streamable-http"` to transport choices
  - Add `--streamable-http-path` option (default: `/mcp`)
  - Add `--stateless` flag for serverless deployment

- **`server.py`**:
  - Add health check route:
    ```python
    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(request):
        from starlette.responses import JSONResponse
        session_count = len(session_mod.session_manager._sessions) if session_mod.session_manager else 0
        return JSONResponse({"status": "ok", "sessions": session_count, "version": SERVER_VERSION})
    ```
  - Handle streamable-http in run logic

- **`config.py`** — Add fields:
  ```
  streamable_http_path: str = "/mcp"
  stateless_http: bool = False
  cors_origins: list[str] = field(default_factory=list)
  ```

**Acceptance criteria:**
- `--transport streamable-http` starts server on configured path
- `/health` endpoint returns JSON with status and session count
- Existing stdio/SSE transports unaffected

---

### 2.2 Progress reporting for long operations

**Problem:** No tool reports progress. Long imports and graph statistics queries appear frozen to the client. The MCP SDK's `ctx.report_progress()` and `ctx.info()` are available but unused.

**Files to modify:**

- **`tools/sql.py`**:
  - `sql_import_batch()` — Add `ctx: Context` parameter, report per-chunk progress:
    ```python
    for i, chunk in enumerate(chunks):
        await ctx.report_progress(i, len(chunks), f"Importing chunk {i+1}/{len(chunks)}")
        ...
    ```
  - `sql_import()` — `await ctx.info(f"Importing {data_format} data into '{table_name}'")`

- **`tools/graph.py`**:
  - `graph_statistics()` — Report progress per table counted
  - `graph_import()` — Log import start/completion

- **Note:** FastMCP automatically injects `ctx: Context` when the parameter is typed — no registration change needed.

**Acceptance criteria:**
- `sql_import_batch` sends progress notifications per chunk
- `graph_statistics` sends progress per table
- Progress visible in MCP clients that support it
- Tools still work when client doesn't support progress (graceful degradation)

---

### 2.3 Tool description improvements for one-shot usability

**Problem:** AI agents frequently need multiple attempts to use tools correctly. Descriptions lack minimal examples, cross-references, and inline enum values.

**Changes (all in tool docstrings):**

**A) Consistent defaults — change graph_query default to "csv":**
- `graph_query(output_format="csv")` instead of `"table"` — matches sql_query, more token-efficient

**B) Add minimal examples to each tool description:**
- `sql_query`: `Example: sql_query(sid, "SELECT * FROM t LIMIT 10")`
- `graph_query`: `Example: graph_query(sid, "MATCH (n) RETURN n.name LIMIT 10;")`
- `graph_import`: Include a complete node + relationship import example
- `think_model`: List all 13 model names inline
- `holon_create`: Show a concrete domain example

**C) Add "See also" cross-references:**
- `graph_compare` → "See also: graph_cross_reference for detailed node-level matching"
- `graph_cross_reference` → "See also: graph_compare for structural overview"
- `think_graph` → "See also: think_model for framework-guided analysis, think_decide for decisions"
- `holon_create` → "See also: think_graph for simpler sequential reasoning"

**D) Add "Common errors" to frequently-misused tools:**
- `graph_query`: "Common error: missing semicolon at end of Cypher statement"
- `graph_import`: "Common error: not creating NODE TABLE before importing nodes"

**E) Inline enum values in descriptions (not just in param docs):**
- `graph_analyze`: List and briefly describe each analysis_type
- `think_model`: List all 13 models with one-line descriptions
- `holon_analyze`: Group 9 actions by use case (navigation vs analysis vs propagation)

**Files:** All `tools/*.py` docstrings.

**Acceptance criteria:**
- Every tool description includes a minimal example
- Enum values listed inline in description body
- Related tools cross-referenced
- graph_query defaults to "csv"
- Review by running server and checking tool descriptions in MCP inspector

---

### 2.4 Documentation update — Tier 2

Update `CLAUDE.md`:
- Add streamable-http transport to "Build & Run Commands" section
- Document env var overrides (if added in this tier)
- Document `/health` endpoint

Update `server.py` guide prompts:
- Tool description improvements are self-documenting (docstrings = tool descriptions)

---

## TIER 3 — Async LadybugDB, Extensions, CLI Env Vars, Resources

### 3.1 LadybugDB async connections

**Problem:** LadybugDB offers `lb.AsyncConnection(db, max_concurrent_queries=4)` but the server uses synchronous `lb.Connection` with `anyio.to_thread.run_sync()` wrappers.

**Design — Dual connection approach:** Keep `_conn` (sync `lb.Connection`) for backward compatibility (tests, simple operations). Add `_async_conn` (`lb.AsyncConnection`) for async tool paths. This avoids breaking the existing synchronous `execute()` method, which returns `QueryResult` directly — switching `_conn` to `AsyncConnection` would break it because `AsyncConnection.execute()` returns a coroutine.

**Files to modify:**

- **`engines/ladybug_engine.py`**:
  - Add `_async_conn: lb.AsyncConnection | None = None` alongside existing `_conn`
  - `connect()` — Create both connections from the same `_db`:
    ```
    self._conn = lb.Connection(self._db)
    self._async_conn = lb.AsyncConnection(self._db, max_concurrent_queries=4, max_threads_per_query=2)
    ```
  - Add `async def execute_async(cypher) → tuple[list[str], list[tuple]]` using `_async_conn`
  - Add `async def execute_arrow_async(cypher) → pa.Table | None` using `_async_conn`
  - Keep synchronous `execute()` and `execute_arrow()` unchanged (use `_conn`)
  - `close()` — Close both connections

- **`tools/graph.py`**:
  - Replace `await anyio.to_thread.run_sync(lambda: info.engine.execute(query))` with `await info.engine.execute_async(query)` in all tool functions
  - Remove thread-pool wrapping for graph operations — native async is cleaner and lower latency
  - Fall back to sync + thread pool if `_async_conn` is None (graceful degradation)

**Acceptance criteria:**
- Graph queries execute natively async (no thread pool)
- Existing synchronous tests still pass (they use `_conn` path)
- `_async_conn` and `_conn` coexist without resource conflicts
- Measured latency improvement on concurrent graph queries

---

### 3.2 LadybugDB extensions — algo, fts, vector

**Problem:** Only the "json" extension is loaded. The "algo", "fts", and "vector" extensions would significantly expand graph capabilities.

**Files to modify:**

- **`engines/ladybug_engine.py`** — `connect()`:
  ```python
  for ext in ["json", "algo"]:
      try:
          self._conn.execute(f"INSTALL {ext}; LOAD {ext};")
      except Exception:
          logger.debug("Extension %s not available", ext)
  ```

- **`tools/graph.py`** — Add dedicated tool:
  - `graph_algorithm(session_id, algorithm, params)` — PageRank, shortest path, community detection, betweenness centrality via algo extension
  - Also document FTS capability in `graph_query` description (no new tool needed — users call FTS via Cypher in graph_query)

**Acceptance criteria:**
- "algo" extension loads successfully (if available in real-ladybug distribution)
- New graph_algorithm tool (or documented Cypher patterns) for common algorithms
- Graceful fallback if extensions aren't available

---

### 3.3 CLI environment variable binding

**Problem:** `load_dotenv()` is called but Click options don't use `envvar=`, so environment variables are ignored.

**File: `__main__.py`** — Add envvar to each option:
```python
@click.option("--transport", ..., envvar="AISMARTBUDDY_TRANSPORT")
@click.option("--port", ..., envvar="AISMARTBUDDY_PORT")
@click.option("--host", ..., envvar="AISMARTBUDDY_HOST")
@click.option("--temp-dir", ..., envvar="AISMARTBUDDY_TEMP_DIR")
@click.option("--max-rows", ..., envvar="AISMARTBUDDY_MAX_ROWS")
@click.option("--max-chars", ..., envvar="AISMARTBUDDY_MAX_CHARS")
@click.option("--session-timeout", ..., envvar="AISMARTBUDDY_SESSION_TIMEOUT")
```

**Acceptance criteria:**
- `AISMARTBUDDY_PORT=9000 uv run python -m aismartbuddy --transport sse` uses port 9000
- CLI flags still override env vars
- Document env vars in `--help` output

---

### 3.4 Dynamic resource templates

**Problem:** Only one static resource `aismartbuddy://sessions`. MCP SDK supports URI templates for per-session detail resources.

**File: `server.py`** — Add resource templates:
```python
@mcp.resource("aismartbuddy://sessions/{session_id}")
async def session_detail(session_id: str) -> str:
    """Get details for a specific session: type, age, schema."""
    ...

@mcp.resource("aismartbuddy://sessions/{session_id}/schema")
async def session_schema(session_id: str) -> str:
    """Get database schema for a session."""
    ...
```

**Acceptance criteria:**
- `aismartbuddy://sessions/{id}` returns session metadata
- `aismartbuddy://sessions/{id}/schema` returns database schema
- Invalid session_id returns helpful error

---

### 3.5 Documentation update — Tier 3

Update `CLAUDE.md`:
- Document async LadybugDB behavior in "Key patterns"
- Document env var config with `AISMARTBUDDY_*` prefix
- Document graph algorithm extension capabilities
- Update resource list to include per-session resources

---

## TIER 4 — Nice-to-Have Improvements

### 4.1 Structured output schemas
- Return Pydantic models from schema/statistics tools
- SDK auto-generates `outputSchema` for programmatic consumption
- Files: tools/sql.py, tools/graph.py, server.py

### 4.2 Graph export tools
- `graph_export(session_id, format="csv"|"cypher")` — dump graph to portable format
- Enables backup, cross-session transfer, sharing
- Files: engines/ladybug_engine.py, tools/graph.py

### 4.3 SQL EXPLAIN support
- Handle `EXPLAIN` and `EXPLAIN ANALYZE` in sql_query or new `sql_explain` tool
- DuckDB supports this natively
- Files: tools/sql.py

### 4.4 Configurable thinking limits
- Move MAX_NODES, MAX_TREES, MAX_HOLONS to RuntimeConfig
- Add CLI options for override
- Files: config.py, __main__.py, engines/thinking_engine.py

### 4.5 Lifespan context instead of module singleton
- Use `yield {"session_manager": mgr}` in lifespan
- Access via `ctx.request_context.lifespan_context["session_manager"]`
- Cleaner than module-level global, enables testing
- Files: server.py, tools/__init__.py

---

## Critical Files Summary

| File | Changes | Tier |
|------|---------|------|
| `pyproject.toml` | Add polars, pyarrow deps | 1.1 |
| `engines/__init__.py` | Add execute_arrow() ABC + cursor management | 1.1, 1.2 |
| `engines/duckdb_engine.py` | Arrow path + pagination cursors + connection config | 1.1, 1.2, 1.3 |
| `engines/ladybug_engine.py` | Arrow path + pagination + buffer config + async + extensions | 1.1, 1.2, 1.3, 3.1, 3.2 |
| `formatting.py` | Polars-based formatters + pagination metadata | 1.1, 1.2 |
| `config.py` | New config fields | 1.3, 2.1, 3.3 |
| `__main__.py` | New CLI options + envvar + transport | 1.3, 2.1, 3.3 |
| `session.py` | Pass config to engines + orphan fix + cursor cleanup | 1.3, 1.4 |
| `server.py` | Cleanup fix + health route + resources + new pagination tools | 1.2, 1.4, 2.1, 3.4 |
| `tools/sql.py` | Arrow path + pagination + progress + descriptions | 1.1, 1.2, 2.2, 2.3 |
| `tools/graph.py` | Arrow path + pagination + progress + descriptions + async | 1.1, 1.2, 2.2, 2.3, 3.1 |
| `tools/think.py` | Description improvements | 2.3 |
| `tools/holon.py` | Description improvements | 2.3 |
| `tools/score.py` | Description improvements | 2.3 |
| `tools/meta.py` | Description improvements | 2.3 |

---

## Verification Plan

### After Tier 1:
```bash
uv sync                              # Install new deps (polars, pyarrow)
uv run pytest -v                     # All existing tests pass
uv run pyright                       # Type check passes
uv run ruff check src/ tests/        # Lint clean
uv run python -c "
from aismartbuddy.engines.duckdb_engine import DuckDBEngine
import tempfile, os
d = tempfile.mkdtemp()
e = DuckDBEngine(os.path.join(d, 'test.db'))
e.connect()
# Verify Arrow path
t = e.execute_arrow('SELECT 1 AS a, 2 AS b')
print(type(t))  # should be pyarrow.Table
print(t.num_rows, t.num_columns)  # 1, 2
# Verify connection config
r = e.execute('PRAGMA threads')
print(r)  # should show configured threads
e.close()
"
```

### After Tier 2:
```bash
# Test streamable-http
uv run python -m aismartbuddy --transport streamable-http --port 8000 &
curl http://localhost:8000/health      # Should return JSON status
kill %1

# Test tool descriptions
uv run python -c "
from aismartbuddy.server import mcp
for tool in mcp._tool_manager._tools.values():
    desc = tool.fn.__doc__
    assert 'Example:' in desc or 'example' in desc.lower(), f'{tool.name} missing example'
    print(f'OK: {tool.name}')
"
```

### After Tier 3:
```bash
# Test env var binding
AISMARTBUDDY_PORT=9000 uv run python -m aismartbuddy --transport sse &
curl http://localhost:9000/health
kill %1

# Test LadybugDB async
uv run pytest tests/test_graph_tools.py -v
```

---

## TLDR

This plan overhauls AISmartBuddy's data pipeline from slow Python tuples + csv.writer to Arrow/Polars (10-100x faster formatting), adds cursor-based and offset/limit pagination so AI agents can page through full datasets beyond the row limit, tunes DuckDB/LadybugDB engine configurations for performance, adds streamable-http transport with progress reporting for production readiness, and improves all 45 tool descriptions with minimal examples and cross-references for reliable one-shot AI usage. Implementation is prioritized across 4 tiers — Arrow/Polars pipeline + pagination first (foundation for everything else), then transport + descriptions, then async + extensions, then nice-to-haves.
