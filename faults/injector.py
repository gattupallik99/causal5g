"""
Fault Injection Framework
Patent Claim Reference:
  Used for PoC validation of Claims 1(f)(g)(h)
  Demonstrates root cause isolation under real fault conditions

Fault Scenarios:
  1. NRF crash       - registry goes down, all NFs lose discovery
  2. AMF overload    - simulated via container pause
  3. SMF crash       - session management failure
  4. PCF timeout     - policy control degradation
"""

import subprocess
import time
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from loguru import logger


@dataclass
class FaultEvent:
    timestamp: str
    scenario: str
    target_nf: str
    action: str        # inject | recover
    expected_impact: list[str]  # NFs expected to be affected


class FaultInjector:
    """
    Injects faults into Free5GC NF containers.
    Uses docker stop/start/pause/unpause to simulate failures.
    """

    SCENARIOS = {
        "nrf_crash": {
            "target": "causal5g-nrf",
            "nf": "nrf",
            "action": "stop",
            "description": "NRF registry crash - all NFs lose discovery",
            "expected_impact": ["amf", "smf", "pcf", "udm", "ausf", "nssf"],
            "severity": "CRITICAL",
        },
        "amf_crash": {
            "target": "causal5g-amf",
            "nf": "amf",
            "action": "stop",
            "description": "AMF crash - UE registration fails",
            "expected_impact": ["smf", "ausf"],
            "severity": "HIGH",
        },
        "smf_crash": {
            "target": "causal5g-smf",
            "nf": "smf",
            "action": "stop",
            "description": "SMF crash - PDU session establishment fails",
            "expected_impact": ["pcf", "udm"],
            "severity": "HIGH",
        },
        "pcf_timeout": {
            "target": "causal5g-pcf",
            "nf": "pcf",
            "action": "pause",
            "description": "PCF timeout - policy decisions delayed",
            "expected_impact": ["smf", "amf"],
            "severity": "MEDIUM",
        },
        "udm_crash": {
            "target": "causal5g-udm",
            "nf": "udm",
            "action": "stop",
            "description": "UDM crash - subscriber data unavailable",
            "expected_impact": ["ausf", "amf", "smf"],
            "severity": "HIGH",
        },
    }

    def __init__(self):
        self.fault_log: list[FaultEvent] = []
        self.active_faults: list[str] = []

    def _run(self, cmd: str) -> tuple[int, str]:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True
        )
        return result.returncode, result.stdout.strip()

    def inject(self, scenario: str) -> FaultEvent:
        """Inject a fault scenario."""
        if scenario not in self.SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")

        s = self.SCENARIOS[scenario]
        action = s["action"]
        target = s["target"]

        logger.warning(
            f"FAULT INJECT: {scenario} | "
            f"{action} {target} | "
            f"severity={s['severity']}"
        )

        if action == "stop":
            rc, out = self._run(f"docker stop {target}")
        elif action == "pause":
            rc, out = self._run(f"docker pause {target}")
        else:
            rc, out = self._run(f"docker {action} {target}")

        event = FaultEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenario=scenario,
            target_nf=s["nf"],
            action="inject",
            expected_impact=s["expected_impact"],
        )
        self.fault_log.append(event)
        self.active_faults.append(scenario)

        if rc == 0:
            logger.warning(f"FAULT ACTIVE: {s['description']}")
        else:
            logger.error(f"Fault injection failed: {out}")

        return event

    def recover(self, scenario: str) -> FaultEvent:
        """Recover from a fault scenario."""
        if scenario not in self.SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")

        s = self.SCENARIOS[scenario]
        action = s["action"]
        target = s["target"]

        logger.info(f"FAULT RECOVER: {scenario} | restarting {target}")

        if action == "stop":
            rc, out = self._run(f"docker start {target}")
        elif action == "pause":
            rc, out = self._run(f"docker unpause {target}")
        else:
            rc, out = self._run(f"docker start {target}")

        event = FaultEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenario=scenario,
            target_nf=s["nf"],
            action="recover",
            expected_impact=[],
        )
        self.fault_log.append(event)
        if scenario in self.active_faults:
            self.active_faults.remove(scenario)

        logger.info(f"RECOVERY INITIATED: {s['description']}")
        return event

    def get_nf_status(self) -> dict[str, str]:
        """Check running status of all NFs."""
        nfs = ["nrf", "amf", "smf", "pcf", "udm", "udr", "ausf", "nssf"]
        status = {}
        for nf in nfs:
            _, out = self._run(
                f"docker inspect causal5g-{nf} "
                f"--format '{{{{.State.Status}}}}' 2>/dev/null"
            )
            status[nf] = out.strip() or "unknown"
        return status


if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/Users/krishnakumargattupalli/causal5g')
    from telemetry.collector.nf_scraper import NFScraper
    from causal.engine.granger import TelemetryBuffer, GrangerCausalityEngine
    from causal.graph.dcgm import DynamicCausalGraphManager

    scraper = NFScraper(scrape_interval=5)
    buffer = TelemetryBuffer(window_size=60)
    granger = GrangerCausalityEngine(max_lag=3, significance=0.05)
    dcgm = DynamicCausalGraphManager()
    injector = FaultInjector()

    print("\n" + "="*65)
    print("FAULT INJECTION TEST: NRF CRASH")
    print("="*65)

    # Phase 1: collect baseline (15 cycles)
    print("\n[PHASE 1] Collecting baseline telemetry (75s)...")
    for i in range(15):
        events = scraper.scrape_all()
        buffer.add_events(events)
        nf_status = injector.get_nf_status()
        up = sum(1 for s in nf_status.values() if s == "running")
        print(f"  Baseline cycle {i+1}/15 | events={len(events)} | NFs up={up}/8")
        time.sleep(5)

    # Baseline Granger
    print("\n[BASELINE] Running Granger analysis...")
    baseline_result = granger.analyze(buffer)
    dcgm.update_from_granger(baseline_result)
    baseline_scores = dcgm.compute_anomaly_scores(buffer)
    print(f"  Baseline causal links: {baseline_result.significant_links}")
    print(f"  Baseline NRF score: {baseline_scores.get('nrf', 0):.4f}")

    # Phase 2: inject NRF crash
    print("\n[PHASE 2] INJECTING NRF CRASH...")
    injector.inject("nrf_crash")
    time.sleep(3)

    # Phase 3: collect fault telemetry (10 cycles)
    print("\n[PHASE 3] Collecting fault telemetry (50s)...")
    fault_events_count = []
    for i in range(10):
        events = scraper.scrape_all()
        buffer.add_events(events)
        nf_status = injector.get_nf_status()
        up = sum(1 for s in nf_status.values() if s == "running")
        critical = sum(
            1 for e in events if e.severity == "critical"
        )
        fault_events_count.append(critical)
        print(
            f"  Fault cycle {i+1}/10 | "
            f"events={len(events)} | "
            f"NFs up={up}/8 | "
            f"critical={critical}"
        )
        time.sleep(5)

    # Fault Granger analysis
    print("\n[FAULT ANALYSIS] Running Granger on fault window...")
    fault_result = granger.analyze(buffer)
    dcgm.update_from_granger(fault_result)
    fault_scores = dcgm.compute_anomaly_scores(buffer)

    # Phase 4: recover
    print("\n[PHASE 4] RECOVERING NRF...")
    injector.recover("nrf_crash")
    time.sleep(15)

    # Print comparison
    print("\n" + "="*65)
    print("FAULT ISOLATION REPORT")
    print("="*65)
    print(f"\nScenario: NRF_CRASH")
    print(f"Critical events during fault: {sum(fault_events_count)}")
    print(f"Causal links baseline: {baseline_result.significant_links}")
    print(f"Causal links during fault: {fault_result.significant_links}")

    print("\nROOT CAUSE RANKING (fault window):")
    ranked = dcgm.get_root_cause_ranking(fault_scores)
    for rank, (nf, score) in enumerate(ranked, 1):
        delta = score - baseline_scores.get(nf, 0)
        delta_str = f"+{delta:.4f}" if delta > 0 else f"{delta:.4f}"
        marker = " <-- ROOT CAUSE DETECTED" if rank == 1 else ""
        print(
            f"  #{rank} {nf:6} | "
            f"score={score:.4f} | "
            f"delta={delta_str}{marker}"
        )

    print("\nNF STATUS AFTER RECOVERY:")
    final_status = injector.get_nf_status()
    for nf, st in final_status.items():
        icon = "✓" if st == "running" else "✗"
        print(f"  {icon} {nf}: {st}")

    print("="*65)

    # Save fault report
    report = {
        "scenario": "nrf_crash",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline_links": baseline_result.significant_links,
        "fault_links": fault_result.significant_links,
        "critical_events": sum(fault_events_count),
        "root_cause_ranking": ranked,
        "fault_log": [
            {"ts": e.timestamp, "action": e.action, "nf": e.target_nf}
            for e in injector.fault_log
        ],
    }
    with open("/tmp/fault_report_nrf_crash.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Fault report saved to /tmp/fault_report_nrf_crash.json")
