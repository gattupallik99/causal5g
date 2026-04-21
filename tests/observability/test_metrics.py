"""
Day 15 regression coverage for ``causal5g.observability.metrics``.

Assertions read directly from the private CollectorRegistry via
:func:`causal5g.observability.metrics.get_sample` rather than
pattern-matching against the text-exposition format. The exposition
format has drifted in small ways across ``prometheus_client`` 0.19
-> 0.25 (``_created`` sub-samples, ``_total`` suffix handling,
OpenMetrics vs Prometheus text). Reading from the registry makes
these tests version-independent.

The tests assert:

1. Every exported helper increments / observes the correct metric
   with the correct labels.
2. The private registry is hermetic — reset_for_tests() fully clears
   state so counters do not bleed between tests.
3. Bounded label cardinality: unknown label values collapse to
   ``"other"`` instead of inflating cardinality.
4. The /metrics exposition renders text/plain Prometheus format.
5. The fallback path (prometheus_client missing) returns no-op for
   every helper and a well-formed empty body from render().

Patent context: these metrics are the operational-readiness evidence
for claims 1-4 (composite score gauge, attribution latency, report
severity counter, remediation-action counter, confidence-gate
decision counter).
"""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def metrics():
    """Fresh metrics module with a clean registry for each test."""
    from causal5g.observability import metrics as mod
    mod.reset_for_tests()
    yield mod
    mod.reset_for_tests()


# ---------------------------------------------------------------------------
# Registry lifecycle
# ---------------------------------------------------------------------------

class TestRegistryLifecycle:

    def test_is_available_when_prometheus_installed(self, metrics):
        # prometheus_client is a test dep — it must be importable.
        assert metrics.is_available() is True

    def test_reset_clears_counters(self, metrics):
        metrics.record_scrape("smf")
        metrics.record_scrape("smf")
        assert metrics.get_sample(
            "causal5g_telemetry_scrapes_total", nf="smf") == 2.0

        metrics.reset_for_tests()
        # After reset the counter family is re-created with zero samples.
        assert metrics.get_sample(
            "causal5g_telemetry_scrapes_total", nf="smf") is None

    def test_render_returns_text_plain_content_type(self, metrics):
        body, ct = metrics.render()
        assert "text/plain" in ct
        # Exposition body must start with a HELP line for at least one
        # metric family, regardless of which version of the format.
        assert b"# HELP causal5g_" in body


# ---------------------------------------------------------------------------
# Counter and gauge contracts
# ---------------------------------------------------------------------------

class TestScrapeCounter:

    def test_per_nf_label_incremented(self, metrics):
        metrics.record_scrape("smf")
        metrics.record_scrape("smf")
        metrics.record_scrape("upf")   # upf is NOT a tracked NF → "other"
        assert metrics.get_sample(
            "causal5g_telemetry_scrapes_total", nf="smf") == 2.0
        assert metrics.get_sample(
            "causal5g_telemetry_scrapes_total", nf="other") == 1.0

    def test_count_parameter(self, metrics):
        metrics.record_scrape("amf", count=5)
        assert metrics.get_sample(
            "causal5g_telemetry_scrapes_total", nf="amf") == 5.0


class TestAttributionLatency:

    def test_histogram_observes_via_context_manager(self, metrics):
        import time as _t
        with metrics.time_attribution():
            _t.sleep(0.002)
        assert metrics.get_sample("causal5g_attribution_seconds_count") == 1.0
        sum_val = metrics.get_sample("causal5g_attribution_seconds_sum")
        assert sum_val is not None and sum_val > 0.0

    def test_direct_observe(self, metrics):
        metrics.observe_attribution_seconds(0.042)
        assert metrics.get_sample("causal5g_attribution_seconds_count") == 1.0
        # 0.042 falls into the 0.05 bucket.
        assert metrics.get_sample(
            "causal5g_attribution_seconds_bucket", le="0.05") == 1.0


class TestCompositeScoreGauge:

    def test_latest_value_wins(self, metrics):
        metrics.observe_composite("smf", 0.5)
        metrics.observe_composite("smf", 0.9)
        assert metrics.get_sample(
            "causal5g_composite_score", nf="smf") == 0.9

    def test_unknown_nf_collapses_to_other(self, metrics):
        metrics.observe_composite("gcp-nf", 0.7)
        assert metrics.get_sample(
            "causal5g_composite_score", nf="other") == 0.7


class TestReportCounter:

    def test_severity_label_bound(self, metrics):
        metrics.record_report("CRITICAL")
        metrics.record_report("CRITICAL")
        metrics.record_report("HIGH")
        metrics.record_report("LOW")
        metrics.record_report("INFO")
        metrics.record_report("WHATEVER")   # → "other"
        assert metrics.get_sample(
            "causal5g_rca_reports_total", severity="CRITICAL") == 2.0
        assert metrics.get_sample(
            "causal5g_rca_reports_total", severity="HIGH") == 1.0
        assert metrics.get_sample(
            "causal5g_rca_reports_total", severity="INFO") == 1.0
        assert metrics.get_sample(
            "causal5g_rca_reports_total", severity="other") == 1.0


class TestRemediationCounters:

    def test_action_and_status_labels(self, metrics):
        metrics.record_remediation("restart_pod", "success")
        metrics.record_remediation("restart_pod", "success")
        metrics.record_remediation("restart_pod", "failed")
        metrics.record_remediation("drain_node", "timeout")
        assert metrics.get_sample(
            "causal5g_remediation_actions_total",
            action="restart_pod", status="success") == 2.0
        assert metrics.get_sample(
            "causal5g_remediation_actions_total",
            action="restart_pod", status="failed") == 1.0
        assert metrics.get_sample(
            "causal5g_remediation_actions_total",
            action="drain_node", status="timeout") == 1.0

    def test_unknown_action_collapses(self, metrics):
        metrics.record_remediation("quantum_tunnel", "success")
        assert metrics.get_sample(
            "causal5g_remediation_actions_total",
            action="other", status="success") == 1.0

    def test_observe_remediation_seconds(self, metrics):
        metrics.observe_remediation_seconds("restart_pod", 0.12)
        assert metrics.get_sample(
            "causal5g_remediation_seconds_count",
            action="restart_pod") == 1.0

    def test_time_remediation_context(self, metrics):
        import time as _t
        with metrics.time_remediation("scale_deployment"):
            _t.sleep(0.002)
        assert metrics.get_sample(
            "causal5g_remediation_seconds_count",
            action="scale_deployment") == 1.0


class TestGateDecisionCounter:

    def test_executed_vs_skipped(self, metrics):
        metrics.record_gate_decision("executed")
        metrics.record_gate_decision("skipped")
        metrics.record_gate_decision("skipped")
        metrics.record_gate_decision("skipped")
        assert metrics.get_sample(
            "causal5g_confidence_gate_decisions_total",
            decision="executed") == 1.0
        assert metrics.get_sample(
            "causal5g_confidence_gate_decisions_total",
            decision="skipped") == 3.0

    def test_unknown_decision_collapses(self, metrics):
        metrics.record_gate_decision("deferred")
        assert metrics.get_sample(
            "causal5g_confidence_gate_decisions_total",
            decision="other") == 1.0


class TestPipelineGauges:

    def test_setters_round_trip(self, metrics):
        metrics.set_pipeline_cycles(120)
        metrics.set_analyses_total(12)
        metrics.set_events_ingested(1200)
        metrics.set_buffer_fill_pct(55.5)
        metrics.set_active_faults(1)
        assert metrics.get_sample("causal5g_pipeline_cycles_total") == 120.0
        assert metrics.get_sample("causal5g_analyses_total") == 12.0
        assert metrics.get_sample("causal5g_events_ingested_total") == 1200.0
        assert metrics.get_sample("causal5g_buffer_fill_pct") == 55.5
        assert metrics.get_sample("causal5g_active_faults") == 1.0


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------

class TestExposition:

    def test_every_metric_family_is_registered(self, metrics):
        # Touch every metric so every family has at least one sample.
        metrics.record_scrape("smf")
        metrics.observe_composite("smf", 0.9)
        metrics.observe_attribution_seconds(0.01)
        metrics.record_report("CRITICAL")
        metrics.record_remediation("restart_pod", "success")
        metrics.observe_remediation_seconds("restart_pod", 0.2)
        metrics.record_gate_decision("executed")
        metrics.set_pipeline_cycles(1)
        metrics.set_analyses_total(1)
        metrics.set_events_ingested(1)
        metrics.set_buffer_fill_pct(1.0)
        metrics.set_active_faults(1)

        # Family names from the registry (not from the text format).
        # Counter families surface without the ``_total`` suffix.
        families = metrics.metric_family_names()
        expected = {
            # counters (minus _total suffix)
            "causal5g_telemetry_scrapes",
            "causal5g_rca_reports",
            "causal5g_remediation_actions",
            "causal5g_confidence_gate_decisions",
            # histograms
            "causal5g_attribution_seconds",
            "causal5g_remediation_seconds",
            # gauges
            "causal5g_composite_score",
            "causal5g_pipeline_cycles_total",
            "causal5g_analyses_total",
            "causal5g_events_ingested_total",
            "causal5g_buffer_fill_pct",
            "causal5g_active_faults",
        }
        missing = expected - families
        assert not missing, f"missing metric families: {missing}"

    def test_render_body_contains_known_metric(self, metrics):
        metrics.record_scrape("smf")
        body, _ = metrics.render()
        text = body.decode()
        # Must contain a # HELP line for our scrape counter family,
        # regardless of whether it is suffixed with _total or not.
        assert "causal5g_telemetry_scrapes" in text


# ---------------------------------------------------------------------------
# Fallback path (prometheus_client missing)
# ---------------------------------------------------------------------------

class TestFallbackPath:
    """If prometheus_client import fails, every helper must be a
    no-op and render() must return an empty body without raising."""

    def test_helpers_are_noops_without_prometheus(self, monkeypatch):
        # Block the lazy import inside _MetricsRegistry.ensure by
        # setting prometheus_client to None in sys.modules (importlib
        # will raise ImportError when the factory tries to import it).
        monkeypatch.setitem(sys.modules, "prometheus_client", None)

        # Re-import metrics with the blocked module path.
        if "causal5g.observability.metrics" in sys.modules:
            del sys.modules["causal5g.observability.metrics"]
        if "causal5g.observability" in sys.modules:
            del sys.modules["causal5g.observability"]
        metrics_mod = importlib.import_module("causal5g.observability.metrics")

        assert metrics_mod.is_available() is False
        # Every helper must tolerate being called.
        metrics_mod.record_scrape("smf")
        metrics_mod.observe_composite("smf", 0.9)
        metrics_mod.observe_attribution_seconds(0.01)
        metrics_mod.record_report("CRITICAL")
        metrics_mod.record_remediation("restart_pod", "success")
        metrics_mod.observe_remediation_seconds("restart_pod", 0.1)
        metrics_mod.record_gate_decision("executed")
        metrics_mod.set_pipeline_cycles(1)
        metrics_mod.set_analyses_total(1)
        metrics_mod.set_events_ingested(1)
        metrics_mod.set_buffer_fill_pct(1.0)
        metrics_mod.set_active_faults(1)
        with metrics_mod.time_attribution():
            pass
        with metrics_mod.time_remediation("restart_pod"):
            pass
        body, ct = metrics_mod.render()
        assert body == b""
        assert "text/plain" in ct
        # Lookup helpers are safe too.
        assert metrics_mod.get_sample("causal5g_pipeline_cycles_total") is None
        assert metrics_mod.metric_family_names() == set()

        # Cleanup: restore the real module for subsequent tests.
        monkeypatch.delitem(sys.modules, "prometheus_client", raising=False)
        if "causal5g.observability.metrics" in sys.modules:
            del sys.modules["causal5g.observability.metrics"]
        if "causal5g.observability" in sys.modules:
            del sys.modules["causal5g.observability"]
        importlib.import_module("causal5g.observability.metrics")
