"""
causal5g.causal.attribution
============================
Claim 1 — Causal attribution scoring for NF-layer and slice-layer
root cause isolation.

Implements the bi-level attribution analysis:
- NF-layer: concentration of scores on a shared NF node -> NF-layer root cause
- Slice-layer: concentration within a single slice subgraph -> slice-layer root cause
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple
import networkx as nx
import numpy as np

from causal5g.graph.bilevel_dag import BiLevelCausalDAG


class RootCauseType(str, Enum):
    NF_LAYER = "nf_layer"
    SLICE_LAYER = "slice_layer"
    UNDETERMINED = "undetermined"


@dataclass
class AttributionResult:
    """Output of the causal attribution scoring procedure."""
    root_cause_type: RootCauseType
    root_cause_node: str              # NF node ID with highest attribution
    attribution_score: float          # causal attribution score [0, 1]
    affected_snssais: List[str]       # S-NSSAI values showing degradation
    implicated_pfcp_seid: Optional[int] = None
    implicated_sbi_service: Optional[str] = None
    confidence: float = 0.0


class CausalAttributionScorer:
    """
    Computes causal attribution scores on the bi-level DAG and isolates
    root cause as NF-layer or slice-layer per Claim 1.

    Supports PageRank-based attribution and structural causal model residuals.

    Parameters
    ----------
    nf_attribution_threshold : float
        Attribution score threshold for NF-layer root cause declaration
    slice_isolation_threshold : float
        Max fraction of slice subgraphs affected for slice-layer classification
    """

    def __init__(self, nf_attribution_threshold: float = 0.4,
                 slice_isolation_threshold: float = 0.34):
        self.nf_attribution_threshold = nf_attribution_threshold
        self.slice_isolation_threshold = slice_isolation_threshold

    def score(self, causal_graph: nx.DiGraph,
              bilevel_dag: BiLevelCausalDAG,
              anomaly_node: str) -> AttributionResult:
        """
        Compute attribution scores and isolate root cause type.

        Parameters
        ----------
        causal_graph : nx.DiGraph
            Output of CausalDiscovery.run() — the fitted causal DAG
        bilevel_dag : BiLevelCausalDAG
            Bi-level topology graph with slice subgraph registry
        anomaly_node : str
            NF node ID where the anomaly was first detected

        Returns
        -------
        AttributionResult with root cause type, node, and affected slices
        """
        scores = self._pagerank_attribution(causal_graph, anomaly_node)
        top_node, top_score = max(scores.items(), key=lambda x: x[1])
        affected_slices = self._get_affected_slices(top_node, bilevel_dag)
        root_cause_type = self._classify(top_node, top_score, affected_slices,
                                         bilevel_dag)
        return AttributionResult(
            root_cause_type=root_cause_type,
            root_cause_node=top_node,
            attribution_score=top_score,
            affected_snssais=affected_slices,
            confidence=self._confidence(top_score, scores),
        )

    def _pagerank_attribution(self, graph: nx.DiGraph,
                               sink: str) -> Dict[str, float]:
        """
        Compute attribution scores via reverse-graph PageRank from anomaly sink.
        Higher score = more likely to be root cause upstream of the anomaly.
        """
        if graph.number_of_nodes() == 0:
            return {}
        reversed_graph = graph.reverse()
        personalization = {n: (1.0 if n == sink else 0.0)
                           for n in reversed_graph.nodes()}
        try:
            scores = nx.pagerank(reversed_graph, personalization=personalization,
                                 alpha=0.85, max_iter=500)
        except nx.PowerIterationFailedConvergence:
            scores = {n: 1.0 / reversed_graph.number_of_nodes()
                      for n in reversed_graph.nodes()}
        return scores

    def _get_affected_slices(self, nf_node: str,
                              bilevel_dag: BiLevelCausalDAG) -> List[str]:
        """Return S-NSSAI values whose subgraphs contain the given NF node."""
        return [snssai for snssai, sg in bilevel_dag.level2_subgraphs.items()
                if nf_node in sg.nf_nodes]

    def _classify(self, top_node: str, top_score: float,
                  affected_slices: List[str],
                  bilevel_dag: BiLevelCausalDAG) -> RootCauseType:
        """
        NF-layer: top_node is shared across multiple slices AND score is high.
        Slice-layer: top_node affects only one slice while others sharing the
                     same NF remain healthy.
        """
        if top_score < self.nf_attribution_threshold:
            return RootCauseType.UNDETERMINED
        total_slices = len(bilevel_dag.level2_subgraphs)
        if total_slices == 0:
            return RootCauseType.NF_LAYER
        affected_fraction = len(affected_slices) / total_slices
        shared_nf_nodes = bilevel_dag.get_shared_nf_nodes()
        if top_node in shared_nf_nodes and affected_fraction > self.slice_isolation_threshold:
            return RootCauseType.NF_LAYER
        return RootCauseType.SLICE_LAYER

    def _confidence(self, top_score: float,
                    all_scores: Dict[str, float]) -> float:
        """Confidence = gap between top score and second-highest score."""
        sorted_scores = sorted(all_scores.values(), reverse=True)
        if len(sorted_scores) < 2:
            return top_score
        return top_score - sorted_scores[1]
