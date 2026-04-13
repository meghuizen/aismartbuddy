# DuckDB Python API

An in-process analytical SQL database engine with a comprehensive Python API. DuckDB runs embedded within the Python process -- there is no server, no network overhead, and no separate installation beyond `pip install duckdb`.

**Version researched**: 1.5.1 (as of 2026-04-10)
**Official docs**: https://duckdb.org/docs/current/clients/python/overview
**PyPI**: https://pypi.org/project/duckdb/
**GitHub**: https://github.com/duckdb/duckdb-python

## Overview

DuckDB is an OLAP (Online Analytical Processing) database designed for fast analytical queries on structured data. Think of it as "SQLite for analytics" -- it runs in-process, requires zero configuration, and is optimized for columnar operations, aggregations, joins, and window functions rather than transactional workloads.

**Use cases for an MCP server:**
- Load CSV/JSON/Parquet files and run analytical SQL queries on them
- Provide AI assistants with a powerful data analysis engine
- Create temporary analytical databases from user-provided data
- Export query results in CSV format for token-efficient responses

## How It Works

### Architecture

DuckDB runs entirely within the Python process. When you call `duckdb.connect()`, you get a `DuckDBPyConnection` object that wraps an embedded database engine. There is no client-server communication -- all operations happen in-process via C++ bindings (pybind11).

### Lazy Evaluation

The `sql()` method returns a `DuckDBPyRelation` object, which represents a query plan -- NOT the results. The query only executes when you materialize results by calling `fetchall()`, `df()`, `show()`, etc. This enables query chaining and optimization.

```python
# This does NOT execute yet -- it's just a relation (query plan)
r1 = con.sql("SELECT * FROM data WHERE amount > 100")

# This also does NOT execute -- it chains onto r1
r2 = r1.aggregate("category, sum(amount)")

# NOW both queries execute (when results are materialized)
results = r2.fetchall()
```

### Two APIs

DuckDB provides two complementary APIs:

1. **DB-API 2.0 (PEP 249)** -- `execute()` / `fetchall()` style, like sqlite3
2. **Relational API** -- `sql()` returns `DuckDBPyRelation` objects with chainable methods

Both are available on the same connection object. Use whichever fits your use case.

## Current State

- **Latest version**: 1.5.1 (April 2026)
- **Python requirement**: 3.9+
- **Key built-in extensions**: core_functions, icu, json, parquet (loaded by default)
- **DB-API compliance**: PEP 249 (DB-API 2.0)

## Setup

### Installation

```bash
pip install duckdb
# or
conda install python-duckdb -c conda-forge
# or
uv add duckdb
```

### Basic Usage

```python
import duckdb

# Simplest possible usage -- module-level default connection
duckdb.sql("SELECT 42 AS answer").show()

# Explicit connection (recommended for applications)
con = duckdb.connect()
con.sql("SELECT 42 AS answer").show()
```

## Connection Management

### Creating Connections

```python
import duckdb

# In-memory database (data lost when connection closes)
con = duckdb.connect()                      # or duckdb.connect(":memory:")

# Named in-memory database (shareable between connections)
con = duckdb.connect(":memory:mydb")

# File-based persistent database
con = duckdb.connect("analytics.duckdb")

# Read-only mode (safe for multi-process reads)
con = duckdb.connect("analytics.duckdb", read_only=True)

# With configuration
con = duckdb.connect(config={
    'threads': 4,
    'memory_limit': '4GB',
    'temp_directory': '/tmp/duckdb_temp',
})

# Default/global connection (used by module-level duckdb.sql())
con = duckdb.connect(":default:")
```

**Signature:**
```python
duckdb.connect(
    database: str = ':memory:',
    read_only: bool = False,
    config: dict = None
) -> DuckDBPyConnection
```

### Context Manager

```python
with duckdb.connect("analytics.duckdb") as con:
    con.sql("CREATE TABLE t (i INTEGER)")
    con.sql("INSERT INTO t VALUES (42)")
# Connection automatically closed on exit
```

### Closing Connections

```python
con.close()  # Explicit close
# Or let Python garbage collect it (implicit close)
```

### Default Connection vs Explicit Connection

The `duckdb` module itself exposes all `DuckDBPyConnection` methods, operating on a shared global in-memory database:

```python
import duckdb

# These use the default global connection
duckdb.sql("CREATE TABLE t (i INTEGER)")
duckdb.sql("INSERT INTO t VALUES (1)")
duckdb.sql("SELECT * FROM t").fetchall()
```

**Important**: The default connection is NOT thread-safe. For applications, always create explicit connections. Package/library authors should ALWAYS use explicit connections to avoid conflicts with other code using the default connection.

### Configuration After Connection

```python
con = duckdb.connect()
con.execute("SET memory_limit = '2GB'")
con.execute("SET threads = 4")
con.execute("SET temp_directory = '/tmp/duckdb'")
con.execute("SET preserve_insertion_order = true")
con.execute("SET enable_progress_bar = false")
```

**Key configuration options:**

| Setting | Default | Description |
|---------|---------|-------------|
| `memory_limit` / `max_memory` | 80% of RAM | Maximum memory usage (e.g., '4GB') |
| `threads` / `worker_threads` | All cores | Number of CPU threads |
| `temp_directory` | `.tmp` | Directory for temp files / spill-to-disk |
| `access_mode` | `automatic` | `AUTOMATIC`, `READ_ONLY`, or `READ_WRITE` |
| `default_order` | `ASCENDING` | Default ORDER BY direction |
| `preserve_insertion_order` | `true` | Maintain row order in results without ORDER BY |
| `enable_progress_bar` | `true` | Show progress bar for long queries |

## Running SQL Queries

### execute() -- DB-API Style

```python
con = duckdb.connect()

# Simple query
con.execute("CREATE TABLE users (id INTEGER, name VARCHAR, age INTEGER)")
con.execute("INSERT INTO users VALUES (1, 'Alice', 30), (2, 'Bob', 25)")

# Fetch results
con.execute("SELECT * FROM users")
rows = con.fetchall()          # [(1, 'Alice', 30), (2, 'Bob', 25)]
one = con.fetchone()           # (1, 'Alice', 30) or None if exhausted
many = con.fetchmany(10)       # Up to 10 rows

# Column info
con.execute("SELECT * FROM users")
print(con.description)         # Column names and types per DB-API 2.0
```

### sql() -- Relational API Style

```python
con = duckdb.connect()

# Returns a DuckDBPyRelation (lazy -- does not execute immediately)
rel = con.sql("SELECT * FROM users WHERE age > 20")

# Materialize results
rows = rel.fetchall()          # List of tuples
df = rel.df()                  # pandas DataFrame
pl_df = rel.pl()               # polars DataFrame
arrow = rel.arrow()            # pyarrow Table
np = rel.fetchnumpy()          # dict of numpy arrays

# Display
rel.show()                     # Print formatted table to stdout
```

### Parameter Binding (Prepared Statements)

```python
# Positional parameters with ?
con.execute("SELECT * FROM users WHERE age > ?", [25])
con.execute("INSERT INTO users VALUES (?, ?, ?)", [3, 'Charlie', 35])

# Dollar-sign notation (allows reuse)
con.execute("SELECT $1, $1, $2", ['duck', 'goose'])
# Returns: [('duck', 'duck', 'goose')]

# Named parameters
con.execute(
    "SELECT * FROM users WHERE name = $name AND age > $min_age",
    {"name": "Alice", "min_age": 20}
)

# Named parameters with sql()
con.sql(
    "SELECT * FROM users WHERE age > $min_age",
    params={"min_age": 25}
)
```

### Batch Operations

```python
# executemany -- for small batches only
con.executemany(
    "INSERT INTO users VALUES (?, ?, ?)",
    [(4, 'Diana', 28), (5, 'Eve', 32)]
)
# WARNING: executemany has significant per-row overhead.
# For bulk loading, use COPY, read_csv, or INSERT INTO ... SELECT instead.
```

### Transactions

```python
con.begin()
try:
    con.execute("INSERT INTO users VALUES (6, 'Frank', 40)")
    con.execute("UPDATE users SET age = 31 WHERE name = 'Alice'")
    con.commit()
except Exception:
    con.rollback()
    raise
```

DuckDB uses auto-commit by default. Each statement is its own transaction unless you explicitly call `begin()`.

### Relations Can Reference Each Other

```python
# Relations stored in Python variables can be referenced by name in SQL
r1 = con.sql("SELECT 42 AS i")
r2 = con.sql("SELECT i * 2 AS doubled FROM r1")  # References r1 by variable name
r2.show()
# | doubled |
# |---------|
# |      84 |
```

## Data Import

### CSV Files

```python
# Python API
rel = con.read_csv("data.csv")
rel = con.read_csv("folder/*.csv")                    # Glob pattern
rel = con.read_csv("data.csv", header=False, sep="\t") # Custom options
rel = con.read_csv("data.csv", dtype=["int", "varchar"]) # Type override

# SQL -- direct file reference (auto-detected)
con.sql("SELECT * FROM 'data.csv'")

# SQL -- explicit function
con.sql("SELECT * FROM read_csv('data.csv')")
con.sql("SELECT * FROM read_csv('data.csv', header=true, delim=',')")

# Load into a table
con.sql("CREATE TABLE t AS SELECT * FROM 'data.csv'")

# COPY into existing table
con.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
con.execute("COPY t FROM 'data.csv' (HEADER, DELIMITER ',')")
```

**Key read_csv parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `header` | auto | First row is header |
| `sep` / `delim` | `,` | Column delimiter |
| `quote` | `"` | Quote character |
| `escape` | `"` | Escape character in quoted values |
| `nullstr` | (empty) | String representing NULL |
| `all_varchar` | false | Treat all columns as VARCHAR |
| `auto_detect` | true | Auto-detect format settings |
| `sample_size` | 20480 | Lines to sample for auto-detection |
| `skip` | 0 | Lines to skip at start |
| `encoding` | UTF-8 | File encoding (UTF-8, UTF-16, Latin-1) |
| `compression` | auto | none, gzip, zstd |
| `parallel` | true | Use parallel CSV reader |
| `dateformat` | auto | Date parsing format |
| `timestampformat` | auto | Timestamp parsing format |
| `ignore_errors` | false | Skip rows with parse errors |
| `filename` | false | Add source filename column |
| `hive_partitioning` | false | Interpret path as Hive partitioned |
| `union_by_name` | false | Align columns by name across files |

### JSON Files

```python
# Python API
rel = con.read_json("data.json")
rel = con.read_json("folder/*.json")

# SQL
con.sql("SELECT * FROM 'data.json'")
con.sql("SELECT * FROM read_json_auto('data.json')")

# Into table
con.sql("CREATE TABLE t AS SELECT * FROM 'data.json'")
```

**Key read_json parameters:**
`columns`, `sample_size`, `maximum_depth`, `records`, `format`, `date_format`, `timestamp_format`, `compression`, `maximum_object_size`, `ignore_errors`, `filename`, `hive_partitioning`, `union_by_name`

### Parquet Files

```python
# Python API
rel = con.read_parquet("data.parquet")
rel = con.read_parquet("folder/*.parquet")
rel = con.read_parquet(["file1.parquet", "file2.parquet"])
rel = con.read_parquet("https://example.com/data.parquet")

# SQL
con.sql("SELECT * FROM 'data.parquet'")
con.sql("SELECT * FROM read_parquet('data.parquet')")

# Into table
con.sql("CREATE TABLE t AS SELECT * FROM 'data.parquet'")
```

**Key read_parquet parameters:**
`binary_as_string`, `file_row_number`, `filename`, `hive_partitioning`, `union_by_name`, `compression`

### From Python Objects (DataFrames, Arrow)

```python
import pandas as pd
import polars as pl
import pyarrow as pa

# Pandas DataFrame -- direct reference by variable name
pandas_df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
con.sql("SELECT * FROM pandas_df")

# Polars DataFrame
polars_df = pl.DataFrame({"a": [1, 2, 3]})
con.sql("SELECT * FROM polars_df")

# PyArrow Table
arrow_table = pa.table({"a": [1, 2, 3]})
con.sql("SELECT * FROM arrow_table")

# Explicit registration (useful for dynamic names or dict lookups)
con.register("my_view", pandas_df)
con.sql("SELECT * FROM my_view")

# Create persistent table from DataFrame
con.sql("CREATE TABLE t AS SELECT * FROM pandas_df")

# Append DataFrame to existing table
con.append("t", pandas_df)                     # Append pandas DF to table 't'
con.append("t", pandas_df, by_name=True)       # Match columns by name not position

# Insert from DataFrame into existing table
con.execute("INSERT INTO t SELECT * FROM pandas_df")
```

**Important**: Querying Python objects is read-only. DuckDB does not modify the original DataFrame/table.

**Pandas tip**: For object-type columns, DuckDB samples 1000 rows by default to infer types. Increase if needed:
```python
con.execute("SET GLOBAL pandas_analyze_sample = 100000")
```

### Bulk Import Best Practices

**DO use for large data:**
- `COPY t FROM 'file.csv'` -- fastest for file imports
- `CREATE TABLE t AS SELECT * FROM 'file.csv'` -- create + import in one step
- `con.read_csv()` / `con.read_parquet()` -- Python API wrappers
- `INSERT INTO t SELECT * FROM read_csv('file.csv')` -- append from file

**DO NOT use for large data:**
- `executemany()` with row-by-row inserts -- significant per-row overhead
- Individual `INSERT INTO ... VALUES` statements in a loop
- `INSERT` statements generally "should be avoided for bulk loading"

## Data Export

### CSV Export (Token-Efficient for MCP)

```python
# Python Relation API
rel = con.sql("SELECT * FROM users")
rel.write_csv("output.csv")
rel.write_csv("output.csv", sep="\t", header=True, na_rep="NULL")

# SQL COPY TO
con.execute("COPY users TO 'output.csv' (HEADER, DELIMITER ',')")
con.execute("COPY (SELECT * FROM users WHERE age > 25) TO 'output.csv' (HEADER)")

# To stdout (useful for capturing as string)
con.execute("COPY users TO '/dev/stdout' (HEADER)")
```

**write_csv() / to_csv() parameters:**

| Parameter | Description |
|-----------|-------------|
| `sep` | Column delimiter |
| `na_rep` | NULL representation |
| `header` | Include header row |
| `quotechar` | Quote character |
| `escapechar` | Escape character |
| `date_format` | Date format string |
| `timestamp_format` | Timestamp format string |
| `quoting` | Quoting behavior |
| `encoding` | Output encoding |
| `compression` | none, gzip, zstd |
| `overwrite` | Overwrite existing file |
| `per_thread_output` | One file per thread |
| `partition_by` | Hive partition columns |

**COPY TO CSV options:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `HEADER` | true | Include column headers |
| `DELIMITER` / `SEP` | `,` | Field separator |
| `QUOTE` | `"` | Quote character |
| `ESCAPE` | `"` | Escape character in quotes |
| `NULLSTR` | (empty) | NULL string representation |
| `DATEFORMAT` | (empty) | Date format |
| `TIMESTAMPFORMAT` | (empty) | Timestamp format |
| `COMPRESSION` | auto | none, gzip, zstd |
| `FORCE_QUOTE` | [] | Always-quote columns |

### Parquet Export

```python
rel.write_parquet("output.parquet")
rel.write_parquet("output.parquet", compression="zstd")

con.execute("COPY users TO 'output.parquet' (FORMAT PARQUET)")
con.execute("COPY users TO 'output.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
```

**COPY TO PARQUET options:**
`COMPRESSION` (snappy, gzip, zstd, brotli, lz4, lz4_raw, uncompressed), `COMPRESSION_LEVEL`, `ROW_GROUP_SIZE`, `ROW_GROUP_SIZE_BYTES`, `PARQUET_VERSION`

### JSON Export

```python
con.execute("COPY users TO 'output.json' (FORMAT JSON)")
con.execute("COPY users TO 'output.json' (FORMAT JSON, ARRAY true)")  # JSON array vs newline-delimited
```

### Fetching Results as Python Objects

```python
rel = con.sql("SELECT * FROM users")

# Tuples
rel.fetchall()               # List[Tuple] -- all rows
rel.fetchone()               # Single Tuple or None
rel.fetchmany(100)           # List[Tuple] -- up to N rows

# DataFrames
rel.df()                     # pandas DataFrame
rel.fetchdf()                # pandas DataFrame (alias)
rel.pl()                     # polars DataFrame

# Arrow
rel.arrow()                  # pyarrow Table
rel.fetch_arrow_table()      # pyarrow Table (alias)
rel.fetch_arrow_reader()     # pyarrow RecordBatchReader (streaming)
rel.fetch_record_batch()     # pyarrow RecordBatch

# NumPy
rel.fetchnumpy()             # dict of numpy arrays

# Chunked (for large results)
rel.fetch_df_chunk(10000)    # pandas DataFrame chunk
```

**Performance note**: `fetchone()` and `fetchmany()` use streaming mode internally and are ~5x slower than `fetchall()` on large datasets. For large results, prefer `fetchall()`, `df()`, or `arrow()` which use non-streaming materialization. For truly large results that exceed memory, use `COPY TO` to write directly to a file.

## Temporary Databases and Cleanup

### Temporary Tables (Session-Scoped)

```python
con = duckdb.connect()

# Create temp table -- automatically dropped when connection closes
con.execute("CREATE TEMPORARY TABLE staging (id INTEGER, data VARCHAR)")
con.execute("INSERT INTO staging VALUES (1, 'test')")

# Temp tables live in the temp.main schema
con.sql("SELECT * FROM staging").show()

# Explicit cleanup
con.execute("DROP TABLE IF EXISTS staging")

# Automatic cleanup happens on con.close()
con.close()  # All temp tables gone
```

**Key facts about temporary tables:**
- Session-scoped: only visible to the connection that created them
- Automatically dropped when the connection closes
- Live in memory but spill to `temp_directory` if configured
- Schema is always `temp.main`
- Cursors created with `cursor()` may NOT see temp tables from the parent connection (known behavior)

### In-Memory Databases as Temporary Workspaces

```python
# Pattern: Create in-memory DB, do work, export results, close
con = duckdb.connect()  # In-memory, no file

# Load data
con.sql("CREATE TABLE analysis AS SELECT * FROM 'raw_data.csv'")

# Do analytical work
result = con.sql("""
    SELECT category, sum(amount) as total
    FROM analysis
    GROUP BY category
    ORDER BY total DESC
""")

# Export results
result.write_csv("results.csv")

# Everything disappears on close
con.close()
```

### File-Based Database Cleanup

```python
import os

db_path = "/tmp/temp_analysis.duckdb"
con = duckdb.connect(db_path)

try:
    # ... do work ...
    pass
finally:
    con.close()
    # Clean up the file
    if os.path.exists(db_path):
        os.remove(db_path)
    # Also remove WAL file if present
    wal_path = db_path + ".wal"
    if os.path.exists(wal_path):
        os.remove(wal_path)
```

## Analytical Query Capabilities

DuckDB excels at analytical SQL. It supports standard SQL plus many extensions.

### Aggregate Functions

All standard aggregates plus many extras:

```sql
-- Standard
SELECT count(*), sum(amount), avg(amount), min(amount), max(amount)
FROM sales GROUP BY category;

-- Statistical
SELECT stddev(amount), variance(amount), median(amount), mode(category)
FROM sales;

-- Advanced
SELECT
    quantile_cont(amount, 0.95) AS p95,
    quantile_disc(amount, [0.25, 0.5, 0.75]) AS quartiles,
    approx_count_distinct(user_id) AS unique_users,
    string_agg(name, ', ' ORDER BY name) AS name_list,
    list(name) AS name_array,
    histogram(category) AS category_dist,
    arg_max(name, amount) AS highest_spender
FROM sales;

-- Boolean
SELECT bool_and(is_active), bool_or(is_admin) FROM users;

-- Bitwise
SELECT bit_and(flags), bit_or(flags), bit_xor(flags) FROM records;
```

### GROUP BY Extensions

```sql
-- GROUP BY ALL (auto-groups by all non-aggregate columns)
SELECT category, region, sum(amount)
FROM sales
GROUP BY ALL;

-- GROUPING SETS
SELECT city, state, sum(sales)
FROM stores
GROUP BY GROUPING SETS ((city, state), (city), (state), ());

-- ROLLUP (hierarchical subtotals)
SELECT country, city, sum(revenue)
FROM sales
GROUP BY ROLLUP (country, city);
-- Produces: (country, city), (country), ()

-- CUBE (all combinations)
SELECT country, city, sum(revenue)
FROM sales
GROUP BY CUBE (country, city);
-- Produces: (country, city), (country), (city), ()

-- GROUPING_ID to identify super-aggregate rows
SELECT country, city, sum(revenue),
    GROUPING_ID(country, city) AS gid
FROM sales
GROUP BY ROLLUP (country, city);
```

### Window Functions

```sql
-- Ranking
SELECT name, department, salary,
    row_number() OVER (ORDER BY salary DESC) AS rn,
    rank() OVER (ORDER BY salary DESC) AS rnk,
    dense_rank() OVER (ORDER BY salary DESC) AS drnk,
    ntile(4) OVER (ORDER BY salary) AS quartile,
    percent_rank() OVER (ORDER BY salary) AS pct_rank,
    cume_dist() OVER (ORDER BY salary) AS cum_dist
FROM employees;

-- Value access
SELECT date, amount,
    lag(amount, 1, 0) OVER (ORDER BY date) AS prev_amount,
    lead(amount, 1) OVER (ORDER BY date) AS next_amount,
    first_value(amount) OVER (ORDER BY date) AS first_amt,
    last_value(amount) OVER (ORDER BY date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS last_amt,
    nth_value(amount, 3) OVER (ORDER BY date) AS third_amt
FROM transactions;

-- Running/sliding aggregates
SELECT date, amount,
    sum(amount) OVER (ORDER BY date) AS running_total,
    avg(amount) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS moving_avg_7,
    sum(amount) OVER (PARTITION BY category ORDER BY date) AS category_running_total
FROM transactions;

-- RANGE framing (value-based windows)
SELECT date, amount,
    avg(amount) OVER (
        ORDER BY date
        RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND CURRENT ROW
    ) AS trailing_7day_avg
FROM transactions;

-- GROUPS framing
SELECT date, amount,
    avg(amount) OVER (
        ORDER BY date GROUPS BETWEEN 3 PRECEDING AND 3 FOLLOWING
    ) AS smoothed
FROM transactions;

-- EXCLUDE clause
SELECT date, amount,
    avg(amount) OVER (
        ORDER BY date
        ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING
        EXCLUDE CURRENT ROW
    ) AS avg_neighbors
FROM transactions;

-- Named windows
SELECT
    sum(amount) OVER w AS running_total,
    avg(amount) OVER w AS running_avg
FROM transactions
WINDOW w AS (PARTITION BY category ORDER BY date);
```

### QUALIFY Clause (Filter Window Results)

```sql
-- Get top 3 employees by salary per department
SELECT name, department, salary
FROM employees
QUALIFY dense_rank() OVER (PARTITION BY department ORDER BY salary DESC) <= 3;

-- Get the latest record per user
SELECT *
FROM events
QUALIFY row_number() OVER (PARTITION BY user_id ORDER BY timestamp DESC) = 1;
```

`QUALIFY` filters after window function evaluation. It is to window functions what `HAVING` is to `GROUP BY`.

### Common Table Expressions (CTEs)

```sql
-- Regular CTE
WITH monthly AS (
    SELECT date_trunc('month', date) AS month, sum(amount) AS total
    FROM sales GROUP BY 1
)
SELECT month, total,
    total - lag(total) OVER (ORDER BY month) AS month_over_month
FROM monthly;

-- Recursive CTE
WITH RECURSIVE hierarchy AS (
    SELECT id, name, parent_id, 1 AS depth
    FROM categories WHERE parent_id IS NULL
    UNION ALL
    SELECT c.id, c.name, c.parent_id, h.depth + 1
    FROM categories c JOIN hierarchy h ON c.parent_id = h.id
)
SELECT * FROM hierarchy;
```

### Other Analytical Features

```sql
-- PIVOT
PIVOT sales ON category USING sum(amount) GROUP BY region;

-- UNPIVOT
UNPIVOT monthly_sales ON jan, feb, mar INTO NAME month VALUE amount;

-- ASOF JOIN (join on closest match)
SELECT *
FROM trades ASOF JOIN quotes
ON trades.ticker = quotes.ticker AND trades.time >= quotes.time;

-- LATERAL JOIN
SELECT *
FROM departments d,
LATERAL (SELECT * FROM employees e WHERE e.dept_id = d.id ORDER BY salary DESC LIMIT 3);

-- SAMPLE
SELECT * FROM large_table USING SAMPLE 10%;
SELECT * FROM large_table USING SAMPLE 1000 ROWS;

-- LIST / STRUCT / MAP types
SELECT list(name) AS names FROM users GROUP BY department;
SELECT {'name': name, 'age': age} AS person FROM users;

-- Friendly SQL: FROM-first syntax
FROM sales SELECT category, sum(amount) GROUP BY category;

-- Friendly SQL: Column aliases in WHERE/GROUP BY
SELECT date_trunc('month', date) AS month, sum(amount) AS total
FROM sales
WHERE month >= '2024-01-01'
GROUP BY month;
```

## Relational API (DuckDBPyRelation)

The Relation object supports chainable operations without writing SQL:

```python
con = duckdb.connect()
con.sql("CREATE TABLE t AS SELECT * FROM range(100) t(i)")

rel = con.table("t")

# Transformation methods
rel.filter("i > 50")                            # WHERE clause
rel.select("i", "i * 2 AS doubled")             # SELECT clause
rel.project("i, i * 2 AS doubled")              # Alias for select
rel.order("i DESC")                              # ORDER BY
rel.limit(10)                                    # LIMIT
rel.limit(10, offset=5)                          # LIMIT with OFFSET
rel.distinct()                                   # DISTINCT

# Aggregation
rel.aggregate("count(*)")                        # Simple aggregate
rel.aggregate("sum(i), avg(i)", "i % 10")        # With GROUP BY
rel.sum("i")                                     # Shorthand
rel.avg("i")
rel.count("i")
rel.min("i")
rel.max("i")
rel.median("i")
rel.std("i")
rel.var("i")

# Joins
rel1.join(rel2, "rel1.id = rel2.id")                     # Inner join
rel1.join(rel2, "rel1.id = rel2.id", how="left")         # Left join
rel1.join(rel2, "rel1.id = rel2.id", how="right")        # Right join
rel1.join(rel2, "rel1.id = rel2.id", how="outer")        # Full outer
rel1.join(rel2, "rel1.id = rel2.id", how="semi")         # Semi join
rel1.join(rel2, "rel1.id = rel2.id", how="anti")         # Anti join
rel1.cross(rel2)                                          # Cross join

# Set operations
rel1.union(rel2)
rel1.intersect(rel2)
rel1.except_(rel2)

# Metadata
rel.columns           # Column names
rel.dtypes            # Column types
rel.types             # Column types
rel.shape             # (rows, cols)
rel.describe()        # Summary statistics
rel.explain()         # Query plan

# Persistence
rel.create("table_name")           # CREATE TABLE AS
rel.to_table("table_name")         # Alias
rel.insert_into("table_name")      # INSERT INTO existing table
rel.create_view("view_name")       # CREATE VIEW
rel.to_view("view_name")           # Alias

# Export
rel.write_csv("out.csv")
rel.write_parquet("out.parquet")
```

## Concurrency and Thread Safety

### Single-Thread Usage

If your MCP server handles one request at a time, a single connection is fine:

```python
con = duckdb.connect()
# Use con for all operations -- simplest approach
```

### Multi-Thread Usage

DuckDB supports concurrent operations within a single process, but with specific rules:

```python
import duckdb
from threading import Thread

# Create ONE connection, then use cursor() per thread
main_con = duckdb.connect("analytics.duckdb")

def worker(main_con, thread_id):
    # Each thread MUST create its own cursor
    local_con = main_con.cursor()
    result = local_con.execute("SELECT count(*) FROM data").fetchall()
    print(f"Thread {thread_id}: {result}")

threads = [Thread(target=worker, args=(main_con, i)) for i in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

### Concurrency Rules

1. **Each thread must use `cursor()`** to create a thread-local handle on the shared connection.
2. **The default module-level connection is NOT thread-safe** -- do not use `duckdb.sql()` from multiple threads.
3. **Appends never conflict** -- multiple threads can INSERT into the same table simultaneously.
4. **Updates/deletes on the same row conflict** -- the second thread gets a `TransactionException`. Use retry logic.
5. **Reads are always safe** alongside writes (MVCC isolation).
6. **Multi-process writes are NOT supported** -- only one process can write to a file-based database at a time.
7. **Multi-process reads are supported** in `read_only=True` mode.

### Connection Pooling

DuckDB does not need traditional connection pooling because it runs in-process. The pattern is:

```python
# For multi-threaded apps: one connection, cursor per thread
class DuckDBPool:
    def __init__(self, database=":memory:"):
        self._con = duckdb.connect(database)

    def get_cursor(self):
        """Get a thread-local cursor."""
        return self._con.cursor()

    def close(self):
        self._con.close()
```

There is no network overhead to "open a connection" -- `cursor()` is cheap.

## Extensions

### How Extensions Work

Extensions add capabilities: new file formats, data types, functions, and external database connectors. They are dynamically loaded shared libraries.

### Installing and Loading

```python
con = duckdb.connect()

# Core extensions (auto-installable)
con.install_extension("httpfs")
con.load_extension("httpfs")

# Community extensions
con.install_extension("h3", repository="community")
con.load_extension("h3")

# Force reinstall
con.install_extension("httpfs", force_install=True)

# SQL equivalent
con.execute("INSTALL httpfs")
con.execute("LOAD httpfs")

# Autoloading: many core extensions load automatically when needed
# e.g., querying an HTTPS URL auto-loads httpfs
```

### Key Core Extensions

| Extension | Auto-loads | Description |
|-----------|-----------|-------------|
| `parquet` | Yes (built-in) | Parquet file read/write |
| `json` | Yes (built-in) | JSON file read/write |
| `icu` | Yes (built-in) | Unicode collation and time zones |
| `core_functions` | Yes (built-in) | Core SQL functions |
| `httpfs` | Yes | HTTP/S3/GCS file access |
| `aws` | No | AWS credential management |
| `azure` | No | Azure Blob Storage access |
| `fts` | No | Full-text search |
| `spatial` | No | Geospatial types and functions |
| `sqlite_scanner` | No | Read/write SQLite databases |
| `postgres_scanner` | No | Read from PostgreSQL |
| `mysql_scanner` | No | Read from MySQL |
| `excel` | No | Read Excel files |
| `inet` | No | IP address types and functions |
| `vss` | No | Vector similarity search |
| `tpch` / `tpcds` | No | TPC-H/TPC-DS benchmark data generators |
| `delta` | No | Delta Lake format |
| `iceberg` | No | Apache Iceberg format |
| `ducklake` | No | DuckLake lakehouse format |
| `encodings` | No | Additional text encodings |

### Useful Extension Examples

```python
# Read from S3
con.install_extension("httpfs")
con.load_extension("httpfs")
con.execute("SET s3_region='us-east-1'")
con.sql("SELECT * FROM 's3://bucket/data.parquet'")

# Read from PostgreSQL
con.install_extension("postgres_scanner")
con.load_extension("postgres_scanner")
con.execute("ATTACH 'dbname=mydb user=postgres' AS pg (TYPE POSTGRES)")
con.sql("SELECT * FROM pg.public.users")

# Full-text search
con.install_extension("fts")
con.load_extension("fts")
con.execute("PRAGMA create_fts_index('docs', 'id', 'content')")
con.sql("SELECT * FROM docs WHERE fts_main_docs.match_bm25(id, 'search query') IS NOT NULL")

# Read SQLite
con.install_extension("sqlite_scanner")
con.load_extension("sqlite_scanner")
con.execute("ATTACH 'legacy.db' AS sqlite_db (TYPE SQLITE)")
con.sql("SELECT * FROM sqlite_db.main.users")
```

### Updating Extensions

```sql
UPDATE EXTENSIONS;
```

### Unsigned/Custom Extensions

```python
# Use with caution -- unsigned extensions are not verified
con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
```

### Extension Storage

Extensions are installed to `~/.duckdb/extensions/{version}/{platform}/` by default.

## User-Defined Functions (UDFs)

```python
import duckdb

con = duckdb.connect()

# Register a scalar UDF
def double_it(x):
    return x * 2

con.create_function("double_it", double_it, [duckdb.typing.BIGINT], duckdb.typing.BIGINT)
con.sql("SELECT double_it(42)").show()  # 84

# Remove a UDF
con.remove_function("double_it")
```

## DuckDBPyConnection -- Complete Method Reference

### Query Execution
| Method | Signature | Description |
|--------|-----------|-------------|
| `execute` | `(query, parameters=None) -> DuckDBPyConnection` | Execute SQL with optional parameters |
| `executemany` | `(query, parameters) -> DuckDBPyConnection` | Execute SQL for each parameter set |
| `sql` | `(query, *, alias='', params=None) -> DuckDBPyRelation` | Execute SQL, return Relation for SELECT |

### Result Fetching
| Method | Returns | Description |
|--------|---------|-------------|
| `fetchall()` | `list[tuple]` | All remaining rows |
| `fetchone()` | `tuple or None` | Single row |
| `fetchmany(size)` | `list[tuple]` | Up to N rows |
| `fetchnumpy()` | `dict[str, ndarray]` | NumPy arrays |
| `df()` / `fetchdf()` | `DataFrame` | pandas DataFrame |
| `pl()` | `DataFrame` | polars DataFrame |
| `arrow()` / `fetch_arrow_table()` | `Table` | pyarrow Table |
| `fetch_arrow_reader()` / `to_arrow_reader()` | `RecordBatchReader` | Streaming Arrow |
| `fetch_record_batch()` | `RecordBatch` | Arrow RecordBatch |
| `torch()` | `dict` | PyTorch tensors |

### Data Loading
| Method | Signature | Description |
|--------|-----------|-------------|
| `read_csv` | `(path, **kwargs) -> DuckDBPyRelation` | Read CSV file(s) |
| `read_json` | `(path, **kwargs) -> DuckDBPyRelation` | Read JSON file(s) |
| `read_parquet` | `(path, **kwargs) -> DuckDBPyRelation` | Read Parquet file(s) |
| `from_csv_auto` | `(path, **kwargs) -> DuckDBPyRelation` | Alias for read_csv |
| `from_df` | `(df) -> DuckDBPyRelation` | From pandas DataFrame |
| `from_arrow` | `(arrow_obj) -> DuckDBPyRelation` | From Arrow object |
| `from_parquet` | `(path, **kwargs) -> DuckDBPyRelation` | Alias for read_parquet |
| `register` | `(view_name, python_object)` | Register Python object as view |
| `unregister` | `(view_name)` | Unregister a view |
| `append` | `(table_name, df, *, by_name=False)` | Append pandas DF to table |

### Schema Access
| Method | Signature | Description |
|--------|-----------|-------------|
| `table` | `(name) -> DuckDBPyRelation` | Get table as Relation |
| `view` | `(name) -> DuckDBPyRelation` | Get view as Relation |
| `query` / `from_query` | `(sql) -> DuckDBPyRelation` | SQL to Relation |
| `values` | `(values) -> DuckDBPyRelation` | Create Relation from values |
| `table_function` | `(name, params) -> DuckDBPyRelation` | Call table function |
| `get_table_names` | `(query) -> set[str]` | Extract table names from SQL |

### Transactions
| Method | Description |
|--------|-------------|
| `begin()` | Start transaction |
| `commit()` | Commit transaction |
| `rollback()` | Rollback transaction |
| `checkpoint()` | Force WAL checkpoint |

### Extensions
| Method | Signature | Description |
|--------|-----------|-------------|
| `install_extension` | `(name, *, force_install=False, repository=None, repository_url=None, version=None)` | Install extension |
| `load_extension` | `(name)` | Load installed extension |

### Connection Management
| Method | Description |
|--------|-------------|
| `cursor()` | Create thread-local cursor (shares underlying DB) |
| `duplicate()` | Create independent duplicate connection |
| `close()` | Close the connection |
| `interrupt()` | Interrupt running query |

### Profiling
| Method | Description |
|--------|-------------|
| `enable_profiling()` | Enable query profiling |
| `disable_profiling()` | Disable query profiling |
| `get_profiling_information()` | Get profiling data |
| `query_progress()` | Get progress of current query |

### Type System
| Method | Description |
|--------|-------------|
| `array_type(inner, size)` | Create ARRAY type |
| `list_type(inner)` | Create LIST type |
| `map_type(key, value)` | Create MAP type |
| `struct_type(fields)` | Create STRUCT type |
| `union_type(members)` | Create UNION type |
| `row_type(fields)` | Create ROW type |
| `decimal_type(width, scale)` | Create DECIMAL type |
| `string_type()` | Get VARCHAR type |
| `enum_type(name, typ, values)` | Create ENUM type |
| `dtype(name)` | Get type by name |
| `sqltype(name)` | Get SQL type by name |
| `type(name)` | Get type by name |

### Filesystem
| Method | Description |
|--------|-------------|
| `register_filesystem(fs)` | Register custom filesystem (fsspec) |
| `unregister_filesystem(name)` | Unregister filesystem |
| `list_filesystems()` | List registered filesystems |
| `filesystem_is_registered(name)` | Check if filesystem registered |

### Properties
| Property | Description |
|----------|-------------|
| `description` | Column names/types of last result (DB-API 2.0) |
| `rowcount` | Number of rows affected by last statement |

## Common Patterns for MCP Server

### Pattern: Load User Data, Query, Return CSV

```python
import duckdb
import tempfile
import os

def analyze_data(file_path: str, query: str) -> str:
    """Load a file and run an analytical query, returning CSV results."""
    con = duckdb.connect()
    try:
        # Auto-detect format from extension
        con.sql(f"CREATE TABLE data AS SELECT * FROM '{file_path}'")

        # Run the user's query
        result = con.sql(query)

        # Return as CSV string (token-efficient for LLM consumption)
        tmp = tempfile.mktemp(suffix=".csv")
        result.write_csv(tmp, header=True)
        with open(tmp) as f:
            csv_content = f.read()
        os.unlink(tmp)
        return csv_content
    finally:
        con.close()
```

### Pattern: Fetchall to CSV String (No Temp File)

```python
import csv
import io

def result_to_csv(con, query: str) -> str:
    """Execute query and return results as CSV string."""
    con.execute(query)
    columns = [desc[0] for desc in con.description]
    rows = con.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue()
```

### Pattern: Schema Discovery

```python
def get_schema(con, table_name: str) -> list:
    """Get table schema information."""
    result = con.sql(f"""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
    """).fetchall()
    return result
```

### Pattern: Safe Query Execution

```python
def safe_query(con, query: str, timeout_seconds: int = 30):
    """Execute a query with error handling."""
    try:
        result = con.sql(query)
        return {"success": True, "data": result.fetchall(), "columns": result.columns}
    except duckdb.ParserException as e:
        return {"success": False, "error": f"SQL syntax error: {e}"}
    except duckdb.BinderException as e:
        return {"success": False, "error": f"Column/table not found: {e}"}
    except duckdb.CatalogException as e:
        return {"success": False, "error": f"Object not found: {e}"}
    except duckdb.IOException as e:
        return {"success": False, "error": f"File I/O error: {e}"}
    except duckdb.OutOfMemoryException as e:
        return {"success": False, "error": f"Out of memory: {e}"}
    except duckdb.Error as e:
        return {"success": False, "error": str(e)}
```

## Common Mistakes

1. **Using executemany for bulk inserts** -- Use `COPY FROM` or `INSERT INTO ... SELECT` instead.
2. **Using the default connection in a library** -- Always create explicit connections with `duckdb.connect()`.
3. **Sharing a connection across threads without cursor()** -- Each thread needs `con.cursor()`.
4. **Not closing connections to file-based databases** -- The file stays locked until closed.
5. **Expecting multi-process write support** -- Only one process can write at a time.
6. **Using fetchone()/fetchmany() for performance-critical paths** -- They are ~5x slower than fetchall() due to streaming mode.
7. **Forgetting that sql() is lazy** -- The query does not execute until you materialize (fetchall, df, show, etc.).
8. **Writing to a database opened in read_only mode** -- You get an error; this is by design for safe multi-process reads.

## Gotchas

- **Relation variable names are SQL-accessible**: `r1 = con.sql("SELECT 1 AS x")` makes `r1` queryable via `con.sql("SELECT * FROM r1")`. This is convenient but can be surprising.
- **cursor() and temp tables**: Temp tables created on a connection may not be visible through cursors created with `cursor()`. This is a known behavior.
- **WAL files**: File-based databases may leave `.wal` files. These are automatically cleaned up on proper shutdown but may persist after crashes.
- **Memory limit is per-connection**: Each connection has its own memory limit. The default is ~80% of system RAM.
- **Parquet is the built-in extension**: Unlike JSON/CSV readers which are also built-in, the Parquet reader is a statically-linked extension that is always available.
- **Column aliases in WHERE/GROUP BY**: DuckDB allows this (unlike standard SQL), which is convenient but non-portable.
- **FROM-first syntax**: `FROM tbl SELECT col` is valid DuckDB SQL but non-portable.
- **QUALIFY clause**: Powerful for filtering window function results, but not supported by most other databases.

## Exception Hierarchy

```
Error
  DatabaseError
    CatalogException
    ConnectionException
    DependencyException
    InternalException
    ParserException
    SequenceException
    TransactionException
    DataError
      ConversionException
    IntegrityError
      ConstraintException
    OperationalError
      IOException
      HTTPException
      OutOfMemoryException
      InterruptException
    ProgrammingError
      BinderException
      InvalidInputException
      InvalidTypeException
      TypeMismatchException
    NotSupportedError
      NotImplementedException
  FatalException
  Warning
```

## Links

- **Official Python API docs**: https://duckdb.org/docs/current/clients/python/overview
- **DB-API reference**: https://duckdb.org/docs/current/clients/python/dbapi
- **Data ingestion**: https://duckdb.org/docs/current/clients/python/data_ingestion
- **API reference (all classes/methods)**: https://duckdb.org/docs/current/clients/python/reference/
- **Concurrency**: https://duckdb.org/docs/current/connect/concurrency
- **Multi-threading guide**: https://duckdb.org/docs/current/guides/python/multiple_threads
- **Extensions**: https://duckdb.org/docs/current/extensions/overview
- **CSV import/export**: https://duckdb.org/docs/current/data/csv/overview
- **COPY statement**: https://duckdb.org/docs/current/sql/statements/copy
- **Window functions**: https://duckdb.org/docs/current/sql/functions/window_functions
- **Configuration reference**: https://duckdb.org/docs/current/configuration/overview
- **SQL reference**: https://duckdb.org/docs/current/sql/introduction
- **PyPI**: https://pypi.org/project/duckdb/
- **GitHub**: https://github.com/duckdb/duckdb-python
- **Changelog**: https://github.com/duckdb/duckdb/releases
