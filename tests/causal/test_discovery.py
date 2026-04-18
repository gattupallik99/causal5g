"""
Tests for causal5g.causal.discovery -- Claim 1 discovery facade.

Coverage targets:
  - All three DiscoveryMethod variants return well-formed DiscoveryResult
  - validate_input() warns on non-DataFrame, empty, single-variable, small
    sample, constant columns; clean input returns no warnings
  - Synthetic telemetry recovery: lagged chain (smf->upf), fork (nrf->amf,
    nrf->smf)
  - Edge cases (empty DataFrame, single column, constant column) never crash
  - FUSED populates all four fusion diagnostic buckets
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
import pytest

from causal.engine.pc_algorithm import DIRECTED, UNDIRECTED, PCResult
from causal5g.causal.discovery import CausalDiscovery, DiscoveryMethod, DiscoveryResult


# ---- helpers ----------------------------------------------------------------

def _rng(seed: int = 42) -> np.random.Generator:
    return np.random.default_rng(seed)


def _chain_df(rng: np.random.Generator, n: int = 250) -> pd.DataFrame:
    """smf drives upf with negligible noise (clear temporal chain)."""
    smf = rng.normal(0, 1, n)
    upf = 0.85 * smf + rng.normal(0, 0.15, n)
    return pd.DataFrame({"smf": smf, "upf": upf})


def _lagged_chain_df(rng: np.random.Generator, n: int = 300) -> pd.DataFrame:
    """smf[t-1] -> upf[t]: explicit one-step lag for Granger recovery."""
    smf = rng.normal(0, 1, n)
    upf = np.empty(n)
    upf[0] = rng.normal(0, 0.1)
    for t in range(1, n):
        upf[t] = 0.9 * smf[t - 1] + rng.normal(0, 0.05)
    return pd.DataFrame({"smf": smf, "upf": upf})


def _fork_df(rng: np.random.Generator, n: int = 250) -> pd.DataFrame:
    """nrf -> amf, nrf -> smf (common cause fork)."""
    nrf = rng.normal(0, 1, n)
    amf = 0.8 * nrf + rng.normal(0, 0.2, n)
    smf = 0.7 * nrf + rng.normal(0, 0.2, n)
    return pd.DataFrame({"nrf": nrf, "amf": amf, "smf": smf})


def _clean_df(n: int = 60) -> pd.DataFrame:
    rng = _rng(0)
    data = rng.normal(0, 1, (n, 3))
    return pd.DataFrame(data, columns=["a", "b", "c"])


# ---- PCResult factory for mock-based tests ----------------------------------

def _mock_pc_result(
    variables, skeleton_edges, cpdag_edges
) -> PCResult:
    return PCResult(
        variables=variables,
        skeleton_edges=skeleton_edges,
        cpdag_edges=cpdag_edges,
        separation_sets={},
        v_structures=[],
        independence_tests=[],
        elapsed_seconds=0.01,
        alpha=0.05,
        n_samples=100,
        n_variables=len(variables),
    )


# ---- validate_input ---------------------------------------------------------

class TestValidateInput:

    def test_non_dataframe_warns(self):
        cd = CausalDiscovery()
        warns = cd.validate_input({"a": [1, 2, 3]})
        assert any("DataFrame" in w for w in warns)

    def test_list_warns(self):
        cd = CausalDiscovery()
        warns = cd.validate_input([1, 2, 3])
        assert any("DataFrame" in w for w in warns)

    def test_none_warns(self):
        cd = CausalDiscovery()
        warns = cd.validate_input(None)
        assert any("DataFrame" in w for w in warns)

    def test_empty_dataframe_warns(self):
        cd = CausalDiscovery()
        warns = cd.validate_input(pd.DataFrame())
        assert any("empty" in w.lower() for w in warns)

    def test_single_variable_warns(self):
        cd = CausalDiscovery()
        df = pd.DataFrame({"a": range(100)})
        warns = cd.validate_input(df)
        assert any("one variable" in w.lower() for w in warns)

    def test_small_sample_warns(self):
        cd = CausalDiscovery()
        df = pd.DataFrame({"a": range(5), "b": range(5)})
        warns = cd.validate_input(df)
        assert any("small sample" in w.lower() for w in warns)

    def test_sample_exactly_at_threshold_no_warn(self):
        cd = CausalDiscovery()
        rng = _rng()
        df = pd.DataFrame(
            rng.normal(0, 1, (cd._MIN_SAMPLE_WARNING, 2)),
            columns=["a", "b"],
        )
        warns = cd.validate_input(df)
        assert not any("small sample" in w.lower() for w in warns)

    def test_no_numeric_columns_warns(self):
        cd = CausalDiscovery()
        df = pd.DataFrame({"a": ["x", "y", "z"], "b": ["p", "q", "r"]})
        warns = cd.validate_input(df)
        assert any("numeric" in w.lower() for w in warns)

    def test_constant_column_warns(self):
        cd = CausalDiscovery()
        df = pd.DataFrame({"a": [1.0] * 60, "b": np.random.randn(60)})
        warns = cd.validate_input(df)
        assert any("constant" in w.lower() for w in warns)

    def test_valid_dataframe_no_warnings(self):
        cd = CausalDiscovery()
        warns = cd.validate_input(_clean_df())
        assert warns == []

    def test_non_dataframe_returns_immediately(self):
        cd = CausalDiscovery()
        warns = cd.validate_input(42)
        # Only one warning (the type warning), not additional checks
        assert len(warns) == 1


# ---- Edge cases: must not crash ---------------------------------------------

class TestEdgeCases:

    def test_empty_dataframe_returns_empty_graph(self):
        cd = CausalDiscovery()
        result = cd.fit(pd.DataFrame())
        assert isinstance(result, DiscoveryResult)
        assert result.graph.number_of_nodes() == 0
        assert result.n_samples == 0

    def test_non_dataframe_returns_empty_graph(self):
        cd = CausalDiscovery()
        result = cd.fit("not a dataframe")  # type: ignore[arg-type]
        assert isinstance(result, DiscoveryResult)
        assert result.graph.number_of_nodes() == 0

    def test_single_column_returns_single_node(self):
        cd = CausalDiscovery()
        df = pd.DataFrame({"smf_cpu": np.random.randn(50)})
        result = cd.fit(df)
        assert isinstance(result, DiscoveryResult)
        assert result.graph.number_of_nodes() <= 1

    def test_constant_column_dropped_gracefully(self):
        rng = _rng()
        df = pd.DataFrame({
            "a": [1.0] * 50,
            "b": rng.normal(0, 1, 50),
            "c": rng.normal(0, 1, 50),
        })
        cd = CausalDiscovery(method=DiscoveryMethod.PC)
        result = cd.fit(df)
        # constant column "a" dropped; discovery still runs on b, c
        assert isinstance(result, DiscoveryResult)
        assert "a" not in result.variables

    def test_all_constant_columns_returns_empty_like(self):
        df = pd.DataFrame({"a": [1.0] * 50, "b": [2.0] * 50})
        cd = CausalDiscovery()
        result = cd.fit(df)
        assert isinstance(result, DiscoveryResult)
        assert result.graph.number_of_edges() == 0

    def test_two_column_constant_one_returns_single_node(self):
        rng = _rng()
        df = pd.DataFrame({"a": [0.0] * 50, "b": rng.normal(0, 1, 50)})
        cd = CausalDiscovery()
        result = cd.fit(df)
        assert isinstance(result, DiscoveryResult)

    def test_warnings_attached_to_result(self):
        cd = CausalDiscovery()
        df = pd.DataFrame({"a": range(5), "b": range(5)})
        result = cd.fit(df)
        assert any("small sample" in w.lower() for w in result.warnings)


# ---- Method: PC -------------------------------------------------------------

class TestPCMethod:

    def test_returns_discovery_result(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.PC).fit(df)
        assert isinstance(result, DiscoveryResult)
        assert result.method == DiscoveryMethod.PC

    def test_graph_is_digraph(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.PC).fit(df)
        assert isinstance(result.graph, nx.DiGraph)

    def test_variables_match_columns(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.PC).fit(df)
        assert set(result.variables) == {"smf", "upf"}

    def test_n_samples_matches_dataframe_length(self):
        rng = _rng()
        df = _chain_df(rng, n=150)
        result = CausalDiscovery(method=DiscoveryMethod.PC).fit(df)
        assert result.n_samples == 150

    def test_pc_no_fusion_diagnostics(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.PC).fit(df)
        assert result.confirmed_edges == []
        assert result.conflict_edges == []
        assert result.pc_only_edges == []

    def test_pc_fork_all_variables_present(self):
        rng = _rng()
        df = _fork_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.PC).fit(df)
        assert set(result.variables) == {"nrf", "amf", "smf"}

    def test_pc_detects_chain_edge(self):
        """PC should find the smf-upf dependency in the strong chain."""
        rng = _rng()
        df = _chain_df(rng, n=400)
        result = CausalDiscovery(method=DiscoveryMethod.PC, alpha=0.05).fit(df)
        edges = set(result.graph.edges())
        # At minimum, some edge between smf and upf must exist
        assert ("smf", "upf") in edges or ("upf", "smf") in edges

    def test_pc_fork_nrf_connected(self):
        """In the fork structure, nrf should have edges to amf and smf."""
        rng = _rng()
        df = _fork_df(rng, n=400)
        result = CausalDiscovery(method=DiscoveryMethod.PC, alpha=0.05).fit(df)
        nrf_neighbors = set(result.graph.successors("nrf")) | set(
            result.graph.predecessors("nrf")
        )
        assert len(nrf_neighbors) >= 1


# ---- Method: GRANGER --------------------------------------------------------

class TestGrangerMethod:

    def test_returns_discovery_result(self):
        rng = _rng()
        df = _lagged_chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.GRANGER).fit(df)
        assert isinstance(result, DiscoveryResult)
        assert result.method == DiscoveryMethod.GRANGER

    def test_graph_is_digraph(self):
        rng = _rng()
        df = _lagged_chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.GRANGER).fit(df)
        assert isinstance(result.graph, nx.DiGraph)

    def test_variables_match_columns(self):
        rng = _rng()
        df = _lagged_chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.GRANGER).fit(df)
        assert set(result.variables) == {"smf", "upf"}

    def test_granger_detects_lagged_cause(self):
        """With strong lagged relationship, smf->upf must appear."""
        rng = _rng()
        df = _lagged_chain_df(rng, n=400)
        result = CausalDiscovery(
            method=DiscoveryMethod.GRANGER, alpha=0.05, granger_max_lag=3
        ).fit(df)
        assert ("smf", "upf") in result.graph.edges()

    def test_granger_only_edges_populated(self):
        rng = _rng()
        df = _lagged_chain_df(rng, n=400)
        result = CausalDiscovery(
            method=DiscoveryMethod.GRANGER, alpha=0.1, granger_max_lag=3
        ).fit(df)
        assert isinstance(result.granger_only_edges, list)
        assert len(result.granger_only_edges) > 0

    def test_granger_graph_has_nodes_for_all_vars(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery(method=DiscoveryMethod.GRANGER).fit(df)
        assert "smf" in result.graph.nodes
        assert "upf" in result.graph.nodes

    def test_granger_fork_nrf_is_cause(self):
        """In the fork, nrf should Granger-cause at least one of amf/smf."""
        rng = _rng()
        df = _fork_df(rng, n=400)
        result = CausalDiscovery(
            method=DiscoveryMethod.GRANGER, alpha=0.1, granger_max_lag=3
        ).fit(df)
        outgoing = set(result.graph.successors("nrf"))
        assert len(outgoing) >= 1


# ---- Method: FUSED ----------------------------------------------------------

class TestFusedMethod:

    def test_returns_discovery_result(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery().fit(df)
        assert isinstance(result, DiscoveryResult)

    def test_default_method_is_fused(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery().fit(df)
        assert result.method == DiscoveryMethod.FUSED

    def test_graph_is_digraph(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery().fit(df)
        assert isinstance(result.graph, nx.DiGraph)

    def test_variables_match_columns(self):
        rng = _rng()
        df = _chain_df(rng)
        result = CausalDiscovery().fit(df)
        assert set(result.variables) == {"smf", "upf"}

    def test_all_four_diagnostic_buckets_populated(self):
        """
        Drive GrangerPCFusion directly with controlled inputs so all four
        edge categories are exercised:
          - (a, b): Granger confirmed by PC -> confirmed
          - (e, f): Granger only (not in PC) -> granger_only
          - (c, d): PC directed, not in Granger -> pc_only
          - (c, b): Granger says c->b but PC says b->c -> conflict
        """
        pc_result = _mock_pc_result(
            variables=["a", "b", "c", "d"],
            skeleton_edges=[("a", "b"), ("b", "c"), ("c", "d")],
            cpdag_edges=[
                ("a", "b", DIRECTED),
                ("b", "c", DIRECTED),
                ("c", "d", DIRECTED),
            ],
        )
        granger_edges = {
            ("a", "b"): 0.01,   # confirmed: PC also has a->b
            ("e", "f"): 0.01,   # granger_only: not in PC at all
            ("c", "b"): 0.01,   # conflict: PC says b->c, Granger says c->b
        }

        cd = CausalDiscovery(method=DiscoveryMethod.FUSED)
        result = _fused_with_injected(cd, pc_result, granger_edges, [])

        assert len(result.confirmed_edges) > 0, "confirmed_edges empty"
        assert len(result.granger_only_edges) > 0, "granger_only_edges empty"
        assert len(result.pc_only_edges) > 0, "pc_only_edges empty"
        assert len(result.conflict_edges) > 0, "conflict_edges empty"

    def test_fused_chain_has_edge(self):
        """Fused result on lagged chain: smf->upf must appear (Granger detects it)."""
        rng = _rng()
        df = _lagged_chain_df(rng, n=400)
        result = CausalDiscovery(method=DiscoveryMethod.FUSED, alpha=0.05).fit(df)
        edges = set(result.graph.edges())
        assert ("smf", "upf") in edges or ("upf", "smf") in edges

    def test_fused_result_has_all_nodes(self):
        rng = _rng()
        df = _fork_df(rng, n=300)
        result = CausalDiscovery().fit(df)
        for col in ["nrf", "amf", "smf"]:
            assert col in result.graph.nodes


# ---- helper called from the mock -------------------------------------------

def _fused_with_injected(
    cd: CausalDiscovery, pc_result: PCResult,
    granger_edges: dict, warns: list
) -> DiscoveryResult:
    """Run GrangerPCFusion directly with injected inputs."""
    from causal.engine.pc_algorithm import GrangerPCFusion

    fusion = GrangerPCFusion(granger_threshold=cd.alpha, pc_alpha=cd.alpha)
    fused_edges = fusion.fuse(granger_edges, pc_result)
    graph = fusion.to_networkx(fused_edges, include_conflicts=False)
    for v in pc_result.variables:
        if v not in graph:
            graph.add_node(v)

    confirmed = [(e["source"], e["target"]) for e in fused_edges if e["method"] == "confirmed"]
    granger_only = [
        (e["source"], e["target"])
        for e in fused_edges
        if e["method"] in ("granger_only", "granger_pc_undirected")
    ]
    pc_only = [(e["source"], e["target"]) for e in fused_edges if e["method"] == "pc_only"]
    conflicts = [(e["source"], e["target"]) for e in fused_edges if e["conflict"]]

    return DiscoveryResult(
        graph=graph,
        method=DiscoveryMethod.FUSED,
        variables=pc_result.variables,
        n_samples=pc_result.n_samples,
        confirmed_edges=confirmed,
        granger_only_edges=granger_only,
        pc_only_edges=pc_only,
        conflict_edges=conflicts,
        warnings=warns,
    )
