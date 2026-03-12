"""
causal5g.remediation.verifier
==============================
Claim 3 — Post-remediation effectiveness verification.

Re-evaluates causal attribution scores over a post-remediation observation
window and generates an alert if scores on the root cause node do not
decrease below a configurable threshold within the window.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of the post-remediation effectiveness check."""
    effective: bool                     # True if root cause score dropped below threshold
    root_cause_node: str
    pre_remediation_score: float
    post_remediation_score: float
    threshold: float
    observation_window_ms: int
    alert_generated: bool
    message: str


class RemediationVerifier:
    """
    Verifies remediation effectiveness by re-evaluating causal attribution
    scores over a post-remediation observation window per Claim 3.

    Parameters
    ----------
    observation_window_ms : int
        Time to wait and observe after remediation before scoring (default 120000ms)
    score_threshold : float
        Attribution score must drop below this to be considered effective
    score_fn : callable
        Function that returns current attribution score for a given node ID
        Signature: (node_id: str) -> float
    alert_fn : callable, optional
        Called with VerificationResult when remediation is ineffective
    """

    def __init__(self, observation_window_ms: int = 120_000,
                 score_threshold: float = 0.2,
                 score_fn: Callable[[str], float] = None,
                 alert_fn: Callable[["VerificationResult"], None] = None):
        self.observation_window_ms = observation_window_ms
        self.score_threshold = score_threshold
        self.score_fn = score_fn
        self.alert_fn = alert_fn

    def verify(self, root_cause_node: str,
               pre_remediation_score: float,
               blocking: bool = False) -> VerificationResult:
        """
        Verify remediation effectiveness.

        Parameters
        ----------
        root_cause_node : str
            NF node ID identified as root cause
        pre_remediation_score : float
            Attribution score before remediation was applied
        blocking : bool
            If True, block for observation_window_ms before checking score.
            If False, returns immediately with a scheduled check (caller handles timing).
        """
        if blocking:
            time.sleep(self.observation_window_ms / 1000)

        post_score = self._get_current_score(root_cause_node)
        effective = post_score < self.score_threshold
        alert = not effective

        result = VerificationResult(
            effective=effective,
            root_cause_node=root_cause_node,
            pre_remediation_score=pre_remediation_score,
            post_remediation_score=post_score,
            threshold=self.score_threshold,
            observation_window_ms=self.observation_window_ms,
            alert_generated=alert,
            message=(
                f"Remediation effective: score {pre_remediation_score:.3f} -> {post_score:.3f}"
                if effective else
                f"ALERT: Remediation ineffective. Score {post_score:.3f} "
                f"still above threshold {self.score_threshold:.3f}"
            )
        )
        if alert:
            logger.warning(result.message)
            if self.alert_fn:
                self.alert_fn(result)
        else:
            logger.info(result.message)
        return result

    def _get_current_score(self, node_id: str) -> float:
        """Get current attribution score for a node via the score_fn callback."""
        if self.score_fn is None:
            raise RuntimeError(
                "score_fn must be provided to RemediationVerifier")
        return self.score_fn(node_id)
