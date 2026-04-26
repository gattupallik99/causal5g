#!/usr/bin/env python3
"""
Day 20 — Claim 4 recalibration loop sweep.

Demonstrates the full closed loop offline:
  RAE outcome signal → recalibrator.recalibrate() → DCGM.apply_recalibration()
  → edge weights shift → next RCSM centrality pass sees updated graph.

Run: python evidence/day20/day20_sweep.py
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from causal.engine.recalibrator import GrangerPCFusionRecalibrator, RecalibrationConfig
from causal.graph.dcgm import DynamicCausalGraphManager
from causal.engine.rcsm import FaultReport, RootCauseCandidate

def _entry(nf, outcome, scenario=None):
    return {"fault_scenario": scenario or f"{nf}_crash",
            "root_cause_nf": nf, "action": "restart_pod",
            "outcome": outcome, "timestamp": time.time(), "slice_id": None}

def run():
    print("\n" + "="*70)
    print("Day 20 — Claim 4 Recalibration Loop Sweep")
    print("="*70)

    results = {}

    # ── Scenario A: 3× successful NRF remediation ──────────────────────
    recal = GrangerPCFusionRecalibrator(RecalibrationConfig(
        learning_rate=0.10, min_feedback_count=1))
    dcgm  = DynamicCausalGraphManager()

    nrf_amf_before = dcgm.graph["nrf"]["amf"]["weight"]
    feedback = [_entry("nrf", 1.0, "nrf_crash")] * 3
    summary  = recal.recalibrate(feedback)
    n_edges  = dcgm.apply_recalibration(recal.get_all_weights())
    nrf_amf_after = dcgm.graph["nrf"]["amf"]["weight"]

    results["success_3x_nrf"] = {
        "scenario": "3× successful NRF remediation",
        "cycles": summary["cycle"], "entries": summary["entries_consumed"],
        "edges_adjusted_recalibrator": summary["edges_adjusted"],
        "dcgm_edges_updated": n_edges,
        "nrf_amf_weight_before": round(nrf_amf_before, 4),
        "nrf_amf_weight_after":  round(nrf_amf_after, 4),
        "delta": round(nrf_amf_after - nrf_amf_before, 4),
        "direction": "reinforced" if nrf_amf_after > nrf_amf_before else "penalised",
    }
    print(f"\n[A] 3× NRF success | nrf→amf: {nrf_amf_before:.4f} → {nrf_amf_after:.4f} "
          f"(Δ{nrf_amf_after-nrf_amf_before:+.4f}) | {n_edges} DCGM edges updated")

    # ── Scenario B: 3× failed PCF remediation ──────────────────────────
    recal2 = GrangerPCFusionRecalibrator(RecalibrationConfig(
        learning_rate=0.10, min_feedback_count=1))
    dcgm2  = DynamicCausalGraphManager()
    import networkx as nx

    pcf_smf_before = dcgm2.graph["pcf"]["smf"]["weight"] if dcgm2.graph.has_edge("pcf","smf") else None
    feedback2 = [_entry("pcf", 0.0, "pcf_timeout")] * 3
    summary2  = recal2.recalibrate(feedback2)
    dcgm2.apply_recalibration(recal2.get_all_weights())
    pcf_smf_after = dcgm2.graph["pcf"]["smf"]["weight"] if dcgm2.graph.has_edge("pcf","smf") else None

    results["failure_3x_pcf"] = {
        "scenario": "3× failed PCF remediation",
        "pcf_smf_weight_before": round(pcf_smf_before, 4) if pcf_smf_before else None,
        "pcf_smf_weight_after":  round(pcf_smf_after, 4) if pcf_smf_after else None,
        "all_recal_weights": {f"{c}→{e}": round(w, 4) for (c,e),w in recal2.get_all_weights().items()},
        "stats": recal2.get_stats(),
    }
    if pcf_smf_before and pcf_smf_after:
        print(f"[B] 3× PCF failure | pcf→smf: {pcf_smf_before:.4f} → {pcf_smf_after:.4f} "
              f"(Δ{pcf_smf_after-pcf_smf_before:+.4f}) penalised")

    # ── Scenario C: FaultReport carries recalibration_snapshot ─────────
    rc = RootCauseCandidate(nf_id="nrf", nf_type="NRF", rank=1,
        composite_score=1.01, centrality_score=0.5, temporal_score=0.3,
        bayesian_score=0.4, confidence=1.0,
        fault_category="Comms Alarm", evidence=[], causal_path=["nrf"])
    report = FaultReport(
        report_id="FR-DAY20", timestamp="2026-04-26T00:00:00Z",
        root_cause=rc, candidates=[rc], fault_category="Comms Alarm",
        severity="CRITICAL", affected_nfs=["nrf"], causal_chain=["nrf"],
        recommended_action="Restart NRF",
        detection_latency_ms=0.0, telemetry_window_cycles=60,
        recalibration_snapshot=recal.get_stats())
    assert report.recalibration_snapshot["cycle_count"] == 1
    results["report_snapshot"] = {
        "report_id": report.report_id,
        "recalibration_cycle": report.recalibration_snapshot["cycle_count"],
        "edges_tracked": report.recalibration_snapshot["edges_tracked"],
        "reinforced": report.recalibration_snapshot["reinforced_edges"],
    }
    print(f"[C] FaultReport.recalibration_snapshot | cycle={report.recalibration_snapshot['cycle_count']} "
          f"| edges_tracked={report.recalibration_snapshot['edges_tracked']}")

    # assertions
    assert results["success_3x_nrf"]["nrf_amf_weight_after"] > nrf_amf_before, "NRF reinforce failed"
    if pcf_smf_after:
        assert pcf_smf_after < pcf_smf_before, "PCF penalise failed"
    print("\n✓ NRF 3× success → nrf→amf weight reinforced")
    print("✓ PCF 3× failure → pcf→smf weight penalised (if edge exists)")
    print("✓ FaultReport.recalibration_snapshot populated correctly")

    # Save
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    (out / "day20_sweep_full.json").write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out}/day20_sweep_full.json")
    print("="*70)
    print("Day 20 sweep PASSED — Claim 4 recalibration loop operational.")
    print("="*70)

if __name__ == "__main__":
    run()
