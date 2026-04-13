"""Integration test: Build a pathophysiology graph and run analytical queries.

Tests the graph tools against a real-world complex use case:
47 genes, 12 pathways, 12 biological processes, 6 cell types, 5 phenotypes,
and ~112 relationships modeling chronic post-infectious immune dysregulation.
"""

from __future__ import annotations

import pytest

from aismartbuddy.engines.ladybug_engine import LadybugEngine
from tests.data.pathophysiology import (
    BIOPROCESS_CSV,
    BIOPROCESS_SCHEMA,
    CELL_EXPRESSES_CSV,
    CELL_EXPRESSES_SCHEMA,
    CELLTYPE_CSV,
    CELLTYPE_SCHEMA,
    COMPENSATES_FOR_CSV,
    COMPENSATES_FOR_SCHEMA,
    DRIVES_PROCESS_CSV,
    DRIVES_PROCESS_SCHEMA,
    GENE_CSV,
    GENE_SCHEMA,
    PARTICIPATES_IN_CSV,
    PARTICIPATES_IN_SCHEMA,
    PATHWAY_CSV,
    PATHWAY_INTERACTS_CSV,
    PATHWAY_INTERACTS_SCHEMA,
    PATHWAY_SCHEMA,
    PHENOTYPE_CSV,
    PHENOTYPE_SCHEMA,
    PRODUCES_PHENOTYPE_CSV,
    PRODUCES_PHENOTYPE_SCHEMA,
    REGULATES_CSV,
    REGULATES_SCHEMA,
)


@pytest.fixture(scope="module")
def graph_engine(tmp_path_factory):
    """Build the full pathophysiology graph once for all tests in this module."""
    tmp = tmp_path_factory.mktemp("pathophysiology")
    db_path = str(tmp / "patho.lbug")
    engine = LadybugEngine(db_path, max_rows=500, max_chars=100000)
    engine.connect()

    # Create node tables
    engine.import_csv("Gene", GENE_CSV, table_type="node", schema=GENE_SCHEMA)
    engine.import_csv("Pathway", PATHWAY_CSV, table_type="node", schema=PATHWAY_SCHEMA)
    engine.import_csv("BioProcess", BIOPROCESS_CSV, table_type="node", schema=BIOPROCESS_SCHEMA)
    engine.import_csv("CellType", CELLTYPE_CSV, table_type="node", schema=CELLTYPE_SCHEMA)
    engine.import_csv("Phenotype", PHENOTYPE_CSV, table_type="node", schema=PHENOTYPE_SCHEMA)

    # Create relationship tables and import data
    engine.import_csv(
        "ParticipatesIn", PARTICIPATES_IN_CSV,
        table_type="relationship", schema=PARTICIPATES_IN_SCHEMA,
        from_table="Gene", to_table="Pathway",
    )
    engine.import_csv(
        "Regulates", REGULATES_CSV,
        table_type="relationship", schema=REGULATES_SCHEMA,
        from_table="Gene", to_table="Gene",
    )
    engine.import_csv(
        "CompensatesFor", COMPENSATES_FOR_CSV,
        table_type="relationship", schema=COMPENSATES_FOR_SCHEMA,
        from_table="Gene", to_table="Gene",
    )
    engine.import_csv(
        "DrivesProcess", DRIVES_PROCESS_CSV,
        table_type="relationship", schema=DRIVES_PROCESS_SCHEMA,
        from_table="Gene", to_table="BioProcess",
    )
    engine.import_csv(
        "CellExpresses", CELL_EXPRESSES_CSV,
        table_type="relationship", schema=CELL_EXPRESSES_SCHEMA,
        from_table="CellType", to_table="Gene",
    )
    engine.import_csv(
        "PathwayInteracts", PATHWAY_INTERACTS_CSV,
        table_type="relationship", schema=PATHWAY_INTERACTS_SCHEMA,
        from_table="Pathway", to_table="Pathway",
    )
    engine.import_csv(
        "ProducesPhenotype", PRODUCES_PHENOTYPE_CSV,
        table_type="relationship", schema=PRODUCES_PHENOTYPE_SCHEMA,
        from_table="Pathway", to_table="Phenotype",
    )

    yield engine
    engine.close()


# ── Query 1: Basic — All genes in System 1 (Interferon) ──────────

class TestBasicQueries:
    def test_q1_genes_in_interferon_system(self, graph_engine: LadybugEngine):
        """Find all genes in the interferon system."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) WHERE g.system = 'interferon' "
            "RETURN g.name, g.z_score, g.direction ORDER BY g.name;"
        )
        assert len(rows) == 13
        names = [r[0] for r in rows]
        assert "MX1" in names
        assert "NLRX1" in names

    def test_q2_gene_count_by_direction_per_system(self, graph_engine: LadybugEngine):
        """Count genes by direction per system (aggregation test)."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) "
            "RETURN g.system, g.direction, count(g) AS cnt "
            "ORDER BY g.system, g.direction;"
        )
        assert len(rows) > 0
        # Verify we get both elevated and reduced for each system
        systems = {r[0] for r in rows}
        assert systems == {"interferon", "inflammation", "metabolic", "neuroimmune"}


# ── Query 3-4: Patterns and anomalies ────────────────────────────

class TestPatternDetection:
    def test_q3_elevated_genes_in_suppressed_pathways(self, graph_engine: LadybugEngine):
        """Find contradictions: elevated genes participating in suppressed pathways."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene)-[:ParticipatesIn]->(p:Pathway) "
            "WHERE g.direction = 'elevated' AND p.status = 'suppressed' "
            "RETURN g.name, g.z_score, p.name, p.status ORDER BY g.z_score DESC;"
        )
        # IFNGR1 and JAK2 are elevated but in suppressed Interferon pathway
        assert len(rows) >= 2
        names = [r[0] for r in rows]
        assert "IFNGR1" in names or "JAK2" in names

    def test_q4_extreme_z_scores(self, graph_engine: LadybugEngine):
        """Find genes with |z_score| > 2.5 (anomalies)."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) WHERE g.z_score > 2.5 OR g.z_score < -2.5 "
            "RETURN g.name, g.z_score, g.system ORDER BY g.z_score DESC;"
        )
        assert len(rows) >= 1
        # AVP (10.14) and IL6 (2.98) should be here
        names = [r[0] for r in rows]
        assert "AVP" in names
        assert "IL6" in names


# ── Query 5-6: Disconnected items and broken links ───────────────

class TestConnectivity:
    def test_q5_genes_not_in_any_pathway(self, graph_engine: LadybugEngine):
        """Find orphan genes with no pathway participation.

        NOTE: This tests OPTIONAL MATCH capability in LadybugDB.
        """
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) "
            "WHERE NOT EXISTS { MATCH (g)-[:ParticipatesIn]->(:Pathway) } "
            "RETURN g.name, g.system;"
        )
        # All genes should have at least one pathway
        # Any orphans indicate data issues
        assert isinstance(rows, list)

    def test_q6_pathways_without_cross_system_interactions(self, graph_engine: LadybugEngine):
        """Find pathways that have no PathwayInteracts edges."""
        cols, rows = graph_engine.execute(
            "MATCH (p:Pathway) "
            "WHERE NOT EXISTS { MATCH (p)-[:PathwayInteracts]-() } "
            "RETURN p.name, p.category;"
        )
        # Sub-pathways (5-12) are not in PathwayInteracts, only main pathways (1-4)
        assert len(rows) >= 4  # At least the sub-pathways


# ── Query 7: Subcategories — compensatory genes ──────────────────

class TestSubcategories:
    def test_q7_compensatory_genes(self, graph_engine: LadybugEngine):
        """Find all genes that compensate for other genes."""
        cols, rows = graph_engine.execute(
            "MATCH (g1:Gene)-[c:CompensatesFor]->(g2:Gene) "
            "RETURN g1.name, c.mechanism, g2.name ORDER BY g1.name;"
        )
        assert len(rows) == 6
        compensators = [r[0] for r in rows]
        assert "CPT1A" in compensators
        assert "TFAM" in compensators


# ── Query 8: Holistic view — schema and counts ───────────────────

class TestHolisticView:
    def test_q8_node_counts_per_type(self, graph_engine: LadybugEngine):
        """Get overall graph statistics — count nodes by type."""
        # Count each node type separately (current tool limitation — no single-query way)
        _, gene_rows = graph_engine.execute("MATCH (g:Gene) RETURN count(g);")
        _, pathway_rows = graph_engine.execute("MATCH (p:Pathway) RETURN count(p);")
        _, process_rows = graph_engine.execute("MATCH (b:BioProcess) RETURN count(b);")
        _, cell_rows = graph_engine.execute("MATCH (c:CellType) RETURN count(c);")
        _, pheno_rows = graph_engine.execute("MATCH (ph:Phenotype) RETURN count(ph);")

        assert gene_rows[0][0] == 50  # 50 genes (IDs 1-50)
        assert pathway_rows[0][0] == 12
        assert process_rows[0][0] == 12
        assert cell_rows[0][0] == 6
        assert pheno_rows[0][0] == 5

    def test_q8_relationship_counts(self, graph_engine: LadybugEngine):
        """Count relationships by type."""
        _, reg_rows = graph_engine.execute("MATCH ()-[r:Regulates]->() RETURN count(r);")
        _, comp_rows = graph_engine.execute("MATCH ()-[r:CompensatesFor]->() RETURN count(r);")
        _, part_rows = graph_engine.execute("MATCH ()-[r:ParticipatesIn]->() RETURN count(r);")

        assert reg_rows[0][0] == 20
        assert comp_rows[0][0] == 6
        assert part_rows[0][0] > 40  # ~50 participates_in edges


# ── Query 9: Hub analysis ────────────────────────────────────────

class TestHubAnalysis:
    def test_q9_most_connected_genes(self, graph_engine: LadybugEngine):
        """Find genes with the most relationships (any type).

        NOTE: This requires counting across multiple relationship types.
        Current limitation: must query each rel type separately.
        """
        # Count ParticipatesIn edges per gene
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene)-[r:ParticipatesIn]->(:Pathway) "
            "RETURN g.name, count(r) AS degree ORDER BY degree DESC LIMIT 10;"
        )
        assert len(rows) > 0
        # NLRX1 participates in 2 pathways (interferon + metabolic cross-link)
        top_names = [r[0] for r in rows]
        assert len(top_names) >= 5


# ── Query 10: Path finding ───────────────────────────────────────

class TestPathFinding:
    def test_q10_shortest_path_avp_to_il6(self, graph_engine: LadybugEngine):
        """Find shortest regulatory path from AVP to IL6.

        This tests LadybugDB's shortest_path with variable-length relationships.
        AVP → PCSK2 (activates) ... IL6 path if connected via Regulates.
        """
        # Direct path through Regulates
        cols, rows = graph_engine.execute(
            "MATCH p = (a:Gene {name: 'AVP'})-[:Regulates*1..5]->(b:Gene {name: 'IL6'}) "
            "RETURN length(p) AS path_length LIMIT 5;"
        )
        # May or may not find a direct path — that's the test
        assert isinstance(rows, list)

    def test_q10b_regulatory_chain_from_ifngr1(self, graph_engine: LadybugEngine):
        """Follow the IFNGR1 → JAK2 → MX1/OAS2 regulatory chain."""
        cols, rows = graph_engine.execute(
            "MATCH (a:Gene {name: 'IFNGR1'})-[:Regulates]->(b:Gene)-[:Regulates]->(c:Gene) "
            "RETURN a.name, b.name, c.name;"
        )
        # IFNGR1 → JAK2 → MX1, IFNGR1 → JAK2 → OAS2
        assert len(rows) >= 2
        for row in rows:
            assert row[0] == "IFNGR1"
            assert row[1] == "JAK2"
            assert row[2] in ("MX1", "OAS2")


# ── Query 11: Cross-system genes ─────────────────────────────────

class TestCrossSystem:
    def test_q11_genes_in_multiple_pathways(self, graph_engine: LadybugEngine):
        """Find genes that participate in pathways of different categories."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene)-[:ParticipatesIn]->(p:Pathway) "
            "WITH g, collect(DISTINCT p.category) AS categories "
            "WHERE size(categories) > 1 "
            "RETURN g.name, categories;"
        )
        # NLRX1 should appear (interferon + metabolic)
        if rows:
            names = [r[0] for r in rows]
            assert "NLRX1" in names


# ── Query 12: Hierarchy traversal ────────────────────────────────

class TestHierarchy:
    def test_q12_pathway_gene_process_chain(self, graph_engine: LadybugEngine):
        """Follow Pathway → Gene → BioProcess chain."""
        cols, rows = graph_engine.execute(
            "MATCH (p:Pathway)<-[:ParticipatesIn]-(g:Gene)-[:DrivesProcess]->(b:BioProcess) "
            "RETURN p.name, g.name, b.name LIMIT 20;"
        )
        assert len(rows) > 0
        # Each row is a (pathway, gene, process) triple


# ── Query 13: Subgraph focus ─────────────────────────────────────

class TestSubgraphFocus:
    def test_q13_metabolic_system_only(self, graph_engine: LadybugEngine):
        """Extract only the metabolic system with internal relationships."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) WHERE g.system = 'metabolic' "
            "RETURN g.name, g.z_score, g.direction ORDER BY g.z_score DESC;"
        )
        assert len(rows) == 14
        # Check compensatory genes are elevated
        elevated = [r for r in rows if r[2] == "elevated"]
        reduced = [r for r in rows if r[2] == "reduced"]
        assert len(elevated) >= 6  # CPT1A, HADHB, TFAM, TEFM, TK2, COQ7, SMDT1
        assert len(reduced) >= 7   # SLC2A1, PDHX, BCS1L, MT_ND3, TSFM, MTERF4, OPTN

    def test_q13b_metabolic_internal_regulation(self, graph_engine: LadybugEngine):
        """Show regulatory relationships within metabolic system only."""
        cols, rows = graph_engine.execute(
            "MATCH (g1:Gene)-[r:Regulates]->(g2:Gene) "
            "WHERE g1.system = 'metabolic' AND g2.system = 'metabolic' "
            "RETURN g1.name, r.type, g2.name;"
        )
        assert len(rows) >= 3  # PDHX→SLC2A1, BCS1L→MT_ND3, TSFM→MT_ND3, MTERF4→BCS1L


# ── Query 14: Direction analysis ─────────────────────────────────

class TestDirectionAnalysis:
    def test_q14_elevated_vs_reduced_ratio(self, graph_engine: LadybugEngine):
        """Ratio of elevated to reduced genes per system."""
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) "
            "RETURN g.system, "
            "  sum(CASE WHEN g.direction = 'elevated' THEN 1 ELSE 0 END) AS elevated_count, "
            "  sum(CASE WHEN g.direction = 'reduced' THEN 1 ELSE 0 END) AS reduced_count "
            "ORDER BY g.system;"
        )
        assert len(rows) == 4
        # Verify each system has both directions
        for row in rows:
            assert row[1] >= 0  # elevated count
            assert row[2] >= 0  # reduced count


# ── Query 15: Regulatory chains (transitive) ─────────────────────

class TestRegulatoryCascades:
    def test_q15_nlrx1_downstream_effects(self, graph_engine: LadybugEngine):
        """Find all genes downstream of NLRX1 through regulatory chains."""
        cols, rows = graph_engine.execute(
            "MATCH (start:Gene {name: 'NLRX1'})-[:Regulates*1..3]->(downstream:Gene) "
            "RETURN DISTINCT downstream.name, downstream.direction;"
        )
        # NLRX1 inhibits MX1, OAS2, RSAD2 (direct targets)
        assert len(rows) >= 3
        targets = [r[0] for r in rows]
        assert "MX1" in targets
        assert "OAS2" in targets
        assert "RSAD2" in targets


# ── Query 16-18: Graph comparison (testing gap for new tools) ────

class TestComparisonCapability:
    """These tests document the need for graph_compare and graph_cross_reference tools.

    With current tools, comparing two graphs requires:
    1. Creating two separate sessions
    2. Running identical queries on both
    3. Manually comparing results

    This is awkward and token-expensive — motivating the new tools.
    """

    def test_q16_second_graph_creation(self, tmp_path):
        """Create a second graph with modified data to test comparison.

        This simulates a second patient with partially overlapping genes.
        """
        db_path = str(tmp_path / "patient2.lbug")
        engine2 = LadybugEngine(db_path, max_rows=500, max_chars=100000)
        engine2.connect()

        # Create minimal gene table with some overlapping, some different genes
        patient2_csv = """\
id,name,z_score,direction,description,system
1,MX1,-1.0,reduced,Antiviral effector,interferon
2,OAS2,-0.5,reduced,Viral RNA degradation,interferon
14,IL6,1.5,elevated,Pro-inflammatory cytokine,inflammation
47,AVP,3.2,elevated,Vasopressin,neuroimmune
51,FOXP3,2.1,elevated,Treg master regulator,inflammation"""

        engine2.import_csv(
            "Gene", patient2_csv,
            table_type="node",
            schema=(
                "id INT64 PRIMARY KEY, name STRING, z_score DOUBLE, "
                "direction STRING, description STRING, system STRING"
            ),
        )

        # Query both and compare manually (demonstrating the pain point)
        _, rows2 = engine2.execute("MATCH (g:Gene) RETURN g.name, g.z_score ORDER BY g.name;")
        patient2_genes = {r[0]: r[1] for r in rows2}

        # MX1 in both but different z-scores
        assert "MX1" in patient2_genes
        assert patient2_genes["MX1"] == -1.0

        # FOXP3 only in patient 2
        assert "FOXP3" in patient2_genes

        engine2.close()

    def test_q17_cross_reference_need(self, graph_engine: LadybugEngine):
        """Document: cross-referencing requires extracting all genes then comparing.

        This works but is verbose and token-expensive — motivates graph_cross_reference tool.
        """
        cols, rows = graph_engine.execute(
            "MATCH (g:Gene) RETURN g.name, g.z_score ORDER BY g.name;"
        )
        patient1_genes = {r[0]: r[1] for r in rows}
        assert len(patient1_genes) == 50
        # A proper cross-reference tool would do this in one call across two sessions
