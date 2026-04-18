"""
Tests for causal5g.graph.cross_domain -- Claim 2 cross-domain edge inference.

The production CI test (_test_independence) is a placeholder that raises
NotImplementedError; tests override it via a subclass to exercise the
infer_edges loop deterministically. All 21 statements covered.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pytest

from causal5g.graph.bilevel_dag import BiLevelCausalDAG, NFNode
from causal5g.graph.cross_domain import CrossDomainEdgeInferrer
from causal5g.graph.hierarchical_dag import Domain, HierarchicalDAG
from causal5g.graph.topology_prior import TopologyPrior


# ---- helpers ---------------------------------------------------------------

def _build_hdag() -> HierarchicalDAG:
    """Minimal hierarchical DAG with a single core NF so HierarchicalDAG
    construction succeeds; cross-domain edges don't depend on core content."""
    prior = TopologyPrior(pfcp_bindings=[("smf-1", "upf-1")])
    core = BiLevelCausalDAG(topology_prior=prior)
    core.add_nf_node(NFNode(nf_id="smf-1", nf_type="SMF", instance_id="smf-1"))
    return HierarchicalDAG(core_dag=core)


def _boundary_metrics() -> dict:
    """One boundary node per domain so every (src,dst) pair yields a test."""
    rng = np.random.default_rng(42)
    return {
        (Domain.CLOUD, "pod-1"): rng.normal(0, 1, 64),
        (Domain.CORE, "smf-1"): rng.normal(0, 1, 64),
        (Domain.TRANSPORT, "n9-1"): rng.normal(0, 1, 64),
        (Domain.RAN, "gnb-1"): rng.normal(0, 1, 64),
    }


class _AlwaysDependent(CrossDomainEdgeInferrer):
    """Forces infer_edges to add every candidate cross-domain edge."""

    def _test_independence(self, x: np.ndarray,
                           y: np.ndarray) -> Tuple[float, int]:
        return 0.001, 250


class _AlwaysIndependent(CrossDomainEdgeInferrer):
    """Forces infer_edges to reject every candidate edge."""

    def _test_independence(self, x: np.ndarray,
                           y: np.ndarray) -> Tuple[float, int]:
        return 0.9, 0


# ---- __init__ --------------------------------------------------------------

class TestInit:
    def test_defaults(self):
        inf = CrossDomainEdgeInferrer()
        assert inf.alpha == pytest.approx(0.05)
        assert inf.max_lag_ms == 5000

    def test_custom_params(self):
        inf = CrossDomainEdgeInferrer(alpha=0.01, max_lag_ms=2000)
        assert inf.alpha == pytest.approx(0.01)
        assert inf.max_lag_ms == 2000


# ---- DOMAIN_BOUNDARIES class constant --------------------------------------

class TestDomainBoundaries:
    def test_boundaries_cover_full_stack(self):
        """Claim 2: edges must chain Cloud -> Core -> Transport -> RAN."""
        pairs = CrossDomainEdgeInferrer.DOMAIN_BOUNDARIES
        assert pairs == [
            (Domain.CLOUD, Domain.CORE),
            (Domain.CORE, Domain.TRANSPORT),
            (Domain.TRANSPORT, Domain.RAN),
        ]

    def test_boundaries_form_contiguous_chain(self):
        pairs = CrossDomainEdgeInferrer.DOMAIN_BOUNDARIES
        for (_, dst_prev), (src_next, _) in zip(pairs, pairs[1:]):
            assert dst_prev == src_next


# ---- infer_edges: empty input ----------------------------------------------

class TestInferEdgesEmpty:
    def test_empty_boundary_metrics_returns_hdag_unchanged(self):
        hdag = _build_hdag()
        out = CrossDomainEdgeInferrer().infer_edges(hdag, boundary_metrics={})
        assert out is hdag
        assert out.cross_domain_graph.number_of_edges() == 0

    def test_only_one_side_populated_produces_no_edges(self):
        """CLOUD populated but no CORE target -> empty dst_nodes loop skipped."""
        hdag = _build_hdag()
        rng = np.random.default_rng(0)
        metrics = {(Domain.CLOUD, "pod-a"): rng.normal(0, 1, 32)}
        out = _AlwaysDependent().infer_edges(hdag, metrics)
        assert out.cross_domain_graph.number_of_edges() == 0


# ---- infer_edges: dependent branch -----------------------------------------

class TestInferEdgesDependent:
    def test_adds_edge_per_boundary_pair_when_dependent(self):
        hdag = _build_hdag()
        out = _AlwaysDependent().infer_edges(hdag, _boundary_metrics())
        # With one node per domain and 3 boundary pairs -> 3 edges
        assert out.cross_domain_graph.number_of_edges() == 3

    def test_edge_attributes_capture_ci_score_and_lag(self):
        hdag = _build_hdag()
        out = _AlwaysDependent().infer_edges(hdag, _boundary_metrics())
        for _, _, data in out.cross_domain_graph.edges(data=True):
            assert data["ci_score"] == pytest.approx(0.001)
            assert data["time_lag_ms"] == 250
            assert "src_domain" in data and "dst_domain" in data

    def test_edges_span_expected_domain_pairs(self):
        hdag = _build_hdag()
        out = _AlwaysDependent().infer_edges(hdag, _boundary_metrics())
        observed = {
            (data["src_domain"], data["dst_domain"])
            for _, _, data in out.cross_domain_graph.edges(data=True)
        }
        assert observed == set(CrossDomainEdgeInferrer.DOMAIN_BOUNDARIES)

    def test_alpha_boundary_p_equal_to_alpha_does_not_add(self):
        """p < alpha (strict) -- p == alpha must NOT add an edge."""

        class _OnBoundary(CrossDomainEdgeInferrer):
            def _test_independence(self, x, y):
                return self.alpha, 100

        hdag = _build_hdag()
        out = _OnBoundary(alpha=0.05).infer_edges(hdag, _boundary_metrics())
        assert out.cross_domain_graph.number_of_edges() == 0


# ---- infer_edges: independent branch ---------------------------------------

class TestInferEdgesIndependent:
    def test_no_edges_when_all_pairs_independent(self):
        hdag = _build_hdag()
        out = _AlwaysIndependent().infer_edges(hdag, _boundary_metrics())
        assert out.cross_domain_graph.number_of_edges() == 0


# ---- _test_independence placeholder ----------------------------------------

class TestTestIndependencePlaceholder:
    def test_raises_not_implemented(self):
        inf = CrossDomainEdgeInferrer()
        with pytest.raises(NotImplementedError):
            inf._test_independence(np.zeros(10), np.zeros(10))
