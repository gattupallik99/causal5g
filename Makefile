# Causal5G — controlled demo orchestration
#
# Single-process uvicorn (no --reload) + docker compose, with clean start/stop.
# Ctrl-C hanging uvicorn is avoided because there's no reload watcher subprocess.
#
#   make start    # docker compose up + uvicorn in background
#   make status   # one-shot health view: containers + API + PID
#   make logs     # tail uvicorn.log (Ctrl-C exits tail, not the server)
#   make stop     # graceful: kill uvicorn by PID + docker compose stop
#   make nuke     # last resort: SIGKILL uvicorn + docker compose down
#   make test     # run the pytest suite
#   make restart  # stop + start
#
# Files produced (gitignored):
#   uvicorn.log   — API stdout/stderr
#   uvicorn.pid   — PID of the background uvicorn process

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

ROOT        := $(shell pwd)
COMPOSE_DIR := $(ROOT)/infra/free5gc
API_PORT    := 8080
API_HOST    := 127.0.0.1
LOG_FILE    := $(ROOT)/uvicorn.log
PID_FILE    := $(ROOT)/uvicorn.pid
PYTHON      := python3

.PHONY: help start stop restart status logs test nuke clean _wait_nrf _kill_api _check_docker

help:
	@echo "Causal5G demo orchestration"
	@echo "  make start    - bring up Free5GC + API (background)"
	@echo "  make status   - container + API health"
	@echo "  make logs     - tail uvicorn.log"
	@echo "  make stop     - graceful shutdown"
	@echo "  make restart  - stop + start"
	@echo "  make test     - pytest --no-cov -q"
	@echo "  make nuke     - force-kill everything"
	@echo "  make clean    - remove uvicorn.log/pid"

# ---------------------------------------------------------------------------
# start: Free5GC stack first, then wait for NRF, then uvicorn in background.
# ---------------------------------------------------------------------------
start: _check_docker _kill_api
	@echo ">>> Starting Free5GC stack (docker compose)..."
	cd $(COMPOSE_DIR) && docker compose up -d
	@$(MAKE) --no-print-directory _wait_nrf
	@echo ">>> Starting uvicorn on $(API_HOST):$(API_PORT) (background)..."
	@: > $(LOG_FILE)
	@nohup $(PYTHON) -m uvicorn api.frg:app \
		--host $(API_HOST) --port $(API_PORT) \
		--log-level warning \
		>> $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE)
	@sleep 2
	@if kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo ">>> API up. PID=$$(cat $(PID_FILE))  log=$(LOG_FILE)"; \
		echo "    Swagger:  http://$(API_HOST):$(API_PORT)/docs"; \
		echo "    Demo UI:  http://$(API_HOST):$(API_PORT)/demo"; \
	else \
		echo "!!! uvicorn failed to start. Tail of log:"; \
		tail -30 $(LOG_FILE); \
		rm -f $(PID_FILE); \
		exit 1; \
	fi

# Preflight: Docker Desktop is a common gotcha after Mac reboots.
_check_docker:
	@if ! docker info >/dev/null 2>&1; then \
		echo "!!! Docker daemon not reachable."; \
		echo "    Start Docker Desktop: open -a 'Docker Desktop'"; \
		echo "    Wait for the menu-bar whale to stop animating, then re-run 'make start'."; \
		exit 1; \
	fi

# NRF is the service registry — everything else is useless until it's up.
# Use a plain TCP port probe (nc -z); SBI HTTP paths return non-2xx without
# a proper service-discovery query, which would make a curl-based check flap.
_wait_nrf:
	@echo ">>> Waiting for NRF to accept TCP on :8000 (up to 30s)..."
	@for i in $$(seq 1 30); do \
		if nc -z 127.0.0.1 8000 2>/dev/null; then \
			echo ">>> NRF TCP ready (after $${i}s)."; exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "!!! NRF did not open :8000 after 30s."; \
	echo "    Check logs: cd infra/free5gc && docker compose logs --tail=40 free5gc-nrf"; \
	exit 1

# ---------------------------------------------------------------------------
# status: one-shot health snapshot
# ---------------------------------------------------------------------------
status:
	@echo "=== Containers ==="
	@cd $(COMPOSE_DIR) && docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "(compose not up)"
	@echo ""
	@echo "=== API process ==="
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "uvicorn running   PID=$$(cat $(PID_FILE))"; \
	else \
		echo "uvicorn not running"; \
	fi
	@echo ""
	@echo "=== API endpoints ==="
	@curl -fsS http://$(API_HOST):$(API_PORT)/health 2>/dev/null && echo "" || echo "/health   DOWN"
	@echo -n "Route count: "
	@curl -fsS http://$(API_HOST):$(API_PORT)/openapi.json 2>/dev/null \
		| $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('paths',{})))" \
		|| echo "openapi DOWN"

# ---------------------------------------------------------------------------
# logs: tail uvicorn.log. Ctrl-C exits tail, not the server.
# ---------------------------------------------------------------------------
logs:
	@test -f $(LOG_FILE) || (echo "No $(LOG_FILE); is the API running? Try: make status"; exit 1)
	tail -f $(LOG_FILE)

# ---------------------------------------------------------------------------
# stop: graceful. SIGTERM to uvicorn, then docker compose stop.
# ---------------------------------------------------------------------------
stop: _kill_api
	@echo ">>> Stopping Free5GC stack (docker compose stop)..."
	cd $(COMPOSE_DIR) && docker compose stop
	@echo ">>> Stopped."

# Helper: gracefully stop the API if running, no-op otherwise.
_kill_api:
	@if [ -f $(PID_FILE) ]; then \
		PID=$$(cat $(PID_FILE)); \
		if kill -0 $$PID 2>/dev/null; then \
			echo ">>> Stopping uvicorn (PID=$$PID, SIGTERM)..."; \
			kill $$PID; \
			for i in $$(seq 1 10); do \
				kill -0 $$PID 2>/dev/null || break; \
				sleep 1; \
			done; \
			if kill -0 $$PID 2>/dev/null; then \
				echo "!!! SIGTERM ignored, sending SIGKILL"; \
				kill -9 $$PID; \
			fi; \
		fi; \
		rm -f $(PID_FILE); \
	fi

restart:
	@$(MAKE) --no-print-directory stop
	@$(MAKE) --no-print-directory start

# ---------------------------------------------------------------------------
# test: pytest run using a /tmp coverage file to avoid permission issues.
# ---------------------------------------------------------------------------
test:
	COVERAGE_FILE=/tmp/.causal5g-coverage $(PYTHON) -m pytest --no-cov -q

# ---------------------------------------------------------------------------
# nuke: last resort. Force-kill uvicorn, docker compose down.
# ---------------------------------------------------------------------------
nuke:
	@echo ">>> Force-killing anything on port $(API_PORT)..."
	-@lsof -ti :$(API_PORT) | xargs -r kill -9 2>/dev/null || true
	-@pkill -9 -f "uvicorn api.frg" 2>/dev/null || true
	@rm -f $(PID_FILE)
	@echo ">>> docker compose down..."
	cd $(COMPOSE_DIR) && docker compose down
	@echo ">>> Everything torn down."

clean:
	rm -f $(LOG_FILE) $(PID_FILE)
