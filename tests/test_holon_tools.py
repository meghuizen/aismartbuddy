"""Tests for holonic thinking tools — multi-level domain modeling."""

from __future__ import annotations

import pytest

from aismartbuddy.engines.thinking_engine import (
    MAX_HOLARCHIES,
    HolonNode,
    ThinkingEngine,
)
from aismartbuddy.session import SessionManager
from aismartbuddy.tools.holon import (
    holon_analyze,
    holon_create,
    holon_query,
    holon_update,
    holon_view,
)


def _extract(result: str, prefix: str) -> str:
    for line in result.split("\n"):
        for part in line.split(" | "):
            part = part.strip()
            if part.startswith(prefix):
                return part[len(prefix):].strip()
    return ""


# ── Engine unit tests ────────────────────────────────────────


class TestHolonEngine:
    @pytest.fixture
    def engine(self):
        e = ThinkingEngine()
        e.connect()
        yield e
        e.close()

    def test_add_holon_root(self, engine: ThinkingEngine):
        node = HolonNode(
            id="h1", name="Root",
            memberships=[{
                "holarchy_id": "hol1", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        )
        engine.add_holon(node)
        assert engine.get_holon_count() == 1
        assert "hol1" in engine.get_holarchy_ids()

    def test_add_holon_child(self, engine: ThinkingEngine):
        engine.add_holon(HolonNode(
            id="r", name="Root",
            memberships=[{
                "holarchy_id": "h1", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.add_holon(HolonNode(
            id="c", name="Child",
            memberships=[{
                "holarchy_id": "h1", "parent_id": "r",
                "role_in_parent": "sub", "level": 1,
            }],
        ))
        children = engine.get_holon_children("r", "h1")
        assert len(children) == 1
        assert children[0].id == "c"

    def test_join_holarchy(self, engine: ThinkingEngine):
        engine.add_holon(HolonNode(
            id="m", name="Mito",
            memberships=[{
                "holarchy_id": "struct", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.add_holon(HolonNode(
            id="met", name="Metabolism",
            memberships=[{
                "holarchy_id": "func", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.join_holarchy("m", "func", "met", "energy producer", 1)
        assert len(engine.get_holon("m").memberships) == 2
        children = engine.get_holon_children("met", "func")
        assert any(c.id == "m" for c in children)

    def test_get_siblings(self, engine: ThinkingEngine):
        engine.add_holon(HolonNode(
            id="r", name="Root",
            memberships=[{
                "holarchy_id": "h", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        for i in range(3):
            engine.add_holon(HolonNode(
                id=f"c{i}", name=f"Child {i}",
                memberships=[{
                    "holarchy_id": "h", "parent_id": "r",
                    "role_in_parent": f"role {i}", "level": 1,
                }],
            ))
        sibs = engine.get_holon_siblings("c0", "h")
        assert len(sibs) == 2
        sib_ids = {s.id for s in sibs}
        assert sib_ids == {"c1", "c2"}

    def test_get_ancestry(self, engine: ThinkingEngine):
        for i, (nid, pid) in enumerate([
            ("r", None), ("a", "r"), ("b", "a")
        ]):
            engine.add_holon(HolonNode(
                id=nid, name=nid.upper(),
                memberships=[{
                    "holarchy_id": "h", "parent_id": pid,
                    "role_in_parent": "", "level": i,
                }],
            ))
        path = engine.get_holon_ancestry("b", "h")
        assert [n.id for n in path] == ["b", "a", "r"]

    def test_find_bridge(self, engine: ThinkingEngine):
        # Two holarchies sharing a holon
        engine.add_holon(HolonNode(
            id="a", name="A",
            memberships=[{
                "holarchy_id": "h1", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.add_holon(HolonNode(
            id="shared", name="Shared",
            memberships=[
                {"holarchy_id": "h1", "parent_id": "a",
                 "role_in_parent": "", "level": 1},
            ],
        ))
        engine.add_holon(HolonNode(
            id="b", name="B",
            memberships=[{
                "holarchy_id": "h2", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.join_holarchy("shared", "h2", "b", "bridge", 1)

        path = engine.find_bridge("a", "b")
        assert len(path) == 3
        assert path[0].id == "a"
        assert path[1].id == "shared"
        assert path[2].id == "b"

    def test_evict_holarchy_preserves_shared(self, engine: ThinkingEngine):
        engine.add_holon(HolonNode(
            id="r1", name="Root1",
            memberships=[{
                "holarchy_id": "h1", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.add_holon(HolonNode(
            id="shared", name="Shared",
            memberships=[{
                "holarchy_id": "h1", "parent_id": "r1",
                "role_in_parent": "", "level": 1,
            }],
        ))
        engine.add_holon(HolonNode(
            id="r2", name="Root2",
            memberships=[{
                "holarchy_id": "h2", "parent_id": None,
                "role_in_parent": "", "level": 0,
            }],
        ))
        engine.join_holarchy("shared", "h2", "r2", "role2", 1)

        # Evict h1
        engine._evict_holarchy("h1")
        # shared should survive (has h2 membership)
        assert engine.get_holon("shared") is not None
        assert len(engine.get_holon("shared").memberships) == 1
        # r1 should be deleted (only h1 membership)
        assert engine.get_holon("r1") is None

    def test_memory_limit_holarchies(self, engine: ThinkingEngine):
        for i in range(MAX_HOLARCHIES + 5):
            engine.add_holon(HolonNode(
                id=f"r{i}", name=f"Root {i}",
                memberships=[{
                    "holarchy_id": f"h{i}", "parent_id": None,
                    "role_in_parent": "", "level": 0,
                }],
            ))
        assert len(engine.get_holarchy_ids()) <= MAX_HOLARCHIES


# ── Tool-level tests ─────────────────────────────────────────


@pytest.fixture
def _init_session_manager(session_manager: SessionManager):
    import aismartbuddy.session as session_mod

    session_mod.session_manager = session_manager
    yield
    session_mod.session_manager = None


@pytest.mark.usefixtures("_init_session_manager")
class TestHolonCreate:
    @pytest.mark.anyio
    async def test_create_root(self):
        r = await holon_create(
            name="Organism", description="The whole organism",
        )
        assert "Session:" in r
        assert "Holarchy:" in r
        assert "Holon:" in r
        assert "Parent: root" in r
        assert "Status: created" in r

    @pytest.mark.anyio
    async def test_create_child(self):
        r1 = await holon_create(
            name="Organism", description="Root",
        )
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        pid = _extract(r1, "Holon:")

        r2 = await holon_create(
            name="Immune System",
            description="Defense and inflammation",
            session_id=sid,
            holarchy_id=hid,
            parent_id=pid,
            role_in_parent="immune defense",
        )
        assert "Level: 1" in r2
        assert "Organism" in r2

    @pytest.mark.anyio
    async def test_invalid_parent(self):
        with pytest.raises(ValueError, match="not found"):
            await holon_create(
                name="X", description="X", parent_id="nonexistent",
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestHolonUpdate:
    @pytest.mark.anyio
    async def test_update_context(self):
        r = await holon_create(name="Cell", description="A cell")
        sid = _extract(r, "Session:")
        hid = _extract(r, "Holon:")
        result = await holon_update(
            session_id=sid, holon_id=hid,
            action="context",
            content="Currently inflamed, Th1-dominant cytokine profile",
        )
        assert "Context updated" in result

    @pytest.mark.anyio
    async def test_join_holarchy(self):
        r1 = await holon_create(
            name="Mito", description="Mitochondrion",
        )
        sid = _extract(r1, "Session:")
        mito_id = _extract(r1, "Holon:")

        r2 = await holon_create(
            name="Metabolism",
            description="Energy metabolism",
            session_id=sid,
        )
        met_hid = _extract(r2, "Holarchy:")
        met_id = _extract(r2, "Holon:")

        r3 = await holon_update(
            session_id=sid, holon_id=mito_id,
            action="join_holarchy",
            holarchy_id=met_hid, parent_id=met_id,
            role_in_parent="ATP production",
        )
        assert "Joined holarchy" in r3
        assert "Memberships: 2" in r3

    @pytest.mark.anyio
    async def test_add_lens(self):
        r = await holon_create(name="Test", description="Test")
        sid = _extract(r, "Session:")
        hid = _extract(r, "Holon:")
        result = await holon_update(
            session_id=sid, holon_id=hid,
            action="add_lens",
            lens_name="vulnerability",
            lens_findings="Single point of failure for ATP",
        )
        assert "vulnerability" in result

    @pytest.mark.anyio
    async def test_invalid_action(self):
        r = await holon_create(name="Test", description="Test")
        sid = _extract(r, "Session:")
        hid = _extract(r, "Holon:")
        with pytest.raises(ValueError, match="Invalid action"):
            await holon_update(
                session_id=sid, holon_id=hid, action="nope",
            )


@pytest.mark.usefixtures("_init_session_manager")
class TestHolonView:
    @pytest.mark.anyio
    async def test_zoom_in(self):
        r1 = await holon_create(name="Root", description="Root")
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        pid = _extract(r1, "Holon:")
        await holon_create(
            name="Child A", description="First child",
            session_id=sid, holarchy_id=hid, parent_id=pid,
            role_in_parent="part A",
        )
        await holon_create(
            name="Child B", description="Second child",
            session_id=sid, holarchy_id=hid, parent_id=pid,
            role_in_parent="part B",
        )
        result = await holon_view(
            session_id=sid, holon_id=pid,
            action="zoom_in", holarchy_id=hid,
        )
        assert "Zooming into: Root" in result
        assert "Child A" in result
        assert "Child B" in result
        assert "Children (2)" in result

    @pytest.mark.anyio
    async def test_zoom_out_synthesis_prompt(self):
        r1 = await holon_create(name="Root", description="Root")
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        pid = _extract(r1, "Holon:")
        r2 = await holon_create(
            name="Child", description="Child",
            session_id=sid, holarchy_id=hid, parent_id=pid,
        )
        child_id = _extract(r2, "Holon:")
        result = await holon_view(
            session_id=sid, holon_id=child_id,
            action="zoom_out", holarchy_id=hid,
        )
        assert "Zooming out from" in result
        assert "Synthesis prompt" in result

    @pytest.mark.anyio
    async def test_memberships_view(self):
        r1 = await holon_create(name="Shared", description="Multi")
        sid = _extract(r1, "Session:")
        shared_id = _extract(r1, "Holon:")
        r2 = await holon_create(
            name="Other Root", description="Other",
            session_id=sid,
        )
        other_hid = _extract(r2, "Holarchy:")
        other_id = _extract(r2, "Holon:")
        await holon_update(
            session_id=sid, holon_id=shared_id,
            action="join_holarchy",
            holarchy_id=other_hid, parent_id=other_id,
            role_in_parent="dual role",
        )
        result = await holon_view(
            session_id=sid, holon_id=shared_id,
            action="memberships",
        )
        assert "Memberships: 2" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestHolonAnalyze:
    @pytest.mark.anyio
    async def test_propagate_up_inform(self):
        r1 = await holon_create(
            name="System", description="System level",
            context="Healthy baseline",
        )
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        sys_id = _extract(r1, "Holon:")
        r2 = await holon_create(
            name="Cell", description="Cell level",
            session_id=sid, holarchy_id=hid, parent_id=sys_id,
        )
        cell_id = _extract(r2, "Holon:")

        result = await holon_analyze(
            session_id=sid, action="propagate_up",
            holon_id=cell_id, holarchy_id=hid,
            insight="Mitochondrial dysfunction detected",
            propagation_type="inform",
        )
        assert "Propagated UP" in result
        assert "System" in result

    @pytest.mark.anyio
    async def test_bridge(self):
        r1 = await holon_create(name="A", description="Start")
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        a_id = _extract(r1, "Holon:")
        r2 = await holon_create(
            name="B", description="Middle",
            session_id=sid, holarchy_id=hid, parent_id=a_id,
        )
        b_id = _extract(r2, "Holon:")
        r3 = await holon_create(
            name="C", description="End",
            session_id=sid, holarchy_id=hid, parent_id=b_id,
        )
        c_id = _extract(r3, "Holon:")

        result = await holon_analyze(
            session_id=sid, action="bridge",
            from_id=a_id, to_id=c_id,
        )
        assert "Bridge: A" in result
        assert "Path length: 3" in result

    @pytest.mark.anyio
    async def test_coherence(self):
        r1 = await holon_create(
            name="Cortisol", description="Stress hormone",
            context="Chronic elevation",
        )
        sid = _extract(r1, "Session:")
        cortisol_id = _extract(r1, "Holon:")
        r2 = await holon_create(
            name="Complex I", description="Mitochondrial",
            context="Reduced activity", session_id=sid,
        )
        complex_id = _extract(r2, "Holon:")

        result = await holon_analyze(
            session_id=sid, action="coherence",
            holon_a_id=cortisol_id, holon_b_id=complex_id,
        )
        assert "Coherence:" in result
        assert "Cortisol" in result
        assert "Complex I" in result
        assert "Coherence prompt" in result

    @pytest.mark.anyio
    async def test_invalid_action(self):
        r = await holon_create(name="X", description="X")
        sid = _extract(r, "Session:")
        with pytest.raises(ValueError, match="Invalid action"):
            await holon_analyze(
                session_id=sid, action="invalid",
            )

    @pytest.mark.anyio
    async def test_feedback_loops(self):
        """Detect bidirectional references in context."""
        r1 = await holon_create(
            name="HPA Axis", description="Stress response",
            context="Activated by neuroinflammation signals",
        )
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        hpa_id = _extract(r1, "Holon:")
        await holon_create(
            name="Neuroinflammation", description="Brain inflammation",
            session_id=sid, holarchy_id=hid, parent_id=hpa_id,
            context="Driven by HPA Axis cortisol output",
        )
        result = await holon_analyze(
            session_id=sid, action="feedback_loops",
            holarchy_id=hid,
        )
        assert "Feedback Loops" in result
        assert "HPA Axis" in result
        assert "Neuroinflammation" in result

    @pytest.mark.anyio
    async def test_leverage_points(self):
        """Find structurally important holons."""
        r1 = await holon_create(
            name="Root", description="Root",
        )
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        root_id = _extract(r1, "Holon:")
        # Add 3 children — root has most connections
        for i in range(3):
            await holon_create(
                name=f"Child {i}", description=f"Child {i}",
                session_id=sid, holarchy_id=hid, parent_id=root_id,
            )
        result = await holon_analyze(
            session_id=sid, action="leverage_points",
        )
        assert "Leverage Points" in result
        assert "Root" in result


@pytest.mark.usefixtures("_init_session_manager")
class TestHolonQuery:
    @pytest.mark.anyio
    async def test_local_query(self):
        r1 = await holon_create(
            name="Root", description="Top level",
            context="Overview context",
        )
        sid = _extract(r1, "Session:")
        hid = _extract(r1, "Holarchy:")
        root_id = _extract(r1, "Holon:")
        await holon_create(
            name="Child", description="Sub level",
            session_id=sid, holarchy_id=hid, parent_id=root_id,
        )
        result = await holon_query(
            session_id=sid,
            question="What's the state?",
            vantage_id=root_id,
            resolution="local",
        )
        assert "Query from: Root" in result
        assert "Resolution: local" in result
        assert "What's the state?" in result
        assert "Child" in result

    @pytest.mark.anyio
    async def test_invalid_resolution(self):
        r = await holon_create(name="X", description="X")
        sid = _extract(r, "Session:")
        hid = _extract(r, "Holon:")
        with pytest.raises(ValueError, match="Invalid resolution"):
            await holon_query(
                session_id=sid, question="?",
                vantage_id=hid, resolution="cosmic",
            )


# ── Pathophysiology integration test ─────────────────────────


@pytest.mark.usefixtures("_init_session_manager")
class TestPathophysiologyCase:
    """ME/CFS: stress → cortisol → immune → neuroinflammation → mito."""

    @pytest.mark.anyio
    async def test_full_pathophysiology_case(self):
        # === Build structural holarchy ===
        r = await holon_create(
            name="ME/CFS Patient",
            description="Organism with chronic fatigue syndrome",
            context="Post-exertional malaise, chronic fatigue",
        )
        sid = _extract(r, "Session:")
        struct_hid = _extract(r, "Holarchy:")
        org_id = _extract(r, "Holon:")

        # Systems
        r_hpa = await holon_create(
            name="HPA Axis",
            description="Hypothalamic-pituitary-adrenal stress axis",
            session_id=sid, holarchy_id=struct_hid, parent_id=org_id,
            role_in_parent="stress response coordination",
            context="Chronically activated",
        )
        hpa_id = _extract(r_hpa, "Holon:")

        r_immune = await holon_create(
            name="Immune System",
            description="Defense and inflammation regulation",
            session_id=sid, holarchy_id=struct_hid, parent_id=org_id,
            role_in_parent="immune defense",
            context="Shifted toward Th1 dominance",
        )
        immune_id = _extract(r_immune, "Holon:")

        r_nervous = await holon_create(
            name="Nervous System",
            description="Signal integration",
            session_id=sid, holarchy_id=struct_hid, parent_id=org_id,
            role_in_parent="neural signaling",
            context="Neuroinflammation present",
        )
        _extract(r_nervous, "Holon:")  # creates the holon

        # Cells under immune
        r_tcell = await holon_create(
            name="CD8+ T Cell",
            description="Cytotoxic immune cell",
            session_id=sid, holarchy_id=struct_hid,
            parent_id=immune_id,
            role_in_parent="cytotoxic response",
        )
        tcell_id = _extract(r_tcell, "Holon:")

        # Molecules under T cell
        r_mito = await holon_create(
            name="Mitochondrial Complex I",
            description="NADH dehydrogenase, first complex of ETC",
            session_id=sid, holarchy_id=struct_hid,
            parent_id=tcell_id,
            role_in_parent="oxidative phosphorylation",
            context="Activity reduced by ~40%",
            properties=["ATP production", "ROS generation"],
        )
        mito_id = _extract(r_mito, "Holon:")

        r_cortisol = await holon_create(
            name="Cortisol Signaling",
            description="GR binding and NF-kB modulation",
            session_id=sid, holarchy_id=struct_hid,
            parent_id=hpa_id,
            role_in_parent="downstream stress effector",
            context="Chronic cortisol elevation",
        )
        cortisol_id = _extract(r_cortisol, "Holon:")

        # === Build functional holarchy (energy metabolism) ===
        r_met = await holon_create(
            name="Energy Metabolism",
            description="Cellular energy production system",
            session_id=sid,
        )
        func_hid = _extract(r_met, "Holarchy:")
        met_id = _extract(r_met, "Holon:")

        # Add mitochondrion to functional holarchy too
        await holon_update(
            session_id=sid, holon_id=mito_id,
            action="join_holarchy",
            holarchy_id=func_hid, parent_id=met_id,
            role_in_parent="ATP production via oxidative phosphorylation",
        )

        # === Test 1: zoom_in on Immune System ===
        view_result = await holon_view(
            session_id=sid, holon_id=immune_id,
            action="zoom_in", holarchy_id=struct_hid,
        )
        assert "CD8+ T Cell" in view_result
        assert "ME/CFS Patient" not in view_result or "constraint" in view_result.lower()

        # === Test 2: sideways — peer systems ===
        side_result = await holon_view(
            session_id=sid, holon_id=immune_id,
            action="sideways", holarchy_id=struct_hid,
        )
        assert "HPA Axis" in side_result
        assert "Nervous System" in side_result

        # === Test 3: multi-membership check ===
        mem_result = await holon_view(
            session_id=sid, holon_id=mito_id,
            action="memberships",
        )
        assert "Memberships: 2" in mem_result

        # === Test 4: coherence between distant holons ===
        coh_result = await holon_analyze(
            session_id=sid, action="coherence",
            holon_a_id=cortisol_id, holon_b_id=mito_id,
        )
        assert "Coherence:" in coh_result
        assert "Cortisol Signaling" in coh_result
        assert "Mitochondrial Complex I" in coh_result

        # === Test 5: bridge ===
        bridge_result = await holon_analyze(
            session_id=sid, action="bridge",
            from_id=org_id, to_id=mito_id,
        )
        assert "Bridge:" in bridge_result
        assert "ME/CFS Patient" in bridge_result
        assert "Mitochondrial Complex I" in bridge_result

        # === Test 6: propagate up with stale tracking ===
        prop_result = await holon_analyze(
            session_id=sid, action="propagate_up",
            holon_id=mito_id, holarchy_id=struct_hid,
            insight="Complex I activity reduced 40%",
            propagation_type="inform",
        )
        assert "Propagated UP" in prop_result
        assert "CD8+ T Cell" in prop_result

        # === Test 7: query from vantage point ===
        query_result = await holon_query(
            session_id=sid,
            question="How does stress reach the mitochondria?",
            vantage_id=mito_id,
            holarchy_id=struct_hid,
            resolution="holarchy",
        )
        assert "Query from: Mitochondrial Complex I" in query_result
        assert "ME/CFS Patient" in query_result

        # === Test 8: custom lens ===
        lens_result = await holon_update(
            session_id=sid, holon_id=mito_id,
            action="add_lens",
            lens_name="vulnerability",
            lens_findings=(
                "Single point of failure for cellular energy. "
                "Complex I dysfunction cascades to all ATP-dependent "
                "processes in the cell."
            ),
        )
        assert "vulnerability" in lens_result
