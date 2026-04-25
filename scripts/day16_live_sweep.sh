#!/usr/bin/env bash
# Day 16 live sweep — one-shot bring-up of Free5GC + uvicorn + sweep.
#
# Prereqs:
#   - Docker Desktop installed (script will start it)
#   - jq installed (brew install jq)
#
# Usage (from ~/causal5g):
#   bash scripts/day16_live_sweep.sh
#
# Overridable env:
#   BUFFER_FILL_MIN (default 40)  % buffer fill before sweep starts
#   BUFFER_WAIT_MAX (default 300) max seconds to wait for buffer fill
#   OUT             (default evidence/day16b)
#   WAIT_DETECT WAIT_REMED SETTLE_BETWEEN  (passed through to sweep)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

OUT="${OUT:-evidence/day16b}"
WAIT_DETECT="${WAIT_DETECT:-180}"
WAIT_REMED="${WAIT_REMED:-30}"
SETTLE_BETWEEN="${SETTLE_BETWEEN:-60}"
BUFFER_FILL_MIN="${BUFFER_FILL_MIN:-40}"
BUFFER_WAIT_MAX="${BUFFER_WAIT_MAX:-300}"

step() { printf '\n─── %s ───\n' "$*"; }

# ---------------------------------------------------------------
step "1/7 Start Docker Desktop"
if ! docker info >/dev/null 2>&1; then
  open -a Docker
  for i in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 2
  done
fi
docker info >/dev/null 2>&1 || { echo "Docker did not start"; exit 1; }
echo "  docker ready"

# ---------------------------------------------------------------
step "2/7 Create causal5g-net (idempotent)"
docker network create causal5g-net 2>/dev/null || echo "  exists"

# ---------------------------------------------------------------
step "3/7 Bring up Free5GC"
( cd infra/free5gc && docker compose up -d )

# ---------------------------------------------------------------
step "4/7 Wait for NFs to register"
for i in $(seq 1 60); do
  up=$(docker ps --filter 'name=causal5g-' --format '{{.Names}}' | sort -u | wc -l | tr -d ' ')
  # Expect at least 9 of the 11 containers up (UPF + optional webui may fail)
  if [ "$up" -ge 9 ]; then
    echo "  $up causal5g-* containers running"
    break
  fi
  sleep 2
done
docker ps --filter 'name=causal5g-' --format 'table {{.Names}}\t{{.Status}}' \
  | tee "$REPO/.day16_containers.txt"

# ---------------------------------------------------------------
step "5/7 Restart uvicorn"
# Kill any uvicorn already bound to 8080 (from an earlier run).
pids=$(lsof -ti tcp:8080 || true)
if [ -n "$pids" ]; then
  echo "  killing pids on :8080 → $pids"
  kill $pids 2>/dev/null || true
  sleep 2
fi
mkdir -p .logs
nohup python3 -m uvicorn api.frg:app --port 8080 \
  > .logs/uvicorn_day16b.log 2>&1 &
echo "  uvicorn pid=$!  log=.logs/uvicorn_day16b.log"
# Wait for /health to respond
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/health >/dev/null; then break; fi
  sleep 1
done
curl -sf http://localhost:8080/health >/dev/null || {
  echo "uvicorn did not come up; see .logs/uvicorn_day16b.log"
  exit 1
}
echo "  uvicorn alive"

# ---------------------------------------------------------------
step "6/7 Wait for telemetry buffer to fill (>= ${BUFFER_FILL_MIN}%)"
for i in $(seq 1 "$BUFFER_WAIT_MAX"); do
  fill=$(curl -sf http://localhost:8080/health | jq -r '.buffer_fill_pct // 0')
  # jq gives a number, but guard against non-numeric / null
  fill_int=$(printf '%.0f' "${fill:-0}" 2>/dev/null || echo 0)
  if [ "$fill_int" -ge "$BUFFER_FILL_MIN" ]; then
    echo "  buffer=$fill% — ready"
    break
  fi
  if [ $((i % 10)) -eq 0 ]; then
    echo "  buffer=$fill% (waited ${i}s)"
  fi
  sleep 1
done

# ---------------------------------------------------------------
step "7/7 Run sweep → $OUT"
OUT="$OUT" WAIT_DETECT="$WAIT_DETECT" WAIT_REMED="$WAIT_REMED" \
  SETTLE_BETWEEN="$SETTLE_BETWEEN" \
  bash scripts/day16_fault_sweep.sh

echo
echo "═══ Live sweep complete ═══"
echo "Evidence: $OUT"
echo "Uvicorn still running in background (pid $(lsof -ti tcp:8080 || echo '?'));"
echo "kill with:  kill \$(lsof -ti tcp:8080)"
