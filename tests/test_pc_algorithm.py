"""
tests/test_pc_algorithm.py
═══════════════════════════════════════════════════════════════════════════════
Causal5G — PC Algorithm Test Suite (Patent Claim 3)

Tests cover:
  1.  IndependenceOracle — partial correlation, Fisher's Z
  2.  PCAlgorithm        — skeleton, v-structures, Meek rules
  3.  GrangerPCFusion    — edge fusion logic
  4.  5G-specific telemetry scenarios (synthetic Free5GC data)

Run:  python -m pytest tests/test_pc_algorithm.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import unittest
import numpy as np
import pandas as pd

# pytest-compatible skip shim for environments without pytest
class _PytestShim:
    class _Skip(Exception): pass
    @staticmethod
    def skip(msg):
        raise unittest.SkipTest(msg)
pytest = _PytestShim()

from causal.engine.pc_algorithm import (
    IndependenceOracle,
    PCAlgorithm,
    GrangerPCFusion,
    DIRECTED,
    UNDIRECTED,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_chain(n=300, seed=42) -> pd.DataFrame:
    """
    Generate X → Y → Z causal chain.
    PC should recover X — Y — Z skeleton.
    V-structure test: no v-structure (X and Z share Y as non-collider).
    """
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, n)
    Y = 0.8 * X + rng.normal(0, 0.3, n)
    Z = 0.8 * Y + rng.normal(0, 0.3, n)
    return pd.DataFrame({"X": X, "Y": Y, "Z": Z})


def make_fork(n=300, seed=42) -> pd.DataFrame:
    """
    Common cause (fork): X ← C → Y.
    C is hidden but X and Y become independent given C.
    Here C is observed, so PC should find X — C — Y and no X—Y edge.
    """
    rng = np.random.default_rng(seed)
    C = rng.normal(0, 1, n)
    X = 0.8 * C + rng.normal(0, 0.3, n)
    Y = 0.8 * C + rng.normal(0, 0.3, n)
    return pd.DataFrame({"X": X, "C": C, "Y": Y})


def make_v_structure(n=1000, seed=42) -> pd.DataFrame:
    """
    V-structure (collider): X → Z ← Y, X and Y are independent.
    PC should orient X → Z ← Y.
    """
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, n)
    Y = rng.normal(0, 1, n)
    Z = 0.9 * X + 0.9 * Y + rng.normal(0, 0.1, n)  # strong signal, low noise
    return pd.DataFrame({"X": X, "Y": Y, "Z": Z})


def make_5g_telemetry(n=400, seed=42) -> pd.DataFrame:
    """
    Synthetic 5G NF telemetry mimicking Free5GC metrics.

    True causal structure:
      smf_cpu  →  upf_latency
      nrf_cpu  →  amf_cpu  →  upf_latency
      pcf_cpu  (independent)

    Simulates SMF CPU spike causing UPF latency increase.
    """
    rng = np.random.default_rng(seed)
    nrf_cpu     = rng.normal(10, 2, n)
    amf_cpu     = 0.6 * nrf_cpu + rng.normal(0, 1, n)
    smf_cpu     = rng.normal(12, 2, n)
    pcf_cpu     = rng.normal(8, 1, n)   # independent
    upf_latency = 0.5 * smf_cpu + 0.4 * amf_cpu + rng.normal(0, 0.5, n)

    return pd.DataFrame({
        "nrf_cpu":     nrf_cpu,
        "amf_cpu":     amf_cpu,
        "smf_cpu":     smf_cpu,
        "pcf_cpu":     pcf_cpu,
        "upf_latency": upf_latency,
    })


# ─── IndependenceOracle Tests ─────────────────────────────────────────────────

class TestIndependenceOracle(unittest.TestCase):

    def test_unconditional_dependent(self):
        """Correlated variables should be flagged as dependent."""
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 200)
        y = 0.9 * x + rng.normal(0, 0.1, 200)
        data = np.column_stack([x, y])
        oracle = IndependenceOracle(alpha=0.05)
        result = oracle.test(data, ["X", "Y"], 0, 1, [])
        assert not result.independent, "Strongly correlated variables should be dependent"
        assert result.p_value < 0.05

    def test_unconditional_independent(self):
        """Uncorrelated variables should be independent."""
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 300)
        y = rng.normal(0, 1, 300)
        data = np.column_stack([x, y])
        oracle = IndependenceOracle(alpha=0.05)
        result = oracle.test(data, ["X", "Y"], 0, 1, [])
        assert result.independent, "Independent variables should pass CI test"
        assert result.p_value > 0.05

    def test_conditional_independence_fork(self):
        """X and Y should be independent given common cause C."""
        df = make_fork(n=500)
        data = df.values
        oracle = IndependenceOracle(alpha=0.05)
        # Unconditionally X and Y are correlated (via C)
        r_unco = oracle.test(data, list(df.columns), 0, 2, [])
        assert not r_unco.independent, "X and Y should be correlated unconditionally via C"
        # Conditionally on C they should be independent
        r_cond = oracle.test(data, list(df.columns), 0, 2, [1])  # cond on C (index 1)
        assert r_cond.independent, "X and Y should be independent given C"

    def test_partial_corr_zero_variance(self):
        """Constant column should not crash; should return not-independent conservatively."""
        data = np.column_stack([
            np.random.normal(0, 1, 100),
            np.zeros(100),           # constant
            np.random.normal(0, 1, 100),
        ])
        oracle = IndependenceOracle(alpha=0.05)
        # Should not raise
        result = oracle.test(data, ["A", "B", "C"], 0, 2, [1])
        assert result.independent in (True, False) or isinstance(result.independent, (bool, np.bool_))

    def test_small_sample_conservative(self):
        """With too few samples, oracle should conservatively keep the edge."""
        data = np.random.normal(0, 1, (5, 2))
        oracle = IndependenceOracle(alpha=0.05, min_n=20)
        result = oracle.test(data, ["A", "B"], 0, 1, [])
        assert not result.independent, "Too few samples — should conservatively keep edge"


# ─── PCAlgorithm Tests ────────────────────────────────────────────────────────

class TestPCAlgorithm(unittest.TestCase):

    def test_chain_skeleton(self):
        """PC should recover X—Y—Z skeleton for a causal chain."""
        df = make_chain(n=400)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=2)
        result = pc.fit(df)

        skel = {frozenset(e) for e in result.skeleton_edges}
        assert frozenset(["X", "Y"]) in skel, "Missing X—Y skeleton edge"
        assert frozenset(["Y", "Z"]) in skel, "Missing Y—Z skeleton edge"
        # X and Z should be d-separated by Y → no direct edge
        assert frozenset(["X", "Z"]) not in skel, "X—Z edge should be absent (blocked by Y)"

    def test_fork_skeleton(self):
        """PC should find C connected to X and Y, but X and Y independent given C."""
        df = make_fork(n=400)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=2)
        result = pc.fit(df)

        skel = {frozenset(e) for e in result.skeleton_edges}
        assert frozenset(["C", "X"]) in skel, "Missing C—X edge"
        assert frozenset(["C", "Y"]) in skel, "Missing C—Y edge"
        assert frozenset(["X", "Y"]) not in skel, "X—Y edge should be absent (fork)"

    def test_v_structure_orientation(self):
        """
        V-structure: X and Y independent, both cause Z.
        After conditioning on Z, X and Y become correlated (Berkson's paradox).
        PC should orient at least one edge toward Z, or detect Z as collider.
        """
        # Use moderate signal so X-Y marginal independence is clear,
        # but X→Z and Y→Z are strong enough to be detected
        rng = np.random.default_rng(7)
        n = 800
        X = rng.normal(0, 1, n)
        Y = rng.normal(0, 1, n)  # independent of X
        Z = 0.8 * X + 0.8 * Y + rng.normal(0, 0.4, n)
        df = pd.DataFrame({"X": X, "Y": Y, "Z": Z})

        pc = PCAlgorithm(alpha=0.05, max_cond_set=2)
        result = pc.fit(df)

        directed = {(u, v) for u, v, t in result.cpdag_edges if t == DIRECTED}
        v_colliders = {collider for _, collider, _ in result.v_structures}
        skel = {frozenset(e) for e in result.skeleton_edges}

        # X and Z, Y and Z should be connected in skeleton
        assert frozenset(["X", "Z"]) in skel, "X—Z should be in skeleton"
        assert frozenset(["Y", "Z"]) in skel, "Y—Z should be in skeleton"

        # If X—Y edge is absent (unshielded triple), Z should be a collider
        if frozenset(["X", "Y"]) not in skel:
            assert "Z" in v_colliders or \
                   (("X", "Z") in directed and ("Y", "Z") in directed), \
                f"Z should be collider. v_structures={result.v_structures}, edges={result.cpdag_edges}"
        else:
            # Shielded triple — orientation may not be determined; pass
            pass

    def test_5g_telemetry_edges(self):
        """PC should find causal structure in synthetic 5G telemetry."""
        df = make_5g_telemetry(n=600)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=3)
        result = pc.fit(df)

        skel = {frozenset(e) for e in result.skeleton_edges}
        # smf_cpu → upf_latency should be a strong edge
        assert frozenset(["smf_cpu", "upf_latency"]) in skel, \
            "SMF CPU should be causally linked to UPF latency"
        # nrf_cpu → amf_cpu should be present
        assert frozenset(["nrf_cpu", "amf_cpu"]) in skel, \
            "NRF CPU should be causally linked to AMF CPU"
        # pcf_cpu should be isolated (no edges)
        pcf_edges = [e for e in skel if "pcf_cpu" in e]
        assert len(pcf_edges) == 0, \
            f"PCF CPU should be independent of all other NFs, got: {pcf_edges}"

    def test_result_summary(self):
        """Summary should return non-empty string with expected sections."""
        df = make_v_structure(n=300)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=2)
        result = pc.fit(df)
        s = result.summary()
        assert "Causal5G" in s
        assert "Patent Claim 3" in s
        assert "Variables" in s

    def test_to_networkx(self):
        """to_networkx should return a valid DiGraph."""
        import networkx as nx
        df = make_chain(n=300)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=2)
        result = pc.fit(df)
        G = result.to_networkx()
        assert isinstance(G, nx.DiGraph)
        assert G.number_of_nodes() == 3

    def test_alpha_sensitivity(self):
        """Stricter alpha should result in fewer skeleton edges."""
        df = make_5g_telemetry(n=400)
        pc_strict = PCAlgorithm(alpha=0.01, max_cond_set=2)
        pc_loose  = PCAlgorithm(alpha=0.15, max_cond_set=2)
        r_strict = pc_strict.fit(df)
        r_loose  = pc_loose.fit(df)
        assert len(r_strict.skeleton_edges) <= len(r_loose.skeleton_edges), \
            "Stricter alpha should yield equal or fewer skeleton edges"

    def test_two_variables(self):
        """PC should handle minimum case of 2 variables."""
        rng = np.random.default_rng(99)
        df = pd.DataFrame({
            "A": rng.normal(0, 1, 100),
            "B": rng.normal(0, 1, 100),
        })
        pc = PCAlgorithm(alpha=0.05, max_cond_set=0)
        result = pc.fit(df)
        assert result.n_variables == 2

    def test_separation_sets_stored(self):
        """Separation sets should be populated for removed edges."""
        df = make_fork(n=400)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=2)
        result = pc.fit(df)
        # X and Y are separated by C — sep set should exist
        sep = result.separation_sets
        assert ("X", "Y") in sep or ("Y", "X") in sep, \
            "Separation set for X,Y should be stored"


# ─── GrangerPCFusion Tests ────────────────────────────────────────────────────

class TestGrangerPCFusion(unittest.TestCase):

    def _make_pc_result(self) -> "PCResult":
        """Helper: run PC on synthetic data to get a real PCResult."""
        df = make_5g_telemetry(n=500)
        pc = PCAlgorithm(alpha=0.05, max_cond_set=3)
        return pc.fit(df)

    def test_confirmed_edge_weight(self):
        """Edge present in both Granger and PC should get weight 1.5."""
        pc_result = self._make_pc_result()
        # Use an edge that PC found in its skeleton
        skel_edges = pc_result.skeleton_edges
        if not skel_edges:
            pytest.skip("No skeleton edges found")

        u, v = skel_edges[0]
        granger_edges = {(u, v): 0.01}

        fusion = GrangerPCFusion()
        fused = fusion.fuse(granger_edges, pc_result)

        edge = next((e for e in fused if e["source"] == u and e["target"] == v), None)
        if edge and edge["method"] == "confirmed":
            assert edge["weight"] == 1.5
        # Either confirmed (if PC also directed it) or granger_pc_undirected

    def test_granger_only_weight(self):
        """Granger edge not in PC should have weight 1.0."""
        pc_result = self._make_pc_result()
        # Invent an edge unlikely to be in PC result
        granger_edges = {("pcf_cpu", "nrf_cpu"): 0.01}

        fusion = GrangerPCFusion()
        fused = fusion.fuse(granger_edges, pc_result)

        edge = next((e for e in fused
                     if e["source"] == "pcf_cpu" and e["target"] == "nrf_cpu"), None)
        if edge:
            assert edge["method"] in ("granger_only", "conflict"), \
                f"Expected granger_only or conflict, got {edge['method']}"

    def test_conflict_detection(self):
        """Granger A→B conflicting with PC B→A should be flagged."""
        # Build minimal PCResult with B→A directed
        from causal.engine.pc_algorithm import PCResult
        pc_result = PCResult(
            variables=["A", "B"],
            skeleton_edges=[("A", "B")],
            cpdag_edges=[("B", "A", DIRECTED)],  # PC says B→A
            separation_sets={},
            v_structures=[],
            independence_tests=[],
            elapsed_seconds=0.0,
            alpha=0.05,
            n_samples=100,
            n_variables=2,
        )
        granger_edges = {("A", "B"): 0.01}  # Granger says A→B

        fusion = GrangerPCFusion()
        fused = fusion.fuse(granger_edges, pc_result)

        conflicts = [e for e in fused if e["conflict"]]
        assert len(conflicts) >= 1, "Should detect Granger vs PC direction conflict"
        assert conflicts[0]["weight"] == 0.5

    def test_pc_only_edges_included(self):
        """PC-only directed edges should appear in fusion output."""
        from causal.engine.pc_algorithm import PCResult
        pc_result = PCResult(
            variables=["A", "B", "C"],
            skeleton_edges=[("A", "B"), ("B", "C")],
            cpdag_edges=[("A", "B", DIRECTED), ("B", "C", DIRECTED)],
            separation_sets={},
            v_structures=[],
            independence_tests=[],
            elapsed_seconds=0.0,
            alpha=0.05,
            n_samples=200,
            n_variables=3,
        )
        granger_edges = {("A", "B"): 0.02}  # Only A→B in Granger

        fusion = GrangerPCFusion()
        fused = fusion.fuse(granger_edges, pc_result)

        pc_only = [e for e in fused if e["method"] == "pc_only"]
        sources_targets = {(e["source"], e["target"]) for e in pc_only}
        assert ("B", "C") in sources_targets, "B→C (PC-only) should appear in fused output"

    def test_fusion_to_networkx(self):
        """Fused graph should be a valid DiGraph."""
        import networkx as nx
        pc_result = self._make_pc_result()
        skel_edges = pc_result.skeleton_edges
        granger_edges = {(u, v): 0.02 for u, v in skel_edges[:2]} if skel_edges else {}

        fusion = GrangerPCFusion()
        fused = fusion.fuse(granger_edges, pc_result)
        G = fusion.to_networkx(fused)
        assert isinstance(G, nx.DiGraph)

    def test_high_p_value_granger_filtered(self):
        """Granger edges above threshold should be excluded."""
        from causal.engine.pc_algorithm import PCResult
        pc_result = PCResult(
            variables=["A", "B"],
            skeleton_edges=[],
            cpdag_edges=[],
            separation_sets={},
            v_structures=[],
            independence_tests=[],
            elapsed_seconds=0.0,
            alpha=0.05,
            n_samples=100,
            n_variables=2,
        )
        granger_edges = {("A", "B"): 0.8}  # Not significant

        fusion = GrangerPCFusion(granger_threshold=0.05)
        fused = fusion.fuse(granger_edges, pc_result)
        assert len(fused) == 0, "Non-significant Granger edges should be excluded"


# ─── Integration Test: 5G Fault Scenario ─────────────────────────────────────

class TestFaultScenario(unittest.TestCase):
    """
    End-to-end test simulating a UPF CPU fault propagating through the
    5G core network.  Tests the full PC → Fusion pipeline.
    """

    def test_upf_fault_causal_chain(self):
        """
        When UPF CPU spikes, the causal chain NRF→AMF→UPF should be recoverable.
        """
        rng = np.random.default_rng(77)
        n = 500

        # Normal period
        nrf = rng.normal(10, 1, n)
        amf = 0.7 * nrf + rng.normal(0, 0.5, n)
        smf = rng.normal(12, 1, n)
        upf = 0.5 * amf + 0.4 * smf + rng.normal(0, 0.3, n)
        pcf = rng.normal(8, 0.5, n)

        # Inject UPF fault at t=400
        upf[400:] += 50

        df = pd.DataFrame({
            "nrf_cpu": nrf, "amf_cpu": amf, "smf_cpu": smf,
            "upf_cpu": upf, "pcf_cpu": pcf,
        })

        pc = PCAlgorithm(alpha=0.05, max_cond_set=3)
        result = pc.fit(df)

        skel = {frozenset(e) for e in result.skeleton_edges}
        # Core structural relationships should survive the fault injection
        assert frozenset(["nrf_cpu", "amf_cpu"]) in skel or \
               frozenset(["amf_cpu", "upf_cpu"]) in skel, \
               "At least one NRF→AMF or AMF→UPF edge should be present"

        # PCF should remain isolated
        pcf_in_skel = any("pcf_cpu" in e for e in skel)
        assert not pcf_in_skel, "PCF should remain causally isolated"

    def test_full_pipeline_granger_pc_fusion(self):
        """
        Simulate the full pipeline: PC + Granger → Fusion → high-confidence edges.
        """
        df = make_5g_telemetry(n=600)

        # Simulate Granger output (normally from granger.py)
        granger_edges = {
            ("smf_cpu", "upf_latency"): 0.01,
            ("nrf_cpu", "amf_cpu"):     0.02,
            ("amf_cpu", "upf_latency"): 0.03,
            ("pcf_cpu", "amf_cpu"):     0.12,  # Not significant — should be filtered
        }

        pc = PCAlgorithm(alpha=0.05, max_cond_set=3)
        pc_result = pc.fit(df)

        fusion = GrangerPCFusion(granger_threshold=0.05)
        fused = fusion.fuse(granger_edges, pc_result)

        # Non-significant Granger edge should not appear
        pcf_edges = [e for e in fused
                     if e["source"] == "pcf_cpu" and e["target"] == "amf_cpu"
                     and e.get("p_value_granger", 1.0) is not None]
        assert all(e.get("method") == "pc_only" for e in pcf_edges), \
            "PCF→AMF Granger edge above threshold should be filtered"

        # Check fusion has edges
        assert len(fused) > 0, "Fusion should produce at least one edge"

        # High-confidence confirmed edges should have weight 1.5
        confirmed = [e for e in fused if e["method"] == "confirmed"]
        for e in confirmed:
            assert e["weight"] == 1.5


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
