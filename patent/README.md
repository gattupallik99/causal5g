# Causal5G — Patent Record

## Status Summary

| Item | Detail |
|---|---|
| **Provisional App #** | 64/015,070 |
| **Patent Center #** | 74984861 |
| **Confirmation #** | 5282 |
| **Filing Date** | March 24, 2026 |
| **Entity Status** | Micro Entity (37 CFR §1.29) |
| **Filing Fee Paid** | $65.00 (Fee Code 3005) |
| **Inventor** | Krishna Kumar Gattupalli |
| **Address** | 6230 Lake Brook DR, Celina, TX 75009, US |
| **Status** | Application Undergoing Preexam Processing |
| **Non-Provisional Deadline** | **March 24, 2027** |
| **PCT Deadline** | **March 24, 2027** |

## Title

System and Method for Slice-Topology-Aware Causal Root Cause Analysis and
Closed-Loop Remediation for Cloud-Native 5G Standalone Core Networks

## CPC Classification Codes

- H04W 24/02 — Testing, monitoring, measuring network performance
- H04L 41/0631 — Network management using causal or temporal analysis
- H04L 41/16 — Using machine learning

## Claims Filed in Provisional (6 claims)

| Claim | Type | Subject |
|---|---|---|
| 1 | Independent method | Bi-level causal DAG with S-NSSAI slice topology, PFCP N4 bindings, SBI structural priors |
| 2 | Dependent (on 1) | Four-domain hierarchical graph: RAN + Transport + Core + Cloud |
| 3 | Dependent (on 1) | Closed-loop remediation action mapper |
| 4 | Independent system | PCMCI causal discovery algorithm with time-lagged 5G telemetry |
| 5 | CRM | Non-transitory computer-readable medium |
| 6 | Dependent (on 1) | O-RAN Non-RT RIC / SMO integration |

## Non-Provisional Draft (this session — April 30, 2026)

15 claims drafted across 3 independent claim types:
- Method (Claims 1–6, 13–15)
- System (Claims 7–10)
- Computer-Readable Medium (Claims 11–12)

**Action required before filing non-provisional:**
- [ ] Fill in official filing date from USPTO Filing Receipt (when issued)
- [ ] Update 3GPP-specific terminology (S-NSSAI, PFCP, SBI) to match provisional depth
- [ ] Attorney review of claim language
- [ ] Convert SVG drawings to USPTO-compliant .tiff format (black & white, 300 DPI)
- [ ] Prepare Application Data Sheet (ADS)
- [ ] Prepare inventor oath/declaration (Form AIA/01)

## Directory Structure

```
patent/
├── README.md                          ← this file
├── provisional/
│   ├── Specification.pdf              ← filed specification (signed)
│   ├── Specification_unsigned.pdf     ← specification (unsigned version)
│   ├── Specification.docx             ← specification (Word source)
│   ├── Causal5G_Patent_Drawings.pdf   ← drawings filed with provisional
│   └── N417.PYMT.pdf                  ← USPTO electronic payment receipt
├── non-provisional/
│   ├── Causal5G_NonProvisional_Patent_DRAFT.docx   ← full draft (Apr 30 2026)
│   ├── build_patent.js                              ← script that generates docx
│   └── figures/
│       ├── FIG1_System_Architecture.svg
│       ├── FIG2_BiLevel_DAG.svg
│       ├── FIG3_Method_Flowchart.svg
│       └── FIG4_Recalibration_Loop.svg
```

## Key Dates

```
Mar 24, 2026  Provisional filed (#64/015,070), $65 fee paid — PRIORITY DATE LOCKED
Apr 30, 2026  Non-provisional draft + USPTO-style figures created (15 claims)
              DEVELOPMENT_LOG updated, all docs committed to main
[TBD]         USPTO issues formal Filing Receipt (check Patent Center Documents tab)
Jan 2027      Target: non-provisional ready for attorney review
Mar 24, 2027  HARD DEADLINE: non-provisional must be filed (12 months from provisional)
Mar 24, 2027  HARD DEADLINE: PCT application if international protection desired
```

## Prior Art Distinguished

| Prior Art | Year | Gap addressed by Causal5G |
|---|---|---|
| CauseInfer (Chen et al.) | 2014 | No S-NSSAI, no PFCP, no SBI, no 5G SA |
| MicroCause (Meng et al.) | 2020 | No slice topology, no bi-level DAG |
| MicroDiag (Wang et al.) | 2021 | No 5G SA awareness, no closed-loop remediation |

## Reduction to Practice (Code Evidence)

All 4 patent claims are fully reduced to practice in `~/causal5g`:

| Claim | Reduced | Days | Key evidence |
|---|---|---|---|
| 1 — Bi-level causal DAG | ✅ | Day 17 + 18 | `causal/slice_ensemble.py`, pcf_timeout SB=0.667 |
| 2 — Multi-source telemetry | ✅ | Day 9–11 | `causal/engine/rcsm.py`, 4-domain ingest |
| 3 — Recalibration loop | ✅ | Day 11–17 | `api/frg.py`, RAE + DCGM recalibration |
| 4 — Composite scoring | ✅ | Day 11–12 | S_i = G_i × C_i × (1 + B_i) |

453 tests passing. Live demo at `/patent-demo-v3` (tag: `day18`).
