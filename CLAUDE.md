# Causal5G — Project Context for Claude Code

## Inventor & Ownership

- **Inventor:** Krishna Kumar Gattupalli
- **Assignee:** Invences Inc., Frisco, Texas
- **Repo:** github.com/gattupallik/causal5g (private)
- **Local path:** ~/causal5g

## Patent Context

**Title:** System and Method for Slice-Topology-Aware Causal Root Cause Analysis and Closed-Loop Remediation for Cloud-Native 5G Standalone Core Networks

**Filing status:** US Provisional — **NOT YET FILED** (top priority)
**Entity status:** Micro Entity ($65 USPTO filing fee)

**The four claims:**
1. **Claim 1** — Bi-level causal DAG construction (Level 1 = NF nodes, Level 2 = slice subgraphs) with NF-layer vs slice-layer root cause attribution
2. **Claim 2** — Hierarchical four-domain graph (RAN → Transport → Core → Cloud) with RCA report artefact
3. **Claim 3** — Confidence-gated closed-loop remediation with persistent policy table and pluggable orchestrator adapter
4. **Claim 4** — Feedback-driven DAG recalibration from remediation outcomes

**All four claims are reduced to practice as of commit `f666442` (Day 11, April 17, 2026).**

## Disclosure Discipline — IMPORTANT

Until the provisional is filed, do not disclose publicly:
- The name "Causal5G"
- The PC algorithm + Granger causality fusion mechanism
- The bi-level DAG slice-topology construction
- Closed-loop remediation details

Applies to: blog posts, conference talks, issue comments, LinkedIn, public README edits, arXiv, IEEE ISEC 2026 (Princeton). The repo itself being public is already a grace-period start; additional disclosure expands exposure.

Safe to discuss publicly: general interest in 5G observability, causal inference, K8s operator work.

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
├── tests/                  # 182 passing tests (pytest --no-cov -q)
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
- **Run tests:** `python3 -m pytest --no-cov -q` (expect 182 passing)
- **Run coverage:** `python3 -m pytest --cov=causal5g --cov-report=term-missing`
- **Run API:** `uvicorn api.frg:app --port 8080 --reload`
- **Swagger:** http://localhost:8080/docs
- **Demo dashboard:** http://localhost:8080/demo
- **Control panel:** http://localhost:8080/control

## Day 12 Priorities (top to bottom)

1. **File US Provisional Patent** — every day without filing is exposure risk. Need: claim language finalized, figures, inventor declaration, $65 fee.
2. **Coverage expansion — Claim 2 modules at 0%:**
   - `causal5g/graph/cross_domain.py` (0%)
   - `causal5g/graph/hierarchical_dag.py` (0%)
   - `causal5g/causal/discovery.py` (0%)
   - `causal5g/causal/pcmci.py` (0%)
3. **Production K8s client integration** — wire the `kubernetes` Python client into `causal5g/remediation/executor.py` `_do_*` handlers. Keep interface contract intact (tests must still pass).
4. **Prometheus metrics exporter** — observability for ISEC 2026 (deferred until post-filing).

## Communication Style

- Direct and concise; no corporate filler
- No em dashes
- No "I'm glad to help" / "Certainly!" openers
- Show diffs before committing, confirm before destructive git operations
- Challenge inconsistent reasoning rather than agreeing
- Refine existing drafts rather than rewriting from scratch
- When unsure, ask before committing

## Related Context

- **IEEE ISEC 2026:** Upcoming presentation at Princeton. Do not use "Causal5G" or disclose the PC-algorithm mechanism until provisional is filed.
- **Invences Inc:** The assignee; Technical Director Krishna runs this as a protected-IP project.
- **H1B status:** Active constraint on any IP-assignment paperwork; all patents are assigned to Invences, not held personally.

---

*This file is read by Claude Code at the start of every session. Keep it updated as the project evolves.*
