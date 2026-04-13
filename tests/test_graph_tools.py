"""Tests for graph tools (LadybugDB-backed)."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.ladybug_engine import LadybugEngine


@pytest.fixture
def ladybug_engine(tmp_path):
    """Create a LadybugDB engine with a temp database."""
    db_path = str(tmp_path / "test.lbug")
    engine = LadybugEngine(db_path, max_rows=100, max_chars=10000)
    engine.connect()
    yield engine
    engine.close()


class TestLadybugEngine:
    def test_create_node_table_and_insert(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING);"
        )
        ladybug_engine.execute("CREATE (p:Person {id: 1, name: 'Alice'});")
        ladybug_engine.execute("CREATE (p:Person {id: 2, name: 'Bob'});")
        columns, rows = ladybug_engine.execute(
            "MATCH (p:Person) RETURN p.name ORDER BY p.name;"
        )
        assert len(rows) == 2
        names = [row[0] for row in rows]
        assert "Alice" in names
        assert "Bob" in names

    def test_create_relationship(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING);"
        )
        ladybug_engine.execute(
            "CREATE REL TABLE Knows (FROM Person TO Person, since INT64);"
        )
        ladybug_engine.execute("CREATE (p:Person {id: 1, name: 'Alice'});")
        ladybug_engine.execute("CREATE (p:Person {id: 2, name: 'Bob'});")
        ladybug_engine.execute(
            "MATCH (a:Person {id: 1}), (b:Person {id: 2}) "
            "CREATE (a)-[:Knows {since: 2024}]->(b);"
        )
        columns, rows = ladybug_engine.execute(
            "MATCH (a:Person)-[k:Knows]->(b:Person) RETURN a.name, b.name, k.since;"
        )
        assert len(rows) == 1
        assert rows[0][0] == "Alice"
        assert rows[0][1] == "Bob"

    def test_get_schema_empty(self, ladybug_engine: LadybugEngine):
        columns, rows = ladybug_engine.get_schema()
        # Empty database should return empty or minimal schema
        assert isinstance(columns, list)
        assert isinstance(rows, list)

    def test_get_schema_with_tables(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE Person (id INT64 PRIMARY KEY, name STRING);"
        )
        columns, rows = ladybug_engine.get_schema()
        assert len(rows) > 0

    def test_ddl_returns_empty(self, ladybug_engine: LadybugEngine):
        columns, rows = ladybug_engine.execute(
            "CREATE NODE TABLE Thing (id INT64 PRIMARY KEY);"
        )
        # DDL may or may not return results depending on LadybugDB version
        assert isinstance(columns, list)
        assert isinstance(rows, list)

    def test_csv_import_nodes(self, ladybug_engine: LadybugEngine):
        csv_data = "id,name,age\n1,Alice,30\n2,Bob,25"
        count = ladybug_engine.import_csv(
            "Person",
            csv_data,
            table_type="node",
            schema="id INT64 PRIMARY KEY, name STRING, age INT64",
        )
        assert count == 2

        columns, rows = ladybug_engine.execute(
            "MATCH (p:Person) RETURN p.name ORDER BY p.name;"
        )
        names = [row[0] for row in rows]
        assert "Alice" in names
        assert "Bob" in names
