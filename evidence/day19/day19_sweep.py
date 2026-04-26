#!/usr/bin/env python3
"""
Day 19 — End-to-end sweep: Level-2 slice attribution wired into FaultReport.

This script simulates the full pipeline_loop() wiring added in Day 19:
  1. For each of the 5 fault scenarios, build a realistic FaultReport
     (as the RCSM would produce post-injection).
  2. Call SliceEnsembleAttributor.attribute() — the Level-2 call now
     embedded in frg.py after every generate_report().
  3. Attach the SliceAttribution dict to report.slice_attribution.
  4. Serialise via report_to_dict() (the GET /rca / GET /faults/active schema).
  5. Verify the Day 19 headline assertion:
       pcf_timeout → slice_breadth ≈ 0.667, isolation_type = slice-isolated
  6. Save results to evidence/day19/results/.

Run without live containers (offline topology-based sweep).
Live API verification steps are documented at the bottom of this script.

Usage:
    python evidence/day19/day19_sweep.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Make sure the repo root is on the path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from causal.engine.rcsm import FaultReport, RootCauseCandidate
from causal5g.causal.slice_ensemble import SliceEnsembleAttributor, SliceAttribution
from causal5g.slice_topology import SliceTopologyManager

# ---------------------------------------------------------------------------
# Test scenarios — representative of Day 17 live NF-layer outputs
# ---------------------------------------------------------------------------

SCENARIOS = [
    {"scenario": "nrf_crash",   "nf": "nrf",  "nf_layer_score": 1.01},
    {"scenario": "amf_crash",   "nf": "amf",  "nf_layer_score": 1.01},
    {"scenario": "smf_crash",   "nf": "smf",  "nf_layer_score": 1.01},
    {"scenario": "pcf_timeout", "nf": "pcf",  "nf_layer_score": 1.01},
    {"scenario": "udm_crash",   "nf": "udm",  "nf_layer_score": 1.01},
]

FAULT_CATEGORIES = {
    "nrf": "Communications Alarm - NF Registry Failure",
    "amf": "Processing Error - Access Management Failure",
    "smf": "Processing Error - Session Management Failure",
    "pcf": "Processing Error - Policy Control Failure",
    "udm": "Processing Error - Subscriber Data Unavailable",
}


def make_candidate(nf: str, score: float) -> RootCauseCandidate:
    return RootCauseCandidate(
        nf_id=nf,
        nf_type=nf.upper(),
        rank=1,
        composite_score=score,
        centrality_score=0.5,
        temporal_score=0.3,
        bayesian_score=0.4,
        confidence=min(score * 2, 1.0),
        fault_category=FAULT_CATEGORIES.get(nf, "Unknown"),
        evidence=[f"{nf.upper()} unreachable (reachability=0)", "Container exited"],
        causal_path=[nf],
    )


def make_report(nf: str, score: float) -> FaultReport:
    rc = make_candidate(nf, score)
    return FaultReport(
        report_id=f"FR-{nf.upper()}-DAY19",
        timestamp=datetime.now(timezone.utc).isoformat(),
        root_cause=rc,
        candidates=[rc],
        fault_category=rc.fault_category,
        severity="CRITICAL",
        affected_nfs=[nf],
        causal_chain=[nf],
        recommended_action=f"Restart {nf.upper()}",
        detection_latency_ms=0.0,
        telemetry_window_cycles=60,
        slice_attribution=None,   # populated by Level-2 below
    )


def report_to_dict(report: FaultReport) -> dict:
    """Mirror of frg.report_to_dict() — the GET /rca response schema."""
    return {
        "report_id": report.report_id,
        "timestamp": report.timestamp,
        "severity": report.severity,
        "fault_category": report.fault_category,
        "affected_nfs": report.affected_nfs,
        "causal_chain": report.causal_chain,
        "recommended_action": report.recommended_action,
        "telemetry_window_cycles": report.telemetry_window_cycles,
        "root_cause": {
            "nf_id": report.root_cause.nf_id,
            "nf_type": report.root_cause.nf_type,
            "rank": report.root_cause.rank,
            "composite_score": report.root_cause.composite_score,
            "centrality_score": report.root_cause.centrality_score,
            "temporal_score": report.root_cause.temporal_score,
            "bayesian_score": report.root_cause.bayesian_score,
            "confidence": report.root_cause.confidence,
            "fault_category": report.root_cause.fault_category,
            "evidence": report.root_cause.evidence,
            "causal_path": report.root_cause.causal_path,
        },
        "all_candidates": [
            {
                "nf_id": c.nf_id,
                "rank": c.rank,
                "composite_score": c.composite_score,
                "centrality_score": c.centrality_score,
                "temporal_score": c.temporal_score,
                "bayesian_score": c.bayesian_score,
                "confidence": c.confidence,
            }
            for c in report.candidates
        ],
        "slice_attribution": report.slice_attribution,
    }


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------

def run_sweep():
    sea = SliceEnsembleAttributor(stm=SliceTopologyManager())
    results = []

    print("\n" + "=" * 72)
    print("Day 19 — Level-2 slice attribution wired into FaultReport (/rca)")
    print("=" * 72)
    print(f"Run time: {datetime.now(timezone.utc).isoformat()}")
    print()

    for sc in SCENARIOS:
        nf    = sc["nf"]
        score = sc["nf_layer_score"]

        # 1. Build the FaultReport (as RCSM.generate_report() would)
        report = make_report(nf, score)

        # 2. Level-2: SliceEnsembleAttributor.attribute() (new Day 19 wiring)
        attr = sea.attribute(root_cause_nf=nf, nf_layer_score=score)

        # 3. Attach to FaultReport.slice_attribution (new Day 19 field)
        report.slice_attribution = attr.to_dict()

        # 4. Serialise (GET /rca response)
        d = report_to_dict(report)

        results.append({
            "scenario":        sc["scenario"],
            "nf":              nf,
            "nf_layer_score":  score,
            "report_id":       report.report_id,
            "timestamp":       report.timestamp,
            "severity":        report.severity,
            "slice_attribution": report.slice_attribution,
            "rca_response":    d,
        })

        sa = report.slice_attribution
        print(
            f"  {sc['scenario']:14s} | nf={nf:3s} | "
            f"nf_score={score:.3f} | "
            f"breadth={sa['slice_breadth']:.4f} ({sa['n_slices_affected']}/{sa['n_slices_total']}) | "
            f"type={sa['isolation_type']:20s} | "
            f"ensemble={sa['ensemble_score']:.4f}"
        )

    # Headline assertion: pcf_timeout is slice-isolated with breadth ≈ 0.667
    pcf = next(r for r in results if r["scenario"] == "pcf_timeout")
    sa_pcf = pcf["slice_attribution"]
    assert abs(sa_pcf["slice_breadth"] - 2/3) < 1e-4, (
        f"ASSERTION FAILED: pcf_timeout slice_breadth={sa_pcf['slice_breadth']}"
    )
    assert sa_pcf["isolation_type"] == "slice-isolated", (
        f"ASSERTION FAILED: pcf_timeout isolation_type={sa_pcf['isolation_type']}"
    )

    nrf = next(r for r in results if r["scenario"] == "nrf_crash")
    sa_nrf = nrf["slice_attribution"]
    assert sa_nrf["slice_breadth"] == 1.0
    assert sa_nrf["isolation_type"] == "infrastructure-wide"

    print()
    print("✓ pcf_timeout: slice_breadth=0.6667, isolation_type=slice-isolated")
    print("✓ nrf_crash:   slice_breadth=1.0000, isolation_type=infrastructure-wide")
    print()

    # per-slice breakdown for pcf_timeout
    print("pcf_timeout per-slice breakdown:")
    print(f"  {'Slice ID':10s}  {'Label':6s}  {'PCF present':12s}  {'Path weight':11s}  Nodes  Edges")
    for ps in sa_pcf["per_slice"]:
        print(
            f"  {ps['slice_id']:10s}  {ps['label']:6s}  "
            f"{'YES' if ps['nf_present'] else 'NO':12s}  "
            f"{ps['path_weight']:11.1f}  "
            f"{ps['node_count']:5d}  {ps['edge_count']:5d}"
        )

    return results


def save_results(results):
    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Full JSON
    full_path = out_dir / "day19_sweep_full.json"
    with open(full_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {full_path}")

    # pcf_timeout /rca response (the key verification artefact)
    pcf = next(r for r in results if r["scenario"] == "pcf_timeout")
    pcf_path = out_dir / "pcf_timeout_rca_response.json"
    with open(pcf_path, "w") as f:
        json.dump(pcf["rca_response"], f, indent=2)
    print(f"Saved: {pcf_path}")

    # Summary TSV
    tsv_path = out_dir / "summary.tsv"
    with open(tsv_path, "w") as f:
        f.write("scenario\tnf\tnf_layer_score\tslice_breadth\tn_affected\tn_total\tisolation_type\tensemble_score\n")
        for r in results:
            sa = r["slice_attribution"]
            f.write(
                f"{r['scenario']}\t{r['nf']}\t{r['nf_layer_score']:.4f}\t"
                f"{sa['slice_breadth']:.4f}\t{sa['n_slices_affected']}\t{sa['n_slices_total']}\t"
                f"{sa['isolation_type']}\t{sa['ensemble_score']:.4f}\n"
            )
    print(f"Saved: {tsv_path}")

    print()
    print("=" * 72)
    print("Day 19 sweep PASSED — Level-2 slice attribution correctly wired.")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Live API verification instructions
# ---------------------------------------------------------------------------

LIVE_VERIFICATION = """
Live API verification (requires running containers):

  # Start the API
  cd /Users/krishnakumargattupalli/causal5g
  uvicorn api.frg:app --host 0.0.0.0 --port 8080 --reload &

  # Wait for pipeline to warm up (buffer needs ~10 cycles = ~50s)
  sleep 60

  # Inject pcf_timeout
  curl -s -X POST http://localhost:8080/faults/inject/pcf_timeout | python3 -m json.tool

  # Wait for next analysis cycle (~30s)
  sleep 35

  # Fetch /rca — verify Level-2 slice attribution in the response
  curl -s http://localhost:8080/rca | python3 -m json.tool | grep -A 15 slice_attribution

  # Expected output includes:
  #   "slice_breadth": 0.6667,
  #   "isolation_type": "slice-isolated",
  #   "ensemble_score": 0.8,
  #   "n_slices_affected": 2,
  #   "n_slices_total": 3

  # Also available at:
  #   GET /faults/active  (same report, backward-compat endpoint)
"""

if __name__ == "__main__":
    results = run_sweep()
    save_results(results)
    print(LIVE_VERIFICATION)
