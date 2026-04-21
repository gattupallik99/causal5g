# Causal5G — Project Context for Claude Code

## Inventor & Ownership

- **Inventor:** Krishna Kumar Gattupalli (independent; no assignee)
- **Official email (filings, counsel, USPTO, all patent communications):** gattupallik@gmail.com
- **Project email (git commits, repo-only work):** harekrishna9krishna@gmail.com
- **Repo:** git@github.com:gattupallik99/causal5g.git (private, SSH)
- **Local path:** ~/causal5g
- **Git identity:** gattupallik99 <harekrishna9krishna@gmail.com>

## Patent Context

**Title:** System and Method for Slice-Topology-Aware Causal Root Cause Analysis and Closed-Loop Remediation for Cloud-Native 5G Standalone Core Networks

**Filing status:** US Provisional — **FILED** (March 2026; confirm exact date + application number)
**Entity status:** Micro Entity ($65 USPTO filing fee)
**Non-provisional deadline:** 12 months from filing date (target: file non-provisional by March 2027)

**The four claims:**
1. **Claim 1** — Bi-level causal DAG construction (Level 1 = NF nodes, Level 2 = slice subgraphs) with NF-layer vs slice-layer root cause attribution
2. **Claim 2** — Hierarchical four-domain graph (RAN → Transport → Core → Cloud) with RCA report artefact
3. **Claim 3** — Confidence-gated closed-loop remediation with persistent policy table and pluggable orchestrator adapter
4. **Claim 4** — Feedback-driven DAG recalibration from remediation outcomes

**All four claims are reduced to practice as of commit `f666442` (Day 11, April 17, 2026).**

## Disclosure Discipline — Post-Filing

Provisional is filed, so public references are now acceptable with the following guardrails:

**Safe to disclose publicly (with "patent pending" attribution):**
- The name "Causal5G"
- High-level mechanism: bi-level DAG, four-domain hierarchy, confidence-gated remediation, feedback recalibration
- Blog posts, LinkedIn, arXiv

**Still sensible to hold back until non-provisional filing strategy is decided:**
- Exact claim language (verbatim from the provisional)
- Implementation specifics that extend beyond the provisional and could become continuation-in-part material
- Pre-release code or unpublished experimental results that could count as new matter

**Foreign filing note:** public disclosure in any form starts the 12-month Paris Convention clock for foreign patents. Track the filing date as the anchor for PCT / direct-national-phase decisions.

## Repository Architecture

```
~/causal5g/
├── api/
│   ├── frg.py              # Main FastAPI app, uvicorn api.frg:app --port 8080
│   ├── rae.py              # Remediation Action Engine (Claim 3)
│   ├── slice_router.py     # Slice topology REST API (Claim 1)
│   ├── pc_causal.py        # PC algorithm REST API (Claim 1)
│   └── control.py          # Control panel UI
├── causal5g/
│   ├── causal/
│   │   ├── attribution.py  # NF/slice attribution (Claim 1)
│   │   ├── discovery.py    # Causal discovery engine (Claim 1)
│   │   └── pcmci.py        # PCMCI time-lagged DAG (Claim 4)
│   ├── graph/
│   │   ├── bilevel_dag.py      # Bi-level NF + slice DAG (Claim 1)
│   │   ├── topology_prior.py   # SBI + PFCP structural prior (Claim 1)
│   │   ├── hierarchical_dag.py # Four-domain hierarchy (Claim 2)
│   │   └── cross_domain.py     # Cross-domain edges (Claim 2)
│   ├── rca/
│   │   └── report.py       # RCAReport + generate_report (Claim 2)
│   ├── remediation/
│   │   ├── policy_store.py # PolicyStore CRUD (Claim 3)
│   │   ├── executor.py     # RemediationExecutor (Claim 3)
│   │   └── verifier.py     # RemediationVerifier (Claim 3)
│   ├── slice_topology.py   # SliceTopologyManager (Claim 1)
│   ├── observability/
│   │   └── metrics.py      # Prometheus exposition (Day 15)
│   └── telemetry/
│       ├── sbi_collector.py   # SBI HTTP/2 capture
│       ├── pfcp_collector.py  # PFCP N4 session stats
│       └── slice_kpi.py       # Per-S-NSSAI KPI
├── causal/engine/
│   ├── granger.py          # GrangerPCFusion (Claim 1)
│   ├── pc_algorithm.py     # Stable-PC algorithm (Claim 1)
│   ├── rcsm.py             # Root Cause Scoring Module
│   └── recalibrator.py     # GrangerPCFusionRecalibrator (Claim 4)
├── faults/
│   └── injector.py         # 5 fault scenarios for demo
├── tests/                  # 334 passing tests (pytest --no-cov -q)
├── DEVELOPMENT_LOG.md      # Day 4-11 narrative, patent-claim mapping
└── pyproject.toml
```

## Commit Discipline

Every commit message must:
1. Name the Day (Day 12, Day 13, etc.)
2. Name the patent claim(s) it enables or touches
3. List code changes with file paths
4. Include test results (e.g., "182 passed (was 161)")
5. Include coverage deltas when relevant
6. End with claim-status summary

Format template (the Day 11 commit `f666442` is the reference):

```
Day N: <focus> (claims <X, Y>)

PATENT CLAIM ENABLEMENT
-----------------------
Claim X (Name): <what this commit does for the claim>

CODE CHANGES
------------
<path>: <summary>
...

TESTS
-----
<added/modified test files>

RESULTS
-------
Tests:    <N> passed
Coverage: <delta>
```

**DEVELOPMENT_LOG.md must be updated in the same commit as code changes** — it's the narrative companion to the git log that the patent attorney will read.

## Workflow

- **Python:** 3.11.9 (Mac Apple Silicon)
- **Run tests:** `python3 -m pytest --no-cov -q` (expect 334 passing after Day 15)
- **Run coverage:** `python3 -m pytest --cov=causal5g --cov-report=term-missing`
- **Run API:** `uvicorn api.frg:app --port 8080 --reload`
- **Swagger:** http://localhost:8080/docs
- **Demo dashboard:** http://localhost:8080/demo
- **Control panel:** http://localhost:8080/control

## Current Priorities (top to bottom)

Provisional is filed. Focus shifts to hardening the reduction-to-practice and preparing the non-provisional.

1. **Coverage expansion — last 0% module:**
   - `causal5g/causal/pcmci.py` (0%) — Claim 4
   - Already closed: `cross_domain.py`, `hierarchical_dag.py`, `discovery.py` (Day 12a-b); `pcmci.py` (Day 12d, 100%)
2. ~~**Wire the four unmounted routers into `api/frg.py`**~~ — done since Day 12c; all four routers (`api/rae.py`, `api/slice_router.py`, `api/pc_causal.py`, `api/control.py`) mounted on `app` and verified live (23 routes across `/slice`, `/causal/pc`, `/remediate`, `/control`).
3. ~~**Production K8s client integration**~~ — done Day 14-b. `causal5g/remediation/executor.py` accepts an optional `k8s_client_factory: Callable[[], tuple[CoreV1Api, AppsV1Api]]`. When None (default), handlers run simulated (byte-identical to pre-Day-14 for 21 legacy tests). When supplied, handlers dispatch real K8s API calls via `asyncio.to_thread` (`delete_namespaced_pod`, `patch_namespaced_deployment_scale`, `patch_node` + `create_namespaced_pod_eviction`, `patch_namespaced_deployment` annotation, `patch_namespaced_service` selector). 18 new K8s-path tests in `tests/remediation/test_executor_k8s.py`. `default_k8s_client_factory(in_cluster, kubeconfig)` lazy-imports `kubernetes` so the library is not a hard dep.
4. ~~**Prometheus metrics exporter**~~ — done Day 15. New package `causal5g/observability/` exposes 12 metrics via `prometheus_client` through the existing `/metrics` endpoint: per-NF scrape counter, attribution-latency histogram, composite-score gauge, RCA-report counter by severity, remediation-action counter by (action, status), remediation-duration histogram, confidence-gate decision counter, and five pipeline gauges. `prometheus_client` is a lazy import so it remains an optional dep; when absent, helpers are no-ops and `/metrics` falls back to the pre-Day-15 hand-rolled plain-text lines. Bounded label cardinality enforced via `_validated()`. 19 new tests in `tests/observability/test_metrics.py`.
5. **Non-provisional prep** — claim language review, figure refinement, continuation-in-part scoping on anything built after the provisional filing date.

## Communication Style

- Direct and concise; no corporate filler
- No em dashes
- No "I'm glad to help" / "Certainly!" openers
- Show diffs before committing, confirm before destructive git operations
- Challenge inconsistent reasoning rather than agreeing
- Refine existing drafts rather than rewriting from scratch
- When unsure, ask before committing

## Related Context

- **H1B status:** Personally-filed independent patent, no employer assignee. Keep patent + immigration counsel in the loop on any IP-assignment question for the non-provisional, especially if employer-related work during H1B specialty-occupation hours could later be challenged as having claims on the invention.

---

*This file is read by Claude Code at the start of every session. Keep it updated as the project evolves.*
