# Day 16 — Live Fault Sweep Evidence

Evidence bundle capturing end-to-end reduction-to-practice for patent
claims 1–4 against the live Free5GC cloud-native 5G core.

Generated: 2026-04-21T04:16:51Z
API base: `http://localhost:8080`

## Summary

| scenario | expected | detected | match | composite | confidence | severity | action | status | outcome | detect_s |
|---|---|---|---|---|---|---|---|---|---|---|
| nrf_crash | nrf | nrf | HIT | 0.85 | 1.0 | CRITICAL | restart_pod | success | 1.0 | 1 |
| amf_crash | amf | nrf | MISS | 1.0 | 1.0 | CRITICAL | restart_pod | success | 1.0 | 1 |
| smf_crash | smf | nrf | MISS | 1.0 | 1.0 | CRITICAL | restart_pod | success | 1.0 | 1 |
| pcf_timeout | pcf | nrf | MISS | 1.0 | 1.0 | CRITICAL | rollback_config | success | 1.0 | 1 |
| udm_crash | udm | nrf | MISS | 1.0 | 1.0 | CRITICAL | restart_pod | success | 1.0 | 1 |

## Claim mapping

- **Claim 1** (bi-level causal DAG, NF-layer + slice-layer attribution) — every `rca.json` exercises the NF-layer root-cause pick against a known ground truth. Match column = HIT when the detected NF equals the injected target.
- **Claim 2** (four-domain RCA report artifact) — every `rca.json` contains the severity, fault_category, causal_chain, and affected_nfs fields the claim specifies.
- **Claim 3** (confidence-gated closed-loop remediation with persistent policy table and pluggable orchestrator adapter) — every `remediate_response.json` shows the gate decision (action + status, or skipped_reason when rcsm_score < threshold) and `remediation_history.json` shows the persistent record.
- **Claim 4** (feedback-driven DAG recalibration) — `outcome_signal` on each remediation record is the signal the `GrangerPCFusionRecalibrator` consumes.

## Reproducing

```
uvicorn api.frg:app --port 8080 &
bash scripts/day16_fault_sweep.sh
```

Environment overrides: `BASE`, `OUT`, `WAIT_DETECT`, `WAIT_REMED`, `WAIT_RECOVER`, `SETTLE_BETWEEN`.
