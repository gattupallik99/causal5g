"""
Tests for causal5g.rca.report — Claim 1 root cause report generation.
"""
import json
import pytest

from causal5g.causal.attribution import AttributionResult, RootCauseType
from causal5g.rca.report import RootCauseReporter, RootCauseReport


@pytest.fixture
def sample_attribution_result():
    return AttributionResult(
        root_cause_type=RootCauseType.NF_LAYER,
        root_cause_node="smf-1",
        attribution_score=0.72,
        affected_snssais=["1:1", "1:2"],
        implicated_pfcp_seid=100001,
        implicated_sbi_service="Nsmf_PDUSession_CreateSMContext",
        confidence=0.45,
    )


class TestRootCauseReporter:
    def test_report_generated(self, sample_attribution_result):
        reporter = RootCauseReporter()
        report = reporter.generate(sample_attribution_result)
        assert isinstance(report, RootCauseReport)
        assert report.root_cause_node == "smf-1"
        assert report.root_cause_type == RootCauseType.NF_LAYER

    def test_report_id_increments(self, sample_attribution_result):
        reporter = RootCauseReporter()
        r1 = reporter.generate(sample_attribution_result)
        r2 = reporter.generate(sample_attribution_result)
        assert r1.report_id != r2.report_id

    def test_report_contains_required_claim1_fields(self, sample_attribution_result):
        """Verify all Claim 1 required report fields are present."""
        reporter = RootCauseReporter()
        report = reporter.generate(sample_attribution_result)
        assert report.root_cause_type is not None
        assert report.attribution_score > 0
        assert len(report.affected_snssais) > 0
        assert report.implicated_pfcp_seid == 100001
        assert report.implicated_sbi_service == "Nsmf_PDUSession_CreateSMContext"

    def test_to_json_valid(self, sample_attribution_result):
        reporter = RootCauseReporter()
        report = reporter.generate(sample_attribution_result)
        parsed = json.loads(report.to_json())
        assert parsed["root_cause_type"] == "nf_layer"
        assert parsed["root_cause_node"] == "smf-1"
        assert "1:1" in parsed["affected_snssais"]

    def test_custom_prefix(self, sample_attribution_result):
        reporter = RootCauseReporter(report_id_prefix="test-rca")
        report = reporter.generate(sample_attribution_result)
        assert report.report_id.startswith("test-rca-")
