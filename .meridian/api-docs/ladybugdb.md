# LadybugDB MCP Server

An MCP server implementation that exposes LadybugDB (an embedded graph database) to AI assistants via the Model Context Protocol, providing Cypher query capabilities.

**Version researched**: mcp-server-ladybug 0.1.2, real-ladybug 0.15.2, LadybugDB core 0.15.3 (as of 2026-04-10)
**Official docs**: https://docs.ladybugdb.com/
**MCP Server repo**: https://github.com/LadybugDB/mcp-server-ladybug
**PyPI (MCP server)**: https://pypi.org/project/mcp-server-ladybug/
**PyPI (Python driver)**: https://pypi.org/project/real-ladybug/

---

## Overview

LadybugDB (formerly known as Kuzu) is an embedded graph database built for query speed and scalability, optimized for complex analytical workloads on large graphs. It uses the Cypher query language (openCypher standard) and runs in-process -- no separate server needed.

The MCP server (`mcp-server-ladybug`) wraps LadybugDB's Python bindings (`real-ladybug`) to expose a single `query` tool that executes Cypher statements, plus a schema resource and multiple prompt templates for guiding AI assistants.

Key characteristics:
- **Embedded**: Runs in the same process as the MCP server, no external DB server
- **Strongly typed schema**: Tables must be defined BEFORE inserting data (unlike Neo4j)
- **Cypher query language**: openCypher-based, with some differences from Neo4j
- **Columnar storage**: CSR (Columnar Sparse Row) adjacency indices for fast graph traversal
- **ACID transactions**: Serializable isolation with Write-Ahead Logging
- **Extensions**: JSON, DuckDB interop, vector search, full-text search, graph algorithms
- **Interoperability**: Parquet, Arrow, DuckDB, Pandas, Polars, PyTorch Geometric, NetworkX

---

## How It Works

### Architecture

```
AI Assistant (Claude, etc.)
    |
    | MCP Protocol (stdio or SSE)
    |
    v
mcp-server-ladybug (Python MCP server)
    |
    | Python bindings
    |
    v
real-ladybug (Python package)
    |
    | In-process FFI
    |
    v
LadybugDB Core (C++ engine)
    |
    v
Disk storage (.lbdb/.ldbdb files) or :memory:
```

### MCP Server Lifecycle

1. **Startup**: The `main()` function (Click CLI) parses arguments, creates the database directory if needed, calls `build_application()` to construct the MCP `Server` instance and `DatabaseClient`.
2. **Database init**: `DatabaseClient.__init__()` calls `_initialize_connection()` which imports `real_ladybug`, creates a `Database` and `Connection`, then installs and loads the `json` and `duckdb` extensions.
3. **Handler registration**: The `build_application()` function registers MCP handlers for resources, prompts, and tools on the server instance.
4. **Transport loop**: Either stdio (default) or SSE transport runs the async event loop, dispatching incoming MCP messages to the registered handlers.
5. **Query execution**: When the `query` tool is called, it delegates to `DatabaseClient._execute()`, which runs the Cypher query, formats results as a table using `tabulate`, and truncates if needed.

### Database Lifecycle

- **In-memory** (`:memory:`): Created fresh on each server start, destroyed on exit. Good for ephemeral analysis.
- **On-disk** (path like `./my.lbdb`): Persists between server restarts. Supports larger-than-memory workloads via WAL and checkpointing.
- The default path is `$HOME/.ladybug/mcp.ldbdb` (the CLI creates the directory if it does not exist).
- There is NO explicit cleanup -- in-memory DBs vanish on process exit, on-disk DBs persist.

### Schema-First Design (CRITICAL)

LadybugDB requires explicit schema definition before data insertion. This is the single most important thing to understand:

```cypher
-- STEP 1: Define the schema (MUST do this first)
CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING, age INT64);
CREATE REL TABLE Knows (FROM Person TO Person, since INT64);

-- STEP 2: Now you can create data
CREATE (p:Person {id: 1, name: 'Alice', age: 30});
CREATE (p:Person {id: 2, name: 'Bob', age: 25});

-- STEP 3: Create relationships
MATCH (a:Person {id: 1}), (b:Person {id: 2})
CREATE (a)-[:Knows {since: 2020}]->(b);
```

If you try `CREATE (n:Person {...})` without first running `CREATE NODE TABLE Person (...)`, you get: **"Table Person does not exist"**.

---

## Current State

- **mcp-server-ladybug**: v0.1.2 (released 2026-01-09), MIT license, maintained by adsharma
- **real-ladybug**: v0.15.2 (released 2026-03-19)
- **LadybugDB core**: v0.15.3 (released 2026-04-01)
- **Release history**: 0.1.0 (2026-01-04), 0.1.1 (2026-01-08), 0.1.2 (2026-01-09)
- **Formerly known as**: Kuzu (the database was rebranded to LadybugDB)

---

## Setup

### Installation Methods

**pip**:
```bash
pip install mcp-server-ladybug
```

**uvx (direct execution)**:
```bash
uvx mcp-server-ladybug --db-path :memory:
```

**Docker**:
```bash
docker run -it --rm ghcr.io/ladybugdb/mcp-server-ladybug:latest --db-path :memory:
```

**From source**:
```bash
git clone https://github.com/LadybugDB/mcp-server-ladybug.git
cd mcp-server-ladybug
uv pip install -e .
```

### CLI Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--transport` | Choice: stdio, sse | `stdio` | Transport protocol |
| `--port` | int | `3000` | Port for SSE transport |
| `--host` | str | `127.0.0.1` | Bind address (SSE only, hardcoded to 0.0.0.0 in code) |
| `--db-path` | str | `$HOME/.ladybug/mcp.ldbdb` | Database file path (`:memory:` for in-memory) |
| `--max-rows` | int | `1024` | Max rows returned per query |
| `--max-chars` | int | `50000` | Max characters in formatted output |

### Claude Desktop / Claude Code Integration

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mcp-server-ladybug": {
      "command": "uvx",
      "args": ["mcp-server-ladybug", "--db-path", ":memory:"]
    }
  }
}
```

**Claude Code** (`.claude/settings.json`):
```json
{
  "mcpServers": {
    "mcp-server-ladybug": {
      "command": "uvx",
      "args": ["mcp-server-ladybug", "--db-path", ":memory:"]
    }
  }
}
```

### Development

```bash
# Makefile targets
make install    # uv pip install -e .
make dev        # python -m mcp_server_ladybug --db-path :memory:
make lint       # ruff check src/
make test       # pytest tests/
make clean      # Remove __pycache__, .pytest_cache, .venv
```

---

## Dependencies (with version constraints)

From `pyproject.toml`:

| Package | Version Constraint | Purpose |
|---------|-------------------|---------|
| `mcp` | >=1.9.4 | MCP SDK (Anthropic's official Python SDK) |
| `real-ladybug` | >=0.14.0 | LadybugDB Python bindings (the database driver) |
| `tabulate` | >=0.9.0 | Formats query results as ASCII tables |
| `click` | >=8.1.8 | CLI argument parsing |
| `starlette` | >=0.46.1 | ASGI framework for SSE transport |
| `uvicorn` | >=0.34.0 | ASGI server for SSE transport |
| `anyio` | >=4.8.0 | Async I/O abstraction |

**Build system**: hatchling
**Python requirement**: >=3.10

---

## MCP Server Implementation (Complete)

### Tools Exposed

The server exposes exactly **one tool**:

#### `query`

Executes a Cypher query against the LadybugDB database.

**Input schema**:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Cypher query to execute on the LadybugDB graph database"
    }
  },
  "required": ["query"]
}
```

**Behavior**:
- Executes the Cypher string via `DatabaseClient._execute()`
- Results are formatted as an ASCII table using `tabulate` with `"pretty"` format
- Output is truncated at `max_chars` (default 50,000) with a truncation notice appended
- Returns `types.TextContent` with the formatted result string
- On error, raises `ValueError` with the error message

**Result format example**:
```
+---------+---------+-------+
|  a.name |  b.name | since |
+---------+---------+-------+
|  Alice  |   Bob   | 2020  |
| Karissa |  Alice  | 2021  |
+---------+---------+-------+
```

If no rows are returned: `"Query executed successfully. No rows returned."`

### Resources Exposed

One resource:

#### `ladybug://schema`

Returns the current database schema by executing `CALL show_tables() RETURN *;`.

**Resource definition**:
```python
types.Resource(
    uri=AnyUrl("ladybug://schema"),
    name="Database Schema",
    description="Current schema of the LadybugDB database including node and relationship tables",
    mimeType="text/plain",
)
```

### Prompts Exposed

Six prompts are registered. These are templates the AI assistant can request to understand how to work with LadybugDB:

| Prompt Name | Description | Purpose |
|-------------|-------------|---------|
| `ladybugdb-initial-prompt` | Core prompt for starting work with LadybugDB | Schema-first approach, basic Cypher patterns, tool/resource discovery |
| `data-types-guide` | Complete data types reference | All numeric, string, temporal, boolean, complex types (STRUCT, MAP, UNION, LIST, ARRAY, JSON) |
| `json-guide` | JSON extension usage guide | INSTALL/LOAD json, json_extract, json_object, json_array, json_merge_patch, json_valid, etc. |
| `functions-guide` | Built-in functions reference | String, aggregation, date/time, type conversion, graph traversal functions |
| `neo4j-differences` | Key differences from Neo4j | Schema requirement, CREATE syntax, COPY vs LOAD CSV, semicolons, 1-based indexing, no MERGE |
| `examples-guide` | Query examples and workflows | Full workflow from schema creation to querying, error handling tips |

### Server Module Structure

```
src/mcp_server_ladybug/
    __init__.py       # Package init, exports main(), sets __version__
    __main__.py       # CLI entry point (Click), transport setup (stdio/SSE)
    server.py         # build_application() - registers all MCP handlers
    database.py       # DatabaseClient class - wraps real_ladybug
    prompt.py         # All prompt template strings (PROMPT_TEMPLATE, DATA_TYPES_PROMPT, etc.)
    configs.py        # SERVER_VERSION = "0.1.0", SERVER_LOCALHOST = "127.0.0.1"
```

---

## Python API for LadybugDB (real-ladybug package)

### Database Class

Creates or opens a LadybugDB database.

```python
import real_ladybug as lb

# In-memory database
db = lb.Database(":memory:")

# On-disk database (created if not exists)
db = lb.Database("./my_graph.lbdb")

# With options
db = lb.Database(
    database_path="./my_graph.lbdb",
    buffer_pool_size=1024 * 1024 * 256,  # 256 MB
    max_num_threads=4,
    compression=True,
    lazy_init=False,
    read_only=False,
    max_db_size=8 * 1024**4,  # 8 TB
    auto_checkpoint=True,
    enable_checksums=True,
)
```

**Constructor parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `database_path` | str/Path/None | None | File path or `:memory:`. None = in-memory |
| `buffer_pool_size` | int | ~80% system RAM | Max buffer pool in bytes |
| `max_num_threads` | int | system default | Thread count for queries |
| `compression` | bool | True | Enable storage compression |
| `lazy_init` | bool | False | Defer init until first query |
| `read_only` | bool | False | Open in read-only mode |
| `max_db_size` | int | 8TB | Max database size in bytes |
| `auto_checkpoint` | bool | True | Auto WAL checkpointing |
| `checkpoint_threshold` | int | -1 | WAL size threshold for checkpoint |
| `throw_on_wal_replay_failure` | bool | True | Error on WAL replay failure |
| `enable_checksums` | bool | True | WAL corruption detection |

**Key methods**:
- `db.init_database()` -- Initialize (usually automatic)
- `db.get_version()` -- Returns version string
- `db.get_storage_version()` -- Returns storage format version
- `db.close()` -- Close database
- `db.is_closed` -- Property, check if closed

### Connection Class (Synchronous)

```python
conn = lb.Connection(db)

# Execute a query
result = conn.execute("MATCH (n:Person) RETURN n.name, n.age;")

# With parameters
result = conn.execute(
    "MATCH (n:Person) WHERE n.name = $name RETURN n;",
    parameters={"name": "Alice"}
)

# Set query timeout (milliseconds)
conn.set_query_timeout(5000)

# Interrupt running query
conn.interrupt()

# Close connection
conn.close()
```

**Constructor parameters**:
- `database` (Database): The database to connect to
- `num_threads` (int, default=0): Max threads for this connection's queries

**Key methods**:
- `execute(query, parameters)` -- Execute Cypher query, returns QueryResult
- `set_query_timeout(timeout_in_ms)` -- Set timeout
- `interrupt()` -- Cancel current query
- `create_function(name, udf, params_type, return_type, ...)` -- Register UDF
- `remove_function(name)` -- Remove UDF
- `close()` -- Close connection

### AsyncConnection Class

```python
async_conn = lb.AsyncConnection(db, max_concurrent_queries=4, max_threads_per_query=2)

result = await async_conn.execute("MATCH (n:Person) RETURN n;")

# Manual connection pool management
conn = await async_conn.acquire_connection()
# ... use conn ...
await async_conn.release_connection(conn)

await async_conn.close()
```

### QueryResult Class

The object returned by `execute()`. Provides multiple ways to consume results.

```python
result = conn.execute("MATCH (n:Person) RETURN n.name, n.age;")

# Get all rows as list of tuples
rows = result.get_all()
# [('Alice', 30), ('Bob', 25)]

# Get N rows
first_two = result.get_n(2)

# Iterate row by row
while result.has_next():
    row = result.get_next()
    print(row)

# As dictionary
result.reset_iterator()
for row_dict in result.rows_as_dict():
    print(row_dict)
# {'n.name': 'Alice', 'n.age': 30}

# Convert to Pandas DataFrame
df = result.get_as_df()

# Convert to Polars DataFrame
pl_df = result.get_as_pl()

# Convert to PyArrow Table
arrow_table = result.get_as_arrow()

# Convert to NetworkX graph
nx_graph = result.get_as_networkx()

# Convert to PyTorch Geometric
pyg_data = result.get_as_torch_geometric()

# Metadata
columns = result.get_column_names()
types = result.get_column_data_types()
schema = result.get_schema()
exec_time = result.get_execution_time()    # ms
compile_time = result.get_compiling_time()  # ms
num_rows = result.get_num_tuples()

result.close()
```

### User-Defined Functions (UDFs)

```python
def my_add(a, b):
    return a + b

conn.create_function(
    name="my_add",
    udf=my_add,
    params_type=[lb.Type.INT64, lb.Type.INT64],
    return_type=lb.Type.INT64,
    default_null_handling=True,
    catch_exceptions=True,
)

result = conn.execute("RETURN my_add(3, 4);")
# Returns 7

conn.remove_function("my_add")
```

### Type Enum

`lb.Type` provides these values: `ANY`, `NODE`, `REL`, `RECURSIVE_REL`, `SERIAL`, `BOOL`, `INT64`, `INT32`, `INT16`, `INT8`, `UINT64`, `UINT32`, `UINT16`, `UINT8`, `INT128`, `DOUBLE`, `FLOAT`, `DATE`, `TIMESTAMP`, `TIMESTAMP_TZ`, `TIMESTAMP_NS`, `TIMESTAMP_MS`, `TIMESTAMP_SEC`, `INTERVAL`, `INTERNAL_ID`, `STRING`, `BLOB`, `UUID`, `LIST`, `ARRAY`, `STRUCT`, `MAP`, `UNION`.

---

## Cypher Query Language Reference

LadybugDB implements the openCypher standard with some extensions and differences. Statements must end with a semicolon (`;`).

### Data Definition Language (DDL)

#### CREATE NODE TABLE

```cypher
-- Basic syntax
CREATE NODE TABLE Person (
    id INT64 PRIMARY KEY,
    name STRING,
    age INT64 DEFAULT 0,
    reg_date DATE
);

-- With SERIAL (auto-increment) primary key
CREATE NODE TABLE Event (
    id SERIAL PRIMARY KEY,
    title STRING,
    date TIMESTAMP DEFAULT current_timestamp()
);

-- IF NOT EXISTS
CREATE NODE TABLE IF NOT EXISTS Person (id INT64 PRIMARY KEY, name STRING);

-- CREATE TABLE AS (infer schema from data)
CREATE NODE TABLE Person AS
    LOAD FROM "person.csv"
    RETURN *;

-- CREATE TABLE AS from existing data
CREATE NODE TABLE YoungPerson AS
    MATCH (p:Person)
    WHERE p.age < 25
    RETURN p.*;
```

**Primary key requirements**:
- Required for all node tables
- Supported types: STRING, numeric types, DATE, BLOB, SERIAL
- Automatically indexed

**Supported data types**:
- Numeric: INT8, INT16, INT32, INT64, INT128, UINT8, UINT16, UINT32, UINT64, FLOAT, DOUBLE, DECIMAL(precision, scale)
- String: STRING (UTF-8)
- Temporal: DATE, TIMESTAMP, INTERVAL/DURATION
- Boolean: BOOLEAN
- Other: UUID, BLOB/BYTEA, SERIAL
- Complex: STRUCT(key TYPE, ...), MAP(key_type, value_type), UNION(type1, type2, ...), LIST/TYPE[], ARRAY/TYPE[n]
- JSON (requires json extension)

#### CREATE REL TABLE

```cypher
-- Basic relationship
CREATE REL TABLE Follows (FROM Person TO Person, since INT64);

-- With multiplicity constraint
CREATE REL TABLE LivesIn (FROM Person TO City, MANY_ONE);

-- Multiple FROM/TO pairs (polymorphic)
CREATE REL TABLE Knows (
    FROM User TO User,
    FROM User TO City,
    weight DOUBLE
);

-- IF NOT EXISTS
CREATE REL TABLE IF NOT EXISTS Follows (FROM Person TO Person, since DATE);

-- CREATE TABLE AS
CREATE REL TABLE Knows(FROM Person TO Person) AS
    LOAD FROM "knows.csv"
    RETURN *;
```

**Relationship multiplicities**:

| Clause | Meaning | Constraint |
|--------|---------|-----------|
| (default) | MANY_MANY | No constraints |
| `MANY_ONE` | n-to-1 | Each source has at most one outgoing rel |
| `ONE_MANY` | 1-to-n | Each dest has at most one incoming rel |
| `ONE_ONE` | 1-to-1 | Both directions limited to one rel |

#### ALTER and DROP

```cypher
-- ALTER TABLE (add/drop/rename columns)
ALTER TABLE Person ADD email STRING;
ALTER TABLE Person DROP age;
ALTER TABLE Person RENAME name TO full_name;

-- DROP TABLE
DROP TABLE Follows;
DROP TABLE Person;
```

#### Schema Discovery

```cypher
CALL show_tables() RETURN *;
```

### Data Manipulation Language (DML)

#### CREATE (nodes and relationships)

```cypher
-- Create a node
CREATE (p:Person {id: 1, name: 'Alice', age: 30});

-- Create multiple nodes
CREATE (p1:Person {id: 1, name: 'Alice'}), (p2:Person {id: 2, name: 'Bob'});

-- Create a relationship (nodes must exist)
MATCH (a:Person {id: 1}), (b:Person {id: 2})
CREATE (a)-[:Follows {since: 2020}]->(b);
```

#### Data Import (COPY FROM)

```cypher
-- From CSV
COPY Person FROM 'persons.csv';
COPY Follows FROM 'follows.csv';

-- From Parquet
COPY Person FROM 'persons.parquet';

-- From JSON (with json extension)
COPY Product FROM 'products.json';
```

#### MATCH and RETURN

```cypher
-- Match all nodes of a type
MATCH (p:Person) RETURN p;
MATCH (p:Person) RETURN p.name, p.age;

-- Match with filter
MATCH (p:Person) WHERE p.age > 25 RETURN p.name;

-- Match relationships
MATCH (a:Person)-[f:Follows]->(b:Person)
RETURN a.name, b.name, f.since;

-- Match with inline property filter
MATCH (a:Person)-[f:Follows {since: 2020}]->(b:Person {name: 'Bob'})
RETURN a.name;

-- Undirected match
MATCH (a:Person)-[f:Follows]-(b:Person) RETURN a.name, b.name;

-- Multi-label match
MATCH (a:Person:City) RETURN a;

-- Any label
MATCH (a) RETURN a LIMIT 10;
```

#### Variable-Length Paths

```cypher
-- 1 to 2 hops
MATCH (a:Person)-[e:Follows*1..2]->(b:Person)
WHERE a.name = 'Alice'
RETURN b.name, length(e);

-- With path semantics
-- WALK (default): nodes and rels can repeat
-- TRAIL: all relationships distinct
-- ACYCLIC: all nodes distinct
MATCH (a:Person)-[e:Follows* TRAIL 2..4]-(b:Person)
WHERE a.name = 'Alice'
RETURN b.name;

-- Recursive filtering
MATCH p = (a:Person)-[:Follows*1..3 (r, n | WHERE r.since > 2020 AND n.age > 25)]->(b:Person)
WHERE a.name = 'Alice'
RETURN b.name;
```

#### Shortest Path

```cypher
-- Single shortest path
MATCH (a:Person)-[e* SHORTEST 1..10]->(b:Person)
WHERE a.name = 'Alice' AND b.name = 'Bob'
RETURN nodes(e), length(e);

-- All shortest paths
MATCH p = (a)-[* ALL SHORTEST 1..5]-(b)
WHERE a.name = 'Alice' AND b.name = 'Bob'
RETURN COUNT(*);

-- Weighted shortest path
MATCH p = (a:Person)-[e:Follows* WSHORTEST(score)]->(b:Person)
WHERE a.name = 'Alice'
RETURN properties(nodes(p), 'name'), cost(e);
```

#### Aggregation

```cypher
-- Implicit grouping (no GROUP BY needed)
MATCH (p:Person)-[:LivesIn]->(c:City)
RETURN c.name, count(p) AS pop, avg(p.age) AS avg_age
ORDER BY pop DESC;

-- Collect into list
MATCH (a:Person)-[:Follows]->(b:Person)
RETURN a.name, collect(b.name) AS follows;
```

#### Named Paths

```cypher
MATCH p = (a:Person)-[:Follows*1..3]->(b:Person)
WHERE a.name = 'Alice'
RETURN nodes(p), rels(p);
```

### Built-in Functions

**Graph traversal**: `nodes(path)`, `rels(path)`, `length(path)`, `properties(nodes, key)`

**String**: `length(str)`, `lower(str)`, `upper(str)`, `starts_with(str, prefix)`, `contains(str, substring)`, `substring(str, start, length)` (1-based indexing!)

**Aggregation**: `count(expr)`, `sum(expr)`, `avg(expr)`, `min(expr)`, `max(expr)`, `collect(expr)`

**Date/Time**: `date('YYYY-MM-DD')`, `timestamp('YYYY-MM-DD hh:mm:ss')`, `now()`, `current_timestamp()`

**Type conversion**: `cast(value AS TYPE)`, `typeof(expr)`

**JSON** (requires `INSTALL json; LOAD json;`):
- `to_json(value)` -- Convert to JSON
- `json_extract(json, path)` -- Extract using `$.field.nested[0]` paths
- `json_object(key1, val1, ...)` -- Create JSON object
- `json_array(val1, ...)` -- Create JSON array
- `json_merge_patch(json1, json2)` -- Merge (RFC 7386)
- `json_array_length(json)` -- Array length
- `json_keys(json)` -- Object keys
- `json_valid(json)` -- Validate
- `json_structure(json)` -- Type structure

### Extensions

Extensions must be installed and loaded per session:

```cypher
INSTALL json;
LOAD json;

INSTALL duckdb;
LOAD duckdb;
```

Available extensions include: `json`, `duckdb`, `algo` (graph algorithms), `vector` (similarity search), `fts` (full-text search via BM25), `neo4j` (data migration), `httpfs` (HTTP file operations).

Management:
```cypher
CALL SHOW_OFFICIAL_EXTENSIONS() RETURN *;
CALL SHOW_LOADED_EXTENSIONS() RETURN *;
UPDATE json;
UNINSTALL json;
```

**Important**: Extensions are session-scoped. The MCP server loads `json` and `duckdb` automatically on startup in `_initialize_connection()`.

---

## Best Practices

### Schema-First Workflow

1. **Define schema first** with `CREATE NODE TABLE` and `CREATE REL TABLE`
2. **Discover existing schema** with `CALL show_tables() RETURN *;` or the `ladybug://schema` resource
3. **Import data** with `COPY FROM` for bulk loading (much faster than individual `CREATE` statements)
4. **Query** using MATCH/WHERE/RETURN patterns

### Use the Prompts

The MCP server provides 6 prompt templates. The `ladybugdb-initial-prompt` is essential for any AI assistant session -- it teaches the schema-first approach and basic Cypher. Load additional prompts (`data-types-guide`, `json-guide`, etc.) on demand.

### Query Result Limits

Default limits prevent token flooding:
- 1,024 rows max (configurable with `--max-rows`)
- 50,000 characters max (configurable with `--max-chars`)

Results are formatted as ASCII tables using `tabulate`. Truncation notices are appended when limits are hit.

### In-Memory vs On-Disk

- Use `:memory:` for ephemeral/demo workflows
- Use a file path for persistent data that survives server restarts
- On-disk databases support larger-than-memory workloads

### Parameters for Safe Queries

Use `$param` syntax for parameterized queries to avoid injection:

```cypher
MATCH (n:Person) WHERE n.name = $name RETURN n;
```

---

## Key Differences from Neo4j

| Aspect | Neo4j | LadybugDB |
|--------|-------|-----------|
| Schema | Flexible, optional | **Required**, strongly typed, must define tables first |
| CREATE nodes | Works immediately | Must CREATE NODE TABLE first, then CREATE nodes |
| CSV import | `LOAD CSV FROM 'file' AS row` | `COPY TableName FROM 'file'` |
| Relationship direction | Optional in CREATE | Required: `FROM NodeType TO NodeType` |
| Semicolons | Optional | **Required** |
| MERGE | Full `ON CREATE`/`ON MATCH` | Not supported |
| Multi-label | Yes | Limited |
| `substring()` indexing | 0-based | **1-based** (SQL standard) |
| Parameters | `$param` | `$param` (same) |
| Deployment | Client-server | **Embedded** (in-process) |

---

## Common Mistakes

1. **Forgetting to create tables before data**: The #1 error. Always `CREATE NODE TABLE` and `CREATE REL TABLE` before `CREATE (n:Label {...})`.
2. **Missing semicolons**: All Cypher statements must end with `;`.
3. **Assuming Neo4j syntax**: No MERGE, no LOAD CSV, no flexible schema. Read the `neo4j-differences` prompt.
4. **Trying 0-based substring indexing**: LadybugDB uses 1-based indexing for `substring()`.
5. **Not loading extensions**: JSON functions require `INSTALL json; LOAD json;` first. The MCP server does this automatically, but standalone usage does not.
6. **Creating relationships without existing nodes**: Source and target nodes must exist before creating a relationship with MATCH+CREATE.

---

## Gotchas

- **Extension session scope**: Extensions must be loaded in each new session. The MCP server handles this automatically in `_initialize_connection()`, but be aware if using the Python API directly.
- **configs.py version mismatch**: `SERVER_VERSION` in `configs.py` is hardcoded to `"0.1.0"` but the PyPI package is at `0.1.2`. The version reported by the server may not match the installed package version.
- **SSE port discrepancy**: The README says default port is 8000, but the actual Click CLI default is `3000`.
- **Host binding**: SSE mode binds to `0.0.0.0` (all interfaces), not the `SERVER_LOCALHOST` constant in configs.py.
- **No streaming results**: The `query` tool fetches all results into memory, formats them, then returns the full string. Very large result sets will be truncated but still consume memory before truncation.
- **Single connection**: The `DatabaseClient` creates one synchronous `Connection` and uses it for all queries. No connection pooling.
- **Error wrapping**: Errors are double-wrapped -- `_execute()` raises `ValueError`, `query()` catches and re-raises as `ValueError`, and `handle_tool_call()` catches and re-raises as `ValueError` again.

---

## Source Code Reference

### server.py -- build_application()

The central factory function. Creates a `Server` and `DatabaseClient`, registers all MCP handlers (list_resources, read_resource, list_prompts, get_prompt, list_tools, call_tool), and returns the server with initialization options.

Key signature:
```python
def build_application(
    db_path: str = ":memory:",
    max_rows: int = 1024,
    max_chars: int = 50000,
) -> tuple[Server, InitializationOptions]:
```

### database.py -- DatabaseClient

Key methods:
- `__init__(db_path, max_rows, max_chars)` -- Creates DB + Connection, installs json/duckdb extensions
- `_initialize_connection()` -- Imports real_ladybug, creates Database + Connection, loads extensions
- `_execute(query)` -- Runs query, formats with tabulate, truncates at max_chars
- `query(query)` -- Public wrapper around _execute with error handling
- `get_schema()` -- Runs `CALL show_tables() RETURN *;`
- `close()` -- Closes connection

Result formatting uses `tabulate(rows, headers=columns, tablefmt="pretty")`.

### __main__.py -- main()

Click CLI entry point. Handles:
- Parsing CLI args (transport, port, db-path, max-rows, max-chars)
- Expanding env vars and creating directories
- Building the application via `build_application()`
- Running either stdio transport (asyncio) or SSE transport (uvicorn + Starlette)

SSE mode creates a Starlette app with CORS middleware (allow all origins), two routes (`/sse` for SSE connections, `/message` for POST messages).

### prompt.py

Contains 6 template strings: `PROMPT_TEMPLATE`, `DATA_TYPES_PROMPT`, `JSON_PROMPT`, `FUNCTIONS_PROMPT`, `NEO4J_DIFFERENCES_PROMPT`, `EXAMPLES_PROMPT`. These are returned verbatim as `TextContent` messages when the corresponding prompt is requested.

---

## Links

- **Official LadybugDB docs**: https://docs.ladybugdb.com/
- **Cypher manual**: https://docs.ladybugdb.com/cypher/
- **Python API guide**: https://docs.ladybugdb.com/client-apis/python/
- **Python API reference**: https://api-docs.ladybugdb.com/python/real_ladybug
- **MCP server repo**: https://github.com/LadybugDB/mcp-server-ladybug
- **MCP server PyPI**: https://pypi.org/project/mcp-server-ladybug/
- **real-ladybug PyPI**: https://pypi.org/project/real-ladybug/
- **LadybugDB core repo**: https://github.com/LadybugDB/ladybug
- **LadybugDB releases**: https://github.com/LadybugDB/ladybug/releases
- **Extensions docs**: https://docs.ladybugdb.com/extensions/
- **Getting started**: https://docs.ladybugdb.com/get-started/
- **Cypher intro**: https://docs.ladybugdb.com/get-started/cypher-intro/
- **Create table DDL**: https://docs.ladybugdb.com/cypher/data-definition/create-table
- **MATCH clause**: https://docs.ladybugdb.com/cypher/query-clauses/match
