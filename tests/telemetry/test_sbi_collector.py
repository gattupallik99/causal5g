"""
Tests for causal5g.telemetry.sbi_collector — Claim 1 SBI telemetry.
"""
import pytest
from causal5g.telemetry.sbi_collector import SBICollector, SBICallRecord


class TestSBICollector:
    def test_ingest_record(self, sbi_collector, sample_sbi_record):
        sbi_collector.ingest(sample_sbi_record)
        assert len(sbi_collector._records) == 1

    def test_callback_invoked(self, sample_sbi_record):
        received = []
        collector = SBICollector(on_record=lambda r: received.append(r))
        collector.ingest(sample_sbi_record)
        assert len(received) == 1
        assert received[0].producer_nf_id == "smf-1"

    def test_call_graph_edges_deduplication(self, sbi_collector, sample_sbi_record):
        sbi_collector.ingest(sample_sbi_record)
        sbi_collector.ingest(sample_sbi_record)   # duplicate
        edges = sbi_collector.get_call_graph_edges()
        assert len(edges) == 1

    def test_call_graph_edge_content(self, sbi_collector, sample_sbi_record):
        sbi_collector.ingest(sample_sbi_record)
        edges = sbi_collector.get_call_graph_edges()
        assert edges[0] == ("smf-1", "amf-1", "Nsmf_PDUSession_CreateSMContext")

    def test_aggregate_metrics(self, sample_sbi_record):
        collector = SBICollector(window_ms=60_000)
        for i in range(10):
            r = SBICallRecord(
                timestamp_ms=1_700_000_000_000 + i * 1000,
                producer_nf_id="smf-1",
                consumer_nf_id="amf-1",
                sbi_service="Nsmf_PDUSession_CreateSMContext",
                http_method="POST",
                http_status=201 if i < 9 else 500,
                latency_ms=10.0 + i,
                snssai="1:1",
            )
            collector.ingest(r)
        now_ms = 1_700_000_000_000 + 10_000
        metrics = collector.aggregate_metrics("smf-1", now_ms=now_ms)
        assert metrics is not None
        assert metrics.error_rate == pytest.approx(0.1)
        assert metrics.request_rate > 0

    def test_aggregate_returns_none_for_unknown_nf(self, sbi_collector):
        metrics = sbi_collector.aggregate_metrics(
            "unknown-nf", now_ms=1_700_000_060_000)
        assert metrics is None
