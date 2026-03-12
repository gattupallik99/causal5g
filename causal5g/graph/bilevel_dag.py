"""
causal5g.graph.bilevel_dag
==========================
Claim 1 — Bi-level causal DAG construction for cloud-native 5G SA core networks.

Level 1: NF-layer nodes (AMF, SMF, UPF, PCF, NRF, AUSF, UDM) with SBI-derived edges.
Level 2: Per-S-NSSAI slice subgraphs as projections of Level 1 NF nodes.

A single NF node may be shared across multiple slice subgraphs to represent
slice-multiplexed NF deployments.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import networkx as nx


@dataclass
class NFNode:
    """Represents a 5G Network Function node at Level 1 of the bi-level DAG."""
    nf_id: str                          # e.g. "smf-1", "upf-2"
    nf_type: str                        # AMF | SMF | UPF | PCF | NRF | AUSF | UDM
    instance_id: str
    shared_across_slices: Set[str] = field(default_factory=set)  # S-NSSAI values


@dataclass
class SliceSubgraph:
    """
    Level 2 projection: all NF nodes participating in a specific network slice
    identified by S-NSSAI. Nodes may be shared with other slice subgraphs.
    """
    snssai: str                         # e.g. "1:1" (eMBB), "1:2" (URLLC), "1:3" (mIoT)
    nf_nodes: List[str]                 # NF node IDs from Level 1
    dedicated_nf_nodes: List[str]       # NF nodes exclusive to this slice
    shared_nf_nodes: List[str]          # NF nodes shared with other slices


class BiLevelCausalDAG:
    """
    Bi-level causal directed acyclic graph (DAG) for 5G SA core network topology.

    Implements Claim 1 of Causal5G patent:
    - Level 1: NF-layer causal graph with SBI HTTP/2-derived edges
    - Level 2: Slice subgraph projections per S-NSSAI

    Parameters
    ----------
    topology_prior : TopologyPrior
        Structural prior constraining candidate causal edges to SBI
        producer-consumer pairs or PFCP session bindings.
    """

    def __init__(self, topology_prior=None):
        self.level1_graph: nx.DiGraph = nx.DiGraph()   # NF-layer DAG
        self.level2_subgraphs: Dict[str, SliceSubgraph] = {}  # keyed by S-NSSAI
        self.nf_nodes: Dict[str, NFNode] = {}
        self.topology_prior = topology_prior

    def add_nf_node(self, node: NFNode) -> None:
        """Add a Network Function node to the Level 1 graph."""
        self.nf_nodes[node.nf_id] = node
        self.level1_graph.add_node(node.nf_id, nf_type=node.nf_type,
                                   instance_id=node.instance_id)

    def add_sbi_edge(self, producer_nf_id: str, consumer_nf_id: str,
                     sbi_service: str, weight: float = 1.0) -> None:
        """
        Add a directed causal edge derived from an SBI HTTP/2 call sequence.

        Parameters
        ----------
        producer_nf_id : str
            NF exposing the SBI service (e.g. "smf-1")
        consumer_nf_id : str
            NF consuming the SBI service (e.g. "amf-1")
        sbi_service : str
            SBI operation name (e.g. "Nsmf_PDUSession_CreateSMContext")
        weight : float
            Conditional mutual information score from causal discovery
        """
        if self.topology_prior and not self.topology_prior.is_valid_sbi_edge(
                producer_nf_id, consumer_nf_id):
            raise ValueError(
                f"Edge {producer_nf_id} -> {consumer_nf_id} violates topology prior")
        self.level1_graph.add_edge(producer_nf_id, consumer_nf_id,
                                   sbi_service=sbi_service, weight=weight)

    def add_slice_subgraph(self, subgraph: SliceSubgraph) -> None:
        """Register a Level 2 slice subgraph projection for an S-NSSAI."""
        self.level2_subgraphs[subgraph.snssai] = subgraph
        for nf_id in subgraph.shared_nf_nodes:
            if nf_id in self.nf_nodes:
                self.nf_nodes[nf_id].shared_across_slices.add(subgraph.snssai)

    def get_shared_nf_nodes(self) -> List[str]:
        """Return NF node IDs shared across two or more slice subgraphs."""
        return [nf_id for nf_id, node in self.nf_nodes.items()
                if len(node.shared_across_slices) > 1]

    def get_slice_subgraph_view(self, snssai: str) -> nx.DiGraph:
        """Return a subgraph view of Level 1 filtered to a specific S-NSSAI."""
        if snssai not in self.level2_subgraphs:
            raise KeyError(f"S-NSSAI {snssai} not registered")
        nodes = self.level2_subgraphs[snssai].nf_nodes
        return self.level1_graph.subgraph(nodes)
