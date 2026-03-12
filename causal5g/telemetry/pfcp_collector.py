"""
causal5g.telemetry.pfcp_collector
==================================
Claim 1 — PFCP session-level statistics from N4 interface sessions
between SMF and UPF instances (3GPP TS 29.244).

Captures per-PDU-session PFCP metrics used as causal edge inputs
in the bi-level DAG and as structural prior for SMF-UPF bindings.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PFCPSessionBinding:
    """
    Association between a PDU session and a PFCP session on the N4 interface.
    Used as a structural prior constraint in the bi-level causal DAG.
    """
    pdu_session_id: str
    supi: str               # Subscription Permanent Identifier
    snssai: str             # S-NSSAI e.g. "1:1"
    smf_id: str             # SMF instance managing this session
    upf_id: str             # UPF instance bound via PFCP
    seid: int               # Session Endpoint Identifier (PFCP)
    established_ms: int     # Timestamp of PFCP Session Establishment


@dataclass
class PFCPSessionStats:
    """
    Per-PFCP-session statistics reported via N4 Usage Report.
    Collected per PDU session per S-NSSAI.
    """
    seid: int
    snssai: str
    smf_id: str
    upf_id: str
    timestamp_ms: int
    # Packet/byte counters
    uplink_packets: int = 0
    downlink_packets: int = 0
    uplink_bytes: int = 0
    downlink_bytes: int = 0
    # Health indicators
    establishment_latency_ms: float = 0.0
    modification_latency_ms: float = 0.0
    rule_application_failures: int = 0     # PDR/FAR match failures
    session_drop_count: int = 0


@dataclass
class N4InterfaceMetrics:
    """Aggregated N4 interface health metrics for a specific SMF-UPF pair."""
    smf_id: str
    upf_id: str
    window_start_ms: int
    window_end_ms: int
    session_establishment_success_rate: float   # PSESR fraction
    avg_establishment_latency_ms: float
    avg_modification_latency_ms: float
    total_rule_failures: int
    active_session_count: int


class PFCPCollector:
    """
    Collects PFCP session statistics from N4 interface telemetry.

    Integration points:
    - UPF Usage Report IE (3GPP TS 29.244 Section 8.2.40)
    - SMF internal PFCP session state export
    - Open5GS / free5GC / OAI SMF Prometheus metrics

    Parameters
    ----------
    window_ms : int
        Aggregation window for N4 interface metrics (default 60000ms)
    """

    def __init__(self, window_ms: int = 60_000):
        self.window_ms = window_ms
        self._bindings: Dict[int, PFCPSessionBinding] = {}  # keyed by SEID
        self._stats: List[PFCPSessionStats] = []

    def register_binding(self, binding: PFCPSessionBinding) -> None:
        """Register a new PFCP session binding (on N4 Session Establishment)."""
        self._bindings[binding.seid] = binding

    def remove_binding(self, seid: int) -> None:
        """Remove a PFCP session binding (on N4 Session Deletion)."""
        self._bindings.pop(seid, None)

    def ingest_stats(self, stats: PFCPSessionStats) -> None:
        """Ingest a PFCP usage report from a UPF for a specific PDU session."""
        self._stats.append(stats)

    def get_active_bindings_for_snssai(self, snssai: str) -> List[PFCPSessionBinding]:
        """Return all active PFCP session bindings for a given S-NSSAI."""
        return [b for b in self._bindings.values() if b.snssai == snssai]

    def get_smf_upf_pairs(self) -> List[tuple]:
        """Return (smf_id, upf_id) pairs with active PFCP bindings."""
        return list({(b.smf_id, b.upf_id) for b in self._bindings.values()})

    def aggregate_n4_metrics(self, smf_id: str, upf_id: str,
                              now_ms: int) -> Optional[N4InterfaceMetrics]:
        """Aggregate N4 interface health metrics for an SMF-UPF pair."""
        window_start = now_ms - self.window_ms
        stats = [s for s in self._stats
                 if s.smf_id == smf_id and s.upf_id == upf_id
                 and s.timestamp_ms >= window_start]
        if not stats:
            return None
        active = len([b for b in self._bindings.values()
                      if b.smf_id == smf_id and b.upf_id == upf_id])
        est_latencies = [s.establishment_latency_ms for s in stats]
        mod_latencies = [s.modification_latency_ms for s in stats
                         if s.modification_latency_ms > 0]
        successes = len([s for s in stats if s.rule_application_failures == 0])
        return N4InterfaceMetrics(
            smf_id=smf_id, upf_id=upf_id,
            window_start_ms=window_start, window_end_ms=now_ms,
            session_establishment_success_rate=successes / len(stats),
            avg_establishment_latency_ms=sum(est_latencies) / len(est_latencies),
            avg_modification_latency_ms=sum(mod_latencies) / len(mod_latencies) if mod_latencies else 0.0,
            total_rule_failures=sum(s.rule_application_failures for s in stats),
            active_session_count=active,
        )
