"""
causal5g.causal.discovery
==========================
Claim 1 — Algorithm-agnostic conditional independence-based causal discovery.

Constructs the causal DAG from multi-source telemetry constrained by the
5G topology structural prior. Supports PC, FCI, and PCMCI backends.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import numpy as np
import networkx as nx

from causal5g.graph.topology_prior import TopologyPrior


class CausalDiscoveryBackend(ABC):
    """Abstract base for pluggable causal discovery algorithm backends."""

    @abstractmethod
    def fit(self, data: np.ndarray, variable_names: List[str],
            topology_prior: TopologyPrior) -> nx.DiGraph:
        """
        Fit a causal DAG from observational time-series data.

        Parameters
        ----------
        data : np.ndarray, shape (T, N)
            T time steps, N variables (one per NF or slice metric)
        variable_names : list of str
            Name for each column in data
        topology_prior : TopologyPrior
            Structural prior constraining candidate edges

        Returns
        -------
        nx.DiGraph with causal edges annotated with weight (CI score)
        """


class CausalDiscovery:
    """
    Algorithm-agnostic causal discovery engine for the bi-level 5G causal DAG.

    Wraps any CausalDiscoveryBackend and applies the topology structural prior
    from Claim 1 to constrain candidate causal edges.

    Parameters
    ----------
    backend : CausalDiscoveryBackend
        Algorithm implementation (PCMCIBackend, PCBackend, etc.)
    topology_prior : TopologyPrior
        5G SBI + PFCP structural prior from graph.topology_prior
    window_ms : int
        Sliding window size for telemetry ingestion (default 300000ms = 5min)
    """

    def __init__(self, backend: CausalDiscoveryBackend,
                 topology_prior: TopologyPrior,
                 window_ms: int = 300_000):
        self.backend = backend
        self.topology_prior = topology_prior
        self.window_ms = window_ms
        self._last_graph: Optional[nx.DiGraph] = None

    def run(self, data: np.ndarray,
            variable_names: List[str]) -> nx.DiGraph:
        """
        Run causal discovery on the provided telemetry window.

        Returns the causal DAG with edges constrained by topology prior.
        """
        raw_graph = self.backend.fit(data, variable_names, self.topology_prior)
        filtered = self._apply_prior(raw_graph, variable_names)
        self._last_graph = filtered
        return filtered

    def _apply_prior(self, graph: nx.DiGraph,
                     variable_names: List[str]) -> nx.DiGraph:
        """Remove edges that violate the topology structural prior."""
        nf_type_map = {}  # populated from topology_prior context
        edges_to_remove = [
            (u, v) for u, v in graph.edges()
            if not self.topology_prior.is_valid_sbi_edge(u, v, nf_type_map)
            and not self.topology_prior.is_valid_pfcp_edge(u, v)
        ]
        graph.remove_edges_from(edges_to_remove)
        return graph

    @property
    def last_graph(self) -> Optional[nx.DiGraph]:
        return self._last_graph
