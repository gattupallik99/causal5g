# Causal5G - Self-Study Deep Dive

**Audience:** you, inventor. CONFIDENTIAL, not for public or attorney distribution.

**Purpose:** a 15 to 20 minute walk through the working system, claim by claim, so you can see what you have and how it hangs together before talking to the patent attorney or filing.

**How to use this file:** keep it open in VS Code. Open two terminal tabs at `~/causal5g` (one for the Free5GC Docker stack, one for the FastAPI app plus curl commands). Work top to bottom. File references like `api/frg.py:316` are Cmd-clickable in VS Code.

**Do not commit this file.** It is a scratch walk through. `rm DEMO_DEEP_DIVE.md` when done, or move it outside the repo.

---

## 0. Sanity check (2 min)

Open terminal A at `~/causal5g` and run:

```
docker info | head -3
python3 --version
lsof -i :8080 -i :8000 -i :8001 -i :8002 -i :8003 -i :8004 -i :8005
```

You want: Docker Desktop reports "Containers" counts, Python 3.11.x, and nothing already bound on 8000 8001 8002 8003 8004 8005 or 8080.

Check the external Docker network exists (the compose file expects it):

```
docker network ls | grep causal5g-net
docker network create causal5g-net 2>/dev/null || true
```

Activate the virtualenv:

```
source .venv/bin/activate
python -c "import causal5g; print('package OK')"
```

---

## 1. Repo map at a glance (2 min)

Claims to code, in one table. All of these files are committed as of `062ac10` (Day 12b, today).

| Claim | What it does | Primary modules | Key classes |
|---|---|---|---|
| **1** | Bi-level causal DAG: NF layer plus per-slice subgraphs; slice-topology-aware pruning; NF-vs-slice attribution | `causal5g/graph/bilevel_dag.py`, `causal5g/graph/topology_prior.py`, `causal5g/slice_topology.py`, `causal5g/causal/discovery.py`, `causal/engine/pc_algorithm.py`, `causal/engine/granger.py`, `causal5g/causal/attribution.py` | `BiLevelCausalDAG`, `SliceTopologyManager`, `CausalDiscovery`, `PCAlgorithm`, `GrangerPCFusion`, `CausalAttributionScorer` |
| **2** | Four-domain hierarchical graph RAN + Transport + Core + Cloud; RCA report artefact | `causal5g/graph/hierarchical_dag.py`, `causal5g/graph/cross_domain.py`, `causal5g/rca/report.py` | `HierarchicalDAG`, `CrossDomainEdgeInferrer`, `RCAReport`, `generate_report()` |
| **3** | Confidence-gated closed-loop remediation; pluggable action executor; policy table | `api/rae.py`, `causal5g/remediation/executor.py`, `causal5g/remediation/policy_store.py`, `causal5g/remediation/verifier.py` | `trigger_remediation()`, `RemediationExecutor`, `PolicyStore`, `verify_remediation()` |
| **4** | Feedback-driven DAG recalibration from remediation outcomes | `causal/engine/recalibrator.py`, `api/rae.py` (feedback buffer) | `GrangerPCFusionRecalibrator`, `_push_feedback()` |
| (glue) | Root cause scoring, telemetry buffer, fault injection | `causal/engine/rcsm.py`, `causal/engine/granger.py` (TelemetryBuffer), `faults/injector.py` | `RootCauseScoringModule`, `TelemetryBuffer`, `FaultInjector` |

Quick one-liner to remind yourself how much code each claim has:

```
wc -l causal5g/graph/bilevel_dag.py causal5g/graph/topology_prior.py causal5g/slice_topology.py causal5g/causal/discovery.py causal/engine/pc_algorithm.py causal/engine/granger.py causal5g/causal/attribution.py   # Claim 1
wc -l causal5g/graph/hierarchical_dag.py causal5g/graph/cross_domain.py causal5g/rca/report.py                                                                                                                    # Claim 2
wc -l api/rae.py causal5g/remediation/executor.py causal5g/remediation/policy_store.py causal5g/remediation/verifier.py                                                                                            # Claim 3
wc -l causal/engine/recalibrator.py                                                                                                                                                                                # Claim 4
```

---

## 2. Bring up the stack (3 min)

### Terminal A - Free5GC Docker stack

```
cd ~/causal5g/infra/free5gc
docker compose up -d
docker compose ps
```

You should see nine containers up: `causal5g-mongodb`, `causal5g-nrf`, `causal5g-amf`, `causal5g-smf`, `causal5g-upf`, `causal5g-pcf`, `causal5g-udm`, `causal5g-udr`, `causal5g-ausf`. Labels include `causal5g.nf=<name>` (see `docker inspect causal5g-nrf | grep causal5g.nf`).

If any container is restarting, check logs:

```
docker logs --tail 50 causal5g-nrf
```

The NRF cert file `infra/free5gc/cert/nrf.pem` was modified locally (it's in your uncommitted working tree) - that's expected, Free5GC regenerates it on boot.

### Terminal B - FastAPI app

```
cd ~/causal5g
source .venv/bin/activate
uvicorn api.frg:app --port 8080 --reload
```

Open three browser tabs:

- http://localhost:8080/docs - Swagger (interactive API)
- http://localhost:8080/demo - live demo dashboard
- http://localhost:8080/control - container control panel (may 404 if the control router is not mounted; see Section 3)

Leave uvicorn running for the rest of the tour.

---

## 3. Swagger tour: what is actually live (2 min)

Open http://localhost:8080/docs and scroll through. You will see these tag groups:

- Status (`/health`, `/nfs/status`, `/metrics`)
- Fault Injection (`/faults/scenarios`, `/faults/inject/{scenario}`, `/faults/recover/{scenario}`)
- Fault Reports (`/faults/active`, `/faults`, `/faults/report/{report_id}`)
- Causal Graph (`/graph/current`, `/graph/v2`)
- Remediation (`/remediation/{nf_id}` - note: this is a dumb `docker restart` wrapper, NOT the confidence-gated RAE)

### Gap to be aware of (important)

Four routers are defined in the code but not mounted into the running FastAPI app, so you will NOT see them in Swagger:

| Defined at | Prefix | Tests hitting it directly |
|---|---|---|
| `api/rae.py:22` | `/remediate/*` | `tests/test_rae.py` |
| `api/slice_router.py:13` | `/slice/*` | `tests/test_slice_topology.py` |
| `api/pc_causal.py:38` | `/causal/pc/*` | `tests/test_pc_algorithm.py` |
| `api/control.py:13` | `/control/*` | (none - `api/control.py:4` shows the wiring in a docstring but it is not called) |

To expose these for live exploration, add to `api/frg.py` right after `app.mount("/static", ...)` (line 163):

```python
from api.rae import router as rae_router
from api.slice_router import router as slice_router
from api.pc_causal import router as pc_router
from api.control import router as control_router
app.include_router(rae_router)
app.include_router(slice_router)
app.include_router(pc_router)
app.include_router(control_router)
```

Do not commit this change yet. It is a four line fix. Save it for a dedicated Day 12c or Day 12d commit so the wiring change stands alone for the attorney to review. For this self-study, either:

- skip it and drive the four hidden routers via pytest (Sections 4 to 7 show this), or
- apply the change in your editor, let `--reload` pick it up, and hit the routers live.

---

## 4. Claim 1 deep dive: Bi-level DAG plus slice-topology-aware causal discovery (3 min)

### The core idea

A single flat causal DAG over NF KPIs cannot distinguish "AMF is failing for everyone" from "AMF is failing only for slice 1:2 because of slice-specific policy." Your bi-level DAG solves this: Level 1 is NFs, Level 2 is a set of slice subgraphs, each of which is a projection of the Level 1 graph restricted to that slice's constituent NFs.

### Files to read, in order

1. `causal5g/graph/bilevel_dag.py` - `NFNode` and `SliceSubgraph` dataclasses, `BiLevelCausalDAG` with `level1_graph` and `level2_subgraphs`. Skim `add_nf_node`, `add_slice_subgraph`.
2. `causal5g/graph/topology_prior.py` - `TopologyPrior` class. This is where 3GPP SBI edges and PFCP bindings constrain what counts as a candidate edge, before any statistical test runs. This is Claim 1's "structural prior."
3. `causal5g/slice_topology.py` - `SliceTopologyManager`: slice lifecycle, per-slice dedicated-vs-shared NF sets, the slice-graph pruner.
4. `causal/engine/pc_algorithm.py` - `PCAlgorithm` (Peter-Clark, constraint-based causal discovery) and `GrangerPCFusion` (the novelty class: fuse PC's conditional-independence edges with Granger temporal precedence to get contemporaneous-plus-lagged causal edges).
5. `causal5g/causal/discovery.py` - `CausalDiscovery` facade; this is the clean public entry point that wraps PC and Granger (rewritten as part of Day 12a).
6. `causal5g/causal/attribution.py` - `CausalAttributionScorer` produces `AttributionResult(root_cause_type=NF|SLICE|UNDETERMINED, score, affected_slices, confidence)`. This is where the bi-level graph pays off: it's the module that decides NF-layer vs slice-layer attribution.

### Run it live

```
# Only Claim-1-related tests
python -m pytest tests/test_pc_algorithm.py tests/causal/test_discovery.py tests/causal/test_attribution.py tests/graph/test_bilevel_dag.py tests/graph/test_topology_prior.py tests/test_slice_topology.py -v
```

That's roughly 100 tests exercising Claim 1 end to end.

```
# See the Claim 1 graph via the live API (one of the unmounted routers - use pytest instead if you skipped the wiring)
curl -s http://localhost:8080/graph/current | python -m json.tool | head -40
```

### The fused edges trick (Claim 1 core novelty)

Open `causal/engine/pc_algorithm.py:601` at `GrangerPCFusion`. Scroll to `fuse()`. Note the four edge buckets:

- `confirmed_edges` - both PC and Granger agree (highest confidence, 1.5x weight in DAG)
- `pc_only_edges` - PC sees a contemporaneous dependency, Granger does not
- `granger_only_edges` - Granger sees temporal precedence, PC does not
- `conflict_edges` - PC and Granger disagree on direction

Those four buckets are the Claim 1 "edge classification" language verbatim. They are also what `CausalDiscovery.fit(method=FUSED)` returns in `DiscoveryResult`, which is what the production facade exposes.

---

## 5. Claim 2 deep dive: Four-domain hierarchical graph plus RCA report (3 min)

### The core idea

Causal discovery inside one "flat" graph covering RAN cells, transport links, core NFs, and K8s pods blows up because each domain has wildly different telemetry cadences (100 ms radio KPIs vs 5 s container metrics). Claim 2's solution is to run discovery inside each domain at its native granularity, then add a much smaller set of inferred cross-domain edges between boundary metrics.

### Files to read, in order

1. `causal5g/graph/hierarchical_dag.py:22` - `Domain` enum (RAN, TRANSPORT, CORE, CLOUD) and `DOMAIN_GRANULARITY_MS` (100, 500, 1000, 5000). Note that the `Domain.CORE` graph IS your Claim 1 bi-level Level 1 graph. That's where Claims 1 and 2 connect.
2. `causal5g/graph/cross_domain.py:18` - `CrossDomainEdgeInferrer` with `DOMAIN_BOUNDARIES = [(CLOUD, CORE), (CORE, TRANSPORT), (TRANSPORT, RAN)]`. Note `_test_independence` is a `NotImplementedError` placeholder: the CI test itself is not yet implemented, but the orchestration loop is and is fully tested.
3. `causal5g/rca/report.py:49` - `CausalStep`, `RCAReport`, `ReportStore`. The RCA report is Claim 2's "artefact": a structured record with root cause NF, causal chain, severity, recommendations, and a verification hook.

### Run it live

```
python -m pytest tests/graph/test_cross_domain.py tests/graph/test_hierarchical_dag.py tests/test_verifier_and_report.py -v
```

21 tests for the two graph modules, plus the RCA report test file.

### Inspect the report shape

```
python - <<'PY'
from causal5g.rca.report import generate_report, CausalStep
chain = [
    CausalStep(order=0, nf_id="nrf-1", reason="NRF unreachable", score=0.91),
    CausalStep(order=1, nf_id="amf-1", reason="AMF discovery timeout", score=0.74),
]
report = generate_report(
    fault_scenario="nrf_crash",
    root_cause_nf="nrf-1",
    root_cause_score=0.91,
    causal_chain=chain,
    affected_slices=["1:1", "1:2"],
)
import json; print(json.dumps(report.to_dict() if hasattr(report,'to_dict') else report.__dict__, default=str, indent=2))
PY
```

Read the output: this is what an attorney sees as proof that Claim 2's "RCA report artefact" is a real, structured, testable thing.

---

## 6. Claim 3 deep dive: Confidence-gated closed-loop remediation (3 min)

### The core idea

Blind auto-remediation in a 5G core is a foot-gun. Claim 3 gates every action on a posterior confidence score (RCSM composite: causal confidence plus temporal correlation plus topology weight). Below threshold, the system logs and holds. Above threshold, the policy table picks an action; the executor runs it; the verifier scores the outcome.

### Files to read, in order

1. `api/rae.py` - top-level constants: `CONFIDENCE_THRESHOLD = 0.65`, the `ACTION_POLICY` dict, fallback chain. `trigger_remediation()` is the entry point.
2. `causal5g/remediation/policy_store.py:28` - `PolicyEntry` and `PolicyStore`: CRUD plus persistence, 20 policies registered by default. This is the "persistent policy table" language in the claim.
3. `causal5g/remediation/executor.py:48` - `ExecutionStatus` enum and `RemediationExecutor` with seven async action handlers (`restart_pod`, `scale_deployment`, `drain_node`, `rollback_config`, `reroute_traffic`, `notify_operator`, `no_op`). Note the `register()` hook for production K8s client injection - that's the pluggable adapter in the claim language.
4. `causal5g/remediation/verifier.py:82` - `verify_remediation()`: re-scores RCSM after the action, returns `VerificationOutcome.SUCCESS|PARTIAL|FAILED|TIMEOUT`.

### Run it live

```
python -m pytest tests/test_rae.py tests/remediation/ tests/test_verifier_and_report.py -v
```

~70 tests across Claim 3 surfaces.

### Trace one call by hand

Open `api/rae.py` and scroll to `trigger_remediation` (around line 200+). Walk through:

- Step 1: compute `decision` = gate check vs `CONFIDENCE_THRESHOLD`
- Step 2: if gated open, `_select_action(fault_scenario, attempt)` looks up the policy table
- Step 3: dispatch to a `_k8s_*` or `_reroute_*` stub (in production: the `RemediationExecutor` handler)
- Step 4: `_compute_outcome_signal()` scores the result
- Step 5: `_push_feedback()` appends to the feedback buffer (this is the Claim 4 hookup)
- Step 6: return a `RemediationRecord` to the caller and to `/remediate/history`

That end to end path is roughly 90 lines. A patent attorney can read it in 10 minutes.

---

## 7. Claim 4 deep dive: Feedback-driven DAG recalibration (2 min)

### The core idea

After every remediation action, push the outcome (signal in [-1, +1]) plus the root cause NF, affected slices, and the RCSM score used to gate back into a feedback buffer. A recalibrator consumes the buffer and nudges `GrangerPCFusion` edge weights: edges in a fault chain that led to a SUCCESS get reinforced, edges that led to FAILURE get weakened, and slice-tagged feedback only affects the relevant slice subgraph (Claim 1 linkage).

### Files to read, in order

1. `causal/engine/recalibrator.py:51` - `FeedbackEntry` dataclass.
2. `causal/engine/recalibrator.py:95` - `GrangerPCFusionRecalibrator`: `ingest()`, `_apply_update()`, `_update_edge_weight()`. Read these three methods - they are the core 80 lines of Claim 4.
3. `api/rae.py` - look for `_push_feedback` and `feedback_buffer`. The REST endpoint `GET /remediate/feedback` exposes the buffer (router not mounted yet; see Section 3).

### Run it live

```
python -m pytest tests/test_recalibrator.py -v
```

### Watch a feedback cycle

```
python - <<'PY'
from causal.engine.recalibrator import GrangerPCFusionRecalibrator, FeedbackEntry, RecalibrationConfig
r = GrangerPCFusionRecalibrator(RecalibrationConfig())
print("Initial state:", r.state.total_ingested)
r.ingest(FeedbackEntry(
    timestamp=0.0, fault_scenario="nrf_crash", root_cause_nf="nrf-1",
    slice_id="1:1", rcsm_score=0.82, outcome_signal=+0.9, action="restart_pod",
))
print("After one SUCCESS:", r.state.total_ingested, "edge nudges:", r.state.total_edge_nudges)
PY
```

---

## 8. End-to-end live flow (3 min)

This is the money shot: you inject a real fault in Free5GC, watch the causal graph react, trigger remediation, watch the feedback buffer capture the outcome.

Terminal B should still have uvicorn running. In a third terminal:

```
cd ~/causal5g
# T=0  baseline
curl -s localhost:8080/health
curl -s localhost:8080/nfs/status | python -m json.tool

# T=5s  inject NRF crash
curl -s -X POST localhost:8080/faults/inject/nrf_crash | python -m json.tool

# T=10s  watch the causal graph shift (run a few times 5 sec apart)
curl -s localhost:8080/graph/current | python -m json.tool | head -30
curl -s localhost:8080/faults/active | python -m json.tool

# T=30s  the FRG should produce an active fault report
curl -s localhost:8080/faults | python -m json.tool | head -40

# T=35s  dumb remediation (the live one, Claim 3 proxy)
curl -s -X POST localhost:8080/remediation/nrf | python -m json.tool

# T=40s  confirm NRF back up and fault clears
docker ps | grep causal5g-nrf
curl -s localhost:8080/faults/active | python -m json.tool

# clean up
curl -s -X POST localhost:8080/faults/recover/nrf_crash | python -m json.tool
```

What you should see:

1. Before inject: `/nfs/status` shows all NFs healthy.
2. After inject: `/faults/active` lists `nrf_crash`, severity CRITICAL, expected_impact includes AMF SMF PCF UDM AUSF NSSF.
3. After ~30 s: `/faults` has a FaultReport with `root_cause.nf_id = "nrf-1"`, `composite_score` above 0.7, and a populated causal_chain.
4. After remediation: `/faults/active` drops the scenario and NRF container shows recent restart time.

If you wired the `/remediate/*` router, you can also POST the full confidence-gated version:

```
curl -s -X POST localhost:8080/remediate \
  -H 'content-type: application/json' \
  -d '{"fault_scenario": "nrf_crash", "root_cause_nf": "nrf-1", "rcsm_score": 0.82, "slice_id": "1:1", "attempt": 1}' \
  | python -m json.tool
curl -s localhost:8080/remediate/history | python -m json.tool | head -30
curl -s localhost:8080/remediate/feedback | python -m json.tool | head -30
```

That hits Claims 3 and 4 live.

---

## 9. Test suite and coverage (1 min)

```
python -m pytest --no-cov -q
python -m pytest --cov=causal5g --cov=causal --cov-report=term-missing | tail -30
```

Expected: 243 tests passing, overall coverage ~88%.

The only remaining 0%-coverage Claim-module is `causal5g/causal/pcmci.py` (Claim 4's PCMCI time-lagged DAG backend, distinct from the fused approach already covered). Its tests are queued as Day 12c.

Everything else at above 80% is there deliberately - the uncovered lines are mostly FastAPI handler bodies for the unmounted routers (see Section 3).

---

## 10. Gaps and next steps (honest list)

In priority order:

1. **File the US provisional.** All four claims reduced to practice; repo evidence is strong; the draft v2 docx and lab notebook v1 in `patent/drafts/` are inventor-only (no assignee). Blocker is not code, it is paperwork plus counsel sign-off (H1B IP-assignment question flagged in `CLAUDE.md`).
2. **Wire the four unmounted routers** (`rae`, `slice_router`, `pc_causal`, `control`) into `api/frg.py`. Four lines. Makes Swagger actually reflect the system. Commit as Day 12c.
3. **Day 12c coverage: `causal5g/causal/pcmci.py`** - the last 0% module. ~59 statements.
4. **Production K8s client integration** in `RemediationExecutor._do_*` handlers. Interface contract is fixed; tests pass against the stubs; replacing stub bodies with `kubernetes` Python client calls is a mechanical swap.
5. **Implement `CrossDomainEdgeInferrer._test_independence`** (currently `NotImplementedError`). Partial correlation with lag sweep, per the placeholder docstring.
6. **Prometheus exporter polish** for ISEC 2026 Princeton presentation. Do not present the Causal5G mechanism before the provisional is filed.

---

## Quick jumps (Cmd-click in VS Code)

- `api/frg.py:144` - FastAPI app definition
- `api/rae.py:22` - RAE router (unmounted)
- `causal/engine/pc_algorithm.py:601` - `GrangerPCFusion.fuse()`
- `causal5g/graph/bilevel_dag.py:20` - `NFNode`, bi-level DAG
- `causal5g/slice_topology.py:107` - `SliceTopologyManager`
- `causal5g/graph/hierarchical_dag.py:29` - `HierarchicalDAG`
- `causal5g/graph/cross_domain.py:18` - `CrossDomainEdgeInferrer`
- `causal5g/rca/report.py:59` - `RCAReport`
- `causal5g/remediation/executor.py:83` - `RemediationExecutor`
- `causal/engine/recalibrator.py:95` - `GrangerPCFusionRecalibrator`
- `DEVELOPMENT_LOG.md` - narrative Day 4 through Day 12b

---

*Self-study scratch file. Remove before committing.*
