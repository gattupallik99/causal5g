"""
RCA Report — Causal5G Day 10
Structured Root Cause Analysis report with causal chain,
root cause NF, confidence score, and remediation taken.
Patent claim 2: RCA output artefact.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rca", tags=["rca-report"])


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"


class RCAStatus(str, Enum):
    OPEN       = "open"
    REMEDIATED = "remediated"
    VERIFIED   = "verified"
    ESCALATED  = "escalated"
    CLOSED     = "closed"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CausalStep:
    """One step in the causal chain leading to the fault."""
    rank:           int         # 1 = root cause, 2 = secondary, etc.
    nf:             str         # Network Function name
    causal_weight:  float       # edge weight from GrangerPCFusion DAG
    contribution:   float       # attribution score 0-1
    evidence:       str         # human-readable evidence description


@dataclass
class RCAReport:
    """
    Full structured RCA report.
    Generated after GrangerPCFusion diagnoses a fault and
    RAE executes remediation.
    """
    report_id:          str
    fault_scenario:     str
    root_cause_nf:      str
    rcsm_score:         float
    severity:           Severity
    slice_id:           str | None
    causal_chain:       list[CausalStep]
    remediation_action: str | None
    remediation_target: str | None
    verification_outcome: str | None
    status:             RCAStatus
    created_at:         float
    updated_at:         float
    summary:            str
    recommendations:    list[str]


# ---------------------------------------------------------------------------
# Report store
# ---------------------------------------------------------------------------

@dataclass
class ReportStore:
    _reports: dict[str, RCAReport] = field(default_factory=dict)

    def add(self, report: RCAReport) -> None:
        self._reports[report.report_id] = report

    def get(self, report_id: str) -> RCAReport | None:
        return self._reports.get(report_id)

    def list_all(self, status: str | None = None) -> list[RCAReport]:
        reports = list(self._reports.values())
        if status:
            reports = [r for r in reports if r.status.value == status]
        return sorted(reports, key=lambda r: r.created_at, reverse=True)

    def update_status(self, report_id: str, status: RCAStatus,
                      verification_outcome: str | None = None) -> RCAReport | None:
        report = self._reports.get(report_id)
        if report:
            report.status = status
            report.updated_at = time.time()
            if verification_outcome:
                report.verification_outcome = verification_outcome
        return report

    def count(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self._reports.values():
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        return counts


_store = ReportStore()


def get_report_store() -> ReportStore:
    return _store


# ---------------------------------------------------------------------------
# Report factory
# ---------------------------------------------------------------------------

def _score_to_severity(score: float) -> Severity:
    if score >= 0.85:   return Severity.CRITICAL
    if score >= 0.70:   return Severity.HIGH
    if score >= 0.50:   return Severity.MEDIUM
    return Severity.LOW


def _build_causal_chain(
    root_cause_nf:   str,
    rcsm_score:      float,
    fault_scenario:  str,
) -> list[CausalStep]:
    """
    Build the causal chain for a fault.
    In production this would be populated from the live GrangerPCFusion DAG.
    Here we generate a realistic chain based on 5G NF topology.
    """
    # 5G SA core causal chains per fault scenario
    chains: dict[str, list[tuple[str, float, float, str]]] = {
        "nrf_crash": [
            ("nrf", 1.00, 1.00, "NRF service unavailable — all NF discovery requests failing"),
            ("amf", 0.85, 0.72, "AMF unable to register with NRF — UE attach failures"),
            ("smf", 0.75, 0.61, "SMF session establishment failing — NRF lookup timeout"),
        ],
        "amf_crash": [
            ("amf", 1.00, 1.00, "AMF pod crashed — all UE registration and mobility affected"),
            ("udm", 0.70, 0.55, "UDM subscription fetch latency spike — correlated with AMF crash"),
        ],
        "smf_crash": [
            ("smf", 1.00, 1.00, "SMF pod crashed — all PDU sessions terminated"),
            ("pcf", 0.65, 0.48, "PCF policy sessions orphaned after SMF crash"),
            ("upf", 0.80, 0.70, "UPF data plane sessions dropped — SMF control plane gone"),
        ],
        "pcf_timeout": [
            ("pcf", 1.00, 1.00, "PCF response timeout — QoS policy enforcement failing"),
            ("smf", 0.60, 0.45, "SMF session modification requests timing out — waiting on PCF"),
        ],
        "udm_crash": [
            ("udm", 1.00, 1.00, "UDM pod crashed — subscriber data unavailable"),
            ("amf", 0.75, 0.62, "AMF authentication failures — UDM unreachable for SUPI lookup"),
        ],
    }
    raw = chains.get(fault_scenario, [
        (root_cause_nf, 1.00, rcsm_score, f"Root cause identified: {root_cause_nf} fault detected")
    ])
    return [
        CausalStep(rank=i+1, nf=nf, causal_weight=cw, contribution=contrib, evidence=ev)
        for i, (nf, cw, contrib, ev) in enumerate(raw)
    ]


def _build_recommendations(
    fault_scenario:     str,
    severity:           Severity,
    verification_outcome: str | None,
) -> list[str]:
    recs = []
    if severity in (Severity.CRITICAL, Severity.HIGH):
        recs.append("Escalate to on-call SRE immediately if not auto-remediated")
    if fault_scenario == "nrf_crash":
        recs.append("Consider deploying NRF in HA mode (active-standby) to prevent single point of failure")
        recs.append("Add NRF health check to K8s liveness probe with aggressive restart policy")
    elif fault_scenario in ("amf_crash", "udm_crash"):
        recs.append("Increase deployment replicas to 2+ for this NF to enable zero-downtime restart")
    elif fault_scenario == "pcf_timeout":
        recs.append("Review PCF policy database load — timeout may indicate resource exhaustion")
        recs.append("Consider PCF rate limiting on policy requests from SMF")
    elif fault_scenario == "smf_crash":
        recs.append("Implement SMF session state persistence to enable graceful restart")
    if verification_outcome == "persisting":
        recs.append("Auto-remediation did not clear fault — manual intervention required")
        recs.append("Review K8s pod logs for the affected NF: kubectl logs -n free5gc <pod>")
    recs.append("Add this fault scenario to regression test suite for ongoing validation")
    return recs


def generate_report(
    fault_scenario:       str,
    root_cause_nf:        str,
    rcsm_score:           float,
    slice_id:             str | None   = None,
    remediation_action:   str | None   = None,
    remediation_target:   str | None   = None,
    verification_outcome: str | None   = None,
    status:               RCAStatus    = RCAStatus.OPEN,
) -> RCAReport:
    """Generate and store a structured RCA report."""
    now      = time.time()
    severity = _score_to_severity(rcsm_score)
    chain    = _build_causal_chain(root_cause_nf, rcsm_score, fault_scenario)
    recs     = _build_recommendations(fault_scenario, severity, verification_outcome)

    summary = (
        f"{severity.value.upper()} fault detected in {root_cause_nf.upper()} "
        f"(scenario: {fault_scenario}, RCSM score: {rcsm_score:.3f}). "
        f"Causal chain: {' → '.join(s.nf for s in chain)}. "
        + (f"Remediation: {remediation_action} on {remediation_target}." if remediation_action else "No remediation triggered.")
    )

    report = RCAReport(
        report_id=str(uuid.uuid4())[:12],
        fault_scenario=fault_scenario,
        root_cause_nf=root_cause_nf,
        rcsm_score=rcsm_score,
        severity=severity,
        slice_id=slice_id,
        causal_chain=chain,
        remediation_action=remediation_action,
        remediation_target=remediation_target,
        verification_outcome=verification_outcome,
        status=status,
        created_at=now,
        updated_at=now,
        summary=summary,
        recommendations=recs,
    )
    _store.add(report)
    logger.info("[RCA] Report %s generated — %s/%s score=%.3f",
                report.report_id, fault_scenario, root_cause_nf, rcsm_score)
    return report


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------

class GenerateReportRequest(BaseModel):
    fault_scenario:       str
    root_cause_nf:        str
    rcsm_score:           float
    slice_id:             str | None = None
    remediation_action:   str | None = None
    remediation_target:   str | None = None
    verification_outcome: str | None = None


def _chain_step_dict(s: CausalStep) -> dict[str, Any]:
    return {
        "rank":          s.rank,
        "nf":            s.nf,
        "causal_weight": s.causal_weight,
        "contribution":  s.contribution,
        "evidence":      s.evidence,
    }


def _report_to_dict(r: RCAReport) -> dict[str, Any]:
    return {
        "report_id":            r.report_id,
        "fault_scenario":       r.fault_scenario,
        "root_cause_nf":        r.root_cause_nf,
        "rcsm_score":           r.rcsm_score,
        "severity":             r.severity.value,
        "slice_id":             r.slice_id,
        "status":               r.status.value,
        "summary":              r.summary,
        "causal_chain":         [_chain_step_dict(s) for s in r.causal_chain],
        "remediation_action":   r.remediation_action,
        "remediation_target":   r.remediation_target,
        "verification_outcome": r.verification_outcome,
        "recommendations":      r.recommendations,
        "created_at":           r.created_at,
        "updated_at":           r.updated_at,
    }


@router.post("/generate", status_code=201)
async def generate(req: GenerateReportRequest):
    """Generate a structured RCA report for a diagnosed fault."""
    report = generate_report(
        fault_scenario=req.fault_scenario,
        root_cause_nf=req.root_cause_nf,
        rcsm_score=req.rcsm_score,
        slice_id=req.slice_id,
        remediation_action=req.remediation_action,
        remediation_target=req.remediation_target,
        verification_outcome=req.verification_outcome,
    )
    return _report_to_dict(report)


@router.get("")
async def list_reports(status: str | None = None, limit: int = 20):
    reports = _store.list_all(status=status)[:limit]
    return {
        "counts":  _store.count(),
        "reports": [_report_to_dict(r) for r in reports],
    }


@router.get("/{report_id}")
async def get_report(report_id: str):
    report = _store.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return _report_to_dict(report)


@router.patch("/{report_id}/status")
async def update_status(report_id: str, status: str, verification_outcome: str | None = None):
    try:
        s = RCAStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    report = _store.update_status(report_id, s, verification_outcome)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return _report_to_dict(report)
