"""
causal5g.telemetry.sbi_collector
=================================
Claim 1 — SBI HTTP/2 call sequence capture via 5G core service mesh.

Collects NF-layer performance metrics from 3GPP Nnf service operations
and constructs the SBI call graph used as the topology structural prior.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional
import time


@dataclass
class SBICallRecord:
    """A single captured SBI HTTP/2 service call between two NFs."""
    timestamp_ms: int
    producer_nf_id: str
    consumer_nf_id: str
    sbi_service: str        # e.g. "Nsmf_PDUSession_CreateSMContext"
    http_method: str        # POST | GET | PATCH | DELETE
    http_status: int        # 200 | 201 | 400 | 500 etc.
    latency_ms: float
    snssai: Optional[str] = None   # S-NSSAI if slice-specific


@dataclass
class SBIMetrics:
    """Aggregated NF-layer SBI metrics over a time window."""
    nf_id: str
    window_start_ms: int
    window_end_ms: int
    request_rate: float             # requests/sec
    error_rate: float               # fraction of non-2xx responses
    p99_latency_ms: float
    service_call_counts: Dict[str, int] = field(default_factory=dict)


class SBICollector:
    """
    Captures SBI HTTP/2 call sequences from the 5G core service mesh.

    Supports integration with:
    - Istio/Envoy service mesh (via Prometheus metrics + access logs)
    - eBPF-based HTTP/2 capture (via 5GC-Observer / Cilium Hubble)
    - 3GPP Nnf_OAM telemetry streams

    Parameters
    ----------
    window_ms : int
        Sliding window size for metric aggregation (default 60000ms = 1min)
    on_record : callable, optional
        Callback invoked for each captured SBI call record
    """

    def __init__(self, window_ms: int = 60_000,
                 on_record: Callable[[SBICallRecord], None] = None):
        self.window_ms = window_ms
        self.on_record = on_record
        self._records: List[SBICallRecord] = []

    def ingest(self, record: SBICallRecord) -> None:
        """Ingest a single SBI call record from the service mesh."""
        self._records.append(record)
        if self.on_record:
            self.on_record(record)

    def get_call_graph_edges(self) -> List[tuple]:
        """
        Return (producer_nf_id, consumer_nf_id, sbi_service) tuples
        observed in the current window, for topology prior construction.
        """
        seen = set()
        edges = []
        for r in self._records:
            key = (r.producer_nf_id, r.consumer_nf_id, r.sbi_service)
            if key not in seen:
                seen.add(key)
                edges.append(key)
        return edges

    def aggregate_metrics(self, nf_id: str,
                          now_ms: int = None) -> Optional[SBIMetrics]:
        """Aggregate SBI metrics for a specific NF over the sliding window."""
        now_ms = now_ms or int(time.time() * 1000)
        window_start = now_ms - self.window_ms
        records = [r for r in self._records
                   if r.producer_nf_id == nf_id
                   and r.timestamp_ms >= window_start]
        if not records:
            return None
        latencies = [r.latency_ms for r in records]
        errors = [r for r in records if r.http_status >= 400]
        service_counts: Dict[str, int] = {}
        for r in records:
            service_counts[r.sbi_service] = service_counts.get(r.sbi_service, 0) + 1
        window_secs = self.window_ms / 1000
        return SBIMetrics(
            nf_id=nf_id,
            window_start_ms=window_start,
            window_end_ms=now_ms,
            request_rate=len(records) / window_secs,
            error_rate=len(errors) / len(records),
            p99_latency_ms=sorted(latencies)[int(len(latencies) * 0.99)],
            service_call_counts=service_counts,
        )
