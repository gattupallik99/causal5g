#!/usr/bin/env bash
# Day 16 fault sweep — captures reduction-to-practice evidence for
# patent claims 1, 2, 3, 4 across all five FaultInjector scenarios.
#
# Prereqs on the Mac:
#   - uvicorn api.frg:app --port 8080 is running against a live Free5GC
#   - docker containers causal5g-{nrf,amf,smf,pcf,udm,...} are up
#   - jq is installed (brew install jq)
#
# Usage:
#   bash scripts/day16_fault_sweep.sh              # default: localhost:8080
#   BASE=http://1.2.3.4:8080 bash scripts/...      # override endpoint
#   WAIT_DETECT=60 bash scripts/...                # shorten detection wait
#
# Output:
#   evidence/day16/<scenario>/  (per-scenario bundle)
#   evidence/day16/summary.tsv  (table for README)

set -euo pipefail

BASE="${BASE:-http://localhost:8080}"
OUT="${OUT:-evidence/day16}"
WAIT_DETECT="${WAIT_DETECT:-90}"
WAIT_REMED="${WAIT_REMED:-20}"
WAIT_RECOVER="${WAIT_RECOVER:-20}"
SETTLE_BETWEEN="${SETTLE_BETWEEN:-30}"

SCENARIOS=(nrf_crash amf_crash smf_crash pcf_timeout udm_crash)

# ---- preflight ----
command -v jq >/dev/null 2>&1 || {
  echo "ERROR: jq not installed. brew install jq" >&2
  exit 2
}
if ! curl -sf "$BASE/health" >/dev/null; then
  echo "ERROR: API not reachable at $BASE. Start uvicorn first:" >&2
  echo "  uvicorn api.frg:app --port 8080" >&2
  exit 3
fi

mkdir -p "$OUT"
summary="$OUT/summary.tsv"
printf 'scenario\texpected_nf\tdetected_nf\tmatch\tcomposite\tconfidence\tseverity\taction\tstatus\toutcome\tdetect_s\n' > "$summary"

echo "Day 16 sweep → $OUT (base=$BASE)"
echo "Scenarios: ${SCENARIOS[*]}"
echo

for S in "${SCENARIOS[@]}"; do
  DIR="$OUT/$S"
  mkdir -p "$DIR"
  printf '═══ %s ═══\n' "$S"

  # Expected root-cause NF per FaultInjector.SCENARIOS
  expected_nf=$(curl -sf "$BASE/faults/scenarios" \
    | jq -r ".scenarios.\"$S\".target_nf // \"?\"")

  # 1) Before snapshots
  curl -sf "$BASE/metrics"      > "$DIR/metrics_before.txt"
  curl -sf "$BASE/nfs/status"   > "$DIR/nfs_status_before.json"
  curl -sf "$BASE/health"       > "$DIR/health_before.json"

  # Capture the baseline report_id so we can distinguish the
  # pre-injection steady-state report from a genuine post-injection one.
  baseline_report_id=$(curl -sf "$BASE/faults/active" \
    | jq -r '.report.report_id // empty' 2>/dev/null || echo "")
  t_inject=$(date -u +%FT%TZ)

  # 2) Inject
  curl -sf -X POST "$BASE/faults/inject/$S" > "$DIR/inject_response.json"
  echo "  injected at $t_inject (expected root cause: $expected_nf, baseline_report=${baseline_report_id:-none})"

  # 3) Poll /faults/active until a NEW report (different id AND timestamp
  # strictly after t_inject) names a root cause. This is the honest
  # post-injection detection path; the older approach of polling for
  # "any report with a root_cause" captured whatever steady-state report
  # the pipeline had already generated before injection, which on the
  # NRF-centric topology is always "nrf".
  detected_nf=""; composite="0"; confidence="0"; severity=""; detect_s=0
  for i in $(seq "$WAIT_DETECT"); do
    active=$(curl -sf "$BASE/faults/active" || printf '{}')
    rid=$(printf '%s'  "$active" | jq -r '.report.report_id // empty')
    rts=$(printf '%s'  "$active" | jq -r '.report.timestamp // empty')
    rc_nf=$(printf '%s' "$active" | jq -r '.report.root_cause.nf_id // empty')
    # Must be a different report AND newer than the injection moment.
    if [ -n "$rc_nf" ] && [ "$rid" != "$baseline_report_id" ] \
       && [ -n "$rts" ] && [ "$rts" \> "$t_inject" ]; then
      printf '%s' "$active" > "$DIR/rca.json"
      detected_nf="$rc_nf"
      composite=$(printf '%s' "$active" | jq -r '.report.root_cause.composite_score // 0')
      confidence=$(printf '%s' "$active" | jq -r '.report.root_cause.confidence // 0')
      severity=$(printf '%s' "$active"  | jq -r '.report.severity // "?"')
      detect_s=$i
      break
    fi
    sleep 1
  done

  if [ -n "$detected_nf" ]; then
    echo "  detected $detected_nf in ${detect_s}s (composite=$composite, conf=$confidence, sev=$severity)"
  else
    echo "  no detection within ${WAIT_DETECT}s — proceeding"
  fi

  # 4) Trigger remediation if we have a diagnosis
  action="none"; status="no_diagnosis"; outcome="n/a"
  if [ -n "$detected_nf" ]; then
    req=$(jq -nc \
      --arg s "$S" \
      --arg nf "$detected_nf" \
      --argjson c "$composite" \
      '{fault_scenario:$s, root_cause_nf:$nf, rcsm_score:$c}')
    if curl -sf -X POST "$BASE/remediate" \
        -H 'content-type: application/json' \
        -d "$req" > "$DIR/remediate_response.json"; then
      action=$(jq -r '.action // "none"' < "$DIR/remediate_response.json")
      status=$(jq -r '.status // "unknown"' < "$DIR/remediate_response.json")
      outcome=$(jq -r '.outcome_signal // "n/a"' < "$DIR/remediate_response.json")
      echo "  remediation: action=$action status=$status outcome=$outcome"
    else
      echo "  remediation POST failed"
      status="api_error"
    fi
    sleep "$WAIT_REMED"
  fi

  # 5) After snapshots
  curl -sf "$BASE/metrics"                  > "$DIR/metrics_after.txt"
  curl -sf "$BASE/nfs/status"               > "$DIR/nfs_status_after.json"
  curl -sf "$BASE/health"                   > "$DIR/health_after.json"
  curl -sf "$BASE/remediate/history?limit=5" > "$DIR/remediation_history.json"

  # 6) Per-scenario notes
  match="MISS"
  [ "$detected_nf" = "$expected_nf" ] && match="HIT"
  cat > "$DIR/notes.md" <<EOF
# $S — Day 16 evidence

- **inject_timestamp_utc:** $t_inject
- **expected_root_cause_nf:** $expected_nf
- **detected_root_cause_nf:** ${detected_nf:-NONE}
- **match:** $match
- **composite_score:** $composite
- **confidence:** $confidence
- **severity:** ${severity:-?}
- **remediation_action:** $action
- **remediation_status:** $status
- **outcome_signal:** $outcome
- **detection_latency_s:** $detect_s

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
EOF

  # 7) Summary row
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$S" "$expected_nf" "${detected_nf:-NONE}" "$match" \
    "$composite" "$confidence" "${severity:-?}" \
    "$action" "$status" "$outcome" "$detect_s" \
    >> "$summary"

  # 8) Recover and settle before next scenario
  curl -sf -X POST "$BASE/faults/recover/$S" > "$DIR/recover_response.json" || true
  echo "  recovered; settling ${SETTLE_BETWEEN}s before next scenario"
  sleep "$SETTLE_BETWEEN"
  echo
done

# ---- Top-level README ----
cat > "$OUT/README.md" <<EOF
# Day 16 — Live Fault Sweep Evidence

Evidence bundle capturing end-to-end reduction-to-practice for patent
claims 1–4 against the live Free5GC cloud-native 5G core.

Generated: $(date -u +%FT%TZ)
API base: \`$BASE\`

## Summary

| scenario | expected | detected | match | composite | confidence | severity | action | status | outcome | detect_s |
|---|---|---|---|---|---|---|---|---|---|---|
EOF
tail -n +2 "$summary" | while IFS=$'\t' read -r scenario expected detected match composite confidence severity action status outcome detect_s; do
  printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
    "$scenario" "$expected" "$detected" "$match" "$composite" "$confidence" "$severity" "$action" "$status" "$outcome" "$detect_s" \
    >> "$OUT/README.md"
done

cat >> "$OUT/README.md" <<'EOF'

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
EOF

printf '\n═══ DONE ═══\n'
echo "Bundle: $OUT"
echo "Summary table:"
column -t -s $'\t' < "$summary"
