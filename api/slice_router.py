"""
Slice topology REST API — Causal5G Day 9
Exposes SliceTopologyManager over HTTP for integration with FRG.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from causal5g.slice_topology import get_stm, SHARED_NFS, SLICE_SPECIFIC_NFS

router = APIRouter(prefix="/slice", tags=["slice-topology"])

_stm = get_stm()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class RegisterSliceRequest(BaseModel):
    nssai:  str            = Field(..., example="1-000001")
    nf_set: list[str] | None = Field(None, example=["amf", "smf", "pcf", "udm", "upf"])


class PruneRequest(BaseModel):
    faulted_nf: str            = Field(..., example="smf")
    slice_id:   str | None     = Field(None, example="1-000001")
    dag_edges:  list[list[str]] | None = Field(
        None,
        description="Live DAG edges from GrangerPCFusion [[cause,effect],...]"
    )


class LeakageRequest(BaseModel):
    fault_slice_id:         str        = Field(..., example="1-000001")
    candidate_root_causes:  list[str]  = Field(..., example=["amf", "smf", "nrf"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
async def list_slices():
    """List all registered slice configurations."""
    return _stm.to_dict()


@router.post("/register")
async def register_slice(req: RegisterSliceRequest):
    """Register or update a slice configuration."""
    nf_set = set(req.nf_set) if req.nf_set else None
    sc = _stm.register_slice(req.nssai, nf_set)
    return {"registered": sc.slice_id, "label": sc.label, "nf_set": sorted(sc.nf_set)}


@router.delete("/{nssai}")
async def remove_slice(nssai: str):
    """Remove a slice configuration."""
    removed = _stm.remove_slice(nssai)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Slice {nssai} not found")
    return {"removed": nssai}


@router.get("/graph/global")
async def global_graph():
    """Return the global (unfiltered) causal graph."""
    g = _stm.build_global_graph()
    return g.to_dict()


@router.get("/graph/{slice_id}")
async def slice_graph(slice_id: str):
    """Return the pruned causal graph for a specific slice."""
    sc = _stm.get_slice(slice_id)
    if sc is None:
        raise HTTPException(status_code=404, detail=f"Slice {slice_id} not found")
    g = _stm.build_slice_graph(slice_id)
    return g.to_dict()


@router.post("/graph/prune")
async def prune_graph(req: PruneRequest):
    """
    Return the minimal causal subgraph relevant to a faulted NF.
    Optionally intersects with live DAG edges from GrangerPCFusion.
    """
    dag_edges = None
    if req.dag_edges:
        dag_edges = [(e[0], e[1]) for e in req.dag_edges if len(e) >= 2]

    g = _stm.prune_for_fault(
        faulted_nf=req.faulted_nf,
        slice_id=req.slice_id,
        dag_edges=dag_edges,
    )
    return g.to_dict()


@router.post("/leakage")
async def detect_leakage(req: LeakageRequest):
    """
    Check whether candidate root causes include NFs from other slices.
    Returns leakage flags per NF.
    """
    result = _stm.detect_cross_slice_leakage(
        fault_slice_id=req.fault_slice_id,
        candidate_root_causes=req.candidate_root_causes,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/nf-catalog")
async def nf_catalog():
    """Return the NF classification used for graph pruning."""
    return {
        "shared_nfs":         sorted(SHARED_NFS),
        "slice_specific_nfs": sorted(SLICE_SPECIFIC_NFS),
    }
