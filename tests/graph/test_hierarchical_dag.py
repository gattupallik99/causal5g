"""
Tests for causal5g.graph.hierarchical_dag -- Claim 2 four-domain graph.

Covers the domain-node add helpers, cross-domain edge recording, and the
granularity / graph accessors. Cross-domain edge recording attribute
semantics are exercised here too (complementing test_cross_domain.py which
tests the inferrer loop).
"""

from __future__ import annotations

import networkx as nx
import pytest

from causal5g.graph.bilevel_dag import BiLevelCausalDAG, NFNode
from causal5g.graph.hierarchical_dag import Domain, HierarchicalDAG
from causal5g.graph.topology_prior import TopologyPrior


@pytest.fixture
def hdag() -> HierarchicalDAG:
    prior = TopologyPrior(pfcp_bindings=[("smf-1", "upf-1")])
    core = BiLevelCausalDAG(topology_prior=prior)
    core.add_nf_node(NFNode(nf_id="smf-1", nf_type="SMF", instance_id="smf-1"))
    return HierarchicalDAG(core_dag=core)


class TestConstruction:
    def test_all_four_domains_initialized(self, hdag):
        for d in (Domain.RAN, Domain.TRANSPORT, Domain.CORE, Domain.CLOUD):
            assert isinstance(hdag.domain_graphs[d], nx.DiGraph)

    def test_core_graph_is_level1_of_bilevel(self, hdag):
        assert hdag.domain_graphs[Domain.CORE] is hdag.core_dag.level1_graph

    def test_cross_domain_graph_starts_empty(self, hdag):
        assert hdag.cross_domain_graph.number_of_edges() == 0


class TestAddDomainNodes:
    def test_add_ran_node_stores_kpis_and_domain(self, hdag):
        hdag.add_ran_node("gnb-1", "gNB", prb_utilization=0.82,
                          pdcp_retx_rate=0.04)
        n = hdag.domain_graphs[Domain.RAN].nodes["gnb-1"]
        assert n["node_type"] == "gNB"
        assert n["domain"] == Domain.RAN
        assert n["prb_utilization"] == pytest.approx(0.82)
        assert n["pdcp_retx_rate"] == pytest.approx(0.04)

    def test_add_transport_node_stores_interface_and_metrics(self, hdag):
        hdag.add_transport_node("n9-1", "N9", latency_ms=2.3,
                                jitter_ms=0.4, packet_loss_pct=0.01)
        n = hdag.domain_graphs[Domain.TRANSPORT].nodes["n9-1"]
        assert n["interface"] == "N9"
        assert n["domain"] == Domain.TRANSPORT
        assert n["latency_ms"] == pytest.approx(2.3)

    def test_add_cloud_node_maps_to_nf_instance(self, hdag):
        hdag.add_cloud_node("pod-amf-1", "pod",
                            nf_instance_id="amf-1",
                            cpu_throttle_pct=0.12,
                            memory_pressure_pct=0.55)
        n = hdag.domain_graphs[Domain.CLOUD].nodes["pod-amf-1"]
        assert n["resource_type"] == "pod"
        assert n["nf_instance_id"] == "amf-1"
        assert n["domain"] == Domain.CLOUD
        assert n["cpu_throttle_pct"] == pytest.approx(0.12)


class TestCrossDomainEdge:
    def test_add_cross_domain_edge_uses_prefixed_ids(self, hdag):
        hdag.add_cross_domain_edge(
            "pod-smf-1", Domain.CLOUD,
            "smf-1", Domain.CORE,
            ci_score=0.002, time_lag_ms=120,
        )
        src = "cloud::pod-smf-1"
        dst = "core::smf-1"
        assert hdag.cross_domain_graph.has_edge(src, dst)
        attrs = hdag.cross_domain_graph.edges[src, dst]
        assert attrs["ci_score"] == pytest.approx(0.002)
        assert attrs["time_lag_ms"] == 120
        assert attrs["src_domain"] == Domain.CLOUD
        assert attrs["dst_domain"] == Domain.CORE


class TestAccessors:
    def test_get_domain_graph_returns_configured_graph(self, hdag):
        assert hdag.get_domain_graph(Domain.RAN) is hdag.domain_graphs[Domain.RAN]
        assert hdag.get_domain_graph(Domain.CORE) is hdag.domain_graphs[Domain.CORE]

    def test_get_granularity_ms_matches_class_map(self, hdag):
        assert hdag.get_granularity_ms(Domain.RAN) == 100
        assert hdag.get_granularity_ms(Domain.TRANSPORT) == 500
        assert hdag.get_granularity_ms(Domain.CORE) == 1000
        assert hdag.get_granularity_ms(Domain.CLOUD) == 5000
