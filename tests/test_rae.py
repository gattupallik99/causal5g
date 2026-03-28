"""
Tests for Remediation Action Engine (RAE) — Day 9
Covers: confidence gating, action selection, fallback, feedback push, stats.
"""

import asyncio
import pytest
from api.rae import (
    trigger_remediation,
    _rae_state,
    _select_action,
    ACTION_POLICY,
    CONFIDENCE_THRESHOLD,
    ActionType,
    RemediationStatus,
    RAEState,
)


# Reset RAE state before each test to avoid cross-test contamination
@pytest.fixture(autouse=True)
def reset_state():
    _rae_state.history.clear()
    _rae_state.feedback_buffer.clear()
    _rae_state.total_triggered = 0
    _rae_state.total_succeeded = 0
    _rae_state.total_skipped = 0
    yield


# ---------------------------------------------------------------------------
# Action policy selection
# ---------------------------------------------------------------------------

def test_select_preferred_action():
    p = _select_action("nrf_crash", attempt=0)
    assert p["action"] == ActionType.RESTART_POD
    assert p["target"] == "nrf"


def test_select_fallback_action():
    p = _select_action("nrf_crash", attempt=1)
    assert p["action"] == ActionType.NOTIFY_OPERATOR


def test_select_beyond_fallback_clamps():
    # attempt=99 should clamp to last available
    p = _select_action("nrf_crash", attempt=99)
    assert p["action"] == ActionType.NOTIFY_OPERATOR


def test_default_policy_for_unknown_fault():
    p = _select_action("totally_unknown_fault", attempt=0)
    assert p["action"] == ActionType.NOTIFY_OPERATOR


def test_all_policy_scenarios_have_at_least_one_action():
    for scenario, candidates in ACTION_POLICY.items():
        assert len(candidates) >= 1, f"Policy for {scenario} is empty"


# ---------------------------------------------------------------------------
# Confidence gating
# ---------------------------------------------------------------------------

def test_low_score_is_skipped():
    record = asyncio.get_event_loop().run_until_complete(
        trigger_remediation("nrf_crash", "nrf", rcsm_score=0.3)
    )
    assert record.status == RemediationStatus.SKIPPED
    assert record.action == ActionType.NO_OP
    assert _rae_state.total_skipped == 1
    assert _rae_state.total_triggered == 0


def test_score_at_threshold_executes():
    record = asyncio.get_event_loop().run_until_complete(
        trigger_remediation("nrf_crash", "nrf", rcsm_score=CONFIDENCE_THRESHOLD)
    )
    assert record.status == RemediationStatus.SUCCESS
    assert _rae_state.total_triggered == 1


def test_high_score_executes():
    record = asyncio.get_event_loop().run_until_complete(
        trigger_remediation("amf_crash", "amf", rcsm_score=0.95)
    )
    assert record.status == RemediationStatus.SUCCESS
    assert record.action == ActionType.RESTART_POD
    assert record.target == "amf"


# ---------------------------------------------------------------------------
# All five fault scenarios
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario,expected_action", [
    ("nrf_crash",   ActionType.RESTART_POD),
    ("amf_crash",   ActionType.RESTART_POD),
    ("smf_crash",   ActionType.RESTART_POD),
    ("pcf_timeout", ActionType.ROLLBACK_CONFIG),
    ("udm_crash",   ActionType.RESTART_POD),
])
def test_fault_scenarios(scenario, expected_action):
    record = asyncio.get_event_loop().run_until_complete(
        trigger_remediation(scenario, scenario.split("_")[0], rcsm_score=0.9)
    )
    assert record.status == RemediationStatus.SUCCESS
    assert record.action == expected_action


# ---------------------------------------------------------------------------
# Outcome signal and feedback
# ---------------------------------------------------------------------------

def test_outcome_signal_populated_on_success():
    record = asyncio.get_event_loop().run_until_complete(
        trigger_remediation("smf_crash", "smf", rcsm_score=0.8)
    )
    assert record.outcome_signal == 1.0


def test_feedback_buffer_populated():
    asyncio.get_event_loop().run_until_complete(
        trigger_remediation("udm_crash", "udm", rcsm_score=0.75)
    )
    assert len(_rae_state.feedback_buffer) == 1
    entry = _rae_state.feedback_buffer[0]
    assert entry["fault_scenario"] == "udm_crash"
    assert entry["outcome"] == 1.0


def test_skipped_does_not_push_feedback():
    asyncio.get_event_loop().run_until_complete(
        trigger_remediation("nrf_crash", "nrf", rcsm_score=0.1)
    )
    assert len(_rae_state.feedback_buffer) == 0


# ---------------------------------------------------------------------------
# Slice context
# ---------------------------------------------------------------------------

def test_slice_id_stored_in_record():
    record = asyncio.get_event_loop().run_until_complete(
        trigger_remediation("amf_crash", "amf", rcsm_score=0.88, slice_id="1-000001")
    )
    assert record.slice_id == "1-000001"
    assert _rae_state.feedback_buffer[0]["slice_id"] == "1-000001"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def test_history_accumulates():
    for _ in range(3):
        asyncio.get_event_loop().run_until_complete(
            trigger_remediation("smf_crash", "smf", rcsm_score=0.85)
        )
    assert len(_rae_state.history) == 3


def test_stats_counters():
    asyncio.get_event_loop().run_until_complete(
        trigger_remediation("nrf_crash", "nrf", rcsm_score=0.9)
    )
    asyncio.get_event_loop().run_until_complete(
        trigger_remediation("nrf_crash", "nrf", rcsm_score=0.2)
    )
    assert _rae_state.total_triggered == 1
    assert _rae_state.total_succeeded == 1
    assert _rae_state.total_skipped == 1


def test_record_ids_are_unique():
    records = []
    for scenario in ["nrf_crash", "amf_crash", "smf_crash"]:
        r = asyncio.get_event_loop().run_until_complete(
            trigger_remediation(scenario, scenario.split("_")[0], rcsm_score=0.8)
        )
        records.append(r.record_id)
    assert len(set(records)) == 3
