"""
DCGM - Dynamic Causal Graph Manager
Patent Claim Reference:
  Claim 1(e) - constructing and dynamically updating a causal graph G=(V,E)
  Claim 4    - computing graph-theoretic centrality scores
  Claim 5    - maintaining historical graph buffer
"""

import networkx as nx
import json
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional
from loguru import logger


@dataclass
class GraphSnapshot:
    """A point-in-time snapshot of the causal graph."""
    timestamp: str
    nodes: list[dict]
    edges: list[dict]
    anomaly_scores: dict[str, float]


class DynamicCausalGraphManager:
    """
    Maintains a directed weighted causal graph G=(V,E) where:
      V = set of 5G NFs (AMF, SMF, PCF, UDM, UDR, AUSF, NSSF, NRF)
      E = causal links discovered by CIE with weight = confidence score

    Patent Claim 1(e): constructing a dynamic causal graph
    Patent Claim 5: maintaining historical graph buffer
    """

    NF_COLORS = {
        "nrf":  "#FF6B6B",  # Red - registry, most critical
        "amf":  "#4ECDC4",  # Teal - access management
        "smf":  "#45B7D1",  # Blue - session management
        "pcf":  "#96CEB4",  # Green - policy
        "udm":  "#FFEAA7",  # Yellow - user data
        "udr":  "#DDA0DD",  # Plum - data repository
        "ausf": "#98D8C8",  # Mint - authentication
        "nssf": "#F7DC6F",  # Gold - slice selection
    }

    # 3GPP-defined NF dependency priors (Patent Claim 7)
    # These seed the graph before causal discovery
    DEPENDENCY_PRIORS = [
        ("nrf", "amf",  0.9),
        ("nrf", "smf",  0.9),
        ("nrf", "pcf",  0.9),
        ("nrf", "udm",  0.9),
        ("nrf", "ausf", 0.9),
        ("nrf", "nssf", 0.9),
        ("amf", "smf",  0.8),
        ("amf", "ausf", 0.7),
        ("udm", "ausf", 0.8),
        ("udm", "udr",  0.9),
        ("smf", "pcf",  0.7),
        ("smf", "udm",  0.6),
    ]

    def __init__(self, history_size: int = 10):
        self.graph = nx.DiGraph()
        self.history: list[GraphSnapshot] = []
        self.history_size = history_size
        self._init_graph()

    def _init_graph(self):
        """Initialize graph with all 8 NF nodes and 3GPP priors."""
        # Add NF nodes
        for nf in self.NF_COLORS:
            self.graph.add_node(nf, nf_type=nf.upper(),
                                color=self.NF_COLORS[nf],
                                anomaly_score=0.0)

        # Seed with 3GPP dependency priors (low weight)
        for src, dst, weight in self.DEPENDENCY_PRIORS:
            self.graph.add_edge(
                src, dst,
                weight=weight * 0.3,  # Prior weight (weak)
                source="3gpp_prior",
                p_value=None,
                confidence=weight * 0.3,
            )

        logger.info(
            f"DCGM initialized: {self.graph.number_of_nodes()} nodes, "
            f"{self.graph.number_of_edges()} edges (priors)"
        )

    def update_from_granger(self, granger_result) -> int:
        """
        Update causal graph with new Granger causality results.
        Patent Claim 1(e): dynamically updating the causal graph.
        Returns number of edges updated.
        """
        updated = 0
        for link in granger_result.links:
            src = link.cause_nf
            dst = link.effect_nf
            weight = link.confidence

            if self.graph.has_edge(src, dst):
                # Blend existing weight with new evidence
                old_weight = self.graph[src][dst]["weight"]
                new_weight = 0.6 * old_weight + 0.4 * weight
                self.graph[src][dst].update({
                    "weight": round(new_weight, 4),
                    "source": "granger",
                    "p_value": link.p_value,
                    "confidence": round(weight, 4),
                    "lag": link.lag,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                })
            else:
                self.graph.add_edge(
                    src, dst,
                    weight=round(weight, 4),
                    source="granger",
                    p_value=link.p_value,
                    confidence=round(weight, 4),
                    lag=link.lag,
                    last_updated=datetime.now(timezone.utc).isoformat(),
                )
            updated += 1

        logger.info(
            f"DCGM updated: {updated} edges from Granger | "
            f"total edges={self.graph.number_of_edges()}"
        )
        return updated

    def apply_recalibration(
        self,
        edge_weights: dict[tuple[str, str], float],
    ) -> int:
        """
        Apply feedback-recalibrated edge weight multipliers to the live graph.

        Patent Claim 4: feedback-driven DAG recalibration. After the
        GrangerPCFusionRecalibrator processes RAE outcome signals, it produces
        an updated {(cause, effect): multiplier} dict. This method multiplies
        each existing DCGM edge weight by the corresponding multiplier, then
        clamps to a safe range, so subsequent centrality computations in RCSM
        reflect the accumulated remediation outcome evidence.

        Self-loops (nf, nf) from the recalibrator are skipped — DCGM carries
        no self-loops.

        Args:
            edge_weights: {(cause_nf, effect_nf): multiplier} from recalibrator.
                          1.0 = neutral, >1.0 = reinforced, <1.0 = penalised.

        Returns:
            Number of DCGM edges that were updated.
        """
        _WEIGHT_MIN = 0.05
        _WEIGHT_MAX = 5.0
        updated = 0
        for (cause, effect), multiplier in edge_weights.items():
            if cause == effect:          # skip self-loops
                continue
            if not self.graph.has_edge(cause, effect):
                continue
            old = self.graph[cause][effect]["weight"]
            new = max(_WEIGHT_MIN, min(_WEIGHT_MAX, old * multiplier))
            self.graph[cause][effect].update({
                "weight":       round(new, 4),
                "recal_weight": round(multiplier, 4),
                "source":       "recalibrated",
                "last_recal":   datetime.now(timezone.utc).isoformat(),
            })
            updated += 1
        if updated:
            logger.info(
                f"DCGM recalibration applied: {updated} edges updated"
            )
        return updated

    def compute_anomaly_scores(
        self, telemetry_buffer
    ) -> dict[str, float]:
        """
        Compute anomaly score per NF using:
          - Out-degree centrality (causal influence)
          - Betweenness centrality (bridge node importance)
          - Recent latency deviation

        Patent Claim 4: graph-theoretic scoring methods
        Patent Claim 1(f): detecting anomalous patterns
        """
        scores = {}

        # Graph centrality scores
        out_degree = nx.out_degree_centrality(self.graph)
        betweenness = nx.betweenness_centrality(self.graph, weight="weight")
        pagerank = nx.pagerank(self.graph, weight="weight", alpha=0.85)

        for nf in self.graph.nodes:
            # Telemetry-based score: latency deviation
            latency_series = telemetry_buffer.get_series(
                nf, "http_response_latency_ms"
            )
            latency_score = 0.0
            if latency_series and len(latency_series) >= 5:
                recent = latency_series[-5:]
                baseline = latency_series[:-5] if len(latency_series) > 5 \
                    else recent
                mean_baseline = sum(baseline) / len(baseline)
                mean_recent = sum(recent) / len(recent)
                if mean_baseline > 0:
                    latency_score = min(
                        (mean_recent - mean_baseline) / mean_baseline, 1.0
                    )
                    latency_score = max(latency_score, 0.0)

            # Composite score: 0.4 graph + 0.3 betweenness + 0.3 latency
            composite = (
                0.4 * out_degree.get(nf, 0) +
                0.3 * betweenness.get(nf, 0) +
                0.3 * latency_score
            )
            scores[nf] = round(composite, 4)
            self.graph.nodes[nf]["anomaly_score"] = scores[nf]

        return scores

    def get_root_cause_ranking(
        self, scores: dict[str, float]
    ) -> list[tuple[str, float]]:
        """
        Rank NFs by anomaly score descending.
        Patent Claim 1(g): scoring each NF as potential root cause.
        """
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked

    def snapshot(self) -> GraphSnapshot:
        """Save current graph state to history buffer."""
        snap = GraphSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            nodes=[
                {"id": n, **self.graph.nodes[n]}
                for n in self.graph.nodes
            ],
            edges=[
                {"src": u, "dst": v, **self.graph[u][v]}
                for u, v in self.graph.edges
            ],
            anomaly_scores={
                n: self.graph.nodes[n].get("anomaly_score", 0.0)
                for n in self.graph.nodes
            },
        )
        self.history.append(snap)
        if len(self.history) > self.history_size:
            self.history.pop(0)
        return snap

    def print_graph(self, scores: dict[str, float]):
        """Pretty print the current causal graph state."""
        print("\n" + "="*65)
        print("DYNAMIC CAUSAL GRAPH - CURRENT STATE")
        print("="*65)
        print(f"Nodes: {self.graph.number_of_nodes()} NFs")
        print(f"Edges: {self.graph.number_of_edges()} causal links")
        print()

        print("ROOT CAUSE RANKING (anomaly score):")
        ranked = self.get_root_cause_ranking(scores)
        for rank, (nf, score) in enumerate(ranked, 1):
            bar = "█" * int(score * 40)
            print(f"  #{rank} {nf:6} | score={score:.4f} | {bar}")

        print()
        print("CAUSAL EDGES (Granger-discovered):")
        granger_edges = [
            (u, v, d) for u, v, d in self.graph.edges(data=True)
            if d.get("source") == "granger"
        ]
        if granger_edges:
            for src, dst, data in sorted(
                granger_edges, key=lambda x: x[2]["weight"], reverse=True
            ):
                print(
                    f"  {src:6} --({data['weight']:.3f})--> {dst:6} | "
                    f"p={data.get('p_value','?')} | "
                    f"lag={data.get('lag','?')}"
                )
        else:
            print("  No Granger edges yet")

        print()
        print("3GPP PRIOR EDGES (top 5 by weight):")
        prior_edges = [
            (u, v, d) for u, v, d in self.graph.edges(data=True)
            if d.get("source") == "3gpp_prior"
        ]
        for src, dst, data in sorted(
            prior_edges, key=lambda x: x[2]["weight"], reverse=True
        )[:5]:
            print(f"  {src:6} --({data['weight']:.3f})--> {dst:6}")
        print("="*65)


if __name__ == "__main__":
    import sys
    import time
    sys.path.insert(0, '/Users/krishnakumargattupalli/causal5g')
    from telemetry.collector.nf_scraper import NFScraper
    from causal.engine.granger import (
        TelemetryBuffer, GrangerCausalityEngine
    )

    logger.info("DCGM Day 3 - Building live causal graph...")

    scraper = NFScraper(scrape_interval=5)
    buffer = TelemetryBuffer(window_size=60)
    granger = GrangerCausalityEngine(max_lag=5, significance=0.05)
    dcgm = DynamicCausalGraphManager(history_size=10)

    logger.info("Collecting 20 cycles of telemetry (~100s)...")
    cycle = 0
    while not buffer.ready:
        events = scraper.scrape_all()
        buffer.add_events(events)
        cycle += 1
        logger.info(
            f"Cycle {cycle}/20 | "
            f"buffer={buffer.fill_pct:.0f}% | "
            f"series={len(buffer.series)}"
        )
        time.sleep(5)

    logger.info("Running Granger analysis...")
    result = granger.analyze(buffer)

    logger.info("Updating causal graph...")
    dcgm.update_from_granger(result)

    logger.info("Computing anomaly scores...")
    scores = dcgm.compute_anomaly_scores(buffer)

    # Print the graph
    dcgm.print_graph(scores)

    # Save snapshot
    snap = dcgm.snapshot()
    with open("/tmp/causal_graph_snapshot.json", "w") as f:
        import numpy as np
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer): return int(obj)
            if isinstance(obj, np.floating): return float(obj)
            return super().default(obj)
    json.dump(asdict(snap), f, indent=2, cls=NpEncoder)
    logger.info("Snapshot saved to /tmp/causal_graph_snapshot.json")

    # Export as GraphML for visualization
    nx.write_graphml(
        dcgm.graph,
        "/tmp/causal5g_graph.graphml"
    )
    logger.info("GraphML exported to /tmp/causal5g_graph.graphml")
