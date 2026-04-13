"""Tests for token-optimized formatting."""

from __future__ import annotations

from aismartbuddy.formatting import (
    format_as_csv,
    format_as_table,
    format_result,
    format_schema_compact,
)


class TestFormatAsCSV:
    def test_basic_csv(self):
        result = format_as_csv(["name", "age"], [("Alice", 30), ("Bob", 25)])
        assert "name,age" in result
        assert "Alice,30" in result
        assert "Bob,25" in result
        assert "# 2 rows x 2 columns" in result

    def test_empty_results(self):
        result = format_as_csv(["name"], [])
        assert "# 0 rows x 1 columns" in result
        assert "name" in result

    def test_truncation_by_rows(self):
        rows = [(i, f"name_{i}") for i in range(50)]
        result = format_as_csv(["id", "name"], rows, max_rows=10)
        assert "showing first 10" in result
        lines = result.strip().split("\n")
        # metadata + header + 10 data rows
        assert len(lines) <= 12

    def test_csv_escaping(self):
        result = format_as_csv(["text"], [('has "quotes"',), ("has,comma",)])
        # CSV should properly escape these
        assert result.count("\n") >= 3  # metadata + header + 2 rows

    def test_none_values(self):
        result = format_as_csv(["name", "age"], [("Alice", None)])
        assert "Alice," in result


class TestFormatAsTable:
    def test_basic_table(self):
        result = format_as_table(["name", "age"], [("Alice", 30), ("Bob", 25)])
        assert "name" in result
        assert "Alice" in result
        assert "# 2 rows x 2 columns" in result


class TestFormatResult:
    def test_csv_format(self):
        result = format_result(["x"], [(1,), (2,)], output_format="csv")
        assert "x" in result
        assert "1" in result

    def test_table_format(self):
        result = format_result(["x"], [(1,), (2,)], output_format="table")
        assert "x" in result

    def test_no_columns_no_rows(self):
        result = format_result([], [])
        assert result == "OK"

    def test_no_columns_with_rows(self):
        result = format_result([], [(1,)])
        assert "1 rows affected" in result

    def test_empty_result_set(self):
        result = format_result(["a", "b"], [])
        assert "No results" in result
        assert "a, b" in result


class TestFormatSchemaCompact:
    def test_basic_schema(self):
        tables = [
            {"name": "users", "columns": [("id", "INTEGER"), ("name", "VARCHAR")]},
            {"name": "orders", "columns": [("id", "INTEGER"), ("total", "DECIMAL")]},
        ]
        result = format_schema_compact(tables)
        assert "users (id INTEGER, name VARCHAR)" in result
        assert "orders (id INTEGER, total DECIMAL)" in result

    def test_empty_schema(self):
        result = format_schema_compact([])
        assert "No tables" in result
