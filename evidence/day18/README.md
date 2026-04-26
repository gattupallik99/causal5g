# Day 18 — Slice-Layer Attribution Sweep

Evidence bundle for **Claim 1's bi-level DAG, Level-2 (slice sub-DAG) tier**.

Generated: 2026-04-26  
API base: `http://localhost:8080` (topology queried offline via SliceTopologyManager)

## Purpose

Day 17 established 5/5 NF-layer attribution accuracy using Docker
container-status as the primary signal. Every scenario produced an
identical composite score gap of 0.01 at the NF layer — the NF-layer
alone cannot distinguish a PCF timeout (slice-isolated fault) from an
NRF crash (infrastructure-wide fault) by score alone.

Day 18 activates Level-2 of Claim 1's bi-level DAG: attribution through
the slice sub-DAG. The sweep shows that the slice layer provides a clean
discriminating signal where the NF layer is ambiguous.

## Slice Topology (default 3-slice Free5GC lab)

| Slice ID | Label | NF set |
|---|---|---|
| 1-000001 | eMBB  | amf, smf, pcf, udm, upf |
| 2-000001 | URLLC | amf, smf, pcf, udm, upf |
| 3-000001 | mIoT  | amf, smf, udm, upf      |

Note: mIoT has no PCF. This is the structural fact that makes the slice
layer discriminating for the pcf_timeout scenario.

## Summary

| Scenario | NF | NF Score | Score Gap | Breadth | Isolation | Ensemble |
|---|---|---|---|---|---|---|
| nrf_crash   | nrf | 1.010 | 0.010 | 1.000 | infrastructure-wide | 1.000 |
| amf_crash   | amf | 1.010 | 0.010 | 1.000 | all-slice-nf        | 1.000 |
| smf_crash   | smf | 1.010 | 0.010 | 1.000 | all-slice-nf        | 1.000 |
| **pcf_timeout** | **pcf** | **1.010** | **0.010** | **0.667** | **slice-isolated** | **0.800** |
| udm_crash   | udm | 1.010 | 0.010 | 1.000 | all-slice-nf        | 1.000 |

## Key Finding

`pcf_timeout` is the **only scenario with `slice_breadth < 1.0`**.

The NF-layer composite gap is 0.01 for every scenario — there is no
score-based way to distinguish a slice-isolated fault from an
infrastructure-wide one at Level-1 alone.

The slice layer resolves this:
- PCF affects only the 2 slices that include PCF (eMBB, URLLC); mIoT is immune.
- `slice_breadth = 2/3 = 0.667` vs NRF `slice_breadth = 1.0`.
- The `isolation_type = "slice-isolated"` classification is only possible
  with Level-2 analysis.

This is Claim 1's bi-level DAG in operation: Level-1 identifies the
root-cause NF; Level-2 characterises the fault's slice scope.

## Per-Slice Detail: pcf_timeout

| Slice | Label | PCF present | Path weight | Nodes | Edges |
|---|---|---|---|---|---|
| 1-000001 | eMBB  | YES | 7.0 | 7 | 10 |
| 2-000001 | URLLC | YES | 7.0 | 7 | 10 |
| 3-000001 | mIoT  | **NO** | **0.0** | 1 | 0 |

mIoT's path_weight = 0 because PCF is absent from its NF set; the pruned
ancestor subgraph for PCF in the mIoT slice graph has no edges.

## Claim Mapping

- **Claim 1** — bi-level causal DAG:
  - Level 1 (NF-layer): `causal/engine/rcsm.py` — composite score
  - Level 2 (slice-layer): `causal5g/causal/slice_ensemble.py` — `SliceEnsembleAttributor`
  - NF-layer vs slice-layer attribution comparison: `evidence/day18/results/summary.tsv`
  - The pcf_timeout per-slice breakdown is the reduction-to-practice for
    the "slice subgraph" part of Claim 1.

## Reproducing

```bash
# From repo root
python3 evidence/day18/day18_sweep.py
```

No live containers required — runs entirely from the imported
`SliceTopologyManager` with the default 3-slice topology.
