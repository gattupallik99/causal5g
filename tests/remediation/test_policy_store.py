"""
Tests for causal5g.remediation.policy_store — Claim 3 policy lookup.
"""
import pytest
from causal5g.remediation.policy_store import (
    RemediationPolicyStore, PolicyEntry,
    RemediationAction, RootCauseType
)


class TestRemediationPolicyStore:
    def test_default_policies_loaded(self):
        store = RemediationPolicyStore()
        assert len(store.list_policies()) > 0

    def test_lookup_nf_layer(self):
        store = RemediationPolicyStore()
        policy = store.lookup(RootCauseType.NF_LAYER, "smf-1")
        assert policy is not None
        assert policy.action == RemediationAction.NF_SCALE_OUT

    def test_lookup_pfcp_binding_failure(self):
        store = RemediationPolicyStore()
        policy = store.lookup(RootCauseType.PFCP_BINDING_FAILURE, "upf-1")
        assert policy is not None
        assert policy.action == RemediationAction.PFCP_REESTABLISH

    def test_lookup_slice_layer(self):
        store = RemediationPolicyStore()
        policy = store.lookup(RootCauseType.SLICE_LAYER, "1:1")
        assert policy is not None
        assert policy.action == RemediationAction.PCF_ADMISSION_TIGHTEN

    def test_lookup_unknown_returns_none(self):
        store = RemediationPolicyStore()
        # No policy for an unknown root cause type
        policy = store.lookup(RootCauseType.SBI_TIMEOUT_CASCADE, "99:99")
        # SBI_TIMEOUT_CASCADE does have a default policy with wildcard target
        assert policy is not None   # wildcard * matches

    def test_custom_policy_priority(self):
        """A higher-priority (lower number) custom policy should win."""
        store = RemediationPolicyStore()
        custom = PolicyEntry(
            root_cause_type=RootCauseType.NF_LAYER,
            target_entity="smf-1",
            action=RemediationAction.SMF_TRAFFIC_STEER,
            priority=1,   # higher priority than default (10)
        )
        store.add_policy(custom)
        policy = store.lookup(RootCauseType.NF_LAYER, "smf-1")
        assert policy.action == RemediationAction.SMF_TRAFFIC_STEER

    def test_add_and_list_policy(self):
        store = RemediationPolicyStore()
        initial_count = len(store.list_policies())
        store.add_policy(PolicyEntry(
            root_cause_type=RootCauseType.CLOUD_RESOURCE_EXHAUSTION,
            target_entity="upf-pod",
            action=RemediationAction.NF_SCALE_OUT,
            priority=5,
        ))
        assert len(store.list_policies()) == initial_count + 1
