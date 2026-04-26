#!/usr/bin/env bash
# Day 17 sweep: applies container-status patch, verifies Docker is
# accessible, restarts uvicorn, runs fault sweep into evidence/day17/.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

OUT="${OUT:-evidence/day17}"
PORT="${PORT:-8080}"
LOG_DIR=".logs"
mkdir -p "$LOG_DIR"

step() { printf '\n─── %s ───\n' "$*"; }

step "1/5 Apply patch"
python3 scripts/day17_apply_patch.py

step "2/5 Verify Docker access"
if ! docker inspect --format '{{.State.Status}}' causal5g-amf >/dev/null 2>&1; then
  echo "ERROR: 'docker inspect causal5g-amf' failed." >&2
  echo "Make sure Docker Desktop is running and Free5GC is up." >&2
  echo "If Free5GC is down, run: bash scripts/day16_live_sweep.sh" >&2
  exit 1
fi
echo "  docker OK"

step "3/5 Restart uvicorn on :$PORT"
if lsof -ti tcp:$PORT >/dev/null 2>&1; then
  kill "$(lsof -ti tcp:$PORT)" 2>/dev/null || true
  for _ in $(seq 1 10); do
    lsof -ti tcp:$PORT >/dev/null 2>&1 || break
    sleep 1
  done
fi
nohup uvicorn api.frg:app --port "$PORT" \
  > "$LOG_DIR/uvicorn_day17.log" 2>&1 &
UVI_PID=$!
echo "  uvicorn pid=$UVI_PID  log=$LOG_DIR/uvicorn_day17.log"
for _ in $(seq 1 30); do
  curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
echo "  uvicorn alive"

step "4/5 Wait for buffer (>= 40%)"
waited=0
while :; do
  fill=$(curl -fsS "http://localhost:$PORT/health" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("buffer_fill_pct", 0))')
  printf "  buffer=%s%% (waited %ds)\n" "$fill" "$waited"
  awk -v a="$fill" -v b="40" 'BEGIN{exit !(a+0 >= b+0)}' && break
  sleep 10; waited=$((waited+10))
  (( waited > 240 )) && { echo "timeout waiting for buffer fill" >&2; exit 1; }
done

step "5/5 Run fault sweep -> $OUT"
if [[ -d "$OUT" ]]; then
  rm -rf "$OUT.prev"
  mv "$OUT" "$OUT.prev"
  echo "  archived old $OUT -> $OUT.prev"
fi
OUT="$OUT" WAIT_DETECT=240 WAIT_REMED=30 SETTLE_BETWEEN=90 \
  bash scripts/day16_fault_sweep.sh

echo
echo "═══ Container status seen by the scorer (last 10 lines) ═══"
grep "Container status:" "$LOG_DIR/uvicorn_day17.log" | tail -10 \
  || echo "  (none — patch may not be active)"

echo
echo "Done. Bundle: $OUT  uvicorn pid=$UVI_PID"
echo "Kill uvicorn:  kill \$(lsof -ti tcp:$PORT)"
