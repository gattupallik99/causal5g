"""
causal5g.graph.cross_domain
============================
Claim 2 — Cross-domain causal edge inference.

Tests conditional independence between domain boundary metrics to infer
causal edges across RAN / Transport / Core / Cloud domain boundaries,
enabling root cause propagation without a monolithic graph.
"""

from __future__ import annotations
from typing import List, Tuple
import numpy as np

from causal5g.graph.hierarchical_dag import Domain, HierarchicalDAG


class CrossDomainEdgeInferrer:
    """
    Infers cross-domain causal edges by testing conditional independence
    between boundary metrics of adjacent domain layers.

    Parameters
    ----------
    alpha : float
        Significance threshold for conditional independence tests (default 0.05)
    max_lag_ms : int
        Maximum time lag to test for cross-domain causal delays (default 5000ms)
    """

    DOMAIN_BOUNDARIES: List[Tuple[Domain, Domain]] = [
        (Domain.CLOUD, Domain.CORE),
        (Domain.CORE, Domain.TRANSPORT),
        (Domain.TRANSPORT, Domain.RAN),
    ]

    def __init__(self, alpha: float = 0.05, max_lag_ms: int = 5000):
        self.alpha = alpha
        self.max_lag_ms = max_lag_ms

    def infer_edges(self, hdag: HierarchicalDAG,
                    boundary_metrics: dict) -> HierarchicalDAG:
        """
        Test all domain boundary metric pairs and add cross-domain edges
        where conditional independence is rejected at significance level alpha.

        Parameters
        ----------
        hdag : HierarchicalDAG
            Hierarchical DAG with populated domain graphs
        boundary_metrics : dict
            {(domain, node_id): np.ndarray time series} for boundary nodes

        Returns
        -------
        HierarchicalDAG with cross-domain edges added
        """
        for src_domain, dst_domain in self.DOMAIN_BOUNDARIES:
            src_nodes = [n for d, n in boundary_metrics if d == src_domain]
            dst_nodes = [n for d, n in boundary_metrics if d == dst_domain]
            for src in src_nodes:
                for dst in dst_nodes:
                    p_value, lag_ms = self._test_independence(
                        boundary_metrics[(src_domain, src)],
                        boundary_metrics[(dst_domain, dst)],
                    )
                    if p_value < self.alpha:
                        hdag.add_cross_domain_edge(
                            src, src_domain, dst, dst_domain,
                            ci_score=p_value, time_lag_ms=lag_ms)
        return hdag

    def _test_independence(self, x: np.ndarray,
                           y: np.ndarray) -> Tuple[float, int]:
        """
        Placeholder: partial correlation-based conditional independence test
        with lag sweep up to max_lag_ms.

        Returns (p_value, best_lag_ms)
        """
        raise NotImplementedError(
            "Implement partial correlation CI test with lag sweep")
