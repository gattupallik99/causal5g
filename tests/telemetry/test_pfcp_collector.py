"""
Tests for causal5g.telemetry.pfcp_collector — Claim 1 PFCP N4 telemetry.
"""
import pytest
from causal5g.telemetry.pfcp_collector import (
    PFCPCollector, PFCPSessionBinding, PFCPSessionStats
)


class TestPFCPCollector:
    def test_register_binding(self, pfcp_collector, sample_pfcp_binding):
        pfcp_collector.register_binding(sample_pfcp_binding)
        assert 100001 in pfcp_collector._bindings

    def test_remove_binding(self, pfcp_collector, sample_pfcp_binding):
        pfcp_collector.register_binding(sample_pfcp_binding)
        pfcp_collector.remove_binding(100001)
        assert 100001 not in pfcp_collector._bindings

    def test_get_active_bindings_for_snssai(self, pfcp_collector, sample_pfcp_binding):
        pfcp_collector.register_binding(sample_pfcp_binding)
        bindings = pfcp_collector.get_active_bindings_for_snssai("1:1")
        assert len(bindings) == 1
        assert bindings[0].snssai == "1:1"

    def test_get_active_bindings_wrong_snssai(self, pfcp_collector, sample_pfcp_binding):
        pfcp_collector.register_binding(sample_pfcp_binding)
        bindings = pfcp_collector.get_active_bindings_for_snssai("1:2")
        assert len(bindings) == 0

    def test_get_smf_upf_pairs(self, pfcp_collector, sample_pfcp_binding):
        pfcp_collector.register_binding(sample_pfcp_binding)
        pairs = pfcp_collector.get_smf_upf_pairs()
        assert ("smf-1", "upf-1") in pairs

    def test_ingest_stats_and_aggregate(self, pfcp_collector, sample_pfcp_binding):
        pfcp_collector.register_binding(sample_pfcp_binding)
        for i in range(5):
            stats = PFCPSessionStats(
                seid=100001 + i,
                snssai="1:1",
                smf_id="smf-1",
                upf_id="upf-1",
                timestamp_ms=1_700_000_000_000 + i * 1000,
                establishment_latency_ms=5.0 + i,
                modification_latency_ms=2.0,
                rule_application_failures=0,
            )
            pfcp_collector.ingest_stats(stats)
        now_ms = 1_700_000_060_000
        metrics = pfcp_collector.aggregate_n4_metrics("smf-1", "upf-1", now_ms)
        assert metrics is not None
        assert metrics.session_establishment_success_rate == 1.0
        assert metrics.avg_establishment_latency_ms == pytest.approx(7.0)
