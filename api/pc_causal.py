"""
api/pc_causal.py
═══════════════════════════════════════════════════════════════════════════════
Causal5G — REST API for PC Algorithm (Patent Claim 3)
Mounts onto existing FastAPI app at localhost:8080

Endpoints
─────────
  POST /causal/pc/fit          — run PC algorithm on posted telemetry data
  GET  /causal/pc/result       — return last PC result (cached)
  GET  /causal/pc/fused        — return Granger+PC fused graph
  GET  /causal/pc/compare      — side-by-side Granger vs PC edge comparison

Author : Krishna Kumar Gattupalli
Patent : US Provisional Filed March 2026
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from causal.engine.pc_algorithm import (
    GrangerPCFusion,
    PCAlgorithm,
    PCResult,
    DIRECTED,
    UNDIRECTED,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/causal/pc", tags=["PC Algorithm (Patent Claim 3)"])

# ── In-memory state (replace with Redis/DB in production) ────────────────────
_last_pc_result: Optional[PCResult] = None
_last_fused_edges: Optional[List[Dict]] = None


# ── Request/Response Models ───────────────────────────────────────────────────

class TelemetryPayload(BaseModel):
    """
    Telemetry data for PC algorithm input.
    Each key is a metric name; value is a list of time-series observations.

    Example:
    {
      "metrics": {
        "amf_cpu":      [12.1, 14.3, 88.2, 91.0, ...],
        "smf_cpu":      [11.0, 13.1, 85.0, 89.5, ...],
        "upf_latency":  [2.1,  2.3,  45.2, 48.1, ...],
        "pcf_cpu":      [9.0,  9.1,  9.3,  9.2,  ...],
        "nrf_cpu":      [5.0,  5.1,  5.2,  5.0,  ...]
      },
      "alpha": 0.05,
      "max_cond_set": 3
    }
    """
    metrics: Dict[str, List[float]] = Field(
        ..., description="NF metric time series. Keys = metric names."
    )
    alpha: float = Field(0.05, ge=0.001, le=0.2,
                         description="Significance level for CI tests")
    max_cond_set: int = Field(3, ge=0, le=6,
                              description="Max conditioning set size")


class GrangerEdgesPayload(BaseModel):
    """Granger edges for fusion with PC result."""
    edges: Dict[str, float] = Field(
        ...,
        description=(
            'Dict of "cause->effect" : p_value. '
            'Example: {"smf_cpu->upf_latency": 0.02}'
        )
    )


class EdgeResponse(BaseModel):
    source: str
    target: str
    edge_type: str   # "-->" or "---"
    method: Optional[str] = None
    weight: Optional[float] = None
    p_value_granger: Optional[float] = None
    conflict: bool = False


class PCFitResponse(BaseModel):
    status: str
    n_variables: int
    n_samples: int
    alpha: float
    elapsed_seconds: float
    skeleton_edge_count: int
    directed_edge_count: int
    undirected_edge_count: int
    v_structure_count: int
    ci_tests_run: int
    cpdag_edges: List[EdgeResponse]
    v_structures: List[Dict[str, str]]
    summary: str


class FusedGraphResponse(BaseModel):
    status: str
    total_edges: int
    confirmed_edges: int      # in both Granger and PC, same direction
    granger_pc_undirected_edges: int = 0  # PC skeleton ⇒ corroborated, direction from Granger
    granger_only_edges: int
    pc_only_edges: int
    conflict_edges: int
    edges: List[Dict[str, Any]]


class CompareResponse(BaseModel):
    granger_edges: List[Dict]
    pc_directed_edges: List[Dict]
    pc_undirected_edges: List[Dict]
    agreement: List[Dict]
    conflicts: List[Dict]
    granger_only: List[Dict]
    pc_only: List[Dict]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/fit", response_model=PCFitResponse, summary="Run PC Algorithm on telemetry")
async def fit_pc(payload: TelemetryPayload):
    """
    Run the PC algorithm (Patent Claim 3) on posted telemetry data.

    The PC algorithm performs constraint-based causal discovery using
    conditional independence tests (partial correlation + Fisher's Z).
    Unlike Granger causality, PC discovers structural (contemporaneous)
    causal relationships and produces a CPDAG.

    The result is cached and available via GET /causal/pc/result.
    """
    global _last_pc_result

    # Validate data
    lengths = [len(v) for v in payload.metrics.values()]
    if len(set(lengths)) > 1:
        raise HTTPException(400, "All metric series must have equal length")
    if min(lengths) < 10:
        raise HTTPException(400, f"Need ≥10 samples per metric; got {min(lengths)}")
    if len(payload.metrics) < 2:
        raise HTTPException(400, "Need ≥2 metrics to discover causal structure")

    df = pd.DataFrame(payload.metrics)

    try:
        pc = PCAlgorithm(
            alpha=payload.alpha,
            max_cond_set=payload.max_cond_set,
        )
        result = pc.fit(df)
    except Exception as exc:
        logger.exception("PC algorithm failed")
        raise HTTPException(500, f"PC algorithm error: {exc}") from exc

    _last_pc_result = result

    return PCFitResponse(
        status="ok",
        n_variables=result.n_variables,
        n_samples=result.n_samples,
        alpha=result.alpha,
        elapsed_seconds=result.elapsed_seconds,
        skeleton_edge_count=len(result.skeleton_edges),
        directed_edge_count=len(result.directed_edges()),
        undirected_edge_count=len(result.undirected_edges()),
        v_structure_count=len(result.v_structures),
        ci_tests_run=len(result.independence_tests),
        cpdag_edges=[
            EdgeResponse(source=u, target=v, edge_type=t)
            for u, v, t in result.cpdag_edges
        ],
        v_structures=[
            {"cause": u, "collider": c, "effect": v}
            for u, c, v in result.v_structures
        ],
        summary=result.summary(),
    )


@router.get("/result", response_model=PCFitResponse, summary="Return last PC result")
async def get_pc_result():
    """Return the most recently computed PC algorithm result."""
    if _last_pc_result is None:
        raise HTTPException(404, "No PC result yet. POST to /causal/pc/fit first.")

    r = _last_pc_result
    return PCFitResponse(
        status="ok",
        n_variables=r.n_variables,
        n_samples=r.n_samples,
        alpha=r.alpha,
        elapsed_seconds=r.elapsed_seconds,
        skeleton_edge_count=len(r.skeleton_edges),
        directed_edge_count=len(r.directed_edges()),
        undirected_edge_count=len(r.undirected_edges()),
        v_structure_count=len(r.v_structures),
        ci_tests_run=len(r.independence_tests),
        cpdag_edges=[
            EdgeResponse(source=u, target=v, edge_type=t)
            for u, v, t in r.cpdag_edges
        ],
        v_structures=[
            {"cause": u, "collider": c, "effect": v}
            for u, c, v in r.v_structures
        ],
        summary=r.summary(),
    )


@router.post("/fused", response_model=FusedGraphResponse,
             summary="Fuse Granger + PC into unified causal graph")
async def fuse_granger_pc(payload: GrangerEdgesPayload):
    """
    Merge Granger causal DAG (Claim 1) with the last PC CPDAG (Claim 3).

    Fusion rules:
    - CONFIRMED      : edge in both → weight 1.5× (high confidence)
    - GRANGER_ONLY   : Granger only → weight 1.0×
    - PC_ONLY        : PC structural only → weight 0.7×
    - CONFLICT       : opposing directions → flagged, weight 0.5×

    Requires a PC result to be available (POST /causal/pc/fit first).
    """
    if _last_pc_result is None:
        raise HTTPException(404, "No PC result cached. POST /causal/pc/fit first.")

    # Parse "cause->effect": p_value format
    granger_edges: Dict[tuple, float] = {}
    for key, p_val in payload.edges.items():
        parts = key.split("->")
        if len(parts) != 2:
            raise HTTPException(400, f"Invalid edge key format: '{key}'. Use 'cause->effect'")
        granger_edges[(parts[0].strip(), parts[1].strip())] = p_val

    fusion = GrangerPCFusion()
    fused = fusion.fuse(granger_edges, _last_pc_result)

    global _last_fused_edges
    _last_fused_edges = fused

    method_counts = {}
    for e in fused:
        method_counts[e["method"]] = method_counts.get(e["method"], 0) + 1

    return FusedGraphResponse(
        status="ok",
        total_edges=len(fused),
        confirmed_edges=method_counts.get("confirmed", 0),
        granger_pc_undirected_edges=method_counts.get("granger_pc_undirected", 0),
        granger_only_edges=method_counts.get("granger_only", 0),
        pc_only_edges=method_counts.get("pc_only", 0),
        conflict_edges=method_counts.get("conflict", 0),
        edges=fused,
    )


@router.get("/compare", response_model=CompareResponse,
            summary="Compare Granger vs PC edge sets")
async def compare_methods():
    """
    Side-by-side comparison of what Granger and PC agree/disagree on.
    Useful for demo and whitepaper — shows where structural and
    temporal causality align.
    """
    if _last_pc_result is None:
        raise HTTPException(404, "No PC result. POST /causal/pc/fit first.")
    if _last_fused_edges is None:
        raise HTTPException(404, "No fused graph. POST /causal/pc/fused first.")

    granger_edges = [e for e in _last_fused_edges if e["method"] in
                     ("confirmed", "granger_only", "conflict", "granger_pc_undirected")]
    pc_dir  = [{"source": u, "target": v}
               for u, v, t in _last_pc_result.cpdag_edges if t == DIRECTED]
    pc_undir = [{"source": u, "target": v}
                for u, v, t in _last_pc_result.cpdag_edges if t == UNDIRECTED]

    agreement  = [e for e in _last_fused_edges if e["method"] in ("confirmed", "granger_pc_undirected")]
    conflicts  = [e for e in _last_fused_edges if e["conflict"]]
    gran_only  = [e for e in _last_fused_edges if e["method"] == "granger_only"]
    pc_only    = [e for e in _last_fused_edges if e["method"] == "pc_only"]

    return CompareResponse(
        granger_edges=[{"source": e["source"], "target": e["target"],
                        "p_value": e["p_value_granger"]} for e in granger_edges],
        pc_directed_edges=pc_dir,
        pc_undirected_edges=pc_undir,
        agreement=[{"source": e["source"], "target": e["target"],
                    "weight": e["weight"]} for e in agreement],
        conflicts=[{"source": e["source"], "target": e["target"]} for e in conflicts],
        granger_only=[{"source": e["source"], "target": e["target"]} for e in gran_only],
        pc_only=[{"source": e["source"], "target": e["target"]} for e in pc_only],
    )
