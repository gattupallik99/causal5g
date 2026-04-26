#!/usr/bin/env python3
"""
Day 17 - Container-status-based root identification.

The Free5GC telemetry's nf_reachability field is cascade-conflated:
when one NF crashes, 5/8 NFs report reachable=false simultaneously.
This makes per-NF root-cause attribution impossible from that signal.

Direct Docker container state is clean ground truth - only the
actually-crashed NF reports state="exited". Verified empirically:
evidence/day16c/amf_crash/nfs_status_after.json shows amf="exited"
while nrf/smf/pcf/udm are all "running" but reachable=false.

This patch:
  1. Adds RootCauseScoringModule._docker_container_status() - a
     subprocess-based query of `docker inspect` for the eight
     causal5g-* containers. Returns {} on any failure (fail-open).
  2. Calls it once at the top of score().
  3. Replaces the Day 13 reachability-floor boost with a precedence-
     ordered boost: container exited -> 0.95; else if unreachable
     -> the original Day 13 floor (kept as fallback when Docker is
     unavailable, e.g. in unit tests).

Idempotent: always restores from rcsm.py.bak.day16 before applying.
ast.parse-validated.
"""
import ast
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = REPO_ROOT / "causal" / "engine" / "rcsm.py"
BACKUP = REPO_ROOT / "causal" / "engine" / "rcsm.py.bak.day16"


DOCKER_METHOD = '''
    # Day 17: Docker container-status helper - the primary root-cause
    # signal. nf_reachability is cascade-conflated in the live Free5GC
    # stack (5/8 NFs report unreachable when only one is actually
    # crashed); container_status from `docker inspect` is clean ground
    # truth - only the crashed NF shows state "exited".
    @staticmethod
    def _docker_container_status() -> dict[str, str]:
        """Return {nf_id: docker_state_status}. Empty dict on any error."""
        import subprocess
        names = [f"causal5g-{nf}" for nf in
                 ("nrf", "amf", "smf", "pcf", "udm", "udr", "ausf", "nssf")]
        try:
            out = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{.Name}} {{.State.Status}}", *names],
                capture_output=True, text=True, timeout=2.0,
            )
        except Exception:
            return {}
        result: dict[str, str] = {}
        for line in out.stdout.strip().splitlines():
            parts = line.strip().lstrip("/").split()
            if len(parts) == 2:
                name, status = parts
                if name.startswith("causal5g-"):
                    result[name.split("-", 1)[1]] = status
        return result
'''

ANCHOR_TRACKED_NFS = (
    '    _TRACKED_NFS = ("nrf", "amf", "smf", "pcf", "udm", "udr", "ausf", "nssf")'
)

OLD_BAYESIAN_CALL = '''        # Component 3: Bayesian posterior
        evidence = self.build_evidence(buffer)
        logger.info(f"Bayesian evidence: {evidence}")
        bayesian_scores = self.bayesian.get_posterior(evidence)'''

NEW_BAYESIAN_CALL = '''        # Day 17: query container_status once - used by the per-NF
        # boost in the loop below. Empty dict if Docker unavailable.
        container_status = self._docker_container_status()
        if container_status:
            logger.info(f"Container status: {container_status}")

        # Component 3: Bayesian posterior
        evidence = self.build_evidence(buffer)
        logger.info(f"Bayesian evidence: {evidence}")
        bayesian_scores = self.bayesian.get_posterior(evidence)'''

OLD_REACH_BOOST = '''            if self._is_unreachable(buffer, nf):
                boosted = self._REACHABILITY_FLOOR + 0.2 * c
                composite = max(composite, boosted)'''

NEW_REACH_BOOST = '''            # Day 17: container-status-based primary boost. Falls back
            # to the Day 13 reachability floor when Docker is
            # unavailable or no container is exited.
            if container_status.get(nf) == "exited":
                composite = max(composite, 0.95)
            elif self._is_unreachable(buffer, nf):
                boosted = self._REACHABILITY_FLOOR + 0.2 * c
                composite = max(composite, boosted)'''


def main() -> int:
    if not TARGET.exists():
        print(f"missing: {TARGET}", file=sys.stderr)
        return 1
    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"created backup: {BACKUP.relative_to(REPO_ROOT)}")
    shutil.copy2(BACKUP, TARGET)

    src = TARGET.read_text(encoding="utf-8")

    def _swap(text: str, old: str, new: str, label: str) -> str:
        if old not in text:
            raise SystemExit(f"anchor missing ({label}): {old[:80]!r}")
        return text.replace(old, new, 1)

    # 1. Insert _docker_container_status after _TRACKED_NFS line.
    src = _swap(src, ANCHOR_TRACKED_NFS, ANCHOR_TRACKED_NFS + DOCKER_METHOD,
                "TRACKED_NFS")
    # 2. Add container_status query just above the Bayesian step.
    src = _swap(src, OLD_BAYESIAN_CALL, NEW_BAYESIAN_CALL, "bayesian call")
    # 3. Replace the Day 13 reach-floor with the container-status boost.
    src = _swap(src, OLD_REACH_BOOST, NEW_REACH_BOOST, "reach boost")

    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"SYNTAX ERROR after patch: {e}", file=sys.stderr)
        return 2

    TARGET.write_text(src, encoding="utf-8")
    print(f"patched. Day-17 markers: {src.count('Day 17:')}")
    print("Next: bash scripts/day17_sweep.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
