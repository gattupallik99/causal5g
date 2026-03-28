"""
SliceTopologyManager — Causal5G Day 9
Implements slice-topology-aware causal graph pruning for 5G SA core.
Patent claims 1-2: NSSAI-aware causal graph construction and per-slice
fault isolation so GrangerPCFusion does not conflate faults across slices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 3GPP slice types (SST values per TS 23.501)
# ---------------------------------------------------------------------------

SST_LABELS = {
    1: "eMBB",    # Enhanced Mobile Broadband
    2: "URLLC",   # Ultra-Reliable Low-Latency
    3: "mIoT",    # Massive IoT
    4: "V2X",     # Vehicle-to-Everything
}

# NFs that are always shared across all slices (non-slice-specific)
SHARED_NFS = {"nrf", "ausf", "udr"}

# NFs that are instantiated per-slice (slice-specific)
SLICE_SPECIFIC_NFS = {"amf", "smf", "pcf", "udm", "upf"}

# Causal edges that exist only within the same slice
INTRA_SLICE_EDGES = {
    ("amf", "smf"),
    ("smf", "upf"),
    ("pcf", "smf"),
    ("udm", "amf"),
    ("smf", "pcf"),
}

# Causal edges that cross slice boundaries (shared NF → slice NF)
CROSS_SLICE_EDGES = {
    ("nrf", "amf"),
    ("nrf", "smf"),
    ("nrf", "pcf"),
    ("nrf", "udm"),
    ("nrf", "upf"),
    ("ausf", "amf"),
    ("udr", "udm"),
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SliceConfig:
    """Represents a single 5G network slice."""
    slice_id:   str           # S-NSSAI string e.g. "1-000001"
    sst:        int           # Slice/Service Type (1-4)
    sd:         str           # Slice Differentiator hex string
    nf_set:     set[str]      # NFs instantiated for this slice
    label:      str = ""

    def __post_init__(self):
        if not self.label:
            self.label = SST_LABELS.get(self.sst, f"SST-{self.sst}")

    @classmethod
    def from_nssai(cls, nssai: str, nf_set: set[str] | None = None) -> "SliceConfig":
        """Parse S-NSSAI string '1-000001' into a SliceConfig."""
        parts = nssai.split("-", 1)
        sst = int(parts[0])
        sd  = parts[1] if len(parts) > 1 else "000000"
        if nf_set is None:
            nf_set = SLICE_SPECIFIC_NFS.copy()
        return cls(slice_id=nssai, sst=sst, sd=sd, nf_set=nf_set)


@dataclass
class TopologyGraph:
    """
    Pruned causal graph for a specific slice or global view.
    Nodes = NF names, edges = (cause, effect) tuples with weight.
    """
    slice_id:   str | None                       # None = global
    nodes:      set[str]              = field(default_factory=set)
    edges:      list[tuple[str, str]] = field(default_factory=list)
    edge_weights: dict[tuple[str, str], float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "nodes":    sorted(self.nodes),
            "edges":    [{"cause": e[0], "effect": e[1],
                          "weight": self.edge_weights.get(e, 1.0)} for e in self.edges],
        }


# ---------------------------------------------------------------------------
# SliceTopologyManager
# ---------------------------------------------------------------------------

class SliceTopologyManager:
    """
    Manages NSSAI slice configs and produces pruned causal graphs.

    Core responsibilities (patent claims 1-2):
    1. Maintain a registry of active slice configs.
    2. Given a fault NF and (optionally) a target slice, prune the
       global causal DAG to only edges relevant to that slice context.
    3. Prevent cross-slice causal leakage: an AMF fault in eMBB slice
       must not appear as a causal predecessor in the URLLC DAG.
    """

    def __init__(self) -> None:
        self._slices: dict[str, SliceConfig] = {}
        self._default_slices_loaded = False
        self._load_defaults()

    # ------------------------------------------------------------------
    # Slice registry
    # ------------------------------------------------------------------

    def _load_defaults(self) -> None:
        """
        Pre-load a representative 3-slice topology matching
        the Free5GC lab environment used in Causal5G demos.
        """
        defaults = [
            SliceConfig(slice_id="1-000001", sst=1, sd="000001",
                        nf_set={"amf", "smf", "pcf", "udm", "upf"},
                        label="eMBB"),
            SliceConfig(slice_id="2-000001", sst=2, sd="000001",
                        nf_set={"amf", "smf", "pcf", "udm", "upf"},
                        label="URLLC"),
            SliceConfig(slice_id="3-000001", sst=3, sd="000001",
                        nf_set={"amf", "smf", "udm", "upf"},
                        label="mIoT"),
        ]
        for sc in defaults:
            self._slices[sc.slice_id] = sc
        self._default_slices_loaded = True
        logger.info("[STM] Loaded %d default slice configs", len(defaults))

    def register_slice(self, nssai: str, nf_set: set[str] | None = None) -> SliceConfig:
        sc = SliceConfig.from_nssai(nssai, nf_set)
        self._slices[nssai] = sc
        logger.info("[STM] Registered slice %s (%s)", nssai, sc.label)
        return sc

    def remove_slice(self, nssai: str) -> bool:
        removed = nssai in self._slices
        self._slices.pop(nssai, None)
        return removed

    def get_slice(self, nssai: str) -> SliceConfig | None:
        return self._slices.get(nssai)

    def list_slices(self) -> list[SliceConfig]:
        return list(self._slices.values())

    # ------------------------------------------------------------------
    # Graph pruning (core patent logic)
    # ------------------------------------------------------------------

    def build_global_graph(self) -> TopologyGraph:
        """
        Global causal graph: all NFs and all edges.
        Used by GrangerPCFusion when no slice context is available.
        """
        g = TopologyGraph(slice_id=None)
        g.nodes = SHARED_NFS | SLICE_SPECIFIC_NFS
        g.edges = list(INTRA_SLICE_EDGES | CROSS_SLICE_EDGES)
        g.edge_weights = {e: 1.0 for e in g.edges}
        return g

    def build_slice_graph(self, slice_id: str) -> TopologyGraph:
        """
        Slice-pruned causal graph (patent claim 1).

        Rules:
        - Include all shared NFs (nrf, ausf, udr) regardless of slice.
        - Include only slice-specific NFs that are in slice.nf_set.
        - Include intra-slice edges only between nodes in this slice.
        - Include cross-slice edges only where the sink NF is in this slice.
        - Assign reduced edge weights for cross-slice edges (0.5) vs
          intra-slice edges (1.0) to reflect isolation priority.
        """
        sc = self._slices.get(slice_id)
        if sc is None:
            logger.warning("[STM] Unknown slice %s — falling back to global graph", slice_id)
            return self.build_global_graph()

        active_nfs = SHARED_NFS | sc.nf_set
        g = TopologyGraph(slice_id=slice_id)
        g.nodes = active_nfs

        for (cause, effect) in INTRA_SLICE_EDGES:
            if cause in active_nfs and effect in active_nfs:
                g.edges.append((cause, effect))
                g.edge_weights[(cause, effect)] = 1.0

        for (cause, effect) in CROSS_SLICE_EDGES:
            if cause in active_nfs and effect in active_nfs:
                g.edges.append((cause, effect))
                g.edge_weights[(cause, effect)] = 0.5   # shared NF → lower isolation weight

        logger.debug("[STM] Slice %s graph: %d nodes, %d edges",
                     slice_id, len(g.nodes), len(g.edges))
        return g

    def prune_for_fault(
        self,
        faulted_nf:  str,
        slice_id:    str | None = None,
        dag_edges:   list[tuple[str, str]] | None = None,
    ) -> TopologyGraph:
        """
        Given a faulted NF and optional slice context, return the
        minimal subgraph relevant for causal root cause analysis.

        Algorithm (patent claim 2 — NSSAI-aware DAG pruning):
        1. Start with the slice-pruned (or global) graph.
        2. Identify ancestor nodes of faulted_nf via BFS on reversed edges.
        3. Keep only nodes reachable to faulted_nf and their connecting edges.
        4. If dag_edges supplied (from GrangerPCFusion), intersect with
           the topology-allowed edges to prevent spurious causal paths.
        """
        base = self.build_slice_graph(slice_id) if slice_id else self.build_global_graph()

        # Override edges with live DAG if provided
        candidate_edges = dag_edges if dag_edges is not None else base.edges

        # Build reverse adjacency: effect → set of causes
        rev: dict[str, set[str]] = {}
        for (cause, effect) in candidate_edges:
            rev.setdefault(effect, set()).add(cause)

        # BFS to find all ancestors of faulted_nf
        ancestors: set[str] = set()
        queue = [faulted_nf]
        while queue:
            node = queue.pop()
            for parent in rev.get(node, set()):
                if parent not in ancestors:
                    ancestors.add(parent)
                    queue.append(parent)

        relevant_nodes = ancestors | {faulted_nf}

        # Filter edges to those within the relevant subgraph
        pruned_edges = [
            (c, e) for (c, e) in candidate_edges
            if c in relevant_nodes and e in relevant_nodes
        ]

        g = TopologyGraph(slice_id=slice_id)
        g.nodes = relevant_nodes
        g.edges = pruned_edges
        # Inherit weights from base, falling back to 1.0
        g.edge_weights = {
            e: base.edge_weights.get(e, 1.0) for e in pruned_edges
        }

        logger.info("[STM] Fault prune: nf=%s slice=%s → %d nodes %d edges",
                    faulted_nf, slice_id, len(g.nodes), len(g.edges))
        return g

    # ------------------------------------------------------------------
    # Cross-slice leakage detection
    # ------------------------------------------------------------------

    def detect_cross_slice_leakage(
        self,
        fault_slice_id: str,
        candidate_root_causes: list[str],
    ) -> dict[str, Any]:
        """
        Patent claim 2 support: determine whether any candidate root
        causes belong to a different slice (leakage indicator).

        Returns a dict with leakage flags per NF.
        """
        fault_sc = self._slices.get(fault_slice_id)
        if fault_sc is None:
            return {"error": f"Unknown slice {fault_slice_id}"}

        in_slice:    list[str] = []
        out_of_slice: list[str] = []
        shared:       list[str] = []

        for nf in candidate_root_causes:
            if nf in SHARED_NFS:
                shared.append(nf)
            elif nf in fault_sc.nf_set:
                in_slice.append(nf)
            else:
                out_of_slice.append(nf)

        return {
            "fault_slice": fault_slice_id,
            "in_slice_causes":     in_slice,
            "out_of_slice_causes": out_of_slice,
            "shared_nf_causes":    shared,
            "leakage_detected":    len(out_of_slice) > 0,
        }

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_count": len(self._slices),
            "slices": [
                {
                    "slice_id": sc.slice_id,
                    "sst":      sc.sst,
                    "sd":       sc.sd,
                    "label":    sc.label,
                    "nf_set":   sorted(sc.nf_set),
                }
                for sc in self._slices.values()
            ],
        }


# Module-level singleton — imported by frg.py and the slice router
_stm = SliceTopologyManager()


def get_stm() -> SliceTopologyManager:
    return _stm
