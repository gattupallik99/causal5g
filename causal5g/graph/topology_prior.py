"""
causal5g.graph.topology_prior
=============================
Claim 1 — Topology structural prior constraining candidate causal edges
to pairs of nodes that share an SBI producer-consumer dependency or a
PFCP session binding.

Reduces causal discovery search space and encodes 3GPP domain knowledge.
"""

from __future__ import annotations
from typing import Dict, List, Set, Tuple


# 3GPP TS 23.501 standard SBI producer-consumer relationships
STANDARD_SBI_EDGES: Set[Tuple[str, str]] = {
    ("AMF", "SMF"),   # Namf -> Nsmf
    ("AMF", "AUSF"),  # Namf -> Nausf
    ("AMF", "UDM"),   # Namf -> Nudm
    ("AMF", "PCF"),   # Namf -> Npcf
    ("AMF", "NRF"),   # Namf -> Nnrf
    ("SMF", "UPF"),   # N4 PFCP (control plane)
    ("SMF", "PCF"),   # Nsmf -> Npcf
    ("SMF", "UDM"),   # Nsmf -> Nudm
    ("SMF", "NRF"),   # Nsmf -> Nnrf
    ("PCF", "UDM"),   # Npcf -> Nudm
    ("PCF", "NRF"),   # Npcf -> Nnrf
    ("AUSF", "UDM"),  # Nausf -> Nudm
}


class TopologyPrior:
    """
    Structural prior for the bi-level causal DAG.

    Constrains candidate causal edges in the causal discovery algorithm
    to pairs of nodes that share:
    - An SBI producer-consumer dependency (3GPP TS 23.501 / TS 29.500), or
    - A PFCP session binding on the N4 interface (3GPP TS 29.244)

    Parameters
    ----------
    custom_sbi_edges : list of (str, str), optional
        Additional SBI edges beyond the 3GPP standard set, e.g. from
        observed service mesh call graph data.
    pfcp_bindings : list of (str, str), optional
        SMF-UPF instance pairs with active PFCP session bindings.
    """

    def __init__(self,
                 custom_sbi_edges: List[Tuple[str, str]] = None,
                 pfcp_bindings: List[Tuple[str, str]] = None):
        self.allowed_nf_type_edges: Set[Tuple[str, str]] = set(STANDARD_SBI_EDGES)
        if custom_sbi_edges:
            self.allowed_nf_type_edges.update(custom_sbi_edges)
        self.pfcp_bindings: Set[Tuple[str, str]] = set(pfcp_bindings or [])
        # Instance-level allowed edges: (nf_id, nf_id)
        self._instance_edges: Set[Tuple[str, str]] = set()

    def register_instance_edge(self, src_nf_id: str, dst_nf_id: str) -> None:
        """Register a specific NF instance pair as a valid causal edge candidate."""
        self._instance_edges.add((src_nf_id, dst_nf_id))

    def is_valid_sbi_edge(self, src_nf_id: str, dst_nf_id: str,
                          nf_type_map: Dict[str, str] = None) -> bool:
        """
        Return True if the edge (src, dst) is permitted by the topology prior.

        Checks instance-level registry first, then NF-type-level SBI edges.
        """
        if (src_nf_id, dst_nf_id) in self._instance_edges:
            return True
        if nf_type_map:
            src_type = nf_type_map.get(src_nf_id, "")
            dst_type = nf_type_map.get(dst_nf_id, "")
            return (src_type, dst_type) in self.allowed_nf_type_edges
        return False

    def is_valid_pfcp_edge(self, smf_id: str, upf_id: str) -> bool:
        """Return True if an active PFCP session binding exists between SMF and UPF."""
        return (smf_id, upf_id) in self.pfcp_bindings

    def get_allowed_edges_for_node(self, nf_id: str) -> Set[str]:
        """Return all NF IDs that nf_id may have a causal edge to/from."""
        return {dst for src, dst in self._instance_edges if src == nf_id} | \
               {src for src, dst in self._instance_edges if dst == nf_id}
