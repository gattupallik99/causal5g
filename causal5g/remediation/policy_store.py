"""
causal5g.remediation.policy_store
===================================
Claim 3 — Remediation action policy store.

Associates causal root cause signatures with candidate remediation actions.
Each policy entry specifies: root cause type, target entity, and action.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RemediationAction(str, Enum):
    NF_SCALE_OUT = "nf_scale_out"                    # Horizontal scale-out via orchestrator
    PFCP_REESTABLISH = "pfcp_reestablish"             # PFCP session re-establishment on alt UPF
    PCF_ADMISSION_TIGHTEN = "pcf_admission_tighten"   # Slice admission control tightening
    SMF_TRAFFIC_STEER = "smf_traffic_steer"           # Traffic steering via N4 PFCP Mod Request


class RootCauseType(str, Enum):
    NF_LAYER = "nf_layer"
    SLICE_LAYER = "slice_layer"
    PFCP_BINDING_FAILURE = "pfcp_binding_failure"
    SBI_TIMEOUT_CASCADE = "sbi_timeout_cascade"
    CLOUD_RESOURCE_EXHAUSTION = "cloud_resource_exhaustion"


@dataclass
class PolicyEntry:
    """
    A single remediation policy entry per Claim 3.

    Attributes
    ----------
    root_cause_type : RootCauseType
    target_entity : str
        NF instance ID, S-NSSAI value, or Kubernetes pod label selector
    action : RemediationAction
    priority : int
        Lower = higher priority when multiple policies match
    condition : dict, optional
        Additional conditions that must hold (e.g. min attribution score)
    """
    root_cause_type: RootCauseType
    target_entity: str
    action: RemediationAction
    priority: int = 100
    condition: Dict = field(default_factory=dict)
    description: str = ""


class RemediationPolicyStore:
    """
    Policy store associating root cause signatures with remediation actions.

    Implements Claim 3's policy lookup: given a root cause type and target
    entity, select the highest-priority applicable remediation action.
    """

    def __init__(self):
        self._policies: List[PolicyEntry] = []
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default 5G SA remediation policies."""
        defaults = [
            PolicyEntry(
                root_cause_type=RootCauseType.NF_LAYER,
                target_entity="*",
                action=RemediationAction.NF_SCALE_OUT,
                priority=10,
                description="Scale out the faulty NF horizontally"),
            PolicyEntry(
                root_cause_type=RootCauseType.PFCP_BINDING_FAILURE,
                target_entity="*",
                action=RemediationAction.PFCP_REESTABLISH,
                priority=10,
                description="Re-establish PFCP session on an alternate UPF"),
            PolicyEntry(
                root_cause_type=RootCauseType.SLICE_LAYER,
                target_entity="*",
                action=RemediationAction.PCF_ADMISSION_TIGHTEN,
                priority=20,
                description="Tighten slice admission control via PCF policy"),
            PolicyEntry(
                root_cause_type=RootCauseType.SBI_TIMEOUT_CASCADE,
                target_entity="*",
                action=RemediationAction.SMF_TRAFFIC_STEER,
                priority=15,
                description="Steer traffic away from degraded NF via SMF N4"),
            PolicyEntry(
                root_cause_type=RootCauseType.CLOUD_RESOURCE_EXHAUSTION,
                target_entity="*",
                action=RemediationAction.NF_SCALE_OUT,
                priority=5,
                description="Scale out NF pod to relieve resource pressure"),
        ]
        self._policies.extend(defaults)

    def add_policy(self, policy: PolicyEntry) -> None:
        """Add a custom policy entry to the store."""
        self._policies.append(policy)

    def lookup(self, root_cause_type: RootCauseType,
               target_entity: str) -> Optional[PolicyEntry]:
        """
        Return the highest-priority matching policy for a given root cause
        type and target entity.
        """
        matches = [
            p for p in self._policies
            if p.root_cause_type == root_cause_type
            and (p.target_entity == "*" or p.target_entity == target_entity)
        ]
        if not matches:
            return None
        return min(matches, key=lambda p: p.priority)

    def list_policies(self) -> List[PolicyEntry]:
        return sorted(self._policies, key=lambda p: p.priority)
