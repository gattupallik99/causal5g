"""
Tests for causal5g.telemetry.slice_kpi — Claim 1 per-S-NSSAI KPIs.
"""
import pytest
from causal5g.telemetry.slice_kpi import SliceKPICollector, SliceKPI


class TestSliceKPICollector:
    def test_ingest_and_get_latest(self, slice_kpi_collector, sample_slice_kpi):
        slice_kpi_collector.ingest(sample_slice_kpi)
        latest = slice_kpi_collector.get_latest("1:1")
        assert latest is not None
        assert latest.pdu_session_establishment_success_rate == pytest.approx(0.98)

    def test_get_latest_unknown_snssai(self, slice_kpi_collector):
        assert slice_kpi_collector.get_latest("9:99") is None

    def test_anomaly_detection_healthy(self, slice_kpi_collector, sample_slice_kpi):
        slice_kpi_collector.ingest(sample_slice_kpi)
        assert not slice_kpi_collector.detect_anomaly("1:1", threshold_psesr=0.95)

    def test_anomaly_detection_degraded(self, slice_kpi_collector):
        degraded = SliceKPI(
            snssai="1:2",
            timestamp_ms=1_700_000_000_000,
            window_ms=60_000,
            pdu_session_establishment_success_rate=0.80,  # below 0.95
            user_plane_latency_ms=45.0,
            packet_loss_ratio=0.05,
        )
        slice_kpi_collector.ingest(degraded)
        assert slice_kpi_collector.detect_anomaly("1:2", threshold_psesr=0.95)

    def test_time_series_extraction(self, slice_kpi_collector):
        base_ms = 1_700_000_000_000
        for i in range(5):
            kpi = SliceKPI(
                snssai="1:1",
                timestamp_ms=base_ms + i * 10_000,
                window_ms=60_000,
                pdu_session_establishment_success_rate=0.95 - i * 0.02,
                user_plane_latency_ms=5.0 + i,
                packet_loss_ratio=0.001,
            )
            slice_kpi_collector.ingest(kpi)
        series = slice_kpi_collector.get_time_series(
            "1:1", "user_plane_latency_ms", now_ms=base_ms + 60_000)
        assert len(series) == 5
        assert series[0] == pytest.approx(5.0)
