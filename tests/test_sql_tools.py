"""Tests for SQL tools (DuckDB-backed)."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.duckdb_engine import DuckDBEngine


class TestDuckDBEngine:
    def test_create_table_and_query(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE t (id INTEGER, name VARCHAR)")
        duckdb_engine.execute("INSERT INTO t VALUES (1, 'Alice'), (2, 'Bob')")
        columns, rows = duckdb_engine.execute("SELECT * FROM t ORDER BY id")
        assert columns == ["id", "name"]
        assert len(rows) == 2
        assert rows[0] == (1, "Alice")
        assert rows[1] == (2, "Bob")

    def test_ddl_returns_result(self, duckdb_engine: DuckDBEngine):
        columns, rows = duckdb_engine.execute("CREATE TABLE t (id INTEGER)")
        # DuckDB may return a Count column for DDL statements
        assert isinstance(columns, list)
        assert isinstance(rows, list)

    def test_aggregation(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute(
            "CREATE TABLE sales (product VARCHAR, amount INTEGER)"
        )
        duckdb_engine.execute(
            "INSERT INTO sales VALUES ('A', 10), ('A', 20), ('B', 50)"
        )
        columns, rows = duckdb_engine.execute(
            "SELECT product, SUM(amount) as total FROM sales GROUP BY product ORDER BY total DESC"
        )
        assert columns == ["product", "total"]
        assert rows[0] == ("B", 50)
        assert rows[1] == ("A", 30)

    def test_window_function(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE emp (name VARCHAR, salary INTEGER)")
        duckdb_engine.execute(
            "INSERT INTO emp VALUES ('Alice', 100), ('Bob', 200), ('Carol', 150)"
        )
        columns, rows = duckdb_engine.execute(
            "SELECT name, salary, RANK() OVER (ORDER BY salary DESC) as rank FROM emp"
        )
        assert "rank" in columns
        assert len(rows) == 3

    def test_import_csv(self, duckdb_engine: DuckDBEngine):
        csv_data = "id,name,age\n1,Alice,30\n2,Bob,25\n3,Carol,35"
        count = duckdb_engine.import_csv("people", csv_data, create_table=True)
        assert count == 3
        columns, rows = duckdb_engine.execute("SELECT * FROM people ORDER BY id")
        assert len(rows) == 3
        assert rows[0][1] == "Alice"

    def test_import_csv_append(self, duckdb_engine: DuckDBEngine):
        csv_data1 = "id,name\n1,Alice\n2,Bob"
        duckdb_engine.import_csv("people", csv_data1, create_table=True)
        csv_data2 = "id,name\n3,Carol"
        duckdb_engine.import_csv("people", csv_data2, create_table=False)
        columns, rows = duckdb_engine.execute("SELECT count(*) FROM people")
        assert rows[0][0] == 3

    def test_import_json(self, duckdb_engine: DuckDBEngine):
        json_data = '[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]'
        count = duckdb_engine.import_json("people", json_data, create_table=True)
        assert count == 2

    def test_get_tables(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE t1 (id INTEGER)")
        duckdb_engine.execute("CREATE TABLE t2 (id INTEGER)")
        tables = duckdb_engine.get_tables()
        assert set(tables) == {"t1", "t2"}

    def test_describe_table(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE t (id INTEGER, name VARCHAR, active BOOLEAN)")
        columns, rows = duckdb_engine.describe_table("t")
        assert len(rows) == 3
        # First column of DESCRIBE output is the column name
        col_names = [row[0] for row in rows]
        assert "id" in col_names
        assert "name" in col_names
        assert "active" in col_names

    def test_empty_table_query(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE t (id INTEGER)")
        columns, rows = duckdb_engine.execute("SELECT * FROM t")
        assert columns == ["id"]
        assert rows == []

    def test_execute_windowed_streams_requested_slice(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE t (id INTEGER)")
        duckdb_engine.execute(
            "INSERT INTO t SELECT i FROM range(0, 250) AS src(i)"
        )

        table, has_more = duckdb_engine.execute_windowed(
            "SELECT id FROM t ORDER BY id",
            offset=100,
            limit=10,
        )

        assert table is not None
        assert table.num_rows == 10
        assert table.column("id").to_pylist() == list(range(100, 110))
        assert has_more is True

    def test_execute_windowed_returns_empty_after_end(self, duckdb_engine: DuckDBEngine):
        duckdb_engine.execute("CREATE TABLE t (id INTEGER)")
        duckdb_engine.execute(
            "INSERT INTO t SELECT i FROM range(0, 5) AS src(i)"
        )

        table, has_more = duckdb_engine.execute_windowed(
            "SELECT id FROM t ORDER BY id",
            offset=10,
            limit=5,
        )

        assert table is not None
        assert table.num_rows == 0
        assert has_more is False


class TestImportFormats:
    """Test all supported import formats via import_data."""

    def test_import_tsv(self, duckdb_engine: DuckDBEngine):
        tsv_data = "id\tname\tage\n1\tAlice\t30\n2\tBob\t25"
        count = duckdb_engine.import_data("people", tsv_data, "tsv")
        assert count == 2
        _, rows = duckdb_engine.execute("SELECT name FROM people ORDER BY id")
        assert rows[0][0] == "Alice"

    def test_import_pipe_delimited(self, duckdb_engine: DuckDBEngine):
        pipe_data = "id|name|score\n1|Alice|95\n2|Bob|87"
        count = duckdb_engine.import_data(
            "scores", pipe_data, "txt", delimiter="|"
        )
        assert count == 2
        _, rows = duckdb_engine.execute(
            "SELECT name, score FROM scores ORDER BY score DESC"
        )
        assert rows[0][0] == "Alice"
        assert rows[0][1] == 95

    def test_import_semicolon_delimited(self, duckdb_engine: DuckDBEngine):
        semi_data = "id;city;pop\n1;Amsterdam;900000\n2;Rotterdam;650000"
        count = duckdb_engine.import_data(
            "cities", semi_data, "txt", delimiter=";"
        )
        assert count == 2

    def test_import_json(self, duckdb_engine: DuckDBEngine):
        json_data = '[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]'
        count = duckdb_engine.import_data("people", json_data, "json")
        assert count == 2

    def test_import_jsonl(self, duckdb_engine: DuckDBEngine):
        jsonl_data = '{"id": 1, "name": "Alice"}\n{"id": 2, "name": "Bob"}'
        count = duckdb_engine.import_data("people", jsonl_data, "jsonl")
        assert count == 2
        _, rows = duckdb_engine.execute("SELECT count(*) FROM people")
        assert rows[0][0] == 2

    def test_import_csv_append_via_import_data(self, duckdb_engine: DuckDBEngine):
        csv1 = "id,val\n1,a\n2,b"
        csv2 = "id,val\n3,c"
        duckdb_engine.import_data("t", csv1, "csv", create_table=True)
        count = duckdb_engine.import_data("t", csv2, "csv", create_table=False)
        assert count == 1  # Only the appended row
        _, rows = duckdb_engine.execute("SELECT count(*) FROM t")
        assert rows[0][0] == 3

    def test_import_batch(self, duckdb_engine: DuckDBEngine):
        chunks = [
            "id,name\n1,Alice\n2,Bob",
            "id,name\n3,Carol\n4,Dave",
            "id,name\n5,Eve",
        ]
        total = duckdb_engine.import_batch("people", chunks, "csv")
        assert total == 5
        _, rows = duckdb_engine.execute(
            "SELECT count(*) FROM people"
        )
        assert rows[0][0] == 5

    def test_import_batch_empty(self, duckdb_engine: DuckDBEngine):
        total = duckdb_engine.import_batch("empty", [], "csv")
        assert total == 0

    def test_import_unsupported_format(self, duckdb_engine: DuckDBEngine):
        with pytest.raises(ValueError, match="Unsupported format"):
            duckdb_engine.import_data("t", "data", "xlsx")


@pytest.mark.usefixtures("_init_session_manager")
class TestSqlToolWindowing:
    @pytest.mark.anyio
    async def test_sql_query_offset_uses_windowed_results(self):
        from aismartbuddy.tools.sql import sql_create_session, sql_query

        sid_result = await sql_create_session()
        sid = next(
            line.split(":", 1)[1].strip()
            for line in sid_result.splitlines()
            if line.startswith("session_id:")
        )

        await sql_query(
            session_id=sid,
            query="CREATE TABLE t (id INTEGER);",
        )
        await sql_query(
            session_id=sid,
            query="INSERT INTO t SELECT i FROM range(0, 25) AS src(i);",
        )

        result = await sql_query(
            session_id=sid,
            query="SELECT id FROM t ORDER BY id;",
            offset=10,
            limit=5,
        )

        assert "# Page: rows 10-14" in result
        assert "10" in result
        assert "14" in result
