"""
FRG - Fault Report Generator
FastAPI REST API serving causal fault isolation reports.

Patent Claim Reference:
  Claim 6 - REST API interface + O-RAN Non-RT RIC / SMO integration
  Claim 1(h) - generating fault report identifying root cause NF

Endpoints:
  GET  /faults/active          - current active fault reports
  GET  /faults/{report_id}     - specific fault report
  GET  /graph/current          - current causal graph state
  GET  /graph/history          - historical graph snapshots
  GET  /nfs/status             - all NF health scores
  POST /remediation/{nf_id}    - trigger remediation action
  GET  /metrics                - Prometheus metrics (for causal5g-api target)
  GET  /health                 - health check
"""

import asyncio
import time
import threading
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
import uvicorn
from loguru import logger

import sys
sys.path.insert(0, '/Users/krishnakumargattupalli/causal5g')

from telemetry.collector.nf_scraper import NFScraper
from causal.engine.granger import TelemetryBuffer, GrangerCausalityEngine
from causal.graph.dcgm import DynamicCausalGraphManager
from causal.engine.rcsm import RootCauseScoringModule, FaultReport


# ── Global pipeline state ─────────────────────────────────────
class PipelineState:
    def __init__(self):
        self.scraper = NFScraper(scrape_interval=5)
        self.buffer = TelemetryBuffer(window_size=60)
        self.granger = GrangerCausalityEngine(max_lag=3, significance=0.05)
        self.dcgm = DynamicCausalGraphManager()
        self.rcsm = RootCauseScoringModule()

        self.latest_report: Optional[FaultReport] = None
        self.report_history: list[FaultReport] = []
        self.candidates = []
        self.cycle_count = 0
        self.analysis_count = 0
        self.last_analysis_ts: Optional[str] = None
        self.running = False
        self.start_time = datetime.now(timezone.utc).isoformat()

        # Prometheus counters
        self.total_events_ingested = 0
        self.total_analyses_run = 0
        self.total_reports_generated = 0


state = PipelineState()


def pipeline_loop():
    """
    Continuous pipeline: MTIE -> CIE -> DCGM -> RCSM
    Runs in background thread.
    Patent Claim 1: end-to-end causal fault isolation pipeline.
    """
    logger.info("Pipeline started")
    state.running = True

    while state.running:
        try:
            # Step 1: MTIE - ingest telemetry
            events = state.scraper.scrape_all()
            state.buffer.add_events(events)
            state.cycle_count += 1
            state.total_events_ingested += len(events)

            # Step 2: CIE + DCGM + RCSM - every 10 cycles once buffer ready
            if state.buffer.ready and state.cycle_count % 10 == 0:
                logger.info(f"Running analysis cycle {state.analysis_count+1}")

                # Granger causality
                result = state.granger.analyze(state.buffer)
                state.dcgm.update_from_granger(result)

                # RCSM scoring
                candidates = state.rcsm.score(result, state.dcgm, state.buffer)
                report = state.rcsm.generate_report(
                    candidates, state.buffer, result
                )

                state.candidates = candidates
                state.latest_report = report
                state.report_history.append(report)
                if len(state.report_history) > 20:
                    state.report_history.pop(0)

                state.analysis_count += 1
                state.total_analyses_run += 1
                state.total_reports_generated += 1
                state.last_analysis_ts = datetime.now(timezone.utc).isoformat()

                logger.info(
                    f"Analysis {state.analysis_count} | "
                    f"root_cause={report.root_cause.nf_id} | "
                    f"score={report.root_cause.composite_score:.4f} | "
                    f"severity={report.severity}"
                )

            time.sleep(5)

        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            time.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start pipeline in background thread
    thread = threading.Thread(target=pipeline_loop, daemon=True)
    thread.start()
    logger.info("FRG API started - pipeline running")
    yield
    state.running = False
    logger.info("FRG API shutting down")


# ── FastAPI app ───────────────────────────────────────────────
app = FastAPI(
    title="causal5g FRG — Fault Report Generator",
    description="Patent Claim 6: REST API for 5G causal fault isolation",
    version="1.0.0",
    lifespan=lifespan,
)


def report_to_dict(report: FaultReport) -> dict:
    """Serialize FaultReport to JSON-safe dict."""
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
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "pipeline_running": state.running,
        "cycle_count": state.cycle_count,
        "buffer_fill_pct": round(state.buffer.fill_pct, 1),
        "analysis_count": state.analysis_count,
        "uptime_since": state.start_time,
    }


@app.get("/faults/active")
async def get_active_faults():
    """
    Get current active fault report.
    Patent Claim 6: GET /faults/active
    """
    if not state.latest_report:
        return {
            "status": "no_analysis_yet",
            "buffer_fill_pct": state.buffer.fill_pct,
            "message": f"Collecting telemetry... {state.cycle_count} cycles so far"
        }
    return {
        "status": "ok",
        "report": report_to_dict(state.latest_report),
    }


@app.get("/faults/{report_id}")
async def get_fault_report(report_id: str):
    """Get a specific fault report by ID."""
    for r in state.report_history:
        if r.report_id == report_id:
            return report_to_dict(r)
    raise HTTPException(status_code=404, detail=f"Report {report_id} not found")


@app.get("/faults")
async def list_faults(limit: int = 10):
    """List recent fault reports."""
    reports = state.report_history[-limit:]
    return {
        "total": len(state.report_history),
        "returned": len(reports),
        "reports": [report_to_dict(r) for r in reversed(reports)],
    }


@app.get("/graph/current")
async def get_current_graph():
    """
    Get current causal graph state.
    Patent Claim 6: GET /graph/current
    """
    graph = state.dcgm.graph
    import networkx as nx
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nodes": [
            {
                "id": n,
                "nf_type": n.upper(),
                "anomaly_score": graph.nodes[n].get("anomaly_score", 0.0),
                "color": state.dcgm.NF_COLORS.get(n, "#888"),
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "src": u, "dst": v,
                "weight": round(d.get("weight", 0), 4),
                "source": d.get("source", "unknown"),
                "p_value": d.get("p_value"),
                "lag": d.get("lag"),
            }
            for u, v, d in graph.edges(data=True)
        ],
        "stats": {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "granger_edges": sum(
                1 for _, _, d in graph.edges(data=True)
                if d.get("source") == "granger"
            ),
        }
    }


@app.get("/nfs/status")
async def get_nf_status():
    """Get health scores for all NFs."""
    scores = {}
    for nf in ["nrf","amf","smf","pcf","udm","udr","ausf","nssf"]:
        latency = state.buffer.get_series(nf, "http_response_latency_ms")
        reach = state.buffer.get_series(nf, "nf_reachability")
        scores[nf] = {
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


@app.post("/remediation/{nf_id}")
async def trigger_remediation(nf_id: str, background_tasks: BackgroundTasks):
    """
    Trigger remediation for an NF.
    Patent Claim 6: POST /remediation/{nf_id}
    """
    valid_nfs = ["nrf","amf","smf","pcf","udm","udr","ausf","nssf"]
    if nf_id not in valid_nfs:
        raise HTTPException(status_code=400, detail=f"Unknown NF: {nf_id}")

    action = f"docker restart causal5g-{nf_id}"
    logger.warning(f"REMEDIATION triggered for {nf_id}: {action}")

    return {
        "status": "remediation_initiated",
        "nf_id": nf_id,
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "recommended_action": RootCauseScoringModule.__dict__.get(
            nf_id, f"Restart {nf_id.upper()} container"
        ),
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """
    Prometheus metrics endpoint for causal5g-api scrape target.
    """
    lines = [
        "# HELP causal5g_pipeline_cycles_total Total scrape cycles",
        "# TYPE causal5g_pipeline_cycles_total counter",
        f"causal5g_pipeline_cycles_total {state.cycle_count}",
        "# HELP causal5g_analyses_total Total Granger analyses run",
        "# TYPE causal5g_analyses_total counter",
        f"causal5g_analyses_total {state.total_analyses_run}",
        "# HELP causal5g_events_ingested_total Total telemetry events ingested",
        "# TYPE causal5g_events_ingested_total counter",
        f"causal5g_events_ingested_total {state.total_events_ingested}",
        "# HELP causal5g_buffer_fill_pct Telemetry buffer fill percentage",
        "# TYPE causal5g_buffer_fill_pct gauge",
        f"causal5g_buffer_fill_pct {state.buffer.fill_pct:.1f}",
    ]
    if state.latest_report:
        rc = state.latest_report.root_cause
        lines += [
            "# HELP causal5g_root_cause_score Current root cause composite score",
            "# TYPE causal5g_root_cause_score gauge",
            f'causal5g_root_cause_score{{nf="{rc.nf_id}"}} {rc.composite_score}',
        ]
        for c in state.candidates:
            lines.append(
                f'causal5g_candidate_score{{nf="{c.nf_id}"}} {c.composite_score}'
            )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
