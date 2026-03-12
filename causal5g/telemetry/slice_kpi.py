"""
causal5g.telemetry.slice_kpi
=============================
Claim 1 — Per-S-NSSAI slice KPI measurement.

Collects PDU session establishment success rate (PSESR), user-plane
latency, and packet loss ratio per S-NSSAI, as required by Claim 1.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SliceKPI:
    """
    Key Performance Indicators for a single network slice instance.
    Measured per S-NSSAI over a sliding time window.
    """
    snssai: str
    timestamp_ms: int
    window_ms: int

    # Claim 1 mandatory KPIs
    pdu_session_establishment_success_rate: float   # PSESR [0.0, 1.0]
    user_plane_latency_ms: float                    # one-way UPF latency
    packet_loss_ratio: float                        # fraction [0.0, 1.0]

    # Extended KPIs
    active_pdu_sessions: int = 0
    pdu_session_setup_attempts: int = 0
    pdu_session_setup_failures: int = 0
    throughput_mbps: float = 0.0


class SliceKPICollector:
    """
    Collects and aggregates per-S-NSSAI KPIs.

    Integration points:
    - 3GPP TS 28.552 (5G NR Management, KPIs)
    - NWDAF Nnwdaf_AnalyticsInfo service (TS 23.288)
    - UPF GTP-U measurement probes
    - Prometheus metrics from SMF/UPF exporters

    Parameters
    ----------
    snssai_list : list of str
        S-NSSAI values to monitor (e.g. ["1:1", "1:2", "1:3"])
    window_ms : int
        KPI aggregation window (default 60000ms)
    """

    def __init__(self, snssai_list: List[str], window_ms: int = 60_000):
        self.snssai_list = snssai_list
        self.window_ms = window_ms
        self._kpi_history: Dict[str, List[SliceKPI]] = {s: [] for s in snssai_list}

    def ingest(self, kpi: SliceKPI) -> None:
        """Ingest a KPI measurement for a specific S-NSSAI."""
        if kpi.snssai not in self._kpi_history:
            self._kpi_history[kpi.snssai] = []
        self._kpi_history[kpi.snssai].append(kpi)

    def get_latest(self, snssai: str) -> Optional[SliceKPI]:
        """Return the most recent KPI snapshot for an S-NSSAI."""
        history = self._kpi_history.get(snssai, [])
        return history[-1] if history else None

    def get_time_series(self, snssai: str, metric: str,
                        now_ms: int) -> List[float]:
        """
        Return a time-ordered list of a specific KPI metric for an S-NSSAI
        within the current sliding window.

        Parameters
        ----------
        metric : str
            Attribute name on SliceKPI, e.g. 'pdu_session_establishment_success_rate'
        """
        window_start = now_ms - self.window_ms
        return [
            getattr(k, metric)
            for k in self._kpi_history.get(snssai, [])
            if k.timestamp_ms >= window_start
        ]

    def detect_anomaly(self, snssai: str,
                       threshold_psesr: float = 0.95) -> bool:
        """Simple threshold-based anomaly trigger on PSESR."""
        latest = self.get_latest(snssai)
        if latest is None:
            return False
        return latest.pdu_session_establishment_success_rate < threshold_psesr
