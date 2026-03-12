"""
causal5g.graph.hierarchical_dag
================================
Claim 2 — Four-domain hierarchical graph spanning:
  - RAN domain    : gNB, CU/DU-split nodes + radio KPIs
  - Transport domain : N2, N3, N9 backhaul links + latency/jitter
  - Core domain   : bi-level NF + slice subgraph DAG (Claim 1)
  - Cloud infra   : VM, container, Kubernetes pod nodes per NF instance

Causal discovery runs within each domain independently, then cross-domain
edges are inferred by conditional independence tests on boundary metrics.
"""

from __future__ import annotations
from enum import Enum
from typing import Dict, List, Optional
import networkx as nx

from causal5g.graph.bilevel_dag import BiLevelCausalDAG


class Domain(str, Enum):
    RAN = "ran"
    TRANSPORT = "transport"
    CORE = "core"
    CLOUD = "cloud"


class HierarchicalDAG:
    """
    Four-domain hierarchical causal graph for Claim 2.

    Each domain maintains an independent causal graph with domain-appropriate
    telemetry time granularities. Cross-domain causal edges are inferred
    separately and stored in cross_domain_graph.

    Parameters
    ----------
    core_dag : BiLevelCausalDAG
        Pre-constructed bi-level DAG from Claim 1 for the core domain.
    """

    DOMAIN_GRANULARITY_MS = {
        Domain.RAN: 100,        # 100ms for radio KPIs
        Domain.TRANSPORT: 500,  # 500ms for backhaul metrics
        Domain.CORE: 1000,      # 1s for NF/slice KPIs
        Domain.CLOUD: 5000,     # 5s for infrastructure metrics
    }

    def __init__(self, core_dag: BiLevelCausalDAG):
        self.domain_graphs: Dict[Domain, nx.DiGraph] = {
            Domain.RAN: nx.DiGraph(),
            Domain.TRANSPORT: nx.DiGraph(),
            Domain.CORE: core_dag.level1_graph,
            Domain.CLOUD: nx.DiGraph(),
        }
        self.core_dag = core_dag
        self.cross_domain_graph: nx.DiGraph = nx.DiGraph()

    def add_ran_node(self, node_id: str, node_type: str, **kpis) -> None:
        """
        Add a RAN domain node (gNB, CU, DU) with radio KPIs.

        Key KPIs: prb_utilization (%), pdcp_retx_rate (%)
        """
        self.domain_graphs[Domain.RAN].add_node(
            node_id, node_type=node_type, domain=Domain.RAN, **kpis)

    def add_transport_node(self, node_id: str, interface: str, **metrics) -> None:
        """
        Add a transport domain node for N2/N3/N9 backhaul links.

        Key metrics: latency_ms, jitter_ms, packet_loss_pct
        """
        self.domain_graphs[Domain.TRANSPORT].add_node(
            node_id, interface=interface, domain=Domain.TRANSPORT, **metrics)

    def add_cloud_node(self, node_id: str, resource_type: str,
                       nf_instance_id: str, **metrics) -> None:
        """
        Add a cloud infrastructure node (VM, container, K8s pod) mapped to an NF.

        Key metrics: cpu_throttle_pct, memory_pressure_pct, pod_eviction_count
        """
        self.domain_graphs[Domain.CLOUD].add_node(
            node_id, resource_type=resource_type,
            nf_instance_id=nf_instance_id, domain=Domain.CLOUD, **metrics)

    def add_cross_domain_edge(self, src_node: str, src_domain: Domain,
                               dst_node: str, dst_domain: Domain,
                               ci_score: float, time_lag_ms: int) -> None:
        """
        Add an inferred cross-domain causal edge between domain boundary metrics.

        Parameters
        ----------
        ci_score : float
            Conditional independence test score (lower = stronger dependency)
        time_lag_ms : int
            Causal propagation delay between domains in milliseconds
        """
        self.cross_domain_graph.add_edge(
            f"{src_domain.value}::{src_node}",
            f"{dst_domain.value}::{dst_node}",
            ci_score=ci_score,
            time_lag_ms=time_lag_ms,
            src_domain=src_domain,
            dst_domain=dst_domain,
        )

    def get_domain_graph(self, domain: Domain) -> nx.DiGraph:
        return self.domain_graphs[domain]

    def get_granularity_ms(self, domain: Domain) -> int:
        return self.DOMAIN_GRANULARITY_MS[domain]
