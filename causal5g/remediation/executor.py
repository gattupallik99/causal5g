"""
causal5g.remediation.executor
==============================
Claim 3 — Remediation action executor.

Issues control-plane API calls to execute remediation actions selected by the
Remediation Action Engine (RAE). This module consolidates the action handlers
previously scattered across api/rae.py into a single reusable executor that
can be wired into any Causal5G deployment context (test, staging, production).

Design contract
---------------
- Accepts a PolicyEntry (plain-string action field) from PolicyStore
- Dispatches to the correct async handler based on action string
- Returns a uniform ExecutionResult regardless of success or failure
- Supports dry_run mode for patent demonstrations and staging validation
- All external calls are stubbed today; production K8s client integration is
  deferred until the lab cluster is live. The handler signatures are locked.

Supported actions (aligned with api.rae.ActionType):
    restart_pod        - Delete pod; let Deployment recreate it
    scale_deployment   - kubectl scale deployment --replicas=N
    drain_node         - Cordon + drain a K8s node
    rollback_config    - Roll back a Deployment to previous revision
    reroute_traffic    - Update Service/Ingress to steer traffic to backup
    notify_operator    - Emit alert to operator; no remediation
    no_op              - Intentional no-op (logged for audit trail)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from causal5g.remediation.policy_store import PolicyEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    SUCCESS   = "success"
    FAILED    = "failed"
    DRY_RUN   = "dry_run"
    UNKNOWN   = "unknown_action"
    TIMEOUT   = "timeout"


@dataclass
class ExecutionResult:
    """Outcome of a single remediation action execution."""
    status:         ExecutionStatus
    action:         str
    target:         str
    started_at:     float
    finished_at:    float
    message:        str = ""
    api_response:   dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status in (ExecutionStatus.SUCCESS, ExecutionStatus.DRY_RUN)

    @property
    def duration_ms(self) -> float:
        return round((self.finished_at - self.started_at) * 1000.0, 3)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

HandlerFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class RemediationExecutor:
    """
    Executes remediation actions against a cloud-native 5G core.

    In the current patent-enablement build all K8s API calls are simulated;
    the handler contracts are finalised so production wiring is a drop-in
    replacement (swap the body of each _do_* coroutine).

    Parameters
    ----------
    namespace : str
        Default K8s namespace for actions that do not specify one.
    dry_run : bool
        If True, log intended actions without touching any API. Used for
        patent demos, what-if analysis, and the /policy/simulate endpoint.
    timeout_s : float
        Per-action timeout in seconds (default 30.0).
    """

    def __init__(self, namespace: str = "free5gc",
                 dry_run: bool = False, timeout_s: float = 30.0):
        self.namespace = namespace
        self.dry_run = dry_run
        self.timeout_s = timeout_s
        self._handlers: dict[str, HandlerFn] = {
            "restart_pod":       self._do_restart_pod,
            "scale_deployment":  self._do_scale_deployment,
            "drain_node":        self._do_drain_node,
            "rollback_config":   self._do_rollback_config,
            "reroute_traffic":   self._do_reroute_traffic,
            "notify_operator":   self._do_notify_operator,
            "no_op":             self._do_no_op,
        }

    # ── public API ──────────────────────────────────────────────────────

    async def execute(self, policy: PolicyEntry,
                      context: dict[str, Any] | None = None) -> ExecutionResult:
        """
        Execute the action in `policy` against `policy.target`.

        Parameters
        ----------
        policy : PolicyEntry
            A policy row from PolicyStore (action + target + params).
        context : dict, optional
            Per-invocation overrides (e.g. slice_id, alternate_target).
            Merged into policy.params; context wins on key conflicts.
        """
        context = context or {}
        action = policy.action
        target = policy.target
        params = {**(policy.params or {}), **context}
        started = time.time()

        logger.info("exec action=%s target=%s dry_run=%s",
                    action, target, self.dry_run)

        handler = self._handlers.get(action)
        if handler is None:
            return ExecutionResult(
                status=ExecutionStatus.UNKNOWN, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"no handler registered for action '{action}'",
            )

        if self.dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"dry-run: would execute {action} on {target}",
                api_response={"simulated": True, "params": params},
            )

        try:
            api_response = await asyncio.wait_for(
                handler(target, params), timeout=self.timeout_s)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"{action} executed on {target}",
                api_response=api_response,
            )
        except asyncio.TimeoutError:
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"{action} timed out after {self.timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001 - we intentionally catch all
            logger.exception("action %s failed: %s", action, exc)
            return ExecutionResult(
                status=ExecutionStatus.FAILED, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"{action} failed: {exc}",
            )

    def supports(self, action: str) -> bool:
        """Return True if `action` has a registered handler."""
        return action in self._handlers

    def register(self, action: str, handler: HandlerFn) -> None:
        """
        Register (or override) a handler for `action`.
        Used in tests to inject fakes and in production to plug in a real
        K8s client once the lab cluster is online.
        """
        self._handlers[action] = handler

    # ── default handlers (simulated) ────────────────────────────────────

    async def _do_restart_pod(self, target: str,
                              params: dict[str, Any]) -> dict[str, Any]:
        """DELETE /api/v1/namespaces/{ns}/pods/{target} — Deployment recreates."""
        ns = params.get("namespace", self.namespace)
        await asyncio.sleep(0)  # cooperative yield; prod client will block here
        return {
            "verb": "DELETE", "kind": "Pod", "namespace": ns,
            "name": target, "simulated": True,
        }

    async def _do_scale_deployment(self, target: str,
                                   params: dict[str, Any]) -> dict[str, Any]:
        """PATCH /apis/apps/v1/namespaces/{ns}/deployments/{target}/scale."""
        ns = params.get("namespace", self.namespace)
        replicas = int(params.get("replicas", 2))
        await asyncio.sleep(0)
        return {
            "verb": "PATCH", "kind": "Scale", "namespace": ns,
            "name": target, "replicas": replicas, "simulated": True,
        }

    async def _do_drain_node(self, target: str,
                             params: dict[str, Any]) -> dict[str, Any]:
        """Cordon node + evict pods; equivalent to `kubectl drain`."""
        grace = int(params.get("grace_period_s", 30))
        await asyncio.sleep(0)
        return {
            "verb": "EVICT", "kind": "Node", "name": target,
            "grace_period_s": grace, "simulated": True,
        }

    async def _do_rollback_config(self, target: str,
                                  params: dict[str, Any]) -> dict[str, Any]:
        """Roll back Deployment to previous revision."""
        ns = params.get("namespace", self.namespace)
        revision = params.get("revision", "previous")
        await asyncio.sleep(0)
        return {
            "verb": "ROLLBACK", "kind": "Deployment", "namespace": ns,
            "name": target, "revision": revision, "simulated": True,
        }

    async def _do_reroute_traffic(self, target: str,
                                  params: dict[str, Any]) -> dict[str, Any]:
        """Update Service selector / Ingress to steer traffic to backup NF."""
        ns = params.get("namespace", self.namespace)
        backup = params.get("backup_target", f"{target}-backup")
        await asyncio.sleep(0)
        return {
            "verb": "PATCH", "kind": "Service", "namespace": ns,
            "name": target, "backup_target": backup, "simulated": True,
        }

    async def _do_notify_operator(self, target: str,
                                  params: dict[str, Any]) -> dict[str, Any]:
        """Emit alert to operator channel (PagerDuty / Slack / Email)."""
        channel = params.get("channel", "pagerduty")
        severity = params.get("severity", "medium")
        return {
            "verb": "NOTIFY", "channel": channel, "target": target,
            "severity": severity, "simulated": True,
        }

    async def _do_no_op(self, target: str,
                        params: dict[str, Any]) -> dict[str, Any]:
        """Audit-only no-op, used when confidence below threshold."""
        return {"verb": "NOOP", "target": target, "reason": params.get("reason", "")}
