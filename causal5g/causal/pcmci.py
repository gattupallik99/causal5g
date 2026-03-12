"""
causal5g.causal.pcmci
======================
Claim 4 — PCMCI causal discovery backend.

PCMCI (Runge et al., 2019, Science Advances) is a time-series-adapted
causal discovery algorithm combining PC skeleton discovery with Momentary
Conditional Independence (MCI) tests. Produces a time-lagged causal DAG
where each edge is annotated with a lag value (tau) indicating the causal
propagation delay between source and target metric variables.

Wraps the `tigramite` library (https://github.com/jakobrunge/tigramite).
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import numpy as np
import networkx as nx

from causal5g.causal.discovery import CausalDiscoveryBackend
from causal5g.graph.topology_prior import TopologyPrior


class PCMCIBackend(CausalDiscoveryBackend):
    """
    PCMCI causal discovery backend for Claim 4.

    Produces a time-lagged causal DAG in which each directed edge is annotated
    with:
    - `tau` : int — time lag in steps at which the causal effect is strongest
    - `weight` : float — MCI test statistic (strength of causal link)
    - `p_value` : float — significance of the MCI test

    Parameters
    ----------
    tau_max : int
        Maximum time lag to test (in telemetry time steps).
        Corresponds to the sliding window parameter in Claim 1.
        E.g. tau_max=10 with 1s granularity = 10s max causal delay.
    alpha : float
        MCI test significance threshold (default 0.05)
    ci_test : str
        Conditional independence test: 'parcorr' | 'robustparcorr' | 'gpdc'
    """

    def __init__(self, tau_max: int = 10, alpha: float = 0.05,
                 ci_test: str = "parcorr"):
        self.tau_max = tau_max
        self.alpha = alpha
        self.ci_test = ci_test
        self._results: Optional[dict] = None

    def fit(self, data: np.ndarray, variable_names: List[str],
            topology_prior: TopologyPrior) -> nx.DiGraph:
        """
        Run PCMCI on the telemetry data array.

        Parameters
        ----------
        data : np.ndarray, shape (T, N)
        variable_names : list of str, length N

        Returns
        -------
        nx.DiGraph with edges annotated with tau, weight, p_value
        """
        try:
            from tigramite import data_processing as pp
            from tigramite.pcmci import PCMCI
            from tigramite.independence_tests.parcorr import ParCorr
            from tigramite.independence_tests.robust_parcorr import RobustParCorr
        except ImportError:
            raise ImportError(
                "tigramite is required for PCMCIBackend. "
                "Install with: pip install tigramite")

        dataframe = pp.DataFrame(data, var_names=variable_names)
        ci_test_obj = ParCorr() if self.ci_test == "parcorr" else RobustParCorr()

        # Build link assumptions from topology prior
        link_assumptions = self._build_link_assumptions(
            variable_names, topology_prior)

        pcmci = PCMCI(dataframe=dataframe, cond_ind_test=ci_test_obj)
        self._results = pcmci.run_pcmci(
            tau_max=self.tau_max,
            alpha_level=self.alpha,
            link_assumptions=link_assumptions,
        )

        return self._results_to_graph(variable_names)

    def _build_link_assumptions(self, variable_names: List[str],
                                 prior: TopologyPrior) -> dict:
        """
        Convert topology prior into tigramite link_assumptions format.
        Allowed edges get '-->' (lagged causal), forbidden get '' (no link).
        """
        N = len(variable_names)
        assumptions = {}
        for j in range(N):
            assumptions[j] = {}
            for i in range(N):
                for tau in range(1, self.tau_max + 1):
                    src = variable_names[i]
                    dst = variable_names[j]
                    if prior.is_valid_sbi_edge(src, dst) or \
                       prior.is_valid_pfcp_edge(src, dst):
                        assumptions[j][(i, -tau)] = "-->"
                    else:
                        assumptions[j][(i, -tau)] = ""
        return assumptions

    def _results_to_graph(self, variable_names: List[str]) -> nx.DiGraph:
        """Convert tigramite PCMCI results into an annotated nx.DiGraph."""
        graph = nx.DiGraph()
        graph.add_nodes_from(variable_names)
        if self._results is None:
            return graph
        val_matrix = self._results.get("val_matrix", np.array([]))
        p_matrix = self._results.get("p_matrix", np.array([]))
        graph_matrix = self._results.get("graph", np.array([]))
        N = len(variable_names)
        for i in range(N):
            for j in range(N):
                if i == j:
                    continue
                for tau in range(1, self.tau_max + 1):
                    if tau < graph_matrix.shape[2] and \
                       graph_matrix[i, j, tau] == "-->":
                        graph.add_edge(
                            variable_names[i], variable_names[j],
                            tau=tau,
                            weight=float(val_matrix[i, j, tau]),
                            p_value=float(p_matrix[i, j, tau]),
                        )
        return graph

    @property
    def results(self) -> Optional[dict]:
        """Raw tigramite PCMCI results dict."""
        return self._results
