"""
Remediation Action Engine (RAE) — Causal5G Day 9
Implements closed-loop remediation for cloud-native 5G SA core.
Patent claims 3-4: action selection, confidence gating, feedback loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/remediate", tags=["remediation"])


# ---------------------------------------------------------------------------
# Enums & constants
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    RESTART_POD        = "restart_pod"
    SCALE_DEPLOYMENT   = "scale_deployment"
    DRAIN_NODE         = "drain_node"
    ROLLBACK_CONFIG    = "rollback_config"
    REROUTE_TRAFFIC    = "reroute_traffic"
    NOTIFY_OPERATOR    = "notify_operator"
    NO_OP              = "no_op"


class RemediationStatus(str, Enum):
    PENDING    = "pending"
    EXECUTING  = "executing"
    SUCCESS    = "success"
    FAILED     = "failed"
    SKIPPED    = "skipped"   # confidence below threshold


# Minimum RCSM composite score to auto-trigger remediation (0-1)
CONFIDENCE_THRESHOLD = 0.65

# Maximum remediation actions retained in history
HISTORY_LIMIT = 200


# ---------------------------------------------------------------------------
# Action policy table
# Maps (root_cause_nf, fault_type) → ordered list of candidate actions.
# First entry = preferred action; subsequent entries = fallbacks.
# ---------------------------------------------------------------------------

ACTION_POLICY: dict[str, list[dict[str, Any]]] = {
    # NRF
    "nrf_crash": [
        {"action": ActionType.RESTART_POD,      "target": "nrf",      "params": {"namespace": "free5gc", "grace_period": 10}},
        {"action": ActionType.NOTIFY_OPERATOR,   "target": "ops-team", "params": {"severity": "critical", "nf": "nrf"}},
    ],
    # AMF
    "amf_crash": [
        {"action": ActionType.RESTART_POD,      "target": "amf",      "params": {"namespace": "free5gc", "grace_period": 5}},
        {"action": ActionType.SCALE_DEPLOYMENT, "target": "amf",      "params": {"namespace": "free5gc", "replicas": 2}},
    ],
    # SMF
    "smf_crash": [
        {"action": ActionType.RESTART_POD,      "target": "smf",      "params": {"namespace": "free5gc", "grace_period": 5}},
        {"action": ActionType.REROUTE_TRAFFIC,  "target": "smf",      "params": {"backup_smf": "smf-backup"}},
    ],
    # PCF timeout — prefer config rollback, then restart
    "pcf_timeout": [
        {"action": ActionType.ROLLBACK_CONFIG,  "target": "pcf",      "params": {"namespace": "free5gc", "revision": -1}},
        {"action": ActionType.RESTART_POD,      "target": "pcf",      "params": {"namespace": "free5gc", "grace_period": 10}},
    ],
    # UDM
    "udm_crash": [
        {"action": ActionType.RESTART_POD,      "target": "udm",      "params": {"namespace": "free5gc", "grace_period": 5}},
        {"action": ActionType.SCALE_DEPLOYMENT, "target": "udm",      "params": {"namespace": "free5gc", "replicas": 2}},
    ],
    # Generic / unknown
    "_default": [
        {"action": ActionType.NOTIFY_OPERATOR, "target": "ops-team", "params": {"severity": "warning", "nf": "unknown"}},
    ],
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class RemediationRecord:
    record_id:       str
    fault_scenario:  str
    root_cause_nf:   str
    rcsm_score:      float
    slice_id:        str | None
    action:          ActionType
    target:          str
    params:          dict[str, Any]
    status:          RemediationStatus
    triggered_at:    float
    completed_at:    float | None  = None
    outcome_signal:  float | None  = None   # 0=failure 1=success, fed back to RCSM
    error_msg:       str | None    = None


@dataclass
class RAEState:
    """Singleton state for the Remediation Action Engine."""
    history:            list[RemediationRecord] = field(default_factory=list)
    feedback_buffer:    list[dict[str, Any]]    = field(default_factory=list)
    total_triggered:    int  = 0
    total_succeeded:    int  = 0
    total_skipped:      int  = 0


# Module-level singleton
_rae_state = RAEState()


# ---------------------------------------------------------------------------
# Kubernetes action stubs
# In production these would invoke kubectl/k8s Python client.
# Stubs simulate latency and return a success signal.
# ---------------------------------------------------------------------------

async def _k8s_restart_pod(target: str, params: dict[str, Any]) -> dict[str, Any]:
    ns = params.get("namespace", "free5gc")
    gp = params.get("grace_period", 5)
    logger.info("[K8s stub] kubectl rollout restart deployment/%s -n %s --grace-period=%s", target, ns, gp)
    await asyncio.sleep(0.1)   # simulate API call latency
    return {"action": "restart_pod", "target": target, "namespace": ns, "simulated": True, "success": True}


async def _k8s_scale(target: str, params: dict[str, Any]) -> dict[str, Any]:
    ns       = params.get("namespace", "free5gc")
    replicas = params.get("replicas", 2)
    logger.info("[K8s stub] kubectl scale deployment/%s --replicas=%d -n %s", target, replicas, ns)
    await asyncio.sleep(0.1)
    return {"action": "scale_deployment", "target": target, "replicas": replicas, "namespace": ns, "simulated": True, "success": True}


async def _k8s_rollback(target: str, params: dict[str, Any]) -> dict[str, Any]:
    ns       = params.get("namespace", "free5gc")
    revision = params.get("revision", -1)
    logger.info("[K8s stub] kubectl rollout undo deployment/%s -n %s --to-revision=%d", target, ns, revision)
    await asyncio.sleep(0.15)
    return {"action": "rollback_config", "target": target, "namespace": ns, "revision": revision, "simulated": True, "success": True}


async def _reroute_traffic(target: str, params: dict[str, Any]) -> dict[str, Any]:
    backup = params.get("backup_smf", "smf-backup")
    logger.info("[Traffic stub] Rerouting traffic from %s to %s", target, backup)
    await asyncio.sleep(0.05)
    return {"action": "reroute_traffic", "target": target, "backup": backup, "simulated": True, "success": True}


async def _notify_operator(target: str, params: dict[str, Any]) -> dict[str, Any]:
    severity = params.get("severity", "warning")
    nf       = params.get("nf", "unknown")
    logger.info("[Notify stub] Alerting %s — severity=%s nf=%s", target, severity, nf)
    await asyncio.sleep(0.02)
    return {"action": "notify_operator", "target": target, "severity": severity, "simulated": True, "success": True}


_ACTION_DISPATCH: dict[ActionType, Any] = {
    ActionType.RESTART_POD:      _k8s_restart_pod,
    ActionType.SCALE_DEPLOYMENT: _k8s_scale,
    ActionType.ROLLBACK_CONFIG:  _k8s_rollback,
    ActionType.REROUTE_TRAFFIC:  _reroute_traffic,
    ActionType.NOTIFY_OPERATOR:  _notify_operator,
}


# ---------------------------------------------------------------------------
# Core RAE logic
# ---------------------------------------------------------------------------

def _select_action(fault_scenario: str, attempt: int = 0) -> dict[str, Any]:
    """Select action from policy table. attempt=0 → preferred, 1 → fallback."""
    candidates = ACTION_POLICY.get(fault_scenario, ACTION_POLICY["_default"])
    idx = min(attempt, len(candidates) - 1)
    return candidates[idx]


async def _execute_action(action: ActionType, target: str, params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch to the appropriate stub. Returns result dict."""
    fn = _ACTION_DISPATCH.get(action)
    if fn is None:
        return {"action": action, "target": target, "simulated": True, "success": True, "note": "no-op"}
    return await fn(target, params)


def _compute_outcome_signal(result: dict[str, Any]) -> float:
    """Convert action result to a 0-1 outcome signal for RCSM feedback."""
    return 1.0 if result.get("success") else 0.0


def _push_feedback(record: RemediationRecord) -> None:
    """
    Push outcome signal into the feedback buffer.
    The RCSM and GrangerPCFusion modules consume this buffer to
    recalibrate causal edge weights (patent claim 4).
    """
    if record.outcome_signal is None:
        return
    entry = {
        "fault_scenario": record.fault_scenario,
        "root_cause_nf":  record.root_cause_nf,
        "action":         record.action.value,
        "outcome":        record.outcome_signal,
        "timestamp":      record.completed_at,
        "slice_id":       record.slice_id,
    }
    _rae_state.feedback_buffer.append(entry)
    # Keep buffer bounded
    if len(_rae_state.feedback_buffer) > HISTORY_LIMIT:
        _rae_state.feedback_buffer = _rae_state.feedback_buffer[-HISTORY_LIMIT:]
    logger.debug("[RAE] Feedback pushed: %s", entry)


async def trigger_remediation(
    fault_scenario: str,
    root_cause_nf:  str,
    rcsm_score:     float,
    slice_id:       str | None = None,
    attempt:        int = 0,
) -> RemediationRecord:
    """
    Main RAE entry point.
    1. Gate on confidence threshold.
    2. Select action from policy table.
    3. Execute via K8s stub.
    4. Record outcome and push feedback.
    """
    record_id = str(uuid.uuid4())[:8]
    triggered_at = time.time()

    policy = _select_action(fault_scenario, attempt)
    action = ActionType(policy["action"])
    target = policy["target"]
    params = policy["params"]

    # Confidence gate
    if rcsm_score < CONFIDENCE_THRESHOLD:
        record = RemediationRecord(
            record_id=record_id,
            fault_scenario=fault_scenario,
            root_cause_nf=root_cause_nf,
            rcsm_score=rcsm_score,
            slice_id=slice_id,
            action=ActionType.NO_OP,
            target="none",
            params={},
            status=RemediationStatus.SKIPPED,
            triggered_at=triggered_at,
            completed_at=time.time(),
            outcome_signal=None,
        )
        _rae_state.total_skipped += 1
        _rae_state.history.append(record)
        logger.info("[RAE] Skipped — score %.3f below threshold %.3f", rcsm_score, CONFIDENCE_THRESHOLD)
        return record

    record = RemediationRecord(
        record_id=record_id,
        fault_scenario=fault_scenario,
        root_cause_nf=root_cause_nf,
        rcsm_score=rcsm_score,
        slice_id=slice_id,
        action=action,
        target=target,
        params=params,
        status=RemediationStatus.EXECUTING,
        triggered_at=triggered_at,
    )
    _rae_state.total_triggered += 1

    try:
        result = await _execute_action(action, target, params)
        record.status         = RemediationStatus.SUCCESS
        record.completed_at   = time.time()
        record.outcome_signal = _compute_outcome_signal(result)
        _rae_state.total_succeeded += 1
        logger.info("[RAE] %s → %s on %s SUCCESS (outcome=%.1f)",
                    fault_scenario, action.value, target, record.outcome_signal)
    except Exception as exc:
        record.status       = RemediationStatus.FAILED
        record.completed_at = time.time()
        record.error_msg    = str(exc)
        record.outcome_signal = 0.0
        logger.error("[RAE] %s → %s FAILED: %s", fault_scenario, action.value, exc)

    _push_feedback(record)

    _rae_state.history.append(record)
    if len(_rae_state.history) > HISTORY_LIMIT:
        _rae_state.history = _rae_state.history[-HISTORY_LIMIT:]

    return record


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------

class RemediateRequest(BaseModel):
    fault_scenario: str            = Field(..., example="nrf_crash")
    root_cause_nf:  str            = Field(..., example="nrf")
    rcsm_score:     float          = Field(..., ge=0.0, le=1.0, example=0.82)
    slice_id:       str | None     = Field(None, example="1-000001")
    attempt:        int            = Field(0, ge=0, le=3, description="0=preferred action, 1+=fallback")


class RemediateResponse(BaseModel):
    record_id:      str
    fault_scenario: str
    root_cause_nf:  str
    rcsm_score:     float
    action:         str
    target:         str
    status:         str
    outcome_signal: float | None
    latency_ms:     float
    slice_id:       str | None
    skipped_reason: str | None


@router.post("", response_model=RemediateResponse)
async def remediate(req: RemediateRequest):
    """
    Trigger closed-loop remediation for a diagnosed fault.
    Confidence-gated: if rcsm_score < 0.65 the action is skipped.
    """
    record = await trigger_remediation(
        fault_scenario=req.fault_scenario,
        root_cause_nf=req.root_cause_nf,
        rcsm_score=req.rcsm_score,
        slice_id=req.slice_id,
        attempt=req.attempt,
    )
    latency_ms = ((record.completed_at or time.time()) - record.triggered_at) * 1000
    skipped_reason = (
        f"RCSM score {req.rcsm_score:.3f} below threshold {CONFIDENCE_THRESHOLD}"
        if record.status == RemediationStatus.SKIPPED else None
    )
    return RemediateResponse(
        record_id=record.record_id,
        fault_scenario=record.fault_scenario,
        root_cause_nf=record.root_cause_nf,
        rcsm_score=record.rcsm_score,
        action=record.action.value,
        target=record.target,
        status=record.status.value,
        outcome_signal=record.outcome_signal,
        latency_ms=round(latency_ms, 2),
        slice_id=record.slice_id,
        skipped_reason=skipped_reason,
    )


@router.get("/history")
async def get_history(limit: int = 20):
    """Return recent remediation records."""
    records = _rae_state.history[-limit:][::-1]
    return {
        "total_triggered": _rae_state.total_triggered,
        "total_succeeded": _rae_state.total_succeeded,
        "total_skipped":   _rae_state.total_skipped,
        "records": [
            {
                "record_id":      r.record_id,
                "fault_scenario": r.fault_scenario,
                "root_cause_nf":  r.root_cause_nf,
                "rcsm_score":     r.rcsm_score,
                "action":         r.action.value,
                "target":         r.target,
                "status":         r.status.value,
                "outcome_signal": r.outcome_signal,
                "slice_id":       r.slice_id,
                "triggered_at":   r.triggered_at,
            }
            for r in records
        ],
    }


@router.get("/feedback")
async def get_feedback(limit: int = 50):
    """
    Return the feedback buffer consumed by RCSM/GrangerPCFusion
    to recalibrate causal edge weights (patent claim 4).
    """
    buf = _rae_state.feedback_buffer[-limit:][::-1]
    return {
        "feedback_count": len(_rae_state.feedback_buffer),
        "entries": buf,
    }


@router.get("/policy")
async def get_policy():
    """Return the current action policy table."""
    return {
        scenario: [
            {"action": c["action"].value if hasattr(c["action"], "value") else c["action"],
             "target": c["target"],
             "params": c["params"]}
            for c in candidates
        ]
        for scenario, candidates in ACTION_POLICY.items()
    }


@router.get("/stats")
async def get_stats():
    """Aggregate RAE performance statistics."""
    success_rate = (
        _rae_state.total_succeeded / _rae_state.total_triggered
        if _rae_state.total_triggered > 0 else 0.0
    )
    avg_outcome = None
    outcomes = [r.outcome_signal for r in _rae_state.history if r.outcome_signal is not None]
    if outcomes:
        avg_outcome = round(sum(outcomes) / len(outcomes), 3)

    return {
        "total_triggered":  _rae_state.total_triggered,
        "total_succeeded":  _rae_state.total_succeeded,
        "total_skipped":    _rae_state.total_skipped,
        "success_rate":     round(success_rate, 3),
        "avg_outcome_signal": avg_outcome,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "history_depth":    len(_rae_state.history),
        "feedback_depth":   len(_rae_state.feedback_buffer),
    }
