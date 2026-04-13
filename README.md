# AISmartBuddy

An MCP (Model Context Protocol) server that gives AI assistants on-demand SQL and graph database capabilities with token-optimized output.

## What It Does

AISmartBuddy provides AI assistants with temporary, session-based databases:

- **SQL Sessions** (DuckDB) — Tabular data, analytics, aggregations, joins, window functions, CSV/JSON/Parquet import
- **Graph Sessions** (LadybugDB/Cypher) — Relationship data, networks, hierarchies, path finding, pattern matching
- **Smart Routing** — A `suggest_database` tool helps the AI choose the right database for each task

Each session gets an isolated temporary database that is automatically cleaned up when destroyed or timed out.

## Quick Start

### Install

```bash
# Clone the repo
git clone https://github.com/your-org/aismartbuddy.git
cd aismartbuddy

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

### Run

```bash
# stdio transport (default — for Claude Code, Cursor, etc.)
uv run python -m aismartbuddy

# SSE transport (for remote/web clients)
uv run python -m aismartbuddy --transport sse --port 8000
```

### Connect to Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "aismartbuddy": {
      "command": "uv",
      "args": ["run", "python", "-m", "aismartbuddy"]
    }
  }
}
```

## Tools Reference

| Tool | Description |
|------|-------------|
| **SQL Tools** | |
| `sql_create_session` | Create a temporary SQL database session (DuckDB) |
| `sql_query` | Execute SQL queries — SELECT, CREATE TABLE, INSERT, analytics |
| `sql_import` | Import data (CSV, TSV, JSON, JSONL, Parquet, custom-delimited) |
| `sql_import_batch` | Import multiple data chunks into one table sequentially |
| `sql_schema` | List tables or describe a specific table's schema |
| `sql_destroy_session` | Destroy session and clean up temp files |
| **Graph Core Tools** | |
| `graph_create_session` | Create a temporary graph database session (LadybugDB) |
| `graph_query` | Execute Cypher queries — MATCH, CREATE, path finding |
| `graph_import` | Import CSV data as nodes or relationships |
| `graph_schema` | Get graph database schema (tables, relationships) |
| `graph_destroy_session` | Destroy session and clean up temp files |
| **Graph Analytics** | |
| `graph_statistics` | Full graph overview in one call (node/edge counts, totals) |
| `graph_neighbors` | Explore N-hop neighborhood around any node |
| `graph_find_connections` | Find all paths between two nodes (shortest first) |
| `graph_analyze` | Pre-built analytics: orphans, hubs, categories, cross-connections |
| **Graph Comparison** | |
| `graph_compare` | Compare two graph sessions (structure, nodes, properties) |
| `graph_cross_reference` | Cross-reference nodes between two graphs (CSV diff) |
| **Knowledge Graph** | |
| `graph_knowledge_add` | Add knowledge entity with confidence and provenance |
| `graph_knowledge_relate` | Add semantic relationship (supports/contradicts/causes/etc.) |
| `graph_knowledge_infer` | Run inference: contradictions, gaps, chains, clusters |
| `graph_knowledge_summary` | Complete knowledge graph overview in one call |
| **Meta** | |
| `suggest_database` | Recommend SQL vs Graph for a given use case |

## SQL Tools (DuckDB)

### Create a Session

```
sql_create_session → session_id: "a1b2c3d4e5f6g7h8"
```

### Import Data

```
sql_import(session_id, "sales", "date,product,amount\n2024-01-01,Widget,100\n2024-01-02,Gadget,250", format="csv")
→ Created table and imported 2 rows into 'sales'.
```

### Run Queries

```
sql_query(session_id, "SELECT product, SUM(amount) as total FROM sales GROUP BY product ORDER BY total DESC")
→ # 2 rows x 2 columns
  product,total
  Gadget,250
  Widget,100
```

### Analytical Queries

DuckDB supports advanced SQL including window functions, CTEs, and date operations:

```sql
-- Window functions
SELECT name, salary, RANK() OVER (ORDER BY salary DESC) FROM employees;

-- CTEs
WITH monthly AS (SELECT date_trunc('month', date) as month, SUM(amount) as total FROM sales GROUP BY 1)
SELECT * FROM monthly ORDER BY month;

-- Direct file queries
SELECT * FROM read_csv_auto('data.csv');
```

## Graph Tools (LadybugDB)

### Create a Session

```
graph_create_session → session_id: "h8g7f6e5d4c3b2a1"
```

### Define Schema (required first!)

```
graph_query(session_id, "CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING, age INT64);")
graph_query(session_id, "CREATE REL TABLE Knows (FROM Person TO Person, since INT64);")
```

### Add Data and Query

```
graph_query(session_id, "CREATE (p:Person {id: 1, name: 'Alice', age: 30});")
graph_query(session_id, "MATCH (p:Person) RETURN p.name, p.age;")
```

### Import Bulk Data

```
graph_import(session_id, "Person", "id,name,age\n1,Alice,30\n2,Bob,25\n3,Carol,35",
             table_type="node", schema="id INT64 PRIMARY KEY, name STRING, age INT64")
```

### Path Finding

```
graph_query(session_id, """
  MATCH p = shortest_path((a:Person)-[:Knows*]->(b:Person))
  WHERE a.name = 'Alice' AND b.name = 'Carol'
  RETURN nodes(p), rels(p);
""")
```

## Running

### CLI Options

```
Usage: aismartbuddy [OPTIONS]

Options:
  --transport [stdio|sse]    Transport protocol (default: stdio)
  --port INTEGER             Port for SSE transport (default: 8000)
  --host TEXT                Host for SSE transport (default: 127.0.0.1)
  --temp-dir TEXT            Override temp directory for databases
  --max-rows INTEGER         Max rows per query result (default: 1000)
  --max-chars INTEGER        Max characters per response (default: 50000)
  --session-timeout INTEGER  Session timeout in seconds (default: 3600)
  --help                     Show this message and exit.
```

### Docker

```bash
docker build -t aismartbuddy .
docker run -i aismartbuddy
```

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
AISMARTBUDDY_TEMP_DIR=/tmp/aismartbuddy
AISMARTBUDDY_MAX_ROWS=1000
AISMARTBUDDY_MAX_CHARS=50000
AISMARTBUDDY_SESSION_TIMEOUT=3600
```

## Debugging

### Test the Server Locally

```bash
# Run with verbose logging
uv run python -m aismartbuddy 2>server.log

# In another terminal, check the log
tail -f server.log
```

### Use the MCP Inspector

```bash
# Install the MCP inspector
npx @modelcontextprotocol/inspector

# Point it at AISmartBuddy
npx @modelcontextprotocol/inspector uv run python -m aismartbuddy
```

### Common Issues

| Issue | Solution |
|-------|----------|
| "Session not found" | Session was destroyed or timed out. Create a new one. |
| "Not connected" | Internal error — session engine failed to initialize. |
| Graph "Table does not exist" | You must CREATE NODE TABLE before CREATE nodes. |
| Import fails | Check CSV has a header row and data matches expected format. |

## Development

### Setup

```bash
# Install with dev dependencies
uv sync --all-extras

# Or
pip install -e ".[dev]"
```

### Commands

```bash
uv run pytest -v              # Run tests
uv run ruff check src/ tests/ # Lint
uv run ruff format src/ tests/ # Format
uv run pyright                 # Type check
```

### Project Structure

```
src/aismartbuddy/
├── __init__.py          # Package init, version
├── __main__.py          # CLI entry point (Click)
├── config.py            # Constants and runtime config
├── server.py            # FastMCP server, tool/prompt/resource registration
├── session.py           # SessionManager — lifecycle of temp databases
├── formatting.py        # Token-optimized output (CSV, tables)
├── tools/
│   ├── sql.py           # SQL tools (DuckDB-backed)
│   ├── graph.py         # Graph tools (LadybugDB-backed)
│   └── meta.py          # Meta tools (suggest_database)
└── engines/
    ├── duckdb_engine.py # DuckDB connection wrapper
    └── ladybug_engine.py # LadybugDB connection wrapper
```

## Token Efficiency

AISmartBuddy defaults to CSV output for SQL queries, which uses 2-3x fewer tokens than JSON:

```
# JSON (verbose)
[{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]

# CSV (compact) — default
name,age
Alice,30
Bob,25
```

This matters when working within AI context windows — less token waste on data formatting means more room for reasoning.

## License

MIT
