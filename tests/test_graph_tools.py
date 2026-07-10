"""Tests for graph tools (LadybugDB-backed)."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.ladybug_engine import LadybugEngine
from aismartbuddy.tools.graph import (
    graph_create_session,
    graph_knowledge_add,
    graph_query,
    knowledge_batch,
)


async def _create_graph_session() -> str:
    result = await graph_create_session()
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("session_id:"):
            return line[len("session_id:"):].strip()
    raise AssertionError(f"no session_id in {result!r}")


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

    def test_get_statistics_uses_schema_name_column(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE KnowledgeNode (id INT64 PRIMARY KEY, name STRING);"
        )
        ladybug_engine.execute(
            "CREATE REL TABLE Supports (FROM KnowledgeNode TO KnowledgeNode, weight DOUBLE);"
        )
        ladybug_engine.execute("CREATE (:KnowledgeNode {id: 1, name: 'A'});")
        ladybug_engine.execute("CREATE (:KnowledgeNode {id: 2, name: 'B'});")
        ladybug_engine.execute(
            "MATCH (a:KnowledgeNode {id: 1}), (b:KnowledgeNode {id: 2}) "
            "CREATE (a)-[:Supports {weight: 1.0}]->(b);"
        )

        stats = ladybug_engine.get_statistics()

        assert stats["node_tables"]["KnowledgeNode"] == 2
        assert stats["rel_tables"]["Supports"] == 1

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

    def test_execute_windowed_middle_slice(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE Item (id INT64 PRIMARY KEY, name STRING);"
        )
        for i in range(20):
            ladybug_engine.execute(f"CREATE (:Item {{id: {i}, name: 'item_{i}'}});")

        table, has_more = ladybug_engine.execute_windowed(
            "MATCH (i:Item) RETURN i.id AS id ORDER BY id;",
            offset=5,
            limit=4,
        )

        assert table is not None
        assert table.column("id").to_pylist() == [5, 6, 7, 8]
        assert has_more is True

    def test_execute_windowed_empty_after_end(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE Item (id INT64 PRIMARY KEY, name STRING);"
        )
        for i in range(3):
            ladybug_engine.execute(f"CREATE (:Item {{id: {i}, name: 'item_{i}'}});")

        table, has_more = ladybug_engine.execute_windowed(
            "MATCH (i:Item) RETURN i.id AS id ORDER BY id;",
            offset=10,
            limit=5,
        )

        assert table is not None
        assert table.num_rows == 0
        assert has_more is False

    def test_execute_windowed_has_more_false_at_end(self, ladybug_engine: LadybugEngine):
        ladybug_engine.execute(
            "CREATE NODE TABLE Item (id INT64 PRIMARY KEY, name STRING);"
        )
        for i in range(5):
            ladybug_engine.execute(f"CREATE (:Item {{id: {i}, name: 'item_{i}'}});")

        table, has_more = ladybug_engine.execute_windowed(
            "MATCH (i:Item) RETURN i.id AS id ORDER BY id;",
            offset=3,
            limit=2,
        )

        assert table is not None
        assert table.column("id").to_pylist() == [3, 4]
        assert has_more is False


@pytest.mark.usefixtures("_init_session_manager")
class TestKnowledgeNodeAuthority:
    """authority tier on KnowledgeNode persists via graph_knowledge_add/knowledge_batch."""

    @pytest.mark.anyio
    async def test_graph_knowledge_add_authority(self):
        sid = await _create_graph_session()
        await graph_knowledge_add(
            session_id=sid,
            entity="GroundTruthNode",
            entity_type="fact",
            authority="ground_truth",
        )
        result = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'GroundTruthNode' "
                "RETURN n.name, n.authority;"
            ),
        )
        assert "ground_truth" in result
        assert "GroundTruthNode" in result

    @pytest.mark.anyio
    async def test_graph_knowledge_add_invalid_authority(self):
        sid = await _create_graph_session()
        with pytest.raises(ValueError, match="authority must be one of"):
            await graph_knowledge_add(
                session_id=sid,
                entity="BadAuthNode",
                entity_type="fact",
                authority="bad",
            )

    @pytest.mark.anyio
    async def test_knowledge_batch_authority(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "WithAuth", "entity_type": "concept", "authority": "primary"},
                {"entity": "NoAuth", "entity_type": "concept"},
            ],
        )
        assert "Nodes added: 2" in result
        # Verify authority stored: 'primary' on WithAuth, "" on NoAuth.
        with_auth = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'WithAuth' "
                "RETURN n.authority;"
            ),
        )
        assert "primary" in with_auth
        no_auth = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'NoAuth' "
                "RETURN n.authority;"
            ),
        )
        # Empty string in CSV — header line present plus an empty value row.
        # We assert that 'primary' is NOT present (i.e. the field is the empty string).
        assert "primary" not in no_auth

    @pytest.mark.anyio
    async def test_knowledge_batch_invalid_authority(self):
        sid = await _create_graph_session()
        with pytest.raises(ValueError, match="authority must be one of"):
            await knowledge_batch(
                session_id=sid,
                nodes=[
                    {"entity": "X", "entity_type": "concept", "authority": "nope"},
                ],
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestKnowledgeNodeDomain:
    """domain tag on KnowledgeNode persists via graph_knowledge_add/knowledge_batch."""

    @pytest.mark.anyio
    async def test_graph_knowledge_add_domain(self):
        sid = await _create_graph_session()
        await graph_knowledge_add(
            session_id=sid,
            entity="MetabolismNode",
            entity_type="concept",
            domain="metabolism",
        )
        result = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'MetabolismNode' "
                "RETURN n.name, n.domain;"
            ),
        )
        assert "metabolism" in result
        assert "MetabolismNode" in result

    @pytest.mark.anyio
    async def test_knowledge_batch_domain_per_node(self):
        sid = await _create_graph_session()
        result = await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "X_front", "entity_type": "concept", "domain": "frontend"},
                {"entity": "Y_none", "entity_type": "concept"},
            ],
        )
        assert "Nodes added: 2" in result
        front = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'X_front' "
                "RETURN n.domain;"
            ),
        )
        assert "frontend" in front
        none_dom = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'Y_none' "
                "RETURN n.domain;"
            ),
        )
        # Y_none has no domain → empty string, not "frontend"
        assert "frontend" not in none_dom

    @pytest.mark.anyio
    async def test_domain_filter_returns_only_tagged(self):
        sid = await _create_graph_session()
        await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "A_m", "entity_type": "concept", "domain": "metabolism"},
                {"entity": "B_m", "entity_type": "concept", "domain": "metabolism"},
                {"entity": "C_i", "entity_type": "concept", "domain": "inflammation"},
                {"entity": "D_u", "entity_type": "concept"},
            ],
        )
        result = await graph_query(
            session_id=sid,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.domain = 'metabolism' "
                "RETURN n.name ORDER BY n.name;"
            ),
        )
        assert "A_m" in result
        assert "B_m" in result
        assert "C_i" not in result
        assert "D_u" not in result

    @pytest.mark.anyio
    async def test_materialize_auto_graph_propagates_domain(self):
        from aismartbuddy.tools.infra import session_create
        from aismartbuddy.tools.think import think_model

        r1 = await session_create(backends=["think", "graph"])
        parent_sid = ""
        for line in r1.split("\n"):
            line = line.strip()
            if line.startswith("session_id:"):
                parent_sid = line[len("session_id:"):].strip()
                break
        assert parent_sid

        await think_model(
            model_name="first_principles",
            session_id=parent_sid,
            auto_graph=True,
            items=[
                {
                    "id": "concept_metab_x",
                    "problem": "P",
                    "steps": ["s1"],
                    "reasoning": "r",
                    "conclusion": "c",
                    "domain": "metabolism",
                }
            ],
        )
        # Now query the graph backend within the parent session.
        from aismartbuddy.tools import get_session_manager

        mgr = get_session_manager()
        graph_info = mgr.resolve_backend_session(parent_sid, "graph")
        result = await graph_query(
            session_id=graph_info.session_id,
            query=(
                "MATCH (n:KnowledgeNode) WHERE n.name = 'concept_metab_x' "
                "RETURN n.name, n.domain;"
            ),
        )
        assert "metabolism" in result
        assert "concept_metab_x" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestCrossBackendResolution:
    """A child session_id resolves transparently to its sibling backend
    when the parent is a unified session. Closes the UX gap where the
    documented contract ('pass the returned session_id to all tools')
    failed for users holding a think-child id but calling a graph tool."""

    @pytest.mark.anyio
    async def test_think_child_id_routes_to_graph_sibling(self):
        from aismartbuddy.tools import get_session_manager
        from aismartbuddy.tools.think import think_science

        # Auto-create a parent with think+graph backends via think_science.
        res = await think_science(
            items=[
                {
                    "id": "H_test",
                    "observation": "obs",
                    "question": "q?",
                    "hypothesis": {
                        "statement": "stmt",
                        "variables": [{"name": "v", "role": "independent"}],
                        "assumptions": ["a1"],
                        "confidence": 0.5,
                        "falsifiability": {
                            "method": "test method spec",
                            "expected_if_false": "negative result",
                        },
                    },
                }
            ],
            auto_graph=True,
        )
        think_child_sid = ""
        for line in res.split("\n"):
            if line.startswith("Session: "):
                think_child_sid = line.split("Session: ", 1)[1].split(" |", 1)[0].strip()
                break
        assert think_child_sid

        # The think-child id should now resolve transparently to the graph
        # sibling when passed to a graph tool. Before the fix this raised
        # "Session 'X' is a think session, not graph."
        mgr = get_session_manager()
        graph_info = mgr.resolve_backend_session(think_child_sid, "graph")
        assert graph_info.session_type == "graph"
        # And the inverse: the resolved graph id is itself routable for think.
        think_info = mgr.resolve_backend_session(graph_info.session_id, "think")
        assert think_info.session_type == "think"
        assert think_info.session_id == think_child_sid

    @pytest.mark.anyio
    async def test_standalone_session_still_raises_on_wrong_backend(self):
        """Standalone (non-unified) sessions must still raise — no silent
        misrouting when there's no parent to walk up to."""
        from aismartbuddy.tools import get_session_manager
        from aismartbuddy.tools.think import think_create_session

        res = await think_create_session()
        sid = ""
        for line in res.split("\n"):
            if line.startswith("session_id:"):
                sid = line.split("session_id:", 1)[1].strip()
                break
        assert sid
        mgr = get_session_manager()
        with pytest.raises(ValueError, match="is a think session, not graph"):
            mgr.resolve_backend_session(sid, "graph")

    @pytest.mark.anyio
    async def test_parent_id_passed_directly_resolves_both_backends(self):
        """Passing the parent_id (returned by session_create(backends=[...]))
        resolves correctly for any sibling backend."""
        from aismartbuddy.tools import get_session_manager
        from aismartbuddy.tools.infra import session_create

        res = await session_create(backends=["think", "graph"])
        parent_sid = ""
        for line in res.split("\n"):
            line = line.strip()
            if line.startswith("session_id:"):
                parent_sid = line.split("session_id:", 1)[1].strip()
                break
        assert parent_sid
        mgr = get_session_manager()
        think_info = mgr.resolve_backend_session(parent_sid, "think")
        graph_info = mgr.resolve_backend_session(parent_sid, "graph")
        assert think_info.session_type == "think"
        assert graph_info.session_type == "graph"
        assert think_info.session_id != graph_info.session_id


@pytest.mark.usefixtures("_init_session_manager")
class TestConvergenceInference:
    """graph_knowledge_infer(convergence) detects nodes whose source-node
    domains span 2+ distinct values. The previous implementation filtered
    only on edge.domain, which is empty on auto_graph edges and missed the
    most common convergence case."""

    @pytest.mark.anyio
    async def test_convergence_uses_source_node_domain(self):
        from aismartbuddy.tools.graph import graph_knowledge_infer

        sid = await _create_graph_session()
        await knowledge_batch(
            session_id=sid,
            nodes=[
                {"entity": "src_a", "entity_type": "concept", "domain": "metabolism"},
                {"entity": "src_b", "entity_type": "concept", "domain": "immunology"},
                {"entity": "src_c", "entity_type": "concept", "domain": "endocrine"},
                # Convergence target — supported by sources in 3 distinct domains
                {"entity": "hub_target", "entity_type": "concept"},
                # Non-convergence — supported by only one domain
                {"entity": "single_src_target", "entity_type": "concept"},
            ],
            relations=[
                # No domain set on edges — must use source-node domain
                {"from_name": "src_a", "to_name": "hub_target", "relation": "supports"},
                {"from_name": "src_b", "to_name": "hub_target", "relation": "supports"},
                {"from_name": "src_c", "to_name": "hub_target", "relation": "supports"},
                {"from_name": "src_a", "to_name": "single_src_target", "relation": "supports"},
            ],
        )
        # Need >= min_nodes_override to bypass the 10-node minimum
        result = await graph_knowledge_infer(
            session_id=sid, inference_type="convergence", min_nodes_override=2
        )
        # hub_target spans 3 domains → must appear; single_src_target only 1 → must not
        assert "hub_target" in result
        assert "single_src_target" not in result
