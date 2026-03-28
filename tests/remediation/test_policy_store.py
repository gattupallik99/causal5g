"""Tests for PolicyStore — Day 10"""
import pytest
from causal5g.remediation.policy_store import PolicyStore

@pytest.fixture
def store():
    return PolicyStore()

def test_defaults_loaded(store):
    policies = store.list_all()
    assert len(policies) >= 11

def test_all_five_scenarios_have_policies(store):
    for scenario in ["nrf_crash","amf_crash","smf_crash","pcf_timeout","udm_crash"]:
        actions = store.get_ordered_actions(scenario)
        assert len(actions) >= 1, f"No policies for {scenario}"

def test_default_fallback_exists(store):
    actions = store.get_ordered_actions("totally_unknown_fault")
    assert len(actions) >= 1
    assert actions[0].fault_scenario == "_default"

def test_create_policy(store):
    entry = store.create("nrf_crash","scale_deployment","nrf",
                         {"namespace":"free5gc","replicas":3}, priority=2,
                         description="Scale NRF on repeated crash")
    assert entry.policy_id is not None
    assert entry.version == 1
    assert entry.enabled is True

def test_get_policy(store):
    entry = store.create("smf_crash","restart_pod","smf",{})
    fetched = store.get(entry.policy_id)
    assert fetched is not None
    assert fetched.policy_id == entry.policy_id

def test_get_nonexistent_returns_none(store):
    assert store.get("nonexistent") is None

def test_update_policy(store):
    entry = store.create("amf_crash","restart_pod","amf",{})
    updated = store.update(entry.policy_id, priority=5, description="Updated")
    assert updated.priority == 5
    assert updated.description == "Updated"
    assert updated.version == 2

def test_update_nonexistent_raises(store):
    with pytest.raises(KeyError):
        store.update("badid", priority=1)

def test_delete_policy(store):
    entry = store.create("udm_crash","restart_pod","udm",{})
    assert store.delete(entry.policy_id) is True
    assert store.get(entry.policy_id) is None

def test_delete_nonexistent_returns_false(store):
    assert store.delete("nonexistent") is False

def test_disable_and_enable(store):
    entry = store.create("nrf_crash","notify_operator","ops",{})
    store.disable(entry.policy_id)
    assert store.get(entry.policy_id).enabled is False
    store.enable(entry.policy_id)
    assert store.get(entry.policy_id).enabled is True

def test_enabled_only_filter(store):
    entry = store.create("nrf_crash","notify_operator","ops",{})
    store.disable(entry.policy_id)
    all_p = store.list_all(fault_scenario="nrf_crash", enabled_only=False)
    enabled = store.list_all(fault_scenario="nrf_crash", enabled_only=True)
    assert len(all_p) > len(enabled)

def test_ordered_actions_sorted_by_priority(store):
    actions = store.get_ordered_actions("nrf_crash")
    priorities = [a.priority for a in actions]
    assert priorities == sorted(priorities)

def test_store_version_increments(store):
    v0 = store.store_version()
    store.create("nrf_crash","restart_pod","nrf",{})
    assert store.store_version() == v0 + 1

def test_audit_log_records_create(store):
    store.create("nrf_crash","restart_pod","nrf",{})
    log = store.get_audit_log()
    assert any(e["op"] == "create" for e in log)

def test_audit_log_records_update(store):
    entry = store.create("nrf_crash","restart_pod","nrf",{})
    store.update(entry.policy_id, priority=9)
    log = store.get_audit_log()
    assert any(e["op"] == "update" for e in log)

def test_audit_log_records_delete(store):
    entry = store.create("nrf_crash","restart_pod","nrf",{})
    store.delete(entry.policy_id)
    log = store.get_audit_log()
    assert any(e["op"] == "delete" for e in log)

def test_to_dict_structure(store):
    d = store.to_dict()
    assert "store_version" in d
    assert "policy_count" in d
    assert "policies" in d
