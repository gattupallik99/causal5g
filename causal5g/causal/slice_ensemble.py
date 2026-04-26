"""
SliceEnsembleAttributor — Causal5G Day 18
Patent Claim 1: Bi-level causal DAG — Level 2 (slice sub-DAG) attribution layer.

This module implements the *second tier* of Claim 1's bi-level DAG.  Given a
root-cause NF already identified by the NF-layer (Level 1 / RCSM), it runs
attribution through every registered slice sub-DAG to produce:

  - per-slice path weights  (how strongly the fault propagates within each slice)
  - slice_breadth           (fraction of slices that carry the fault path)
  - isolation_type          (slice-isolated | all-slice-nf | infrastructure-wide)
  - ensemble_score          (0.7 × NF-layer score  +  0.3 × slice discriminant)

Key discriminating example (Day 18 target scenario):
  pcf_timeout  → slice_breadth = 0.67  (mIoT slice has no PCF → isolated)
  nrf_crash    → slice_breadth = 1.00  (shared NF → infrastructure-wide)

The breadth < 1.0 signal is Claim 1's proof that the bi-level DAG adds
discriminating power beyond the NF-layer alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from causal5g.slice_topology import get_stm, SHARED_NFS, SLICE_SPECIFIC_NFS, SliceTopologyManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PerSliceResult:
    """Attribution result for a single slice sub-DAG."""
    slice_id:     str
    label:        str
    nf_present:   bool    # root-cause NF appears in this slice's causal subgraph
    path_weight:  float   # sum of edge weights in the pruned ancestor subgraph
    node_count:   int
    edge_count:   int

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id":    self.slice_id,
            "label":       self.label,
            "nf_present":  self.nf_present,
            "path_weight": self.path_weight,
            "node_count":  self.node_count,
            "edge_count":  self.edge_count,
        }


@dataclass
class SliceAttribution:
    """
    Complete slice-layer attribution result for one fault.
    The ensemble_score is the authoritative output that consumers
    (e.g. a report generator or a downstream policy store) should use
    when both DAG levels are available.
    """
    root_cause_nf:    str
    nf_layer_score:   float
    per_slice:        list[PerSliceResult] = field(default_factory=list)

    # Aggregate slice metrics
    n_slices_total:   int   = 0
    n_slices_affected: int  = 0
    slice_breadth:    float = 0.0   # n_affected / n_total

    # Discriminant: "how well does the slice layer distinguish this fault?"
    slice_discriminant: float = 0.0  # ∈ [0, 1]; 1 = perfectly isolating signal

    # Fault classification from slice topology
    isolation_type: str = "unknown"
    # "slice-isolated"       – root cause NF absent from ≥1 slice
    # "all-slice-nf"         – slice-specific NF but present in every slice
    # "infrastructure-wide"  – shared NF (nrf, ausf, udr), affects all by design

    # Combined score
    ensemble_score: float = 0.0
    # 0.7 × nf_layer_score  +  0.3 × slice_discriminant

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_cause_nf":     self.root_cause_nf,
            "nf_layer_score":    self.nf_layer_score,
            "per_slice":         [r.to_dict() for r in self.per_slice],
            "n_slices_total":    self.n_slices_total,
            "n_slices_affected": self.n_slices_affected,
            "slice_breadth":     self.slice_breadth,
            "slice_discriminant": self.slice_discriminant,
            "isolation_type":    self.isolation_type,
            "ensemble_score":    self.ensemble_score,
        }


# ---------------------------------------------------------------------------
# SliceEnsembleAttributor
# ---------------------------------------------------------------------------

class SliceEnsembleAttributor:
    """
    Runs Level-2 (slice sub-DAG) attribution over all registered slices.

    Patent Claim 1 — bi-level DAG:
      Level 1:  NF-layer attribution via RCSM (composite score).
      Level 2:  Slice sub-DAG attribution via SliceTopologyManager pruning.

    The two levels are fused into an ensemble_score.  More importantly the
    slice_breadth and isolation_type expose *discriminating power* that the
    NF-layer alone cannot provide:

        NRF crash   → breadth 1.0, infrastructure-wide
        PCF timeout → breadth 0.67, slice-isolated (mIoT has no PCF)

    Parameters
    ----------
    stm : SliceTopologyManager | None
        If None the module-level singleton from get_stm() is used.
    nf_weight : float
        Weight assigned to the NF-layer score in the ensemble (default 0.7).
    slice_weight : float
        Weight assigned to the slice discriminant (default 0.3).
    """

    _NF_WEIGHT:    float = 0.7
    _SLICE_WEIGHT: float = 0.3

    def __init__(
        self,
        stm: SliceTopologyManager | None = None,
        nf_weight:    float = 0.7,
        slice_weight: float = 0.3,
    ) -> None:
        self._stm          = stm or get_stm()
        self._nf_weight    = nf_weight
        self._slice_weight = slice_weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attribute(
        self,
        root_cause_nf:  str,
        nf_layer_score: float,
        dag_edges:      list[tuple[str, str]] | None = None,
    ) -> SliceAttribution:
        """
        Run Level-2 attribution for a single root-cause NF.

        Parameters
        ----------
        root_cause_nf  : NF identifier (lower-case, e.g. "pcf")
        nf_layer_score : composite score from RCSM (Level 1)
        dag_edges      : optional live DAG edges from GrangerPCFusion to
                         intersect with topology-allowed edges (passed
                         through to SliceTopologyManager.prune_for_fault)

        Returns
        -------
        SliceAttribution with per-slice breakdown + ensemble score.
        """
        slices = self._stm.list_slices()
        if not slices:
            logger.warning("[SEA] No slices registered — returning trivial attribution")
            return SliceAttribution(
                root_cause_nf=root_cause_nf,
                nf_layer_score=nf_layer_score,
                ensemble_score=round(self._nf_weight * nf_layer_score, 4),
                isolation_type="no-slices",
            )

        per_slice: list[PerSliceResult] = []

        for sc in slices:
            pruned = self._stm.prune_for_fault(
                faulted_nf=root_cause_nf,
                slice_id=sc.slice_id,
                dag_edges=dag_edges,
            )
            path_weight = sum(pruned.edge_weights.values()) if pruned.edge_weights else 0.0

            # nf_present: does this root-cause NF actually *belong* to this slice?
            # Note: prune_for_fault always adds faulted_nf to relevant_nodes even
            # when it is absent from the slice (so we cannot use `root_cause_nf in
            # pruned.nodes`). We must check the slice config directly.
            #   - A shared NF (nrf, ausf, udr) is always present in every slice.
            #   - A slice-specific NF is present only if it is in sc.nf_set.
            nf_present = (root_cause_nf in SHARED_NFS) or (root_cause_nf in sc.nf_set)

            per_slice.append(PerSliceResult(
                slice_id    = sc.slice_id,
                label       = sc.label,
                nf_present  = nf_present,
                path_weight = round(path_weight, 4),
                node_count  = len(pruned.nodes),
                edge_count  = len(pruned.edges),
            ))

        n_affected    = sum(1 for r in per_slice if r.nf_present)
        n_total       = len(per_slice)
        slice_breadth = n_affected / n_total if n_total else 0.0

        # Isolation classification
        if root_cause_nf in SHARED_NFS:
            isolation_type = "infrastructure-wide"
        elif slice_breadth < 1.0:
            isolation_type = "slice-isolated"
        else:
            isolation_type = "all-slice-nf"

        # Slice discriminant:
        #   ∈ [0, 1]; maximises at breadth = 0 or 1.0 (clear signal),
        #   minimises at breadth = 0.5 (ambiguous).
        #   Formula: |breadth - 0.5| × 2
        slice_discriminant = abs(slice_breadth - 0.5) * 2

        ensemble_score = (
            self._nf_weight    * min(nf_layer_score, 1.0) +
            self._slice_weight * slice_discriminant
        )

        result = SliceAttribution(
            root_cause_nf     = root_cause_nf,
            nf_layer_score    = nf_layer_score,
            per_slice         = per_slice,
            n_slices_total    = n_total,
            n_slices_affected = n_affected,
            slice_breadth     = round(slice_breadth, 4),
            slice_discriminant= round(slice_discriminant, 4),
            isolation_type    = isolation_type,
            ensemble_score    = round(ensemble_score, 4),
        )

        logger.info(
            "[SEA] %s | nf_score=%.4f | breadth=%.2f (%d/%d) | type=%s | ensemble=%.4f",
            root_cause_nf, nf_layer_score,
            slice_breadth, n_affected, n_total,
            isolation_type, ensemble_score,
        )
        return result

    def sweep(
        self,
        scenarios: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Run attribute() for a list of scenarios and return a flat results list.

        Each item in `scenarios` must have:
          - "scenario"       : str  (e.g. "pcf_timeout")
          - "expected_nf"    : str  (ground truth)
          - "detected_nf"    : str  (NF-layer top-ranked NF)
          - "nf_layer_score" : float
          - "dag_edges"      : list[tuple[str,str]] | None  (optional)

        Returns a list of dicts merging scenario metadata with SliceAttribution.
        """
        results = []
        for sc in scenarios:
            attr = self.attribute(
                root_cause_nf  = sc["detected_nf"],
                nf_layer_score = sc["nf_layer_score"],
                dag_edges      = sc.get("dag_edges"),
            )
            results.append({
                "scenario":          sc["scenario"],
                "expected_nf":       sc["expected_nf"],
                "detected_nf":       sc["detected_nf"],
                "nf_layer_score":    sc["nf_layer_score"],
                "slice_breadth":     attr.slice_breadth,
                "n_slices_affected": attr.n_slices_affected,
                "n_slices_total":    attr.n_slices_total,
                "isolation_type":    attr.isolation_type,
                "slice_discriminant":attr.slice_discriminant,
                "ensemble_score":    attr.ensemble_score,
                "match":             sc["expected_nf"] == sc["detected_nf"],
                "per_slice":         [r.to_dict() for r in attr.per_slice],
            })
        return results
