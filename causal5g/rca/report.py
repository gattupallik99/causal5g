"""
causal5g.rca.report
====================
Claim 1 — Root cause report generation.

Produces a structured root cause report specifying:
- Root cause type (NF-layer or slice-layer)
- Causal attribution score
- Affected S-NSSAI identifiers
- Implicated N4 PFCP session or SBI service operation
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json
import time

from causal5g.causal.attribution import AttributionResult, RootCauseType


@dataclass
class RootCauseReport:
    """
    Structured root cause report output — Claim 1 required fields.
    """
    report_id: str
    generated_at_ms: int
    root_cause_type: RootCauseType
    root_cause_node: str
    attribution_score: float
    confidence: float
    affected_snssais: List[str]

    # Claim 1: implicated N4 PFCP session OR SBI service operation
    implicated_pfcp_seid: Optional[int] = None
    implicated_sbi_service: Optional[str] = None

    # Extended fields
    causal_path: List[str] = field(default_factory=list)
    recommended_action: Optional[str] = None
    raw_scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at_ms": self.generated_at_ms,
            "root_cause_type": self.root_cause_type.value,
            "root_cause_node": self.root_cause_node,
            "attribution_score": round(self.attribution_score, 4),
            "confidence": round(self.confidence, 4),
            "affected_snssais": self.affected_snssais,
            "implicated_pfcp_seid": self.implicated_pfcp_seid,
            "implicated_sbi_service": self.implicated_sbi_service,
            "causal_path": self.causal_path,
            "recommended_action": self.recommended_action,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


class RootCauseReporter:
    """
    Generates RootCauseReport instances from AttributionResult output.

    Parameters
    ----------
    report_id_prefix : str
        Prefix for auto-generated report IDs (default "causal5g-rca")
    """

    def __init__(self, report_id_prefix: str = "causal5g-rca"):
        self.report_id_prefix = report_id_prefix
        self._report_counter = 0

    def generate(self, result: AttributionResult,
                 raw_scores: Dict[str, float] = None,
                 causal_path: List[str] = None) -> RootCauseReport:
        """Generate a RootCauseReport from an AttributionResult."""
        self._report_counter += 1
        report_id = f"{self.report_id_prefix}-{self._report_counter:06d}"
        return RootCauseReport(
            report_id=report_id,
            generated_at_ms=int(time.time() * 1000),
            root_cause_type=result.root_cause_type,
            root_cause_node=result.root_cause_node,
            attribution_score=result.attribution_score,
            confidence=result.confidence,
            affected_snssais=result.affected_snssais,
            implicated_pfcp_seid=result.implicated_pfcp_seid,
            implicated_sbi_service=result.implicated_sbi_service,
            causal_path=causal_path or [],
            raw_scores=raw_scores or {},
        )
