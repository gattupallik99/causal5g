"""
GrangerPCFusion feedback recalibration — Causal5G Day 10
Patch file: adds recalibrate() and supporting methods to GrangerPCFusion.

HOW TO APPLY:
  Add the contents of the GrangerPCFusionRecalibrator mixin into your
  existing GrangerPCFusion class in causal/engine/granger.py, OR
  import and instantiate GrangerPCFusionRecalibrator alongside it.

Patent claim 4: remediation outcome signals fed back from RAE to
recalibrate causal edge weights in the live DAG.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recalibration configuration
# ---------------------------------------------------------------------------

@dataclass
class RecalibrationConfig:
    """Tunable parameters for the feedback recalibration algorithm."""
    # Learning rate: how much each feedback signal shifts an edge weight
    learning_rate:      float = 0.05
    # Decay factor: older feedback counts less (per recalibration cycle)
    temporal_decay:     float = 0.90
    # Minimum edge weight floor — prevents edges dropping to zero
    weight_floor:       float = 0.10
    # Maximum edge weight ceiling
    weight_ceiling:     float = 2.00
    # Minimum number of feedback entries before recalibration fires
    min_feedback_count: int   = 2
    # Maximum feedback entries to retain per (fault_scenario, edge) key
    max_history_per_edge: int = 50


# ---------------------------------------------------------------------------
# Feedback entry (mirrors what RAE._push_feedback() produces)
# ---------------------------------------------------------------------------

@dataclass
class FeedbackEntry:
    fault_scenario: str
    root_cause_nf:  str
    action:         str
    outcome:        float       # 0.0 = failed, 1.0 = succeeded
    timestamp:      float
    slice_id:       str | None  = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeedbackEntry":
        return cls(
            fault_scenario=d["fault_scenario"],
            root_cause_nf=d["root_cause_nf"],
            action=d.get("action", "unknown"),
            outcome=float(d["outcome"]),
            timestamp=float(d.get("timestamp") or time.time()),
            slice_id=d.get("slice_id"),
        )


# ---------------------------------------------------------------------------
# Recalibration state
# ---------------------------------------------------------------------------

@dataclass
class RecalibrationState:
    """
    Tracks edge weight adjustments across recalibration cycles.
    edge_weights: {(cause_nf, effect_nf): float} — current adjusted weights
    feedback_history: {fault_scenario: [FeedbackEntry]}
    cycle_count: total recalibration cycles executed
    last_recalibrated_at: unix timestamp
    """
    edge_weights:           dict[tuple[str, str], float] = field(default_factory=dict)
    feedback_history:       dict[str, list[FeedbackEntry]] = field(default_factory=lambda: defaultdict(list))
    cycle_count:            int   = 0
    last_recalibrated_at:   float = 0.0
    total_entries_consumed: int   = 0


# ---------------------------------------------------------------------------
# GrangerPCFusionRecalibrator
# ---------------------------------------------------------------------------

class GrangerPCFusionRecalibrator:
    """
    Feedback recalibration engine for GrangerPCFusion.

    Patent claim 4 — closed feedback loop:
      RAE remediates fault → outcome signal (0/1) pushed to feedback_buffer
      → recalibrate() ingests buffer → adjusts causal edge weights
      → next GrangerPCFusion DAG construction uses updated weights
      → more accurate root cause isolation on subsequent faults

    Algorithm:
      For each feedback entry:
        1. Identify the causal edges that implicate root_cause_nf
           (edges where root_cause_nf is the cause node)
        2. If outcome=1.0 (remediation succeeded): REINFORCE those edges
           (the causal attribution was correct — increase weight)
        3. If outcome=0.0 (remediation failed): PENALISE those edges
           (the root cause attribution may have been wrong — decrease weight)
        4. Apply temporal decay to existing weights (older signals fade)
        5. Clamp weights to [floor, ceiling]

    Integration:
      Call recalibrate(feedback_buffer) after each RAE remediation cycle.
      Call get_edge_weight(cause, effect) when building the causal DAG
      to retrieve the recalibration-adjusted weight for each edge.
    """

    def __init__(self, config: RecalibrationConfig | None = None) -> None:
        self.config = config or RecalibrationConfig()
        self.state  = RecalibrationState()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recalibrate(self, feedback_buffer: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Ingest RAE feedback buffer and update edge weights.

        Args:
            feedback_buffer: list of dicts from RAE._push_feedback()
                Each dict: {fault_scenario, root_cause_nf, action,
                            outcome, timestamp, slice_id}

        Returns:
            Summary dict with recalibration statistics.
        """
        if len(feedback_buffer) < self.config.min_feedback_count:
            logger.debug("[Recal] Skipped — only %d entries (min=%d)",
                         len(feedback_buffer), self.config.min_feedback_count)
            return {"skipped": True, "reason": "insufficient_feedback",
                    "entries": len(feedback_buffer),
                    "min_required": self.config.min_feedback_count}

        entries = [FeedbackEntry.from_dict(d) for d in feedback_buffer]

        # Apply temporal decay to all existing weights first
        self._apply_decay()

        # Process each feedback entry
        adjustments: dict[tuple[str, str], float] = {}
        for entry in entries:
            self._process_entry(entry, adjustments)
            self.state.feedback_history[entry.fault_scenario].append(entry)
            # Bound per-scenario history
            if len(self.state.feedback_history[entry.fault_scenario]) > self.config.max_history_per_edge:
                self.state.feedback_history[entry.fault_scenario] = \
                    self.state.feedback_history[entry.fault_scenario][-self.config.max_history_per_edge:]

        # Apply accumulated adjustments
        for edge, delta in adjustments.items():
            old = self.state.edge_weights.get(edge, 1.0)
            new = max(self.config.weight_floor,
                      min(self.config.weight_ceiling, old + delta))
            self.state.edge_weights[edge] = new
            logger.debug("[Recal] Edge %s→%s: %.3f → %.3f (Δ%.3f)",
                         edge[0], edge[1], old, new, delta)

        self.state.cycle_count            += 1
        self.state.last_recalibrated_at    = time.time()
        self.state.total_entries_consumed += len(entries)

        summary = {
            "skipped":           False,
            "cycle":             self.state.cycle_count,
            "entries_consumed":  len(entries),
            "edges_adjusted":    len(adjustments),
            "timestamp":         self.state.last_recalibrated_at,
            "edge_weights":      {f"{c}→{e}": round(w, 4)
                                  for (c, e), w in self.state.edge_weights.items()},
        }
        logger.info("[Recal] Cycle %d — %d entries, %d edges adjusted",
                    self.state.cycle_count, len(entries), len(adjustments))
        return summary

    def get_edge_weight(self, cause: str, effect: str) -> float:
        """
        Return the recalibration-adjusted weight for a causal edge.
        Falls back to 1.0 (neutral) if the edge has never been adjusted.
        """
        return self.state.edge_weights.get((cause, effect), 1.0)

    def get_all_weights(self) -> dict[tuple[str, str], float]:
        """Return a copy of all current edge weights."""
        return dict(self.state.edge_weights)

    def get_stats(self) -> dict[str, Any]:
        """Return recalibration statistics for the /remediate/feedback endpoint."""
        weights = self.state.edge_weights
        return {
            "cycle_count":            self.state.cycle_count,
            "total_entries_consumed": self.state.total_entries_consumed,
            "last_recalibrated_at":   self.state.last_recalibrated_at,
            "edges_tracked":          len(weights),
            "reinforced_edges":       sum(1 for w in weights.values() if w > 1.0),
            "penalised_edges":        sum(1 for w in weights.values() if w < 1.0),
            "config": {
                "learning_rate":    self.config.learning_rate,
                "temporal_decay":   self.config.temporal_decay,
                "weight_floor":     self.config.weight_floor,
                "weight_ceiling":   self.config.weight_ceiling,
                "min_feedback_count": self.config.min_feedback_count,
            },
            "edge_weights": {
                f"{c}→{e}": round(w, 4)
                for (c, e), w in sorted(weights.items())
            },
        }

    def reset(self) -> None:
        """Reset all recalibration state (useful for testing)."""
        self.state = RecalibrationState()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_decay(self) -> None:
        """
        Apply temporal decay to all existing edge weights.
        Weights drift back toward 1.0 over time, preventing stale
        recalibrations from dominating future fault diagnoses.
        """
        decay = self.config.temporal_decay
        for edge in list(self.state.edge_weights.keys()):
            w = self.state.edge_weights[edge]
            # Decay toward neutral weight of 1.0
            self.state.edge_weights[edge] = 1.0 + (w - 1.0) * decay

    def _process_entry(
        self,
        entry: FeedbackEntry,
        adjustments: dict[tuple[str, str], float],
    ) -> None:
        """
        Compute weight adjustments for edges implicating entry.root_cause_nf.

        Reinforcement: outcome=1.0 → the causal attribution was correct.
            Increase weights on edges where root_cause_nf is the CAUSE.
        Penalisation: outcome=0.0 → attribution may be wrong.
            Decrease weights on same edges.

        The adjustment magnitude scales with learning_rate.
        """
        lr     = self.config.learning_rate
        nf     = entry.root_cause_nf
        # outcome=1.0 → +lr (reinforce), outcome=0.0 → -lr (penalise)
        delta  = lr * (2.0 * entry.outcome - 1.0)

        # Identify edges where this NF is the root cause (cause node)
        # We adjust all outgoing edges from root_cause_nf, since the
        # causal attribution pointed to this NF as the origin.
        affected_edges = self._edges_from_nf(nf)

        for edge in affected_edges:
            adjustments[edge] = adjustments.get(edge, 0.0) + delta

        # Also adjust the self-loop proxy (NF → NF) as a scalar
        # representing the overall reliability of this NF's causal signal
        self_edge = (nf, nf)
        adjustments[self_edge] = adjustments.get(self_edge, 0.0) + delta * 0.5

    def _edges_from_nf(self, nf: str) -> list[tuple[str, str]]:
        """
        Return all known causal edges where `nf` is the cause.
        Uses a hardcoded 5G NF topology — in production this would
        query SliceTopologyManager for the live slice graph.
        """
        # 5G SA core causal graph — cause → effects
        NF_OUTGOING: dict[str, list[str]] = {
            "nrf":  ["amf", "smf", "pcf", "udm", "upf"],
            "ausf": ["amf"],
            "udr":  ["udm"],
            "amf":  ["smf"],
            "smf":  ["upf", "pcf"],
            "pcf":  ["smf"],
            "udm":  ["amf"],
            "upf":  [],
        }
        targets = NF_OUTGOING.get(nf, [])
        return [(nf, t) for t in targets]


# ---------------------------------------------------------------------------
# Module-level singleton — imported by frg.py and slice_router.py
# ---------------------------------------------------------------------------

_recalibrator = GrangerPCFusionRecalibrator()


def get_recalibrator() -> GrangerPCFusionRecalibrator:
    return _recalibrator
