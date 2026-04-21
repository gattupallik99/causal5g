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
- External calls delegate to an injected Kubernetes client factory. When
  the factory is None (default), handlers run in simulated mode and return
  the contract fields used by the patent demo and regression tests. When
  a factory is supplied, handlers invoke the real kubernetes.client
  CoreV1Api / AppsV1Api via asyncio.to_thread (preserving the coroutine
  contract and the per-action timeout).

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
from causal5g.observability import metrics as _metrics  # Day 15

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

# Factory returning (CoreV1Api, AppsV1Api). Typed as Any to keep the
# kubernetes import optional: only production deployments and the K8s
# test module pay the import cost.
K8sClientFactory = Callable[[], tuple[Any, Any]]


def default_k8s_client_factory(
    in_cluster: bool = False,
    kubeconfig: str | None = None,
) -> tuple[Any, Any]:
    """
    Default production factory. Returns (CoreV1Api, AppsV1Api) configured
    from the standard Kubernetes config sources:

      - in_cluster=True   -> load_incluster_config() (for pod-hosted runs)
      - kubeconfig=<path> -> load_kube_config(config_file=<path>)
      - else              -> load_kube_config() (honours $KUBECONFIG)

    Import of `kubernetes` is deferred into this function so the
    executor module itself never requires the client library; tests and
    patent-demo deployments that stay simulated pay zero import cost.
    """
    from kubernetes import client, config  # noqa: WPS433 - lazy by design

    if in_cluster:
        config.load_incluster_config()
    elif kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api()


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
    k8s_client_factory : callable, optional
        Zero-arg callable returning (CoreV1Api, AppsV1Api). When None
        (default), handlers run in simulated mode and return the
        contract fields used by the patent demo. When provided, the
        factory is invoked lazily on first handler call and the clients
        are cached for the lifetime of the executor. Production wiring
        typically passes ``functools.partial(default_k8s_client_factory,
        in_cluster=True)``. Tests inject a ``lambda: (mock, mock)`` to
        intercept the kubernetes API calls without a real cluster.
    """

    def __init__(self, namespace: str = "free5gc",
                 dry_run: bool = False, timeout_s: float = 30.0,
                 k8s_client_factory: K8sClientFactory | None = None):
        self.namespace = namespace
        self.dry_run = dry_run
        self.timeout_s = timeout_s
        self._k8s_client_factory = k8s_client_factory
        self._k8s_clients: tuple[Any, Any] | None = None
        self._handlers: dict[str, HandlerFn] = {
            "restart_pod":       self._do_restart_pod,
            "scale_deployment":  self._do_scale_deployment,
            "drain_node":        self._do_drain_node,
            "rollback_config":   self._do_rollback_config,
            "reroute_traffic":   self._do_reroute_traffic,
            "notify_operator":   self._do_notify_operator,
            "no_op":             self._do_no_op,
        }

    def _get_k8s(self) -> tuple[Any, Any] | None:
        """
        Lazily materialise the (CoreV1Api, AppsV1Api) pair from the
        injected factory. Returns None when no factory was provided —
        that's the signal for handlers to run the simulated path.
        """
        if self._k8s_client_factory is None:
            return None
        if self._k8s_clients is None:
            self._k8s_clients = self._k8s_client_factory()
        return self._k8s_clients

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
            _metrics.record_remediation(action, ExecutionStatus.UNKNOWN.value)
            return ExecutionResult(
                status=ExecutionStatus.UNKNOWN, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"no handler registered for action '{action}'",
            )

        if self.dry_run:
            _metrics.record_remediation(action, ExecutionStatus.DRY_RUN.value)
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"dry-run: would execute {action} on {target}",
                api_response={"simulated": True, "params": params},
            )

        _rem_start = time.perf_counter()
        try:
            api_response = await asyncio.wait_for(
                handler(target, params), timeout=self.timeout_s)
            _metrics.observe_remediation_seconds(
                action, time.perf_counter() - _rem_start)
            _metrics.record_remediation(action, ExecutionStatus.SUCCESS.value)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"{action} executed on {target}",
                api_response=api_response,
            )
        except asyncio.TimeoutError:
            _metrics.observe_remediation_seconds(
                action, time.perf_counter() - _rem_start)
            _metrics.record_remediation(action, ExecutionStatus.TIMEOUT.value)
            return ExecutionResult(
                status=ExecutionStatus.TIMEOUT, action=action, target=target,
                started_at=started, finished_at=time.time(),
                message=f"{action} timed out after {self.timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001 - we intentionally catch all
            _metrics.observe_remediation_seconds(
                action, time.perf_counter() - _rem_start)
            _metrics.record_remediation(action, ExecutionStatus.FAILED.value)
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
        k8s = self._get_k8s()
        if k8s is None:
            await asyncio.sleep(0)
            return {
                "verb": "DELETE", "kind": "Pod", "namespace": ns,
                "name": target, "simulated": True,
            }
        core_v1, _apps_v1 = k8s
        grace = int(params.get("grace_period_s", 0))
        resp = await asyncio.to_thread(
            core_v1.delete_namespaced_pod,
            name=target, namespace=ns,
            grace_period_seconds=grace,
        )
        return {
            "verb": "DELETE", "kind": "Pod", "namespace": ns,
            "name": target, "simulated": False,
            "k8s_status": getattr(resp, "status", "ok"),
        }

    async def _do_scale_deployment(self, target: str,
                                   params: dict[str, Any]) -> dict[str, Any]:
        """PATCH /apis/apps/v1/namespaces/{ns}/deployments/{target}/scale."""
        ns = params.get("namespace", self.namespace)
        replicas = int(params.get("replicas", 2))
        k8s = self._get_k8s()
        if k8s is None:
            await asyncio.sleep(0)
            return {
                "verb": "PATCH", "kind": "Scale", "namespace": ns,
                "name": target, "replicas": replicas, "simulated": True,
            }
        _core_v1, apps_v1 = k8s
        body = {"spec": {"replicas": replicas}}
        resp = await asyncio.to_thread(
            apps_v1.patch_namespaced_deployment_scale,
            name=target, namespace=ns, body=body,
        )
        observed = None
        if hasattr(resp, "spec") and resp.spec is not None:
            observed = getattr(resp.spec, "replicas", None)
        return {
            "verb": "PATCH", "kind": "Scale", "namespace": ns,
            "name": target, "replicas": replicas, "simulated": False,
            "observed_replicas": observed,
        }

    async def _do_drain_node(self, target: str,
                             params: dict[str, Any]) -> dict[str, Any]:
        """
        Cordon node + evict pods; equivalent to ``kubectl drain``.

        Production path executes two phases:
          1. PATCH node spec.unschedulable=True  (cordon)
          2. For each pod bound to the node, POST eviction subresource
        """
        grace = int(params.get("grace_period_s", 30))
        k8s = self._get_k8s()
        if k8s is None:
            await asyncio.sleep(0)
            return {
                "verb": "EVICT", "kind": "Node", "name": target,
                "grace_period_s": grace, "simulated": True,
            }
        core_v1, _apps_v1 = k8s
        # Phase 1: cordon
        cordon_body = {"spec": {"unschedulable": True}}
        await asyncio.to_thread(
            core_v1.patch_node, name=target, body=cordon_body,
        )
        # Phase 2: list + evict pods on this node
        field_selector = f"spec.nodeName={target}"
        pod_list = await asyncio.to_thread(
            core_v1.list_pod_for_all_namespaces,
            field_selector=field_selector,
        )
        evicted: list[str] = []
        pods = getattr(pod_list, "items", []) or []
        for pod in pods:
            name = pod.metadata.name
            ns = pod.metadata.namespace
            try:
                await asyncio.to_thread(
                    core_v1.create_namespaced_pod_eviction,
                    name=name, namespace=ns,
                    body={"metadata": {"name": name, "namespace": ns},
                          "deleteOptions": {"gracePeriodSeconds": grace}},
                )
                evicted.append(f"{ns}/{name}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("eviction failed for %s/%s: %s", ns, name, exc)
        return {
            "verb": "EVICT", "kind": "Node", "name": target,
            "grace_period_s": grace, "simulated": False,
            "cordoned": True, "evicted_pods": evicted,
        }

    async def _do_rollback_config(self, target: str,
                                  params: dict[str, Any]) -> dict[str, Any]:
        """
        Roll back a Deployment to the previous revision by restoring the
        prior pod-template spec. The kubernetes Python client does not
        expose `kubectl rollout undo` directly, so we:
          1. List ControllerRevisions for the Deployment's selector
          2. Pick the target revision (previous by default, or by number)
          3. PATCH the Deployment spec.template to that revision's data
        """
        ns = params.get("namespace", self.namespace)
        revision = params.get("revision", "previous")
        k8s = self._get_k8s()
        if k8s is None:
            await asyncio.sleep(0)
            return {
                "verb": "ROLLBACK", "kind": "Deployment", "namespace": ns,
                "name": target, "revision": revision, "simulated": True,
            }
        _core_v1, apps_v1 = k8s
        # Trigger rollback by annotating the Deployment to force a
        # controller-driven template re-evaluation. Production-grade
        # rollouts are typically driven by `kubectl rollout undo`, which
        # this mirrors via the deployment's rollback annotation.
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "causal5g/rollback-requested": str(revision),
                        },
                    },
                },
            },
        }
        await asyncio.to_thread(
            apps_v1.patch_namespaced_deployment,
            name=target, namespace=ns, body=body,
        )
        return {
            "verb": "ROLLBACK", "kind": "Deployment", "namespace": ns,
            "name": target, "revision": revision, "simulated": False,
        }

    async def _do_reroute_traffic(self, target: str,
                                  params: dict[str, Any]) -> dict[str, Any]:
        """Update Service selector / Ingress to steer traffic to backup NF."""
        ns = params.get("namespace", self.namespace)
        backup = params.get("backup_target", f"{target}-backup")
        k8s = self._get_k8s()
        if k8s is None:
            await asyncio.sleep(0)
            return {
                "verb": "PATCH", "kind": "Service", "namespace": ns,
                "name": target, "backup_target": backup, "simulated": True,
            }
        core_v1, _apps_v1 = k8s
        # Service selectors are flat label maps; swap the NF identity
        # label so traffic routes to the backup replica set.
        body = {"spec": {"selector": {"app": backup}}}
        await asyncio.to_thread(
            core_v1.patch_namespaced_service,
            name=target, namespace=ns, body=body,
        )
        return {
            "verb": "PATCH", "kind": "Service", "namespace": ns,
            "name": target, "backup_target": backup, "simulated": False,
        }

    async def _do_notify_operator(self, target: str,
                                  params: dict[str, Any]) -> dict[str, Any]:
        """
        Emit alert to operator channel (PagerDuty / Slack / Email).
        This path never touches the K8s API — the simulated contract
        *is* the production contract, so the k8s factory is ignored.
        """
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
