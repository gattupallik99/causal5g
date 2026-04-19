"""
causal5g.causal.discovery
==========================
Claim 1 -- Algorithm-agnostic causal discovery facade for NF telemetry.

Public entry point to the Causal5G discovery pipeline. Wraps
causal.engine.pc_algorithm.PCAlgorithm and GrangerPCFusion; does not
duplicate their internal logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple

import networkx as nx
import numpy as np
import pandas as pd

from causal.engine.pc_algorithm import GrangerPCFusion, PCAlgorithm


class DiscoveryMethod(str, Enum):
    PC = "pc"
    GRANGER = "granger"
    FUSED = "fused"


class CausalDiscoveryBackend(ABC):
    """
    Claim 4 — Algorithm-agnostic backend contract for causal discovery.

    Pluggable backends implement a single `fit` method that consumes a
    telemetry data array plus a topology prior and returns an annotated
    `nx.DiGraph`. The contract is deliberately minimal so a single pipeline
    can swap between constraint-based (PC), temporal (Granger), and
    time-lagged (PCMCI) discovery without leaking algorithm-specific
    details into the caller.

    Subclasses currently in the tree:
      - `causal5g.causal.pcmci.PCMCIBackend` — Claim 4 time-lagged DAG

    Subclasses should annotate returned edges with algorithm-specific
    attributes (e.g. ``tau``, ``weight``, ``p_value``) so the fusion and
    reporting layers can consume them uniformly.
    """

    @abstractmethod
    def fit(
        self,
        data: "np.ndarray",
        variable_names: List[str],
        topology_prior: "object",
    ) -> "nx.DiGraph":
        """Run causal discovery and return an annotated graph.

        Parameters
        ----------
        data : np.ndarray, shape (T, N)
            Time-series telemetry matrix (T time steps, N variables).
        variable_names : list of str, length N
            Column labels for ``data``.
        topology_prior : causal5g.graph.topology_prior.TopologyPrior
            Structural prior restricting candidate causal edges to
            3GPP-valid SBI / PFCP pairs. Typed as ``object`` here to
            avoid a circular import; subclasses validate at call time.

        Returns
        -------
        nx.DiGraph
            Nodes are the variable names; edges carry algorithm-specific
            attributes (see subclass docstrings).
        """
        raise NotImplementedError


@dataclass
class DiscoveryResult:
    """Output of the CausalDiscovery facade.

    Fusion diagnostic fields (confirmed_edges, granger_only_edges,
    pc_only_edges, conflict_edges) match the Claim 1 language for
    the PC + Granger dual-evidence edge classification.
    """

    graph: nx.DiGraph
    method: DiscoveryMethod
    variables: List[str]
    n_samples: int
    confirmed_edges: List[Tuple[str, str]] = field(default_factory=list)
    granger_only_edges: List[Tuple[str, str]] = field(default_factory=list)
    pc_only_edges: List[Tuple[str, str]] = field(default_factory=list)
    conflict_edges: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class CausalDiscovery:
    """
    Claim 1 facade: accepts NF telemetry DataFrame, returns DiscoveryResult.

    Wraps PCAlgorithm (constraint-based, contemporaneous) and GrangerPCFusion
    (temporal + structural evidence fusion) from causal.engine.pc_algorithm.

    Parameters
    ----------
    method : DiscoveryMethod
        PC, GRANGER, or FUSED (default).
    alpha : float
        Significance level for CI tests and Granger tests.
    max_cond_set : int
        Maximum conditioning set size for PC skeleton phase.
    granger_max_lag : int
        Maximum lag order for pairwise Granger causality tests.
    """

    _MIN_SAMPLE_WARNING = 30

    def __init__(
        self,
        method: DiscoveryMethod = DiscoveryMethod.FUSED,
        alpha: float = 0.05,
        max_cond_set: int = 4,
        granger_max_lag: int = 3,
    ) -> None:
        self.method = method
        self.alpha = alpha
        self.max_cond_set = max_cond_set
        self.granger_max_lag = granger_max_lag

    # ---- Public API ----------------------------------------------------------

    def validate_input(self, df: object) -> List[str]:
        """Return validation warnings without raising exceptions.

        Callers may inspect the list before calling fit(); fit() itself
        calls validate_input() and attaches warnings to DiscoveryResult.
        """
        warns: List[str] = []
        if not isinstance(df, pd.DataFrame):
            warns.append(
                f"Input must be a pandas DataFrame, got {type(df).__name__}"
            )
            return warns
        if df.empty:
            warns.append("DataFrame is empty")
            return warns
        numeric = df.select_dtypes(include=[np.number])
        if numeric.shape[1] == 0:
            warns.append("No numeric columns found")
            return warns
        if numeric.shape[1] == 1:
            warns.append(
                "Only one variable; causal discovery requires at least two"
            )
        if numeric.shape[0] < self._MIN_SAMPLE_WARNING:
            warns.append(
                f"Small sample ({numeric.shape[0]} rows); "
                "CI test reliability may be reduced"
            )
        constant = [c for c in numeric.columns if numeric[c].std() == 0]
        if constant:
            warns.append(
                f"Constant columns (zero variance) will be dropped: {constant}"
            )
        return warns

    def fit(self, df: pd.DataFrame) -> DiscoveryResult:
        """Run causal discovery on a telemetry DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Rows = time steps, columns = NF metric names.

        Returns
        -------
        DiscoveryResult with causal graph and fusion diagnostics.
        """
        input_warnings = self.validate_input(df)

        if not isinstance(df, pd.DataFrame) or df.empty:
            return DiscoveryResult(
                graph=nx.DiGraph(),
                method=self.method,
                variables=[],
                n_samples=0,
                warnings=input_warnings,
            )

        df = df.select_dtypes(include=[np.number])
        df = df.loc[:, df.std() > 0]

        if df.shape[1] < 2:
            g = nx.DiGraph()
            g.add_nodes_from(df.columns)
            return DiscoveryResult(
                graph=g,
                method=self.method,
                variables=list(df.columns),
                n_samples=len(df),
                warnings=input_warnings,
            )

        dispatch = {
            DiscoveryMethod.PC: self._run_pc,
            DiscoveryMethod.GRANGER: self._run_granger,
            DiscoveryMethod.FUSED: self._run_fused,
        }
        return dispatch[self.method](df, input_warnings)

    # ---- Method runners ------------------------------------------------------

    def _run_pc(self, df: pd.DataFrame, warns: List[str]) -> DiscoveryResult:
        pc = PCAlgorithm(alpha=self.alpha, max_cond_set=self.max_cond_set)
        result = pc.fit(df)
        return DiscoveryResult(
            graph=result.to_networkx(),
            method=DiscoveryMethod.PC,
            variables=result.variables,
            n_samples=result.n_samples,
            warnings=warns,
        )

    def _run_granger(self, df: pd.DataFrame, warns: List[str]) -> DiscoveryResult:
        granger_edges = self._compute_granger_edges(df)
        graph = nx.DiGraph()
        graph.add_nodes_from(df.columns)
        for (cause, effect), p_val in granger_edges.items():
            if p_val <= self.alpha:
                graph.add_edge(cause, effect, weight=1.0 - p_val, p_value=p_val)
        significant = [
            (c, e) for (c, e), p in granger_edges.items() if p <= self.alpha
        ]
        return DiscoveryResult(
            graph=graph,
            method=DiscoveryMethod.GRANGER,
            variables=list(df.columns),
            n_samples=len(df),
            granger_only_edges=significant,
            warnings=warns,
        )

    def _run_fused(self, df: pd.DataFrame, warns: List[str]) -> DiscoveryResult:
        pc = PCAlgorithm(alpha=self.alpha, max_cond_set=self.max_cond_set)
        pc_result = pc.fit(df)
        granger_edges = self._compute_granger_edges(df)

        fusion = GrangerPCFusion(
            granger_threshold=self.alpha, pc_alpha=self.alpha
        )
        fused_edges = fusion.fuse(granger_edges, pc_result)
        graph = fusion.to_networkx(fused_edges, include_conflicts=False)
        for v in pc_result.variables:
            if v not in graph:
                graph.add_node(v)

        confirmed = [
            (e["source"], e["target"])
            for e in fused_edges
            if e["method"] == "confirmed"
        ]
        granger_only = [
            (e["source"], e["target"])
            for e in fused_edges
            if e["method"] in ("granger_only", "granger_pc_undirected")
        ]
        pc_only = [
            (e["source"], e["target"])
            for e in fused_edges
            if e["method"] == "pc_only"
        ]
        conflicts = [
            (e["source"], e["target"])
            for e in fused_edges
            if e["conflict"]
        ]

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

    # ---- Helpers -------------------------------------------------------------

    def _compute_granger_edges(
        self, df: pd.DataFrame
    ) -> Dict[Tuple[str, str], float]:
        """Pairwise Granger causality p-values for all ordered column pairs."""
        from statsmodels.tsa.stattools import grangercausalitytests

        cols = list(df.columns)
        edges: Dict[Tuple[str, str], float] = {}
        data = df.copy().fillna(df.mean())
        data = (data - data.mean()) / (data.std() + 1e-8)

        for cause in cols:
            for effect in cols:
                if cause == effect:
                    continue
                try:
                    test_df = pd.DataFrame(
                        {"y": data[effect].values, "x": data[cause].values}
                    )
                    results = grangercausalitytests(
                        test_df, maxlag=self.granger_max_lag, verbose=False
                    )
                    best_p = min(
                        r[0]["ssr_ftest"][1] for r in results.values()
                    )
                    edges[(cause, effect)] = best_p
                except Exception:
                    pass
        return edges
