# causal5g

**Causal Graph-Based Real-Time Fault Isolation in Virtualized 5G Core Networks**

> Patent Pending — Provisional Application Filed March 2026

## Overview

This repository implements the proof-of-concept for a patented method of automated
fault isolation in virtualized 5G core networks using dynamic causal graph construction
from multi-modal telemetry streams.

## Architecture
```
Multi-Modal Telemetry (PFCP/N4, SBI HTTP2, Prometheus, Logs)
        |
        v
+------------------+
|      MTIE        |  Multi-Modal Telemetry Ingestion Engine
+--------+---------+
         |
+--------v---------+
|      CIE         |  Causal Inference Engine (Granger + PC Algorithm)
+--------+---------+
         |
+--------v---------+
|      DCGM        |  Dynamic Causal Graph Manager (NetworkX)
+--------+---------+
         |
+--------v---------+
|      RCSM        |  Root Cause Scoring Module (Bayesian + Graph-theoretic)
+--------+---------+
         |
+--------v---------+
|      FRG         |  Fault Report Generator (REST API)
+------------------+
```

## Quickstart
```bash
git clone git@github.com:gattupallik/causal5g.git
cd causal5g
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d
uvicorn api.main:app --reload
```

## Project Structure

| Directory | Description |
|-----------|-------------|
| infra/    | Docker configs for Free5GC, Prometheus, Grafana, Loki, Jaeger |
| telemetry/| MTIE - telemetry ingestion and normalization |
| causal/   | CIE, DCGM, RCSM - core invention |
| api/      | FRG - northbound REST API |
| faults/   | Fault injection framework and scenarios |
| notebooks/| Jupyter experiment notebooks |
| docs/     | Patent documents and architecture diagrams |
| tests/    | Unit and integration tests |

## Patent

- **Title**: Causal Graph-Based Real-Time Fault Isolation in Virtualized 5G Core Networks
- **Status**: Patent Pending (Provisional Filed March 2026)
- **Inventor**: Krishna Kumar Gattupalli

## License

Proprietary. All rights reserved. Patent Pending.
