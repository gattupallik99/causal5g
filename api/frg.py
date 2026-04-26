"""
FRG - Fault Report Generator v2 (Day 5)
Adds fault injection endpoints to the REST API.

New endpoints (Day 5):
  POST /faults/inject/{scenario}   - inject a fault scenario
  POST /faults/recover/{scenario}  - recover from a fault
  GET  /faults/scenarios           - list available scenarios
  GET  /faults/inject/status       - current injection state
  WS   /ws/live                    - websocket live feed
"""

import asyncio
import time
import threading
import json
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.responses import PlainTextResponse, HTMLResponse
import uvicorn
from loguru import logger

import sys
sys.path.insert(0, '/Users/krishnakumargattupalli/causal5g')

from telemetry.collector.nf_scraper import NFScraper
from causal.engine.granger import TelemetryBuffer, GrangerCausalityEngine
from causal.graph.dcgm import DynamicCausalGraphManager
from causal.engine.rcsm import RootCauseScoringModule, FaultReport
from faults.injector import FaultInjector
from causal5g.observability import metrics as _metrics  # Day 15
from causal5g.causal.slice_ensemble import SliceEnsembleAttributor  # Day 19
from causal.engine.recalibrator import get_recalibrator             # Day 20


def _to_py(x):
    """Convert numpy scalars (int64, float64, bool_, etc.) to native Python
    types so FastAPI's jsonable_encoder can serialize them. Pass through for
    anything already native, None, or composite types."""
    if x is None:
        return None
    if hasattr(x, "item") and not isinstance(x, (list, tuple, dict, set, str, bytes)):
        try:
            return x.item()
        except (ValueError, AttributeError):
            return x
    return x


# ── Global pipeline state ─────────────────────────────────────
class PipelineState:
    def __init__(self):
        self.scraper = NFScraper(scrape_interval=5)
        self.buffer = TelemetryBuffer(window_size=60)
        self.granger = GrangerCausalityEngine(max_lag=3, significance=0.05)
        self.dcgm = DynamicCausalGraphManager()
        self.rcsm = RootCauseScoringModule()
        self.injector = FaultInjector()
        self.sea = SliceEnsembleAttributor()       # Day 19: Level-2 slice attributor
        self.recalibrator = get_recalibrator()    # Day 20: Claim 4 feedback recalibrator
        self._last_feedback_consumed: int = 0    # index into RAE feedback buffer

        self.latest_report: Optional[FaultReport] = None
        self.report_history: list[FaultReport] = []
        self.candidates = []
        self.cycle_count = 0
        self.analysis_count = 0
        self.last_analysis_ts: Optional[str] = None
        self.running = False
        self.start_time = datetime.now(timezone.utc).isoformat()

        self.total_events_ingested = 0
        self.total_analyses_run = 0
        self.total_reports_generated = 0

        # WebSocket clients
        self.ws_clients: list[WebSocket] = []


state = PipelineState()


async def broadcast(msg: dict):
    """Broadcast to all connected WebSocket clients."""
    dead = []
    for ws in state.ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        state.ws_clients.remove(ws)


def pipeline_loop():
    """Continuous MTIE -> CIE -> DCGM -> RCSM pipeline."""
    logger.info("Pipeline started")
    state.running = True

    while state.running:
        try:
            events = state.scraper.scrape_all()
            state.buffer.add_events(events)
            state.cycle_count += 1
            state.total_events_ingested += len(events)

            # Day 15: per-NF scrape counter + pipeline gauges.
            for ev in events:
                nf_id = getattr(ev, "nf_id", None) or (
                    ev.get("nf_id") if isinstance(ev, dict) else None)
                if nf_id:
                    _metrics.record_scrape(str(nf_id).lower())
            _metrics.set_pipeline_cycles(state.cycle_count)
            _metrics.set_events_ingested(state.total_events_ingested)
            _metrics.set_buffer_fill_pct(state.buffer.fill_pct)
            _metrics.set_active_faults(len(state.injector.active_faults))

            if state.buffer.ready and state.cycle_count % 10 == 0:
                result = state.granger.analyze(state.buffer)
                state.dcgm.update_from_granger(result)
                candidates = state.rcsm.score(result, state.dcgm, state.buffer)
                report = state.rcsm.generate_report(candidates, state.buffer, result)

                # Day 19: Level-2 slice-layer attribution.
                # Skip for INFO reports (root_cause.nf_id == "none") — no
                # real NF to attribute.  For all genuine attributions, run
                # SliceEnsembleAttributor and attach the result dict so every
                # downstream consumer (report_to_dict, /rca, /faults/active)
                # sees slice_breadth + isolation_type alongside the NF score.
                if report.root_cause.nf_id != "none":
                    try:
                        slice_attr = state.sea.attribute(
                            root_cause_nf=report.root_cause.nf_id,
                            nf_layer_score=report.root_cause.composite_score,
                        )
                        report.slice_attribution = slice_attr.to_dict()
                        logger.info(
                            f"Level-2 | nf={report.root_cause.nf_id} | "
                            f"breadth={slice_attr.slice_breadth:.4f} | "
                            f"type={slice_attr.isolation_type} | "
                            f"ensemble={slice_attr.ensemble_score:.4f}"
                        )
                    except Exception as _sea_exc:
                        logger.warning(f"SliceEnsembleAttributor failed: {_sea_exc}")

                # Day 20: Claim 4 recalibration loop.
                # Consume any new RAE feedback entries since the last cycle,
                # run the recalibrator, and apply adjusted weights back into
                # the DCGM so the next RCSM centrality pass uses them.
                try:
                    from api.rae import get_feedback_buffer as _get_fb
                    feedback_buf = _get_fb()
                    new_entries = feedback_buf[state._last_feedback_consumed:]
                    if new_entries:
                        recal_summary = state.recalibrator.recalibrate(new_entries)
                        state._last_feedback_consumed = len(feedback_buf)
                        if not recal_summary.get("skipped"):
                            n_edges = state.dcgm.apply_recalibration(
                                state.recalibrator.get_all_weights()
                            )
                            logger.info(
                                f"Recalibration | cycle={recal_summary['cycle']} | "
                                f"entries={recal_summary['entries_consumed']} | "
                                f"dcgm_edges_updated={n_edges}"
                            )
                    # Attach recalibration snapshot to the report artefact
                    report.recalibration_snapshot = state.recalibrator.get_stats()
                except Exception as _recal_exc:
                    logger.warning(f"Recalibration tick failed: {_recal_exc}")

                state.candidates = candidates
                state.latest_report = report
                state.report_history.append(report)
                if len(state.report_history) > 50:
                    state.report_history.pop(0)

                state.analysis_count += 1
                state.total_analyses_run += 1
                state.total_reports_generated += 1
                state.last_analysis_ts = datetime.now(timezone.utc).isoformat()

                logger.info(
                    f"Analysis {state.analysis_count} | "
                    f"root_cause={report.root_cause.nf_id} | "
                    f"score={report.root_cause.composite_score:.4f} | "
                    f"active_faults={state.injector.active_faults}"
                )

                # Broadcast to websocket clients
                asyncio.run(broadcast({
                    "type": "analysis",
                    "report_id": report.report_id,
                    "root_cause": report.root_cause.nf_id,
                    "score": report.root_cause.composite_score,
                    "severity": report.severity,
                    "active_faults": state.injector.active_faults,
                    "causal_chain": report.root_cause.causal_path,
                    "timestamp": report.timestamp,
                }))

            time.sleep(5)

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            time.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=pipeline_loop, daemon=True)
    thread.start()
    logger.info("FRG v2 API started")
    yield
    state.running = False


app = FastAPI(
    title="causal5g FRG — Fault Report Generator",
    description="""
## Patent Claim 6: REST API for 5G Causal Fault Isolation

### Day 5: Fault Injection + Live Demo Loop

Inject faults via REST, watch the causal graph react in real time.

**Demo flow:**
1. `GET /faults/scenarios` — see available fault scenarios
2. `POST /faults/inject/nrf_crash` — crash NRF
3. `GET /faults/active` — watch root cause shift
4. `POST /faults/recover/nrf_crash` — recover
5. `GET /faults/active` — confirm system normalizes
""",
    version="2.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="docs"), name="static")

# --- Patent-claim routers (Claims 1 + 3) -----------------------------------
# These APIRouter modules each define their own `prefix`; mounting them here
# exposes the slice-topology CRUD, PC-algorithm discovery, Remediation Action
# Engine, and container control-panel routes in the live OpenAPI schema.
from api.rae import router as rae_router
from api.slice_router import router as slice_router
from api.pc_causal import router as pc_causal_router
from api.control import router as control_router

app.include_router(rae_router)
app.include_router(slice_router)
app.include_router(pc_causal_router)
app.include_router(control_router)
# ---------------------------------------------------------------------------

@app.get("/demo", include_in_schema=False)
async def demo():
    return FileResponse("docs/causal5g_demo.html")


def report_to_dict(report: FaultReport) -> dict:
    return {
        "report_id": report.report_id,
        "timestamp": report.timestamp,
        "severity": report.severity,
        "fault_category": report.fault_category,
        "affected_nfs": report.affected_nfs,
        "causal_chain": report.causal_chain,
        "recommended_action": report.recommended_action,
        "telemetry_window_cycles": report.telemetry_window_cycles,
        "root_cause": {
            "nf_id": report.root_cause.nf_id,
            "nf_type": report.root_cause.nf_type,
            "rank": report.root_cause.rank,
            "composite_score": report.root_cause.composite_score,
            "centrality_score": report.root_cause.centrality_score,
            "temporal_score": report.root_cause.temporal_score,
            "bayesian_score": report.root_cause.bayesian_score,
            "confidence": report.root_cause.confidence,
            "fault_category": report.root_cause.fault_category,
            "evidence": report.root_cause.evidence,
            "causal_path": report.root_cause.causal_path,
        },
        "all_candidates": [
            {
                "nf_id": c.nf_id,
                "rank": c.rank,
                "composite_score": c.composite_score,
                "centrality_score": c.centrality_score,
                "temporal_score": c.temporal_score,
                "bayesian_score": c.bayesian_score,
                "confidence": c.confidence,
            }
            for c in report.candidates
        ],
        # Day 19: Level-2 slice-layer attribution (None on INFO reports)
        "slice_attribution": report.slice_attribution,
        # Day 20: Claim 4 recalibration state at report time
        "recalibration_snapshot": report.recalibration_snapshot,
    }


# ── Recalibration (Day 20) ───────────────────────────────────

@app.get("/recalibration/stats", tags=["Recalibration"])
async def get_recalibration_stats():
    """
    Current state of the Claim 4 feedback recalibration engine.

    Patent Claim 4: feedback-driven DAG recalibration from remediation outcomes.
    Reports how many feedback cycles have run, how many DCGM edges were adjusted,
    and the current per-edge weight multipliers.

    The recalibrator ingests outcome signals from the RAE feedback buffer
    (GET /remediate/feedback) each analysis cycle and nudges causal edge
    weights toward or away from 1.0 (neutral) based on whether remediation
    of the attributed root cause succeeded or failed.
    """
    stats = state.recalibrator.get_stats()
    stats["feedback_buffer_depth"] = state._last_feedback_consumed
    return stats


@app.post("/recalibration/reset", tags=["Recalibration"])
async def reset_recalibration():
    """
    Reset all recalibration state (edge weights back to neutral 1.0).
    Useful for starting a clean sweep without restarting the API.
    """
    state.recalibrator.reset()
    state._last_feedback_consumed = 0
    return {"status": "reset", "message": "Recalibration state cleared"}


# ── RCA endpoint (Day 19) ────────────────────────────────────
# Returns the latest FaultReport including Level-2 slice attribution.
# This is the primary verification target for the live end-to-end sweep.

@app.get("/rca", tags=["Fault Reports"])
async def get_rca():
    """
    Latest root-cause analysis report including Level-2 slice attribution.
    Patent Claim 1: bi-level DAG output (NF layer + slice layer).

    After injecting a fault, poll this endpoint to confirm:
      - root_cause.nf_id  — Level-1 NF identification
      - slice_attribution.slice_breadth    — fraction of slices affected
      - slice_attribution.isolation_type   — slice-isolated | all-slice-nf | infrastructure-wide
      - slice_attribution.ensemble_score   — fused bi-level score
    """
    if not state.latest_report:
        return {
            "status": "collecting",
            "message": "No analysis complete yet — pipeline still warming up.",
            "buffer_fill_pct": round(state.buffer.fill_pct, 1),
            "cycle_count": state.cycle_count,
        }
    return {
        "status": "ok",
        "active_injections": state.injector.active_faults,
        "report": report_to_dict(state.latest_report),
    }


# ── Health & Status ───────────────────────────────────────────

@app.get("/health", tags=["Status"])
async def health():
    return {
        "status": "healthy",
        "pipeline_running": state.running,
        "cycle_count": state.cycle_count,
        "buffer_fill_pct": round(state.buffer.fill_pct, 1),
        "analysis_count": state.analysis_count,
        "active_faults": state.injector.active_faults,
        "uptime_since": state.start_time,
    }


@app.get("/nfs/status", tags=["Status"])
async def get_nf_status():
    nf_status = state.injector.get_nf_status()
    scores = {}
    for nf in ["nrf","amf","smf","pcf","udm","udr","ausf","nssf"]:
        latency = state.buffer.get_series(nf, "http_response_latency_ms")
        reach = state.buffer.get_series(nf, "nf_reachability")
        scores[nf] = {
            "container_status": nf_status.get(nf, "unknown"),
            "reachable": reach[-1] > 0 if reach else True,
            "latest_latency_ms": round(latency[-1], 2) if latency else None,
            "anomaly_score": round(
                state.dcgm.graph.nodes[nf].get("anomaly_score", 0.0), 4
            ) if nf in state.dcgm.graph.nodes else 0.0,
            "candidate_rank": next(
                (c.rank for c in state.candidates if c.nf_id == nf), None
            ),
        }
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "nfs": scores}


# ── Fault Reports ─────────────────────────────────────────────

@app.get("/faults/active", tags=["Fault Reports"])
async def get_active_faults():
    if not state.latest_report:
        return {
            "status": "collecting",
            "buffer_fill_pct": state.buffer.fill_pct,
            "cycle_count": state.cycle_count,
        }
    return {
        "status": "ok",
        "active_injections": state.injector.active_faults,
        "report": report_to_dict(state.latest_report),
    }


@app.get("/faults", tags=["Fault Reports"])
async def list_faults(limit: int = 10):
    reports = state.report_history[-limit:]
    return {
        "total": len(state.report_history),
        "reports": [report_to_dict(r) for r in reversed(reports)],
    }


# ── Fault Injection ───────────────────────────────────────────

@app.get("/faults/scenarios", tags=["Fault Injection"])
async def list_scenarios():
    """List all available fault injection scenarios."""
    return {
        "scenarios": {
            name: {
                "target_nf": s["nf"],
                "description": s["description"],
                "severity": s["severity"],
                "expected_impact": s["expected_impact"],
                "action": s["action"],
            }
            for name, s in FaultInjector.SCENARIOS.items()
        }
    }


@app.get("/faults/report/{report_id}", tags=["Fault Reports"])
async def get_fault_report(report_id: str):
    """Get a specific fault report by ID."""
    for r in state.report_history:
        if r.report_id == report_id:
            return report_to_dict(r)
    raise HTTPException(status_code=404, detail=f"Report {report_id} not found")


@app.get("/faults/inject/status", tags=["Fault Injection"])
async def injection_status():
    """Current fault injection state."""
    return {
        "active_faults": state.injector.active_faults,
        "fault_log": [
            {
                "timestamp": e.timestamp,
                "scenario": e.scenario,
                "target_nf": e.target_nf,
                "action": e.action,
            }
            for e in state.injector.fault_log[-20:]
        ],
        "nf_container_status": state.injector.get_nf_status(),
    }


@app.post("/faults/inject/{scenario}", tags=["Fault Injection"])
async def inject_fault(scenario: str):
    """
    Inject a fault scenario into the live 5G core.
    Patent Claim 6: POST /faults/inject/{scenario}

    Available scenarios: nrf_crash, amf_crash, smf_crash, pcf_timeout, udm_crash
    """
    if scenario not in FaultInjector.SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario}'. Available: {list(FaultInjector.SCENARIOS.keys())}"
        )
    if scenario in state.injector.active_faults:
        raise HTTPException(
            status_code=409,
            detail=f"Scenario '{scenario}' already active"
        )

    s = FaultInjector.SCENARIOS[scenario]
    event = state.injector.inject(scenario)

    await broadcast({
        "type": "fault_injected",
        "scenario": scenario,
        "target_nf": s["nf"],
        "severity": s["severity"],
        "expected_impact": s["expected_impact"],
        "timestamp": event.timestamp,
    })

    return {
        "status": "injected",
        "scenario": scenario,
        "target_nf": s["nf"],
        "severity": s["severity"],
        "description": s["description"],
        "expected_impact": s["expected_impact"],
        "timestamp": event.timestamp,
        "next_analysis_in": f"{(10 - state.cycle_count % 10) * 5}s",
        "watch": "GET /faults/active to see root cause shift",
    }


@app.post("/faults/recover/{scenario}", tags=["Fault Injection"])
async def recover_fault(scenario: str):
    """Recover from an active fault scenario."""
    if scenario not in FaultInjector.SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario}")

    event = state.injector.recover(scenario)

    await broadcast({
        "type": "fault_recovered",
        "scenario": scenario,
        "timestamp": event.timestamp,
    })

    return {
        "status": "recovering",
        "scenario": scenario,
        "timestamp": event.timestamp,
        "watch": "GET /faults/active to confirm system normalizes",
    }


# ── Causal Graph ──────────────────────────────────────────────

@app.get("/graph/current", tags=["Causal Graph"])
async def get_current_graph():
    graph = state.dcgm.graph
    import networkx as nx
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_faults": state.injector.active_faults,
        "nodes": [
            {
                "id": n,
                "nf_type": n.upper(),
                "anomaly_score": round(float(_to_py(graph.nodes[n].get("anomaly_score", 0.0)) or 0.0), 4),
                "color": state.dcgm.NF_COLORS.get(n, "#888"),
                "container_status": "running",
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "src": u, "dst": v,
                "weight": round(float(_to_py(d.get("weight", 0)) or 0.0), 4),
                "source": d.get("source", "unknown"),
                "p_value": _to_py(d.get("p_value")),
                "lag": _to_py(d.get("lag")),
            }
            for u, v, d in graph.edges(data=True)
        ],
        "stats": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "granger_edges": sum(
                1 for _, _, d in graph.edges(data=True)
                if d.get("source") == "granger"
            ),
        }
    }


# ── Remediation ───────────────────────────────────────────────

@app.post("/remediation/{nf_id}", tags=["Remediation"])
async def trigger_remediation(nf_id: str):
    valid = ["nrf","amf","smf","pcf","udm","udr","ausf","nssf"]
    if nf_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown NF: {nf_id}")

    import subprocess
    result = subprocess.run(
        f"docker restart causal5g-{nf_id}",
        shell=True, capture_output=True, text=True
    )

    logger.warning(f"REMEDIATION: restarted causal5g-{nf_id}")
    return {
        "status": "restarted",
        "nf_id": nf_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "docker_output": result.stdout.strip(),
    }


# ── WebSocket Live Feed ───────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    """WebSocket live feed of analysis results and fault events."""
    await websocket.accept()
    state.ws_clients.append(websocket)
    logger.info(f"WebSocket client connected ({len(state.ws_clients)} total)")
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "causal5g live feed",
            "cycle_count": state.cycle_count,
        })
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        state.ws_clients.remove(websocket)
        logger.info("WebSocket client disconnected")


# ── Prometheus Metrics ────────────────────────────────────────
# Day 15: standards-compliant Prometheus exposition via
# ``causal5g.observability.metrics``. The helper keeps a private
# CollectorRegistry so scrapes return a coherent snapshot; the
# fallback path (prometheus_client not installed) preserves the
# original hand-rolled plain-text lines used by the patent demo.

from fastapi import Response  # local import: already used below

@app.get("/metrics", tags=["Status"])
async def prometheus_metrics():
    # Refresh gauges at scrape time so a bare /metrics call (no active
    # pipeline loop) still reports the latest state.
    _metrics.set_pipeline_cycles(state.cycle_count)
    _metrics.set_analyses_total(state.total_analyses_run)
    _metrics.set_events_ingested(state.total_events_ingested)
    _metrics.set_buffer_fill_pct(state.buffer.fill_pct)
    _metrics.set_active_faults(len(state.injector.active_faults))

    if _metrics.is_available():
        body, content_type = _metrics.render()
        return Response(content=body, media_type=content_type)

    # Fallback: hand-rolled plain text (pre-Day-15 behaviour).
    lines = [
        f"causal5g_pipeline_cycles_total {state.cycle_count}",
        f"causal5g_analyses_total {state.total_analyses_run}",
        f"causal5g_events_ingested_total {state.total_events_ingested}",
        f"causal5g_buffer_fill_pct {state.buffer.fill_pct:.1f}",
        f"causal5g_active_faults {len(state.injector.active_faults)}",
    ]
    if state.latest_report:
        rc = state.latest_report.root_cause
        lines.append(f'causal5g_root_cause_score{{nf="{rc.nf_id}"}} {rc.composite_score}')
        for c in state.candidates:
            lines.append(f'causal5g_candidate_score{{nf="{c.nf_id}"}} {c.composite_score}')
    return PlainTextResponse("\n".join(lines) + "\n")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")

# ── Patched graph endpoint (fix async blocking) ───────────────────────────────
import asyncio
from fastapi import Response
import json as _json

@app.get("/graph/v2", tags=["Causal Graph"])
async def get_current_graph_v2():
    loop = asyncio.get_event_loop()
    graph = state.dcgm.graph
    nf_status = await loop.run_in_executor(None, state.injector.get_nf_status)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_faults": state.injector.active_faults,
        "nodes": [
            {
                "id": n,
                "nf_type": n.upper(),
                "anomaly_score": round(float(_to_py(graph.nodes[n].get("anomaly_score", 0.0)) or 0.0), 4),
                "color": state.dcgm.NF_COLORS.get(n, "#888"),
                "container_status": nf_status.get(n, "unknown"),
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "src": u, "dst": v,
                "weight": round(float(_to_py(d.get("weight", 0)) or 0.0), 4),
                "source": d.get("source", "unknown"),
                "p_value": _to_py(d.get("p_value")),
                "lag": _to_py(d.get("lag")),
            }
            for u, v, d in graph.edges(data=True)
        ],
        "stats": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "granger_edges": sum(1 for _, _, d in graph.edges(data=True) if d.get("source") == "granger"),
        }
    }
    return result
