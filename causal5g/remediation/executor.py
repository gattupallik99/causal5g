"""
causal5g.remediation.executor
==============================
Claim 3 — Remediation action executor.

Executes selected remediation actions by issuing control-plane API calls
to the 5G core orchestration layer:
- NF scale-out: Kubernetes HPA / orchestrator API
- PFCP re-establishment: SMF N4 PFCP Session Deletion + Establishment
- PCF admission tighten: Npcf_PolicyAuthorization service operation
- SMF traffic steer: N4 PFCP Modification Request
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import logging

from causal5g.remediation.policy_store import PolicyEntry, RemediationAction

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a remediation action execution."""
    success: bool
    action: RemediationAction
    target_entity: str
    message: str
    api_response: Optional[dict] = None


class RemediationExecutor:
    """
    Issues control-plane API calls to execute remediation actions per Claim 3.

    Parameters
    ----------
    orchestrator_url : str
        Base URL of the 5G core orchestration API (Kubernetes, OSM, etc.)
    smf_api_url : str
        SMF northbound API URL for N4 PFCP operations
    pcf_api_url : str
        PCF Npcf_PolicyAuthorization service base URL
    dry_run : bool
        If True, log intended actions without executing (default False)
    """

    def __init__(self, orchestrator_url: str = "", smf_api_url: str = "",
                 pcf_api_url: str = "", dry_run: bool = False):
        self.orchestrator_url = orchestrator_url
        self.smf_api_url = smf_api_url
        self.pcf_api_url = pcf_api_url
        self.dry_run = dry_run

    def execute(self, policy: PolicyEntry,
                target_entity: str,
                context: dict = None) -> ExecutionResult:
        """
        Execute the remediation action specified in the policy entry.

        Parameters
        ----------
        policy : PolicyEntry
            Selected policy from RemediationPolicyStore.lookup()
        target_entity : str
            Resolved NF instance ID, S-NSSAI, or pod label selector
        context : dict, optional
            Additional context (e.g. PFCP SEID, alternate UPF ID)
        """
        context = context or {}
        action = policy.action
        logger.info(f"Executing remediation: {action.value} on {target_entity}"
                    + (" [DRY RUN]" if self.dry_run else ""))
        handlers = {
            RemediationAction.NF_SCALE_OUT: self._scale_out_nf,
            RemediationAction.PFCP_REESTABLISH: self._reestablish_pfcp,
            RemediationAction.PCF_ADMISSION_TIGHTEN: self._tighten_pcf_admission,
            RemediationAction.SMF_TRAFFIC_STEER: self._steer_traffic,
        }
        handler = handlers.get(action)
        if not handler:
            return ExecutionResult(False, action, target_entity,
                                   f"No handler for action {action}")
        return handler(target_entity, context)

    def _scale_out_nf(self, target_entity: str, ctx: dict) -> ExecutionResult:
        """Scale out NF horizontally via cloud-native orchestrator API."""
        raise NotImplementedError(
            "Implement: PATCH /apis/autoscaling/v2/namespaces/{ns}/horizontalpodautoscalers/{nf}")

    def _reestablish_pfcp(self, target_entity: str, ctx: dict) -> ExecutionResult:
        """Re-establish PFCP session on an alternate UPF via SMF N4."""
        raise NotImplementedError(
            "Implement: SMF internal API — trigger N4 Session Deletion + "
            "Establishment toward alternate UPF ID from ctx['alt_upf_id']")

    def _tighten_pcf_admission(self, target_entity: str, ctx: dict) -> ExecutionResult:
        """Tighten slice admission via PCF Npcf_PolicyAuthorization."""
        raise NotImplementedError(
            "Implement: POST {pcf_api_url}/npcf-policyauthorization/v1/app-sessions "
            "with updated MaxBwDl/MaxBwUl for S-NSSAI {target_entity}")

    def _steer_traffic(self, target_entity: str, ctx: dict) -> ExecutionResult:
        """Steer traffic via SMF N4 PFCP Modification Request."""
        raise NotImplementedError(
            "Implement: SMF internal API — issue PFCP Session Modification Request "
            "with updated FAR to redirect traffic away from degraded NF")
