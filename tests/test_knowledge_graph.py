"""Tests for knowledge graph tools."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.ladybug_engine import LadybugEngine


@pytest.fixture
def kg_engine(tmp_path):
    """Create a LadybugDB engine for knowledge graph testing."""
    db_path = str(tmp_path / "kg_test.lbug")
    engine = LadybugEngine(db_path, max_rows=100, max_chars=10000)
    engine.connect()

    # Create KnowledgeNode table (matching the schema from tools)
    engine.execute(
        "CREATE NODE TABLE KnowledgeNode ("
        "id SERIAL PRIMARY KEY, name STRING, description STRING, "
        "entity_type STRING, confidence DOUBLE, "
        "source STRING, created_at STRING);"
    )
    yield engine
    engine.close()


class TestKnowledgeNodeCreation:
    def test_create_knowledge_node(self, kg_engine: LadybugEngine):
        kg_engine.execute(
            "CREATE (n:KnowledgeNode {"
            "name: 'Mitochondrial Dysfunction', "
            "description: 'ETC impairment with compensatory biogenesis', "
            "entity_type: 'concept', "
            "confidence: 0.9, "
            "source: 'literature', "
            "created_at: '2024-01-01T00:00:00Z'"
            "});"
        )
        cols, rows = kg_engine.execute(
            "MATCH (n:KnowledgeNode) RETURN n.name, n.entity_type, n.confidence;"
        )
        assert len(rows) == 1
        assert rows[0][0] == "Mitochondrial Dysfunction"
        assert rows[0][1] == "concept"
        assert rows[0][2] == 0.9

    def test_multiple_entity_types(self, kg_engine: LadybugEngine):
        for etype in ["concept", "entity", "fact", "evidence"]:
            kg_engine.execute(
                f"CREATE (n:KnowledgeNode {{"
                f"name: '{etype}_node', entity_type: '{etype}', "
                f"confidence: 0.8, source: 'test', created_at: 'now'"
                f"}});"
            )
        cols, rows = kg_engine.execute(
            "MATCH (n:KnowledgeNode) "
            "RETURN n.entity_type, count(n) AS cnt "
            "ORDER BY n.entity_type;"
        )
        assert len(rows) == 4


class TestKnowledgeRelationships:
    def _setup_nodes(self, engine: LadybugEngine):
        engine.execute(
            "CREATE (n:KnowledgeNode {"
            "name: 'IL6_elevation', entity_type: 'fact', "
            "confidence: 0.95, source: 'data', created_at: 'now'});"
        )
        engine.execute(
            "CREATE (n:KnowledgeNode {"
            "name: 'Chronic_Inflammation', entity_type: 'concept', "
            "confidence: 0.9, source: 'inference', created_at: 'now'});"
        )
        engine.execute(
            "CREATE (n:KnowledgeNode {"
            "name: 'ISG_Suppression', entity_type: 'fact', "
            "confidence: 0.85, source: 'data', created_at: 'now'});"
        )

    def test_supports_relationship(self, kg_engine: LadybugEngine):
        self._setup_nodes(kg_engine)
        kg_engine.execute(
            "CREATE REL TABLE Supports ("
            "FROM KnowledgeNode TO KnowledgeNode, "
            "weight DOUBLE, justification STRING, "
            "source STRING, created_at STRING);"
        )
        kg_engine.execute(
            "MATCH (a:KnowledgeNode {name: 'IL6_elevation'}), "
            "(b:KnowledgeNode {name: 'Chronic_Inflammation'}) "
            "CREATE (a)-[:Supports {"
            "weight: 0.95, justification: 'IL6 drives inflammation', "
            "source: 'ai', created_at: 'now'}]->(b);"
        )
        cols, rows = kg_engine.execute(
            "MATCH (a:KnowledgeNode)-[r:Supports]->(b:KnowledgeNode) "
            "RETURN a.name, r.weight, r.justification, b.name;"
        )
        assert len(rows) == 1
        assert rows[0][0] == "IL6_elevation"
        assert rows[0][1] == 0.95
        assert rows[0][3] == "Chronic_Inflammation"

    def test_contradicts_relationship(self, kg_engine: LadybugEngine):
        self._setup_nodes(kg_engine)
        kg_engine.execute(
            "CREATE REL TABLE Contradicts ("
            "FROM KnowledgeNode TO KnowledgeNode, "
            "weight DOUBLE, justification STRING, "
            "source STRING, created_at STRING);"
        )
        kg_engine.execute(
            "MATCH (a:KnowledgeNode {name: 'IL6_elevation'}), "
            "(b:KnowledgeNode {name: 'ISG_Suppression'}) "
            "CREATE (a)-[:Contradicts {"
            "weight: 0.7, justification: 'Elevated receptor but no effector', "
            "source: 'ai', created_at: 'now'}]->(b);"
        )
        cols, rows = kg_engine.execute(
            "MATCH (a)-[r:Contradicts]->(b) "
            "RETURN a.name, r.weight, b.name;"
        )
        assert len(rows) == 1
        assert rows[0][1] == 0.7


class TestKnowledgeInference:
    def _build_graph(self, engine: LadybugEngine):
        """Build a small knowledge graph for inference testing."""
        for name, etype, conf in [
            ("A", "concept", 0.9),
            ("B", "fact", 0.3),
            ("C", "evidence", 0.8),
            ("D", "concept", 0.5),
        ]:
            engine.execute(
                f"CREATE (n:KnowledgeNode {{"
                f"name: '{name}', entity_type: '{etype}', "
                f"confidence: {conf}, source: 'test', created_at: 'now'"
                f"}});"
            )

        engine.execute(
            "CREATE REL TABLE Supports ("
            "FROM KnowledgeNode TO KnowledgeNode, "
            "weight DOUBLE, justification STRING, "
            "source STRING, created_at STRING);"
        )
        # A supports B, B supports C (chain: A→B→C)
        engine.execute(
            "MATCH (a:KnowledgeNode {name: 'A'}), "
            "(b:KnowledgeNode {name: 'B'}) "
            "CREATE (a)-[:Supports {weight: 0.9, justification: '', "
            "source: 'test', created_at: 'now'}]->(b);"
        )
        engine.execute(
            "MATCH (a:KnowledgeNode {name: 'B'}), "
            "(b:KnowledgeNode {name: 'C'}) "
            "CREATE (a)-[:Supports {weight: 0.8, justification: '', "
            "source: 'test', created_at: 'now'}]->(b);"
        )

    def test_transitive_chains(self, kg_engine: LadybugEngine):
        self._build_graph(kg_engine)
        cols, rows = kg_engine.execute(
            "MATCH (a:KnowledgeNode)-[:Supports*2..3]->"
            "(b:KnowledgeNode) "
            "RETURN a.name AS start_node, b.name AS end_node;"
        )
        # Should find A→(B→)C chain
        assert len(rows) >= 1
        starts = [row[0] for row in rows]
        ends = [row[1] for row in rows]
        assert "A" in starts
        assert "C" in ends

    def test_gap_detection(self, kg_engine: LadybugEngine):
        self._build_graph(kg_engine)
        # B has confidence=0.3 and connections — should show as gap
        cols, rows = kg_engine.execute(
            "MATCH (n:KnowledgeNode)-[r]-() "
            "RETURN n.name, n.confidence, count(r) AS degree "
            "ORDER BY n.confidence ASC;"
        )
        assert len(rows) >= 1
        # B should be first (lowest confidence with connections)
        low_conf_nodes = [r for r in rows if r[1] < 0.5]
        assert len(low_conf_nodes) >= 1

    def test_confidence_distribution(self, kg_engine: LadybugEngine):
        self._build_graph(kg_engine)
        cols, rows = kg_engine.execute(
            "MATCH (n:KnowledgeNode) RETURN "
            "sum(CASE WHEN n.confidence >= 0.9 THEN 1 ELSE 0 END) AS high, "
            "sum(CASE WHEN n.confidence >= 0.5 AND n.confidence < 0.9 "
            "THEN 1 ELSE 0 END) AS medium, "
            "sum(CASE WHEN n.confidence < 0.5 THEN 1 ELSE 0 END) AS low;"
        )
        assert len(rows) == 1
        # A(0.9)=high, C(0.8)=medium, D(0.5)=medium, B(0.3)=low
        assert rows[0][0] >= 1  # high
        assert rows[0][2] >= 1  # low
