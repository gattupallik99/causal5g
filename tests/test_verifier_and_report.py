"""Tests for RemediationVerifier and RCAReport — Day 10"""
import pytest
from causal5g.remediation.verifier import (
    verify_remediation, outcome_to_signal, VerificationOutcome,
    CLEARED_THRESHOLD, MIN_IMPROVEMENT, _state as verifier_state
)
from causal5g.rca.report import (
    generate_report, RCAStatus, Severity, _store as report_store,
    _score_to_severity, ReportStore
)

# ── Verifier tests ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_verifier():
    verifier_state.results.clear()
    verifier_state.total_verified = 0
    verifier_state.total_cleared = 0
    verifier_state.total_escalated = 0
    yield

def test_cleared_when_post_below_threshold():
    result = verify_remediation("nrf_crash","nrf",0.85, CLEARED_THRESHOLD - 0.01, "r1")
    assert result.outcome == VerificationOutcome.CLEARED
    assert result.escalate is False

def test_persisting_when_improvement_below_min():
    result = verify_remediation("nrf_crash","nrf",0.85, 0.80, "r2")
    assert result.outcome == VerificationOutcome.PERSISTING
    assert result.escalate is True

def test_degraded_when_partial_improvement():
    result = verify_remediation("smf_crash","smf",0.85, 0.85 - MIN_IMPROVEMENT - 0.01, "r3")
    assert result.outcome == VerificationOutcome.DEGRADED
    assert result.escalate is False

def test_inconclusive_when_no_post_score():
    result = verify_remediation("amf_crash","amf",0.75, None, "r4")
    assert result.outcome == VerificationOutcome.INCONCLUSIVE
    assert result.escalate is False

def test_improvement_computed_correctly():
    result = verify_remediation("pcf_timeout","pcf",0.80,0.55,"r5")
    assert abs(result.improvement - 0.25) < 0.001

def test_slice_id_stored():
    result = verify_remediation("nrf_crash","nrf",0.85,0.20,"r6",slice_id="1-000001")
    assert result.slice_id == "1-000001"

def test_counters_increment():
    verify_remediation("nrf_crash","nrf",0.85,0.20,"r7")  # cleared
    verify_remediation("nrf_crash","nrf",0.85,0.83,"r8")  # persisting
    assert verifier_state.total_verified == 2
    assert verifier_state.total_cleared == 1
    assert verifier_state.total_escalated == 1

def test_outcome_signals():
    assert outcome_to_signal(VerificationOutcome.CLEARED)      == 1.0
    assert outcome_to_signal(VerificationOutcome.PERSISTING)   == 0.0
    assert outcome_to_signal(VerificationOutcome.DEGRADED)     == 0.6
    assert outcome_to_signal(VerificationOutcome.INCONCLUSIVE) == 0.5
    assert outcome_to_signal(VerificationOutcome.TIMEOUT)      == 0.2

def test_all_five_fault_scenarios():
    for scenario, nf in [("nrf_crash","nrf"),("amf_crash","amf"),
                          ("smf_crash","smf"),("pcf_timeout","pcf"),("udm_crash","udm")]:
        r = verify_remediation(scenario, nf, 0.85, 0.20, f"r-{scenario}")
        assert r.outcome == VerificationOutcome.CLEARED

# ── RCA Report tests ──────────────────────────────────────────────────────

@pytest.fixture
def fresh_store():
    return ReportStore()

def test_generate_report_returns_report(fresh_store):
    r = generate_report("nrf_crash","nrf",0.85)
    assert r.report_id is not None
    assert r.fault_scenario == "nrf_crash"
    assert r.root_cause_nf == "nrf"

def test_severity_critical_above_085():
    assert _score_to_severity(0.90) == Severity.CRITICAL
    assert _score_to_severity(0.85) == Severity.CRITICAL

def test_severity_high():
    assert _score_to_severity(0.75) == Severity.HIGH

def test_severity_medium():
    assert _score_to_severity(0.60) == Severity.MEDIUM

def test_severity_low():
    assert _score_to_severity(0.40) == Severity.LOW

def test_causal_chain_populated():
    r = generate_report("nrf_crash","nrf",0.85)
    assert len(r.causal_chain) >= 1
    assert r.causal_chain[0].nf == "nrf"
    assert r.causal_chain[0].rank == 1

def test_causal_chain_ranked():
    r = generate_report("smf_crash","smf",0.80)
    ranks = [s.rank for s in r.causal_chain]
    assert ranks == list(range(1, len(ranks)+1))

def test_recommendations_not_empty():
    r = generate_report("nrf_crash","nrf",0.85)
    assert len(r.recommendations) >= 1

def test_remediation_fields_stored():
    r = generate_report("amf_crash","amf",0.82,
                         remediation_action="restart_pod",
                         remediation_target="amf")
    assert r.remediation_action == "restart_pod"
    assert r.remediation_target == "amf"

def test_status_defaults_to_open():
    r = generate_report("udm_crash","udm",0.75)
    assert r.status == RCAStatus.OPEN

def test_slice_id_stored_in_report():
    r = generate_report("amf_crash","amf",0.80,slice_id="2-000001")
    assert r.slice_id == "2-000001"

def test_summary_contains_key_fields():
    r = generate_report("pcf_timeout","pcf",0.78)
    assert "pcf" in r.summary.lower()
    assert "pcf_timeout" in r.summary

def test_report_store_get(fresh_store):
    r = generate_report("nrf_crash","nrf",0.85)
    fetched = report_store.get(r.report_id)
    assert fetched is not None
    assert fetched.report_id == r.report_id

def test_report_store_update_status():
    r = generate_report("nrf_crash","nrf",0.85)
    updated = report_store.update_status(r.report_id, RCAStatus.REMEDIATED, "cleared")
    assert updated.status == RCAStatus.REMEDIATED
    assert updated.verification_outcome == "cleared"

def test_all_fault_scenarios_generate_reports():
    for scenario, nf in [("nrf_crash","nrf"),("amf_crash","amf"),
                          ("smf_crash","smf"),("pcf_timeout","pcf"),("udm_crash","udm")]:
        r = generate_report(scenario, nf, 0.80)
        assert r.root_cause_nf == nf
        assert len(r.causal_chain) >= 1
