"""
RemediationVerifier — Causal5G Day 10
Post-remediation verification: re-scores RCSM after action,
confirms fault cleared or escalates to fallback.
Patent claim 4: feedback loop outcome confirmation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/verify", tags=["verifier"])


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class VerificationOutcome(str, Enum):
    CLEARED      = "cleared"       # fault gone — remediation succeeded
    PERSISTING   = "persisting"    # fault still active — escalate
    DEGRADED     = "degraded"      # partial improvement — monitor
    TIMEOUT      = "timeout"       # verification window expired
    INCONCLUSIVE = "inconclusive"  # insufficient signal


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    record_id:          str
    fault_scenario:     str
    root_cause_nf:      str
    pre_rcsm_score:     float           # RCSM score before remediation
    post_rcsm_score:    float | None    # RCSM score after remediation
    outcome:            VerificationOutcome
    improvement:        float | None    # post - pre (positive = better)
    verified_at:        float
    escalate:           bool            # True → trigger fallback action
    slice_id:           str | None
    notes:              str = ""


@dataclass
class VerifierState:
    results:        list[VerificationResult] = field(default_factory=list)
    total_verified: int = 0
    total_cleared:  int = 0
    total_escalated: int = 0


_state = VerifierState()


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# RCSM score below this = fault is considered cleared
CLEARED_THRESHOLD   = 0.30
# Minimum improvement required to avoid escalation
MIN_IMPROVEMENT     = 0.20
# Score reduction that indicates degraded (partial fix)
DEGRADED_THRESHOLD  = 0.10


# ---------------------------------------------------------------------------
# Core verifier logic
# ---------------------------------------------------------------------------

def verify_remediation(
    fault_scenario:  str,
    root_cause_nf:   str,
    pre_rcsm_score:  float,
    post_rcsm_score: float | None,
    record_id:       str,
    slice_id:        str | None = None,
) -> VerificationResult:
    """
    Compare pre- and post-remediation RCSM scores to determine outcome.

    Patent claim 4: this function provides the outcome signal that
    feeds back into the causal DAG recalibration loop.

    Logic:
      post_score < CLEARED_THRESHOLD (0.30)  → CLEARED
      improvement >= MIN_IMPROVEMENT (0.20)  → DEGRADED (partial fix)
      improvement < MIN_IMPROVEMENT          → PERSISTING (escalate)
      post_score is None                     → INCONCLUSIVE
    """
    import uuid
    verified_at = time.time()

    if post_rcsm_score is None:
        result = VerificationResult(
            record_id=record_id,
            fault_scenario=fault_scenario,
            root_cause_nf=root_cause_nf,
            pre_rcsm_score=pre_rcsm_score,
            post_rcsm_score=None,
            outcome=VerificationOutcome.INCONCLUSIVE,
            improvement=None,
            verified_at=verified_at,
            escalate=False,
            slice_id=slice_id,
            notes="No post-remediation score available",
        )
    else:
        improvement = pre_rcsm_score - post_rcsm_score  # positive = improvement

        if post_rcsm_score < CLEARED_THRESHOLD:
            outcome  = VerificationOutcome.CLEARED
            escalate = False
            notes    = f"Fault cleared — post-score {post_rcsm_score:.3f} below threshold {CLEARED_THRESHOLD}"
        elif improvement >= MIN_IMPROVEMENT:
            outcome  = VerificationOutcome.DEGRADED
            escalate = False
            notes    = f"Partial improvement — Δ{improvement:.3f} — monitoring recommended"
        else:
            outcome  = VerificationOutcome.PERSISTING
            escalate = True
            notes    = f"Fault persisting — improvement {improvement:.3f} below {MIN_IMPROVEMENT} — escalating"

        result = VerificationResult(
            record_id=record_id,
            fault_scenario=fault_scenario,
            root_cause_nf=root_cause_nf,
            pre_rcsm_score=pre_rcsm_score,
            post_rcsm_score=post_rcsm_score,
            outcome=outcome,
            improvement=improvement,
            verified_at=verified_at,
            escalate=escalate,
            slice_id=slice_id,
            notes=notes,
        )

    _state.results.append(result)
    _state.total_verified += 1
    if result.outcome == VerificationOutcome.CLEARED:
        _state.total_cleared += 1
    if result.escalate:
        _state.total_escalated += 1
        logger.warning("[Verifier] Escalating %s on %s — fault persisting (post=%.3f)",
                       fault_scenario, root_cause_nf, post_rcsm_score or -1)
    else:
        logger.info("[Verifier] %s on %s → %s",
                    fault_scenario, root_cause_nf, result.outcome.value)

    # Bound history
    if len(_state.results) > 200:
        _state.results = _state.results[-200:]

    return result


def outcome_to_signal(outcome: VerificationOutcome) -> float:
    """
    Convert verification outcome to a 0-1 signal for recalibrator.
    Patent claim 4: this signal drives causal edge weight adjustment.
    """
    return {
        VerificationOutcome.CLEARED:      1.0,
        VerificationOutcome.DEGRADED:     0.6,
        VerificationOutcome.PERSISTING:   0.0,
        VerificationOutcome.INCONCLUSIVE: 0.5,
        VerificationOutcome.TIMEOUT:      0.2,
    }[outcome]


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    record_id:       str
    fault_scenario:  str
    root_cause_nf:   str
    pre_rcsm_score:  float
    post_rcsm_score: float | None = None
    slice_id:        str | None   = None


def _result_to_dict(r: VerificationResult) -> dict[str, Any]:
    return {
        "record_id":       r.record_id,
        "fault_scenario":  r.fault_scenario,
        "root_cause_nf":   r.root_cause_nf,
        "pre_rcsm_score":  r.pre_rcsm_score,
        "post_rcsm_score": r.post_rcsm_score,
        "outcome":         r.outcome.value,
        "improvement":     round(r.improvement, 4) if r.improvement is not None else None,
        "escalate":        r.escalate,
        "outcome_signal":  outcome_to_signal(r.outcome),
        "verified_at":     r.verified_at,
        "slice_id":        r.slice_id,
        "notes":           r.notes,
    }


@router.post("")
async def verify(req: VerifyRequest):
    """
    Verify remediation outcome by comparing pre/post RCSM scores.
    Returns outcome signal for recalibrator consumption.
    """
    result = verify_remediation(
        fault_scenario=req.fault_scenario,
        root_cause_nf=req.root_cause_nf,
        pre_rcsm_score=req.pre_rcsm_score,
        post_rcsm_score=req.post_rcsm_score,
        record_id=req.record_id,
        slice_id=req.slice_id,
    )
    return _result_to_dict(result)


@router.get("/history")
async def get_history(limit: int = 20):
    results = _state.results[-limit:][::-1]
    return {
        "total_verified":  _state.total_verified,
        "total_cleared":   _state.total_cleared,
        "total_escalated": _state.total_escalated,
        "clear_rate": round(_state.total_cleared / _state.total_verified, 3)
                      if _state.total_verified > 0 else 0.0,
        "results": [_result_to_dict(r) for r in results],
    }


@router.get("/thresholds")
async def get_thresholds():
    return {
        "cleared_threshold":  CLEARED_THRESHOLD,
        "min_improvement":    MIN_IMPROVEMENT,
        "degraded_threshold": DEGRADED_THRESHOLD,
        "outcome_signals": {o.value: outcome_to_signal(o) for o in VerificationOutcome},
    }
