"""
MTIE - Multi-Modal Telemetry Ingestion Engine
NF Scraper: Collects metrics from Free5GC NFs via HTTP

Patent Claim Reference:
  Claim 1(a) - continuously ingesting multi-modal telemetry streams
  Claim 1(b) - normalizing to unified timestamp domain
"""

import time
import requests
import json
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional
from loguru import logger


# ── Unified Telemetry Event Schema ──────────────────────────
# This is the core data structure referenced in patent claims
@dataclass
class TelemetryEvent:
    timestamp: str          # ISO8601 UTC
    nf_id: str              # e.g. amf-01, smf-01
    nf_type: str            # AMF | SMF | PCF | UDM | UDR | AUSF | NSSF | NRF
    event_type: str         # metric | log | trace | pfcp
    signal_name: str        # metric or event name
    value: float | str      # numeric or string value
    severity: str           # info | warn | error | critical
    source_url: str         # origin endpoint
    raw: Optional[dict] = None  # original payload for audit


# ── NF Registry ─────────────────────────────────────────────
NF_ENDPOINTS = {
    "nrf":  "http://localhost:9091",
    "amf":  "http://localhost:9092",
    "smf":  "http://localhost:9093",
    "pcf":  "http://localhost:9094",
    "udm":  "http://localhost:9095",
    "udr":  "http://localhost:9096",
    "ausf": "http://localhost:9097",
    "nssf": "http://localhost:9098",
}

# SBI ports for API queries
NF_SBI_ENDPOINTS = {
    "nrf":  "http://localhost:8000",
    "amf":  "http://localhost:8001",
    "smf":  "http://localhost:8002",
    "pcf":  "http://localhost:8003",
    "udm":  "http://localhost:8004",
    "udr":  "http://localhost:8005",
    "ausf": "http://localhost:8006",
    "nssf": "http://localhost:8007",
}

NF_TYPES = {
    "nrf": "NRF", "amf": "AMF", "smf": "SMF",
    "pcf": "PCF", "udm": "UDM", "udr": "UDR",
    "ausf": "AUSF", "nssf": "NSSF"
}


class NFScraper:
    """
    Scrapes telemetry from Free5GC NF HTTP endpoints.
    Implements MTIE subsystem of the patent invention.
    """

    def __init__(self, scrape_interval: int = 5):
        self.scrape_interval = scrape_interval
        self.session = requests.Session()
        self.session.timeout = 3
        self.events: list[TelemetryEvent] = []

    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def scrape_nf_health(self, nf_id: str, base_url: str) -> list[TelemetryEvent]:
        """
        Scrape NF health and status via SBI HTTP endpoint.
        Maps to patent claim: SBI HTTP/2 inter-NF call trace data
        """
        events = []
        nf_type = NF_TYPES.get(nf_id, nf_id.upper())

        try:
            resp = self.session.get(
                f"{base_url}/metrics",
                timeout=3
            )
            latency_ms = resp.elapsed.total_seconds() * 1000

            # HTTP response time as a metric
            events.append(TelemetryEvent(
                timestamp=self.now(),
                nf_id=nf_id,
                nf_type=nf_type,
                event_type="metric",
                signal_name="http_response_latency_ms",
                value=round(latency_ms, 2),
                severity="info",
                source_url=f"{base_url}/metrics",
            ))

            # HTTP status as a metric
            events.append(TelemetryEvent(
                timestamp=self.now(),
                nf_id=nf_id,
                nf_type=nf_type,
                event_type="metric",
                signal_name="http_status_code",
                value=float(resp.status_code),
                severity="info" if resp.status_code == 200 else "warn",
                source_url=f"{base_url}/metrics",
            ))

            # Parse Prometheus metrics if available
            if resp.status_code == 200 and resp.text:
                prom_events = self._parse_prometheus(
                    resp.text, nf_id, nf_type, base_url
                )
                events.extend(prom_events)

        except requests.exceptions.ConnectionError:
            events.append(TelemetryEvent(
                timestamp=self.now(),
                nf_id=nf_id,
                nf_type=nf_type,
                event_type="metric",
                signal_name="nf_reachability",
                value=0.0,
                severity="critical",
                source_url=base_url,
            ))
            logger.warning(f"{nf_id}: connection refused")

        except requests.exceptions.Timeout:
            events.append(TelemetryEvent(
                timestamp=self.now(),
                nf_id=nf_id,
                nf_type=nf_type,
                event_type="metric",
                signal_name="nf_reachability",
                value=0.0,
                severity="error",
                source_url=base_url,
            ))
            logger.warning(f"{nf_id}: timeout")

        return events

    def _parse_prometheus(
        self, text: str, nf_id: str,
        nf_type: str, source_url: str
    ) -> list[TelemetryEvent]:
        """
        Parse Prometheus text format metrics.
        Maps to patent claim: time-series performance metrics
        via Prometheus-compatible scrape endpoint
        """
        events = []
        for line in text.strip().split("\n"):
            if line.startswith("#") or not line.strip():
                continue
            try:
                parts = line.rsplit(" ", 1)
                if len(parts) == 2:
                    metric_name = parts[0].split("{")[0].strip()
                    value = float(parts[1].strip())
                    severity = "info"
                    if "error" in metric_name.lower():
                        severity = "warn"
                    if "fail" in metric_name.lower():
                        severity = "error"
                    events.append(TelemetryEvent(
                        timestamp=self.now(),
                        nf_id=nf_id,
                        nf_type=nf_type,
                        event_type="metric",
                        signal_name=metric_name,
                        value=value,
                        severity=severity,
                        source_url=source_url,
                    ))
            except (ValueError, IndexError):
                continue
        return events

    def scrape_nrf_registry(self) -> list[TelemetryEvent]:
        """
        Query NRF for registered NF instances.
        Generates nf_registration_count metric per NF type.
        """
        events = []
        try:
            resp = self.session.get(
                "http://localhost:8000/nnrf-nfm/v1/nf-instances",
                timeout=3
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data if isinstance(data, list) else \
                    data.get("_embedded", {}).get("nfInstances", [])
                events.append(TelemetryEvent(
                    timestamp=self.now(),
                    nf_id="nrf",
                    nf_type="NRF",
                    event_type="metric",
                    signal_name="registered_nf_count",
                    value=float(len(items)),
                    severity="info",
                    source_url="http://localhost:8000/nnrf-nfm/v1/nf-instances",
                ))
                logger.info(f"NRF: {len(items)} NFs registered")
        except Exception as e:
            logger.warning(f"NRF registry query failed: {e}")
        return events

    def scrape_all(self) -> list[TelemetryEvent]:
        """Single scrape cycle across all NFs."""
        all_events = []
        for nf_id, url in NF_ENDPOINTS.items():
            events = self.scrape_nf_health(nf_id, url)
            all_events.extend(events)
            logger.debug(f"{nf_id}: {len(events)} events collected")
        all_events.extend(self.scrape_nrf_registry())
        return all_events

    def run(self, max_cycles: int = None):
        """
        Continuous scraping loop.
        Implements: 'continuously ingesting multi-modal telemetry streams'
        """
        logger.info(f"MTIE NFScraper started | interval={self.scrape_interval}s")
        cycle = 0
        while True:
            cycle += 1
            events = self.scrape_all()
            self.events.extend(events)
            logger.info(
                f"Cycle {cycle} | {len(events)} events | "
                f"total={len(self.events)}"
            )
            # Print sample event as JSON
            if events:
                print(json.dumps(asdict(events[0]), indent=2))
            if max_cycles and cycle >= max_cycles:
                break
            time.sleep(self.scrape_interval)
        return self.events


if __name__ == "__main__":
    scraper = NFScraper(scrape_interval=5)
    scraper.run(max_cycles=3)
