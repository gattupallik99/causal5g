# nrf_crash — Day 16 evidence

- **inject_timestamp_utc:** 2026-04-26T13:04:41Z
- **expected_root_cause_nf:** nrf
- **detected_root_cause_nf:** nrf
- **match:** HIT
- **composite_score:** 1.01
- **confidence:** 1.0
- **severity:** CRITICAL
- **remediation_action:** restart_pod
- **remediation_status:** success
- **outcome_signal:** 1.0
- **detection_latency_s:** 30

## Files
- inject_response.json
- rca.json
- remediate_response.json
- remediation_history.json
- metrics_before.txt / metrics_after.txt
- nfs_status_before.json / nfs_status_after.json
- health_before.json / health_after.json

## Patent claim mapping
- **Claim 1** (bi-level DAG, NF-layer attribution): rca.json → root_cause.nf_id, all_candidates, composite_score
- **Claim 2** (four-domain RCA report): rca.json → severity, fault_category, causal_chain, affected_nfs
- **Claim 3** (confidence-gated remediation): remediate_response.json → action, status, skipped_reason
- **Claim 4** (feedback recalibration): outcome_signal feeds the GrangerPCFusionRecalibrator
