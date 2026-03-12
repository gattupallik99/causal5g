"""
Tests for causal5g.causal.attribution — Claim 1 root cause isolation.
"""
import pytest
import networkx as nx

from causal5g.causal.attribution import (
    CausalAttributionScorer, RootCauseType
)


class TestCausalAttributionScorer:
    def test_nf_layer_classification(self, two_slice_dag):
        """
        When the highest-scoring node (amf-1) is shared across both slices,
        the root cause should be classified as NF_LAYER.
        """
        graph = nx.DiGraph()
        graph.add_edge("amf-1", "smf-1", weight=0.9)
        graph.add_edge("amf-1", "pcf-1", weight=0.8)
        graph.add_edge("smf-1", "upf-1", weight=0.5)

        scorer = CausalAttributionScorer(nf_attribution_threshold=0.1)
        result = scorer.score(graph, two_slice_dag, anomaly_node="smf-1")
        assert result.root_cause_type == RootCauseType.NF_LAYER

    def test_attribution_score_nonnegative(self, two_slice_dag):
        graph = nx.DiGraph()
        graph.add_edge("smf-1", "upf-1", weight=0.7)
        scorer = CausalAttributionScorer()
        result = scorer.score(graph, two_slice_dag, anomaly_node="upf-1")
        assert result.attribution_score >= 0.0

    def test_empty_graph_returns_undetermined(self, two_slice_dag):
        graph = nx.DiGraph()
        scorer = CausalAttributionScorer()
        result = scorer.score(graph, two_slice_dag, anomaly_node="smf-1")
        assert result.root_cause_type == RootCauseType.UNDETERMINED

    def test_affected_snssais_populated(self, two_slice_dag):
        graph = nx.DiGraph()
        graph.add_edge("amf-1", "smf-1", weight=0.9)
        scorer = CausalAttributionScorer(nf_attribution_threshold=0.01)
        result = scorer.score(graph, two_slice_dag, anomaly_node="smf-1")
        # amf-1 is shared across both slices
        assert len(result.affected_snssais) >= 1

    def test_confidence_is_positive(self, two_slice_dag):
        graph = nx.DiGraph()
        graph.add_edge("amf-1", "smf-1", weight=0.9)
        graph.add_edge("pcf-1", "smf-1", weight=0.3)
        scorer = CausalAttributionScorer(nf_attribution_threshold=0.01)
        result = scorer.score(graph, two_slice_dag, anomaly_node="smf-1")
        assert result.confidence >= 0.0
