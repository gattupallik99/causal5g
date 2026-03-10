"""
RCSM - Root Cause Scoring Module
Patent Claim Reference:
  Claim 1(g) - scoring each network function as a potential root cause
  Claim 4    - composite scoring: centrality + temporal + Bayesian posterior
  Claim 6    - REST API integration (via FRG)

Composite score formula (Patent Claim 4):
  score(NF) = 0.4 * out_degree_centrality(NF)
            + 0.3 * temporal_precedence_score(NF)
            + 0.3 * bayesian_posterior(NF | evidence)
"""

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

try:
    from pgmpy.models import DiscreteBayesianNetwork as BayesianNetwork
    from pgmpy.factors.discrete import TabularCPD
    from pgmpy.inference import VariableElimination
    PGMPY_AVAILABLE = True
except ImportError:
    PGMPY_AVAILABLE = False
    logger.warning("pgmpy not available - Bayesian layer disabled")


@dataclass
class RootCauseCandidate:
    """A scored NF root cause candidate."""
    nf_id: str
    nf_type: str
    rank: int
    composite_score: float
    centrality_score: float
    temporal_score: float
    bayesian_score: float
    confidence: float          # 0-1
    fault_category: str        # 3GPP TS 32.111 category
    evidence: list[str]        # supporting evidence strings
    causal_path: list[str]     # NF chain leading to fault


@dataclass
class FaultReport:
    """
    Complete fault isolation report.
    Patent Claim 1(h): generating a fault report identifying root cause.
    Maps to 3GPP TS 32.111 fault categories.
    """
    report_id: str
    timestamp: str
    root_cause: RootCauseCandidate
    candidates: list[RootCauseCandidate]
    fault_category: str
    severity: str
    affected_nfs: list[str]
    causal_chain: list[str]
    recommended_action: str
    detection_latency_ms: float
    telemetry_window_cycles: int


# 3GPP TS 32.111 fault categories
FAULT_CATEGORIES = {
    "nrf":  "Communications Alarm - NF Registry Failure",
    "amf":  "Processing Error - Access Management Failure",
    "smf":  "Processing Error - Session Management Failure",
    "pcf":  "Processing Error - Policy Control Failure",
    "udm":  "Processing Error - Subscriber Data Unavailable",
    "udr":  "Processing Error - Data Repository Failure",
    "ausf": "Security Alarm - Authentication Server Failure",
    "nssf": "Processing Error - Network Slice Selection Failure",
}

RECOMMENDED_ACTIONS = {
    "nrf":  "Restart NRF immediately. Check MongoDB connectivity. Verify NF re-registration after recovery.",
    "amf":  "Restart AMF. Check N1/N2 interface. Verify UE registration recovery.",
    "smf":  "Restart SMF. Check N4 interface to UPF. Verify PDU session re-establishment.",
    "pcf":  "Restart PCF. Check N7 interface to SMF. Verify policy rule re-application.",
    "udm":  "Restart UDM. Check UDR connectivity. Verify subscriber data consistency.",
    "udr":  "Restart UDR. Check MongoDB. Rebuild UDM cache after recovery.",
    "ausf": "Restart AUSF. Check UDM connectivity. Force UE re-authentication.",
    "nssf": "Restart NSSF. Check slice configuration. Verify AMF slice selection recovery.",
}


class BayesianRootCauseLayer:
    """
    Bayesian Network for posterior probability estimation.
    Patent Claim 4: Bayesian posterior P(root_cause | evidence)

    Network structure encodes 3GPP NF dependencies:
    NRF -> AMF, SMF, PCF, UDM, AUSF, NSSF
    AMF -> AUSF
    UDM -> AUSF, UDR
    SMF -> PCF
    """

    def __init__(self):
        self.model = None
        self.inference = None
        if PGMPY_AVAILABLE:
            self._build_network()

    def _build_network(self):
        """Build Bayesian Network from 3GPP NF dependencies."""
        try:
            self.model = BayesianNetwork([
                ("NRF", "AMF"), ("NRF", "SMF"), ("NRF", "PCF"),
                ("NRF", "UDM"), ("NRF", "AUSF"), ("NRF", "NSSF"),
                ("AMF", "AUSF"), ("UDM", "AUSF"), ("SMF", "PCF"),
            ])

            # CPDs: P(NF_failure | parent_failures)
            # Prior failure probability for root nodes
            cpd_nrf = TabularCPD("NRF", 2, [[0.95], [0.05]])

            # P(AMF_fail | NRF_fail)
            cpd_amf = TabularCPD("AMF", 2,
                [[0.99, 0.30], [0.01, 0.70]],
                evidence=["NRF"], evidence_card=[2])

            # P(SMF_fail | NRF_fail)
            cpd_smf = TabularCPD("SMF", 2,
                [[0.99, 0.40], [0.01, 0.60]],
                evidence=["NRF"], evidence_card=[2])

            # P(UDM_fail | NRF_fail)
            cpd_udm = TabularCPD("UDM", 2,
                [[0.98, 0.35], [0.02, 0.65]],
                evidence=["NRF"], evidence_card=[2])

            # P(PCF_fail | NRF_fail, SMF_fail)
            cpd_pcf = TabularCPD("PCF", 2,
                [[0.99, 0.60, 0.50, 0.20],
                 [0.01, 0.40, 0.50, 0.80]],
                evidence=["NRF", "SMF"], evidence_card=[2, 2])

            # P(AUSF_fail | NRF_fail, AMF_fail, UDM_fail)
            cpd_ausf = TabularCPD("AUSF", 2,
                [[0.99, 0.70, 0.65, 0.45, 0.60, 0.35, 0.30, 0.10],
                 [0.01, 0.30, 0.35, 0.55, 0.40, 0.65, 0.70, 0.90]],
                evidence=["NRF", "AMF", "UDM"], evidence_card=[2, 2, 2])

            # P(NSSF_fail | NRF_fail)
            cpd_nssf = TabularCPD("NSSF", 2,
                [[0.99, 0.45], [0.01, 0.55]],
                evidence=["NRF"], evidence_card=[2])

            self.model.add_cpds(
                cpd_nrf, cpd_amf, cpd_smf, cpd_udm,
                cpd_pcf, cpd_ausf, cpd_nssf
            )

            if self.model.check_model():
                self.inference = VariableElimination(self.model)
                logger.info("Bayesian network built and validated")
            else:
                logger.error("Bayesian network validation failed")
                self.model = None

        except Exception as e:
            logger.error(f"Bayesian network build failed: {e}")
            self.model = None

    def get_posterior(
        self, evidence: dict[str, int]
    ) -> dict[str, float]:
        """
        Compute P(NF_failure=1 | evidence) for each NF.
        evidence: dict of {nf_name: 0/1} observed states
        Returns: dict of {nf_name: posterior_probability}
        """
        if not self.inference:
            # Fallback: uniform priors
            return {nf: 0.5 for nf in
                    ["NRF","AMF","SMF","PCF","UDM","UDR","AUSF","NSSF"]}

        posteriors = {}
        nfs = ["NRF", "AMF", "SMF", "PCF", "UDM", "AUSF", "NSSF"]

        for nf in nfs:
            try:
                # Only use evidence for nodes in the network
                valid_evidence = {
                    k: v for k, v in evidence.items()
                    if k in self.model.nodes() and k != nf
                }
                result = self.inference.query(
                    variables=[nf],
                    evidence=valid_evidence,
                    show_progress=False
                )
                posteriors[nf.lower()] = float(result.values[1])
            except Exception as e:
                logger.debug(f"Bayesian query failed for {nf}: {e}")
                posteriors[nf.lower()] = 0.5

        posteriors["udr"] = 0.3  # UDR not in BN, use prior
        return posteriors


class RootCauseScoringModule:
    """
    RCSM: Combines graph centrality, temporal precedence,
    and Bayesian posterior into a composite root cause score.

    Patent Claim 1(g): scoring each NF as potential root cause
    Patent Claim 4:    composite scoring formula
    """

    WEIGHTS = {
        "centrality": 0.4,
        "temporal":   0.3,
        "bayesian":   0.3,
    }

    def __init__(self):
        self.bayesian = BayesianRootCauseLayer()
        self.report_counter = 0

    def compute_temporal_scores(
        self, granger_result, buffer
    ) -> dict[str, float]:
        """
        Temporal precedence score: NFs that causally precede others
        with short lags score higher (they are earlier in the fault chain).
        Patent Claim 4: temporal ordering component.
        """
        scores = {nf: 0.0 for nf in
                  ["nrf","amf","smf","pcf","udm","udr","ausf","nssf"]}

        if not granger_result.links:
            return scores

        # Score based on: causes many others + short lag = likely root cause
        for link in granger_result.links:
            cause = link.cause_nf
            lag_weight = 1.0 / link.lag if link.lag > 0 else 1.0
            confidence = link.confidence
            scores[cause] = scores.get(cause, 0.0) + (
                lag_weight * confidence * (1 - link.p_value)
            )

        # Normalize to 0-1
        max_score = max(scores.values()) if scores.values() else 1.0
        if max_score > 0:
            scores = {k: v/max_score for k, v in scores.items()}

        return scores

    def build_evidence(self, buffer) -> dict[str, int]:
        """
        Build evidence dict for Bayesian inference from telemetry.
        NF is considered failed if reachability = 0.
        """
        evidence = {}
        nf_map = {
            "NRF": "nrf", "AMF": "amf", "SMF": "smf",
            "PCF": "pcf", "UDM": "udm", "AUSF": "ausf", "NSSF": "nssf"
        }
        for bn_name, nf_id in nf_map.items():
            reach = buffer.get_series(nf_id, "nf_reachability")
            if reach and len(reach) >= 3:
                # 1 = failed (reachability=0), 0 = healthy
                recent_avg = sum(reach[-3:]) / 3
                evidence[bn_name] = 1 if recent_avg < 0.5 else 0
        return evidence

    def score(
        self,
        granger_result,
        dcgm,
        buffer,
    ) -> list[RootCauseCandidate]:
        """
        Main scoring function. Combines all three components.
        Patent Claim 4: composite scoring.
        """
        start_ms = datetime.now(timezone.utc).timestamp() * 1000

        # Component 1: Graph centrality (from DCGM)
        import networkx as nx
        graph = dcgm.graph
        out_degree = nx.out_degree_centrality(graph)
        betweenness = nx.betweenness_centrality(graph, weight="weight")

        centrality_scores = {}
        for nf in graph.nodes:
            centrality_scores[nf] = (
                0.6 * out_degree.get(nf, 0) +
                0.4 * betweenness.get(nf, 0)
            )
        max_c = max(centrality_scores.values()) or 1.0
        centrality_scores = {k: v/max_c for k, v in centrality_scores.items()}

        # Component 2: Temporal precedence
        temporal_scores = self.compute_temporal_scores(granger_result, buffer)

        # Component 3: Bayesian posterior
        evidence = self.build_evidence(buffer)
        logger.info(f"Bayesian evidence: {evidence}")
        bayesian_scores = self.bayesian.get_posterior(evidence)

        # Composite score
        candidates = []
        for nf in graph.nodes:
            c = centrality_scores.get(nf, 0.0)
            t = temporal_scores.get(nf, 0.0)
            b = bayesian_scores.get(nf, 0.5)

            composite = (
                self.WEIGHTS["centrality"] * c +
                self.WEIGHTS["temporal"] * t +
                self.WEIGHTS["bayesian"] * b
            )

            # Build evidence strings
            ev_strings = []
            in_edges = [
                (u, d) for u, v, d in graph.edges(data=True)
                if v == nf and d.get("source") == "granger"
            ]
            out_edges = [
                (v, d) for u, v, d in graph.edges(data=True)
                if u == nf and d.get("source") == "granger"
            ]
            if out_edges:
                ev_strings.append(
                    f"Causes {len(out_edges)} downstream NFs"
                )
            if in_edges:
                ev_strings.append(
                    f"Influenced by {len(in_edges)} upstream NFs"
                )
            reach = buffer.get_series(nf, "nf_reachability")
            if reach and reach[-1] == 0.0:
                ev_strings.append("NF unreachable (reachability=0)")
            latency = buffer.get_series(nf, "http_response_latency_ms")
            if latency and len(latency) >= 5:
                recent = sum(latency[-3:])/3
                baseline = sum(latency[:5])/5
                if baseline > 0 and recent/baseline > 1.5:
                    ev_strings.append(
                        f"Latency elevated {recent/baseline:.1f}x baseline"
                    )

            # Causal path: NFs this NF causes
            causal_path = [nf] + [
                v for u, v, d in graph.edges(data=True)
                if u == nf and d.get("source") == "granger"
            ]

            candidates.append(RootCauseCandidate(
                nf_id=nf,
                nf_type=nf.upper(),
                rank=0,  # set after sorting
                composite_score=round(composite, 4),
                centrality_score=round(c, 4),
                temporal_score=round(t, 4),
                bayesian_score=round(b, 4),
                confidence=round(min(composite * 2, 1.0), 4),
                fault_category=FAULT_CATEGORIES.get(nf, "Unknown"),
                evidence=ev_strings,
                causal_path=causal_path,
            ))

        # Sort and rank
        candidates.sort(key=lambda x: x.composite_score, reverse=True)
        for i, c in enumerate(candidates):
            c.rank = i + 1

        end_ms = datetime.now(timezone.utc).timestamp() * 1000
        logger.info(
            f"RCSM scoring complete | "
            f"top={candidates[0].nf_id}({candidates[0].composite_score:.4f}) | "
            f"latency={end_ms-start_ms:.1f}ms"
        )
        return candidates

    def generate_report(
        self,
        candidates: list[RootCauseCandidate],
        buffer,
        granger_result,
    ) -> FaultReport:
        """
        Generate a structured fault report.
        Patent Claim 1(h): generating fault report.
        Patent Claim 6: maps to REST API response schema.
        """
        self.report_counter += 1
        root = candidates[0]

        # Find affected NFs (those with positive reachability events)
        affected = []
        for nf in ["nrf","amf","smf","pcf","udm","udr","ausf","nssf"]:
            reach = buffer.get_series(nf, "nf_reachability")
            if reach and any(v == 0.0 for v in reach[-5:]):
                affected.append(nf)

        severity = "CRITICAL" if root.composite_score > 0.6 else \
                   "HIGH" if root.composite_score > 0.4 else \
                   "MEDIUM" if root.composite_score > 0.2 else "LOW"

        return FaultReport(
            report_id=f"FR-{self.report_counter:04d}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            root_cause=root,
            candidates=candidates,
            fault_category=root.fault_category,
            severity=severity,
            affected_nfs=affected,
            causal_chain=root.causal_path,
            recommended_action=RECOMMENDED_ACTIONS.get(
                root.nf_id, "Investigate NF logs"
            ),
            detection_latency_ms=0.0,
            telemetry_window_cycles=len(buffer.timestamps),
        )


if __name__ == "__main__":
    import sys, time
    sys.path.insert(0, '/Users/krishnakumargattupalli/causal5g')
    from telemetry.collector.nf_scraper import NFScraper
    from causal.engine.granger import TelemetryBuffer, GrangerCausalityEngine
    from causal.graph.dcgm import DynamicCausalGraphManager

    logger.info("RCSM Day 4 - Root Cause Scoring Module test")

    scraper = NFScraper(scrape_interval=5)
    buffer = TelemetryBuffer(window_size=60)
    granger = GrangerCausalityEngine(max_lag=3, significance=0.05)
    dcgm = DynamicCausalGraphManager()
    rcsm = RootCauseScoringModule()

    logger.info("Collecting 20 cycles...")
    while not buffer.ready:
        events = scraper.scrape_all()
        buffer.add_events(events)
        logger.info(f"Buffer {buffer.fill_pct:.0f}%")
        time.sleep(5)

    logger.info("Running Granger...")
    result = granger.analyze(buffer)
    dcgm.update_from_granger(result)

    logger.info("Running RCSM scoring...")
    candidates = rcsm.score(result, dcgm, buffer)
    report = rcsm.generate_report(candidates, buffer, result)

    print("\n" + "="*65)
    print(f"FAULT REPORT: {report.report_id}")
    print("="*65)
    print(f"Timestamp:  {report.timestamp}")
    print(f"Severity:   {report.severity}")
    print(f"Category:   {report.fault_category}")
    print(f"Affected:   {report.affected_nfs or ['none detected']}")
    print(f"\nROOT CAUSE: {report.root_cause.nf_type}")
    print(f"  Composite score:  {report.root_cause.composite_score:.4f}")
    print(f"  Centrality:       {report.root_cause.centrality_score:.4f}")
    print(f"  Temporal:         {report.root_cause.temporal_score:.4f}")
    print(f"  Bayesian post.:   {report.root_cause.bayesian_score:.4f}")
    print(f"  Confidence:       {report.root_cause.confidence:.4f}")
    print(f"  Causal chain:     {' -> '.join(report.root_cause.causal_path)}")
    print(f"  Evidence:")
    for ev in report.root_cause.evidence:
        print(f"    - {ev}")
    print(f"\nACTION: {report.recommended_action}")
    print(f"\nALL CANDIDATES:")
    for c in candidates:
        print(
            f"  #{c.rank} {c.nf_id:6} | "
            f"composite={c.composite_score:.4f} | "
            f"C={c.centrality_score:.3f} "
            f"T={c.temporal_score:.3f} "
            f"B={c.bayesian_score:.3f}"
        )
    print("="*65)
