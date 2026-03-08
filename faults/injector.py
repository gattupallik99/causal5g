import subprocess
import time
from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class FaultEvent:
    timestamp: str
    scenario: str
    target_nf: str
    action: str
    expected_impact: list


class FaultInjector:
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

    def _run(self, cmd: str) -> tuple:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.returncode, result.stdout.strip()

    def inject(self, scenario: str) -> FaultEvent:
        s = self.SCENARIOS[scenario]
        action = s["action"]
        target = s["target"]
        if action == "stop":
            self._run(f"docker stop {target}")
        elif action == "pause":
            self._run(f"docker pause {target}")
        event = FaultEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            scenario=scenario,
            target_nf=s["nf"],
            action="inject",
            expected_impact=s["expected_impact"],
        )
        self.fault_log.append(event)
        self.active_faults.append(scenario)
        return event

    def recover(self, scenario: str) -> FaultEvent:
        s = self.SCENARIOS[scenario]
        target = s["target"]
        action = s["action"]
        if action == "stop":
            self._run(f"docker start {target}")
        elif action == "pause":
            self._run(f"docker unpause {target}")
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
        return event

    def get_nf_status(self) -> dict:
        nfs = ["nrf", "amf", "smf", "pcf", "udm", "udr", "ausf", "nssf"]
        status = {}
        for nf in nfs:
            _, out = self._run(
                f"docker inspect causal5g-{nf} --format '{{{{.State.Status}}}}' 2>/dev/null"
            )
            status[nf] = out.strip() or "unknown"
        return status
