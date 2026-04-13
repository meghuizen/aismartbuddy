# AISmartBuddy MCP Server — Implementation Plan

## Verbatim Requirements

### Original Request
> load the skill of mcp server building. I want this project to be a python mcp server which will be high performance and highly effective in extending AI with thinking capabilities and tools. the MCP server will need to use proper data types optimized for tokens (like CSV export for bulk data instead of JSON). The MCP server can run as remote MCP server and as a local stdio mcp server. the name will be AISmartBuddy and build in python. The first focus will be for this MCP server: The MCP server will provide a temporary session based duckdb database which it can setup, get's a session token, can setup the database and import data (singular, but also in bulk) and can run all kinds of queries against that database. Ofcourse duckdb is for SQL, tabular and also analytical kind of queries. It will create random named databases, which will be cleaned/removed when it's done as well using a general temporary directory. For graph databases we will also expose graph database using ladybug. Make sure you create proper tools which assist the AI in using the correct database for the correct use cases. Here you have an example of a ladybug mcp server which you can use to create a proper graph tools (call them graph and sql endpoints, not the name of the database), this is the folder location: https://github.com/LadybugDB/mcp-server-ladybug.git   Also start meridian research agents on duckdb and ladybug before you build them. use clear-thought and this is the start for more functionality to come. also create a good README.md with proper getting started, how to debug, how to run, what tools it expose.

### Clarifications
**Q:** LadybugDB MCP server location
**A:** the mcp server for ladybug you can find locally: C:\Users\michiele\source\repos\mcp-server-ladybug

---

## Context

This is a greenfield Python MCP server project. The directory currently contains only a `CLAUDE.md` file and the `.agents/skills/mcp-builder/` reference skill. No Python code, no `pyproject.toml`, no tests exist yet.

The goal is to build a production-quality MCP server that gives AI assistants on-demand access to both SQL analytics (via DuckDB) and graph database capabilities (via LadybugDB/Cypher). Each AI conversation gets isolated, temporary database sessions that are cleaned up automatically. Output is token-optimized (CSV for bulk tabular data) to minimize context window consumption.

This is the foundation — designed to be extended with additional tools and capabilities in future iterations.

---

## Reference Implementation

The LadybugDB MCP server at `C:\Users\michiele\source\repos\mcp-server-ladybug` serves as the architectural reference. Key patterns to adopt:
- `build_application()` pattern returning `(server, init_options)`
- Click-based CLI with transport/port/host/config args
- DatabaseClient wrapper class for DB lifecycle
- Tabulate-based result formatting with row/char limits
- Prompt templates for AI guidance
- Starlette+Uvicorn for SSE transport

---

## Architecture

```
                    ┌──────────────────────────────────┐
                    │         __main__.py               │
                    │   CLI (Click) + Transport Setup   │
                    │      stdio / sse transport        │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │          server.py                │
                    │   FastMCP server instance         │
                    │   Tool/Resource/Prompt registration│
                    └──────────────┬───────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────▼────────┐ ┌────────▼────────┐ ┌─────────▼────────┐
    │  tools/sql.py    │ │ tools/graph.py  │ │  tools/meta.py   │
    │  sql_* tools     │ │ graph_* tools   │ │  suggest_database│
    └─────────┬────────┘ └────────┬────────┘ └──────────────────┘
              │                    │
    ┌─────────▼────────┐ ┌────────▼──────────┐
    │ engines/         │ │ engines/           │
    │ duckdb_engine.py │ │ ladybug_engine.py  │
    │ DuckDB wrapper   │ │ LadybugDB wrapper  │
    └─────────┬────────┘ └────────┬──────────┘
              │                    │
    ┌─────────▼────────────────────▼──────────┐
    │           session.py                     │
    │   SessionManager: create/get/destroy     │
    │   UUID sessions, temp dirs, cleanup      │
    └──────────────────────────────────────────┘
              │
    ┌─────────▼────────────────────────────────┐
    │           formatting.py                   │
    │   Token-optimized output: CSV, tabulate   │
    │   Row/char truncation, metadata           │
    └──────────────────────────────────────────┘
```

---

## File Plan

### Files to Create

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, dependencies, entry points, dev tools config |
| `README.md` | Getting started, tools reference, debugging, running |
| `Dockerfile` | Container deployment |
| `makefile` | Dev commands (install, dev, lint, test, clean) |
| `.env.example` | Environment variable template |
| `src/aismartbuddy/__init__.py` | Package init, version, logging setup |
| `src/aismartbuddy/__main__.py` | CLI entry point (Click), transport setup |
| `src/aismartbuddy/config.py` | Constants, defaults |
| `src/aismartbuddy/server.py` | FastMCP server, all tool/resource/prompt registration |
| `src/aismartbuddy/session.py` | SessionManager class |
| `src/aismartbuddy/formatting.py` | Token-optimized formatting (CSV, tabulate) |
| `src/aismartbuddy/tools/__init__.py` | Tools package |
| `src/aismartbuddy/tools/sql.py` | SQL tool implementations |
| `src/aismartbuddy/tools/graph.py` | Graph tool implementations |
| `src/aismartbuddy/tools/meta.py` | Meta tool (suggest_database) |
| `src/aismartbuddy/engines/__init__.py` | Engines package |
| `src/aismartbuddy/engines/duckdb_engine.py` | DuckDB connection/query/import wrapper |
| `src/aismartbuddy/engines/ladybug_engine.py` | LadybugDB connection/query/import wrapper |
| `tests/__init__.py` | Tests package |
| `tests/conftest.py` | Shared pytest fixtures |
| `tests/test_sql_tools.py` | SQL tool tests |
| `tests/test_graph_tools.py` | Graph tool tests |
| `tests/test_session.py` | Session management tests |
| `tests/test_formatting.py` | Formatting tests |
| `tests/test_meta_tools.py` | Meta tool tests (suggest_database) |

### Files to Update

| File | Change |
|------|--------|
| `CLAUDE.md` | Update with real architecture, actual file paths, real commands |

---

## Implementation Steps

### Step 1: Project Scaffold

Create `pyproject.toml`:
```toml
[project]
name = "aismartbuddy"
version = "0.1.0"
description = "AI-extending MCP server with SQL and graph database capabilities"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.9.4",
    "duckdb>=1.2.0",
    "real-ladybug>=0.14.0",
    "tabulate>=0.9.0",
    "click>=8.1.8",
    "python-dotenv>=1.0.0",
    "starlette>=0.46.1",
    "uvicorn>=0.34.0",
    "anyio>=4.8.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.8", "pyright>=1.1"]

[project.scripts]
aismartbuddy = "aismartbuddy:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aismartbuddy"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Create `src/aismartbuddy/__init__.py`:
- Export `main` function, `__version__ = "0.1.0"`
- Set up logging: `logging.getLogger("aismartbuddy")`

Create `src/aismartbuddy/config.py`:
- `SERVER_VERSION = "0.1.0"`
- `SERVER_NAME = "aismartbuddy"`
- `DEFAULT_MAX_ROWS = 1000`
- `DEFAULT_MAX_CHARS = 50000`
- `DEFAULT_SESSION_TIMEOUT = 3600`
- `DEFAULT_HOST = "127.0.0.1"`
- `DEFAULT_PORT = 8000`

Create `.env.example`:
```
# AISmartBuddy Configuration
# AISMARTBUDDY_TEMP_DIR=/tmp/aismartbuddy    # Override temp directory
# AISMARTBUDDY_MAX_ROWS=1000                 # Max rows per query result
# AISMARTBUDDY_MAX_CHARS=50000               # Max chars per response
# AISMARTBUDDY_SESSION_TIMEOUT=3600          # Session timeout in seconds
```

Create `makefile`:
```makefile
install:
	uv sync
dev:
	uv run python -m aismartbuddy --transport stdio
dev-sse:
	uv run python -m aismartbuddy --transport sse --port 8000
lint:
	uv run ruff check src/ tests/
format:
	uv run ruff format src/ tests/
test:
	uv run pytest -v
typecheck:
	uv run pyright
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf dist/ *.egg-info
docker-build:
	docker build -t aismartbuddy .
```

### Step 2: Session Management (`session.py`)

`SessionManager` class — **module-level singleton** accessed by all tool modules via `from aismartbuddy.session import session_manager`:
- `__init__(self, temp_base_dir: str | None = None, session_timeout: int = 3600, max_rows: int = 1000, max_chars: int = 50000)`
- Creates base temp dir: `{temp_base}/aismartbuddy/`
- `_sessions: dict[str, SessionInfo]` mapping session_id → metadata
- `SessionInfo` dataclass: `session_id, session_type ("sql"|"graph"), db_path, created_at, last_accessed, engine (DuckDBEngine | LadybugEngine)`

Methods:
- `create_session(session_type: str) -> SessionInfo`: Generate UUID, create temp subdir, instantiate engine, return info. **Opportunistic cleanup**: calls `cleanup_expired()` before creating to reclaim stale sessions.
- `get_session(session_id: str) -> SessionInfo`: Lookup with validation, update last_accessed. Raises ValueError if not found.
- `destroy_session(session_id: str) -> None`: Close engine, delete temp dir via `shutil.rmtree`
- `list_sessions() -> list[SessionInfo]`: Return all active sessions
- `cleanup_expired() -> int`: Remove sessions where `now - last_accessed > timeout`, return count removed
- `cleanup_all() -> None`: Destroy all sessions (for shutdown)

**Initialization pattern**: The SessionManager is instantiated in `server.py`'s lifespan and stored at module level. Tool modules import it. On server shutdown (lifespan exit), `cleanup_all()` is called.

**Background cleanup for SSE mode**: In the lifespan, start an `anyio` background task that calls `cleanup_expired()` every 5 minutes. This prevents session leaks when multiple clients connect/disconnect.

Session directory structure: `{temp_base}/aismartbuddy/{session_id}/data.duckdb` or `{session_id}/graph.lbug`

### Step 3: Database Engines

**Important: Async wrapping** — Both DuckDB and LadybugDB use synchronous C/C++ bindings. All blocking engine methods must be called via `await anyio.to_thread.run_sync(engine.execute, sql)` in the tool layer to avoid blocking the asyncio event loop. This is critical for SSE mode with concurrent clients.

**`engines/duckdb_engine.py`** — `DuckDBEngine` class:
- `__init__(self, db_path: str, max_rows: int, max_chars: int)`
- `connect()`: `duckdb.connect(db_path)` — creates file-based DB
- `execute(sql: str) -> tuple[list[str], list[tuple]]`: Run SQL, return (columns, rows). Columns from `result.description`, rows from `result.fetchmany(max_rows)`.
- `import_csv(table_name: str, csv_data: str, create_table: bool) -> int`: Write CSV string to temp file in session dir, use `CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{path}')` if create_table, else `INSERT INTO {name} SELECT * FROM read_csv_auto('{path}')`. Return row count.
- `import_json(table_name: str, json_data: str, create_table: bool) -> int`: Same pattern with `read_json_auto`
- `get_tables() -> list[str]`: `SHOW TABLES` → extract table names
- `describe_table(name: str) -> list[tuple]`: `DESCRIBE {name}` → return column info
- `close()`: `self._conn.close()`

**`engines/ladybug_engine.py`** — `LadybugEngine` class:
- `__init__(self, db_path: str, max_rows: int, max_chars: int)`
- `connect()`: `lb.Database(db_path)`, `lb.Connection(db)`, install json extension via `conn.execute("INSTALL json; LOAD json;")`
- `execute(cypher: str) -> tuple[list[str], list[tuple]]`: Run Cypher, extract via `result.columns` for headers, iterate result for rows (up to max_rows)
- `import_csv(table_name: str, csv_data: str, table_type: str, schema: str | None, from_table: str | None, to_table: str | None) -> int`: Write CSV to temp file in session dir, execute `CREATE NODE TABLE` or `CREATE REL TABLE` if schema provided, then `COPY {name} FROM '{path}'`
- `get_schema() -> str`: `CALL show_tables() RETURN *;` formatted with tabulate
- `close()`: Close connection

### Step 4: Token-Optimized Formatting (`formatting.py`)

Functions:
- `format_as_csv(columns: list[str], rows: list[tuple], max_rows: int, max_chars: int) -> str`:
  - Header: column names comma-separated
  - Rows: values comma-separated, proper CSV escaping
  - Prepend: `# {n} rows x {m} columns`
  - If truncated: append `# ... truncated ({total} total rows)`

- `format_as_table(columns: list[str], rows: list[tuple], max_rows: int, max_chars: int) -> str`:
  - Use tabulate with "simple" format
  - Same truncation logic

- `format_result(columns, rows, max_rows, max_chars, output_format="csv") -> str`:
  - Dispatch to csv or table formatter
  - If 0 rows: return "No results"
  - If write operation (no columns): return "OK, {affected_rows} rows affected"

- `format_schema_compact(tables: list[dict]) -> str`:
  - One line per table: `table_name (col1 TYPE, col2 TYPE, ...)`

### Step 5: SQL Tools (`tools/sql.py`)

All tools are async functions that will be registered on the FastMCP instance.

Tool functions access the SessionManager singleton via `from aismartbuddy.session import session_manager`. Blocking engine calls are wrapped with `await anyio.to_thread.run_sync(...)`.

```python
async def sql_create_session() -> str:
    """Create a new SQL database session. Returns a session_id token.
    Use this session_id in all subsequent sql_* tool calls.
    SQL sessions use DuckDB — ideal for tabular data, analytics,
    aggregations, joins, window functions, and time-series analysis."""

async def sql_query(session_id: str, query: str, output_format: str = "csv") -> str:
    """Execute a SQL query against a session's database.
    Supports all SQL: CREATE TABLE, INSERT, SELECT, UPDATE, DELETE,
    analytical functions, window functions, CTEs, etc.
    Results returned in token-efficient CSV format by default."""

async def sql_import(session_id: str, table_name: str, data: str,
                     format: str = "csv", create_table: bool = True) -> str:
    """Import data into a SQL session table.
    Accepts CSV or JSON string data. Set create_table=True to
    auto-detect schema and create the table from the data.
    For bulk imports, CSV format is most efficient."""

async def sql_schema(session_id: str, table_name: str | None = None) -> str:
    """Get database schema information.
    Without table_name: lists all tables.
    With table_name: shows column names, types, and sample data."""

async def sql_destroy_session(session_id: str) -> str:
    """Destroy a SQL session and clean up all temporary data.
    Always call this when done to free resources."""
```

### Step 6: Graph Tools (`tools/graph.py`)

Same dependency pattern as SQL tools: imports `session_manager`, wraps blocking calls with `anyio.to_thread.run_sync`.

```python
async def graph_create_session() -> str:
    """Create a new graph database session. Returns a session_id token.
    Graph sessions use Cypher query language — ideal for relationship
    data, networks, hierarchies, path finding, and connected data analysis.
    IMPORTANT: You must CREATE NODE TABLE before creating nodes."""

async def graph_query(session_id: str, query: str) -> str:
    """Execute a Cypher query against a graph session.
    Supports schema creation (CREATE NODE TABLE, CREATE REL TABLE),
    data creation (CREATE), queries (MATCH...RETURN), imports (COPY FROM),
    and all standard Cypher operations."""

async def graph_import(session_id: str, table_name: str, data: str,
                       table_type: str = "node",
                       schema: str | None = None,
                       from_table: str | None = None,
                       to_table: str | None = None) -> str:
    """Import data into a graph session.
    For nodes: provide table_name, CSV data, and schema string.
    For relationships: also provide from_table and to_table.
    Schema example: 'id INT64 PRIMARY KEY, name STRING, age INT64'"""

async def graph_schema(session_id: str) -> str:
    """Get graph database schema — node tables, relationship tables,
    and their properties."""

async def graph_destroy_session(session_id: str) -> str:
    """Destroy a graph session and clean up all temporary data."""
```

### Step 7: Meta Tools (`tools/meta.py`)

```python
async def suggest_database(use_case: str) -> str:
    """Given a description of what you want to do with data,
    recommends whether to use SQL or Graph database and explains why.
    Examples: 'analyze sales trends' → SQL, 'find shortest path between users' → Graph"""
```

Implementation: keyword/pattern matching with weighted scoring:
- Graph indicators: relationship, connected, network, hierarchy, path, traversal, graph, link, node, edge, social, dependency, genealogy, recommendation
- SQL indicators: aggregate, sum, count, average, tabular, time series, filter, sort, join, pivot, window, analytics, statistics, report, CSV

Returns: recommendation with brief explanation of why, plus example queries for the recommended database type.

### Step 8: Server Assembly (`server.py`)

**Uses FastMCP exclusively** — no low-level Server class. FastMCP handles transport switching internally via `mcp.run(transport=...)`.

```python
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
import anyio

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize SessionManager, start background cleanup, shutdown cleanly."""
    from aismartbuddy import session as session_mod
    session_mod.session_manager = SessionManager(temp_dir, timeout, max_rows, max_chars)
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(_periodic_cleanup)  # cleanup every 5 min
        yield
        tg.cancel_scope.cancel()
    
    session_mod.session_manager.cleanup_all()

mcp = FastMCP("aismartbuddy", lifespan=app_lifespan)
```

- Import and register all tool functions via `@mcp.tool()` with proper annotations
- Register prompts via `@mcp.prompt()`:
  - `aismartbuddy-guide`: Overview of SQL vs graph capabilities, when to use each
  - `sql-guide`: DuckDB SQL syntax, import patterns, analytical functions
  - `graph-guide`: Cypher syntax, schema-first approach (adapted from LadybugDB prompts)
  - `import-guide`: How to import CSV/JSON data into both database types
- Register resources via `@mcp.resource()`:
  - `aismartbuddy://sessions`: List active sessions with type, id, created_at
- Configuration (max_rows, max_chars, temp_dir, timeout) passed in during lifespan init from CLI args stored in module-level config

### Step 9: CLI Entry Point (`__main__.py`)

Click-based CLI that calls `mcp.run()` for all transports:

```python
@click.command()
@click.option("--transport", type=click.Choice(["stdio", "sse"]), default="stdio")
@click.option("--port", type=int, default=8000)
@click.option("--host", type=str, default="127.0.0.1")
@click.option("--temp-dir", type=str, default=None)
@click.option("--max-rows", type=int, default=1000)
@click.option("--max-chars", type=int, default=50000)
@click.option("--session-timeout", type=int, default=3600)
def main(transport, port, host, temp_dir, max_rows, max_chars, session_timeout):
    load_dotenv()  # Load .env file if present
    
    # Store config for lifespan to read
    from aismartbuddy import config as cfg
    cfg.RUNTIME_CONFIG = { ... }
    
    # Print startup info to stderr (not stdout — stdio transport uses stdout)
    click.echo(f"AISmartBuddy v{SERVER_VERSION}", err=True)
    click.echo(f"Transport: {transport}", err=True)
    
    from aismartbuddy.server import mcp
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "sse":
        mcp.run(transport="sse", host=host, port=port)
```

**Key: FastMCP's `.run()` handles all transport wiring internally** — no manual Starlette/Uvicorn setup needed. This is simpler and more maintainable than the LadybugDB reference's manual approach.

### Step 10: README.md

Sections:
1. **Overview** — What AISmartBuddy does, SQL vs graph capabilities
2. **Quick Start** — Install, run, connect to Claude Code
3. **Tools Reference** — Table of all 11 tools with descriptions
4. **SQL Tools** — Detailed SQL tool docs with examples
5. **Graph Tools** — Detailed graph tool docs with examples
6. **Data Import** — CSV/JSON import patterns, bulk import
7. **Running** — stdio, SSE, Docker, CLI args
8. **Debugging** — How to test tools, logging, common issues
9. **Development** — Setup, testing, linting
10. **Configuration** — Environment variables, CLI options

### Step 11: Update CLAUDE.md

Replace placeholder content with real architecture, actual file paths, real build commands verified against pyproject.toml.

### Step 12: Tests

**`tests/conftest.py`**:
- `session_manager` fixture with tmp_path
- `duckdb_engine` fixture
- `ladybug_engine` fixture

**`tests/test_session.py`**:
- Test create/get/destroy session lifecycle
- Test session not found error
- Test cleanup expired sessions
- Test cleanup all on shutdown

**`tests/test_sql_tools.py`**:
- Test create session → query (CREATE TABLE, INSERT, SELECT) → destroy
- Test CSV import with auto table creation
- Test JSON import
- Test schema listing
- Test analytical queries (GROUP BY, window functions)
- Test CSV output format is token-efficient

**`tests/test_graph_tools.py`**:
- Test create session → schema → query → destroy
- Test node creation and relationship queries
- Test CSV import for graph data
- Test Cypher traversal queries

**`tests/test_formatting.py`**:
- Test CSV formatting with various data shapes
- Test truncation at max_rows and max_chars
- Test empty results
- Test schema formatting

**`tests/test_meta_tools.py`**:
- Test suggest_database with SQL-leaning use case ("analyze sales trends over time")
- Test suggest_database with graph-leaning use case ("find shortest path between users")
- Test suggest_database with ambiguous use case (returns a valid recommendation)

### Step 13: Dockerfile

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN uv pip install --system .
CMD ["aismartbuddy", "--transport", "stdio"]
```

---

## Verification

1. **Install and build**: `uv sync` succeeds
2. **Run server**: `uv run python -m aismartbuddy` starts without errors
3. **Run tests**: `uv run pytest -v` — all pass
4. **Type check**: `uv run pyright` — no errors
5. **Lint**: `uv run ruff check .` — clean
6. **Manual test via Claude Code**: Add to `.claude/settings.json` and verify tools appear, create a SQL session, import data, query, destroy
7. **Docker build**: `docker build -t aismartbuddy .` succeeds

---

## Non-Goals

- Authentication/authorization (future iteration)
- Persistent databases across server restarts
- Multi-user access control
- Web UI or dashboard
- Cloud deployment scripts
- Performance benchmarking

---

## TLDR

Building AISmartBuddy, a Python MCP server that gives AI assistants temporary SQL (DuckDB) and graph (LadybugDB/Cypher) database sessions with token-optimized CSV output. The server exposes 11 tools (sql_create_session, sql_query, sql_import, sql_schema, sql_destroy_session, and matching graph_* tools, plus suggest_database), runs on stdio or SSE transport, and follows the LadybugDB MCP server as architectural reference. Sessions use UUID-keyed temp directories that auto-cleanup, and all bulk results default to CSV format for minimal token consumption.
