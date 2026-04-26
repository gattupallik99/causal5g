# Day 19 — Level-2 Slice Attribution Wired into Live API

Evidence bundle for **Claim 1's bi-level DAG, fully integrated into the REST API**.

Generated: 2026-04-26  
API base: `http://localhost:8080` (topology sweep run offline)

## Purpose

Day 18 built `SliceEnsembleAttributor` and proved Level-2 attribution offline.
Day 19 wires it into the live pipeline: every `FaultReport` produced by
`frg.py`'s `pipeline_loop()` now carries `slice_attribution` containing the
Level-2 result. The `GET /rca` endpoint exposes both levels simultaneously.

## What changed

| File | Change |
|---|---|
| `causal/engine/rcsm.py` | Added `slice_attribution: Optional[dict] = None` field to `FaultReport` |
| `api/frg.py` | Import + instantiate `SliceEnsembleAttributor` in `PipelineState`; call `sea.attribute()` after every real Level-1 report; attach result to `report.slice_attribution` |
| `api/frg.py` | Updated `report_to_dict()` to include `slice_attribution` key |
| `api/frg.py` | Added `GET /rca` endpoint (live sweep target) |
| `tests/integration/test_day19_slice_wiring.py` | 37 new tests — all pass |

## Sweep results

Offline simulation of the pipeline wiring (5 fault scenarios):

| Scenario | NF | NF-layer score | Breadth | Affected | Isolation type | Ensemble |
|---|---|---|---|---|---|---|
| nrf_crash | nrf | 1.010 | 1.0000 | 3/3 | infrastructure-wide | 1.0000 |
| amf_crash | amf | 1.010 | 1.0000 | 3/3 | all-slice-nf | 1.0000 |
| smf_crash | smf | 1.010 | 1.0000 | 3/3 | all-slice-nf | 1.0000 |
| **pcf_timeout** | **pcf** | **1.010** | **0.6667** | **2/3** | **slice-isolated** | **0.8000** |
| udm_crash | udm | 1.010 | 1.0000 | 3/3 | all-slice-nf | 1.0000 |

**pcf_timeout per-slice breakdown:**

| Slice ID | Label | PCF present | Path weight | Nodes | Edges |
|---|---|---|---|---|---|
| 1-000001 | eMBB | YES | 7.0 | 7 | 10 |
| 2-000001 | URLLC | YES | 7.0 | 7 | 10 |
| 3-000001 | mIoT | **NO** | **0.0** | 1 | 0 |

## Key assertions verified

- `pcf_timeout` → `slice_breadth = 0.6667`, `isolation_type = "slice-isolated"` ✓
- `nrf_crash` → `slice_breadth = 1.0`, `isolation_type = "infrastructure-wide"` ✓
- `GET /rca` response schema includes `slice_attribution` dict for real faults ✓
- INFO reports (no fault detected) leave `slice_attribution = null` ✓

## GET /rca response schema (Day 19)

```json
{
  "status": "ok",
  "active_injections": ["pcf_timeout"],
  "report": {
    "report_id": "FR-0001-...",
    "severity": "CRITICAL",
    "root_cause": {
      "nf_id": "pcf",
      "composite_score": 1.01,
      ...
    },
    "slice_attribution": {
      "root_cause_nf": "pcf",
      "nf_layer_score": 1.01,
      "n_slices_total": 3,
      "n_slices_affected": 2,
      "slice_breadth": 0.6667,
      "slice_discriminant": 0.6667,
      "isolation_type": "slice-isolated",
      "ensemble_score": 0.8,
      "per_slice": [
        {"slice_id": "1-000001", "label": "eMBB",  "nf_present": true,  "path_weight": 7.0, ...},
        {"slice_id": "2-000001", "label": "URLLC", "nf_present": true,  "path_weight": 7.0, ...},
        {"slice_id": "3-000001", "label": "mIoT",  "nf_present": false, "path_weight": 0.0, ...}
      ]
    }
  }
}
```

## Patent claim mapping

- **Claim 1 (bi-level causal DAG):** Level-1 (RCSM) + Level-2 (SliceEnsembleAttributor)
  now run in sequence within `pipeline_loop()`. The `FaultReport` is the single
  artefact carrying both levels.
- **Claim 1(h) (fault report):** `FaultReport.slice_attribution` extends the
  report with the Level-2 verdict — `isolation_type` and `slice_breadth` are
  outputs the NF layer alone cannot produce.
- **Claim 6 (REST API):** `GET /rca` is the new primary endpoint exposing the
  complete bi-level report. `GET /faults/active` also returns the full report
  for backward compatibility.
