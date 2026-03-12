# Causal5G

**Causal Directed Acyclic Graph-Based Fault Isolation for Cloud-Native 5G Standalone Core Networks**

> US Provisional Patent Application — Pending  
> Inventor: Krishna Kumar Gattupalli  
> Status: Pre-filing. All rights reserved.

---

## Overview

Causal5G is a research and patent project implementing slice-topology-aware causal root cause analysis (RCA) for cloud-native 5G Standalone (SA) core networks.

The core problem: when a KPI degrades in a multi-slice 5G SA deployment, existing tools cannot distinguish between:

- An **NF-layer fault** — a shared Network Function (AMF, SMF, UPF) that affects all slices using it
- A **slice-layer fault** — a configuration, policy, or session issue local to one S-NSSAI

Causal5G solves this using a **bi-level causal DAG** that is structurally aware of 5G slice topology, SBI HTTP/2 dependencies, and PFCP session bindings.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Telemetry Layer                       │
│  sbi_collector.py  pfcp_collector.py  slice_kpi.py      │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                  Bi-Level Causal DAG                     │
│                                                          │
│  Level 1: NF Graph (AMF─SMF─UPF─PCF─NRF─AUSF─UDM)      │
│           edges = SBI HTTP/2 call sequences              │
│                                                          │
│  Level 2: Slice Subgraphs per S-NSSAI                    │
│           1:1 (eMBB)  1:2 (URLLC)  1:3 (mIoT)           │
│           shared NF nodes appear in multiple subgraphs   │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Causal Discovery (PCMCI / PC / FCI)         │
│         constrained by topology structural prior         │
│              topology_prior.py  ·  pcmci.py              │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                  Attribution Scoring                     │
│   NF-layer fault?  ──  shared NF, multiple slices        │
│   Slice-layer fault? ── single subgraph, isolated        │
│                    attribution.py                        │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│            Closed-Loop Remediation (Claim 3)             │
│   policy_store.py → executor.py → verifier.py            │
│                                                          │
│   NF scale-out  ·  PFCP re-establish  ·  PCF tighten    │
└─────────────────────────────────────────────────────────┘
```

---

## Patent Claims Summary

| Claim | Type | Description |
|---|---|---|
| 1 | Independent Method | Bi-level causal DAG construction + NF/slice root cause isolation |
| 2 | Dependent Method | Four-domain hierarchical graph (RAN → Transport → Core → Cloud) |
| 3 | Dependent Method | Closed-loop remediation with SBI/PFCP control-plane execution |
| 4 | Independent System | Apparatus claim with PCMCI named + time-lag edge annotation |

---

## Prior Art Differentiation

| Feature | CauseInfer '14 | MicroCause '20 | MicroDiag '21 | Causal5G |
|---|---|---|---|---|
| Bi-level NF + slice subgraph | ✗ | ✗ | ✗ | ✅ |
| S-NSSAI slice identity | ✗ | ✗ | ✗ | ✅ |
| PFCP N4 session telemetry | ✗ | ✗ | ✗ | ✅ |
| SBI HTTP/2 topology prior | ✗ | ✗ | ✗ | ✅ |
| NF-layer vs slice-layer isolation | ✗ | ✗ | ✗ | ✅ |
| RAN→Transport→Core→Cloud hierarchy | ✗ | ✗ | ✗ | ✅ |
| Closed-loop SBI/PFCP remediation | ✗ | ✗ | ✗ | ✅ |

---

## Repository Structure

```
causal5g/
├── graph/
│   ├── bilevel_dag.py        # Claim 1: bi-level NF + slice DAG
│   ├── topology_prior.py     # Claim 1: SBI + PFCP structural prior
│   ├── hierarchical_dag.py   # Claim 2: four-domain hierarchy
│   └── cross_domain.py       # Claim 2: cross-domain edge inference
├── telemetry/
│   ├── sbi_collector.py      # Claim 1: SBI HTTP/2 call capture
│   ├── pfcp_collector.py     # Claim 1: PFCP N4 session stats
│   └── slice_kpi.py          # Claim 1: per-S-NSSAI KPI measurement
├── causal/
│   ├── discovery.py          # Claim 1: algorithm-agnostic causal engine
│   ├── pcmci.py              # Claim 4: PCMCI time-lagged DAG (tigramite)
│   └── attribution.py        # Claim 1: NF/slice attribution scoring
├── rca/
│   └── report.py             # Claim 1: structured RCA report
└── remediation/
    ├── policy_store.py       # Claim 3: policy lookup by root cause type
    ├── executor.py           # Claim 3: K8s/SMF/PCF API execution
    └── verifier.py           # Claim 3: post-remediation effectiveness check
patent/
└── drafts/
    └── Causal5G_Patent_Draft_v2.docx
tests/
└── ...
```

---

## Installation

```bash
# Clone
git clone git@github.com:gattupallik/causal5g.git
cd causal5g

# Install with dev dependencies
pip install -e ".[dev]"

# With Kubernetes orchestrator support (Claim 3 executor)
pip install -e ".[dev,orchestrator]"

# With service mesh telemetry support
pip install -e ".[dev,servicemesh]"
```

---

## Quick Start

```python
from causal5g.graph.bilevel_dag import BiLevelCausalDAG, NFNode, SliceSubgraph
from causal5g.graph.topology_prior import TopologyPrior
from causal5g.causal.discovery import CausalDiscovery
from causal5g.causal.pcmci import PCMCIBackend
from causal5g.causal.attribution import CausalAttributionScorer
from causal5g.rca.report import RootCauseReporter

# 1. Build topology prior from 3GPP SBI relationships
prior = TopologyPrior(pfcp_bindings=[("smf-1", "upf-1"), ("smf-1", "upf-2")])

# 2. Construct bi-level DAG
dag = BiLevelCausalDAG(topology_prior=prior)
for nf_id, nf_type in [("amf-1","AMF"),("smf-1","SMF"),("upf-1","UPF"),("pcf-1","PCF")]:
    dag.add_nf_node(NFNode(nf_id=nf_id, nf_type=nf_type, instance_id=nf_id))

# Shared AMF across all slices, dedicated SMF/UPF per slice
dag.add_slice_subgraph(SliceSubgraph(
    snssai="1:1", nf_nodes=["amf-1","smf-1","upf-1","pcf-1"],
    dedicated_nf_nodes=["smf-1","upf-1"], shared_nf_nodes=["amf-1"]))
dag.add_slice_subgraph(SliceSubgraph(
    snssai="1:2", nf_nodes=["amf-1","smf-1","upf-2","pcf-1"],
    dedicated_nf_nodes=["upf-2"], shared_nf_nodes=["amf-1","smf-1"]))

# 3. Run PCMCI causal discovery on telemetry window
import numpy as np
data = np.random.randn(300, 4)   # 300 time steps, 4 NF metrics
backend = PCMCIBackend(tau_max=10, alpha=0.05)
engine = CausalDiscovery(backend=backend, topology_prior=prior)
causal_graph = engine.run(data, variable_names=["amf-1","smf-1","upf-1","pcf-1"])

# 4. Score and isolate root cause
scorer = CausalAttributionScorer()
result = scorer.score(causal_graph, dag, anomaly_node="smf-1")

# 5. Generate report
reporter = RootCauseReporter()
report = reporter.generate(result)
print(report.to_json())
```

---

## Running Tests

```bash
pytest tests/ -v --cov=causal5g
```

---

## Key References

- 3GPP TS 23.501 — System Architecture for 5G SA
- 3GPP TS 29.244 — PFCP Protocol (N4 Interface)
- 3GPP TS 29.500 — 5G SBI HTTP/2 Framework
- Runge et al. (2019) — PCMCI, *Science Advances*
- Spirtes, Glymour, Scheines (1993) — PC Algorithm
- CauseInfer (2014), MicroCause (2020), MicroDiag (2021) — prior art

---

## Legal

**CONFIDENTIAL — All Rights Reserved**  
US Provisional Patent Application Pending.  
Unauthorized use, reproduction, or distribution is prohibited.  
© 2025 Krishna Kumar Gattupalli
