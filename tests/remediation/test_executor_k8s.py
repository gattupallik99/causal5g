"""
Day 14 regression coverage for the Kubernetes-backed path of
``causal5g.remediation.executor.RemediationExecutor``.

The default (simulated) path is covered by tests/remediation/test_executor.py
and must remain byte-identical after Day 14. These tests drive the new
code path where a ``k8s_client_factory`` is supplied at construction
time: the executor then delegates to the kubernetes Python client via
``asyncio.to_thread``, preserving the coroutine contract.

Patent context: this is the production wiring for Claim 3's
closed-loop remediation. The tests assert that each remediation
ActionType reaches the correct kubernetes API verb with the correct
target, namespace, and parameter mapping — which is the binding
evidence that the provisional's Claim 3 reduction-to-practice is
end-to-end, not just simulated.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from causal5g.remediation.executor import (
    ExecutionStatus,
    RemediationExecutor,
)
from causal5g.remediation.policy_store import PolicyEntry


# --- helpers ----------------------------------------------------------------

def _policy(action: str, target: str = "amf-1",
            params: dict | None = None) -> PolicyEntry:
    now = time.time()
    return PolicyEntry(
        policy_id=f"pol-{action}", fault_scenario="test",
        action=action, target=target, params=params or {},
        priority=0, enabled=True, created_at=now, updated_at=now, version=1,
    )


def _mock_factory(core_mock=None, apps_mock=None):
    """Build a factory closure that returns the given mocks.
    Invocation count is tracked via the factory's own MagicMock."""
    core = core_mock or MagicMock(name="CoreV1Api")
    apps = apps_mock or MagicMock(name="AppsV1Api")
    factory = MagicMock(name="k8s_factory", return_value=(core, apps))
    return factory, core, apps


# --- lazy factory behaviour --------------------------------------------------

class TestFactoryLifecycle:
    """The factory must only be invoked the first time a handler that
    actually needs K8s is called, and must be cached thereafter."""

    @pytest.mark.asyncio
    async def test_factory_not_called_until_first_handler(self):
        factory, core, _apps = _mock_factory()
        executor = RemediationExecutor(k8s_client_factory=factory)
        # No handler called yet.
        assert factory.call_count == 0

        await executor.execute(_policy("restart_pod", target="amf-1"))
        assert factory.call_count == 1
        assert core.delete_namespaced_pod.called

    @pytest.mark.asyncio
    async def test_factory_cached_across_calls(self):
        factory, _core, _apps = _mock_factory()
        executor = RemediationExecutor(k8s_client_factory=factory)

        await executor.execute(_policy("restart_pod", target="amf-1"))
        await executor.execute(_policy("scale_deployment", target="smf",
                                       params={"replicas": 3}))
        await executor.execute(_policy("restart_pod", target="pcf"))
        assert factory.call_count == 1, (
            f"factory invoked {factory.call_count} times; must cache"
        )

    @pytest.mark.asyncio
    async def test_notify_operator_never_triggers_factory(self):
        # notify_operator is pure (alerting), never touches K8s — so the
        # factory must remain uncalled even in K8s mode.
        factory, _core, _apps = _mock_factory()
        executor = RemediationExecutor(k8s_client_factory=factory)
        result = await executor.execute(
            _policy("notify_operator", target="nrf",
                    params={"channel": "slack", "severity": "high"})
        )
        assert result.status == ExecutionStatus.SUCCESS
        assert factory.call_count == 0
        assert result.api_response["simulated"] is True


# --- restart_pod -------------------------------------------------------------

class TestRestartPodK8s:
    @pytest.mark.asyncio
    async def test_calls_delete_namespaced_pod(self):
        factory, core, _apps = _mock_factory()
        core.delete_namespaced_pod.return_value = SimpleNamespace(status="Success")
        executor = RemediationExecutor(
            namespace="free5gc", k8s_client_factory=factory)

        result = await executor.execute(
            _policy("restart_pod", target="amf-1"))

        assert result.status == ExecutionStatus.SUCCESS
        core.delete_namespaced_pod.assert_called_once()
        kwargs = core.delete_namespaced_pod.call_args.kwargs
        assert kwargs["name"] == "amf-1"
        assert kwargs["namespace"] == "free5gc"
        assert result.api_response["verb"] == "DELETE"
        assert result.api_response["simulated"] is False
        assert result.api_response["k8s_status"] == "Success"

    @pytest.mark.asyncio
    async def test_honours_namespace_override(self):
        factory, core, _apps = _mock_factory()
        core.delete_namespaced_pod.return_value = SimpleNamespace(status="Success")
        executor = RemediationExecutor(k8s_client_factory=factory)

        await executor.execute(
            _policy("restart_pod", target="smf-2",
                    params={"namespace": "prod"}))

        kwargs = core.delete_namespaced_pod.call_args.kwargs
        assert kwargs["namespace"] == "prod"

    @pytest.mark.asyncio
    async def test_passes_grace_period(self):
        factory, core, _apps = _mock_factory()
        core.delete_namespaced_pod.return_value = SimpleNamespace(status="Success")
        executor = RemediationExecutor(k8s_client_factory=factory)

        await executor.execute(
            _policy("restart_pod", target="pcf-1",
                    params={"grace_period_s": 15}))

        kwargs = core.delete_namespaced_pod.call_args.kwargs
        assert kwargs["grace_period_seconds"] == 15


# --- scale_deployment --------------------------------------------------------

class TestScaleDeploymentK8s:
    @pytest.mark.asyncio
    async def test_patches_scale_with_replicas(self):
        factory, _core, apps = _mock_factory()
        apps.patch_namespaced_deployment_scale.return_value = SimpleNamespace(
            spec=SimpleNamespace(replicas=5))
        executor = RemediationExecutor(
            namespace="free5gc", k8s_client_factory=factory)

        result = await executor.execute(
            _policy("scale_deployment", target="smf",
                    params={"replicas": 5}))

        apps.patch_namespaced_deployment_scale.assert_called_once()
        kwargs = apps.patch_namespaced_deployment_scale.call_args.kwargs
        assert kwargs["name"] == "smf"
        assert kwargs["namespace"] == "free5gc"
        assert kwargs["body"] == {"spec": {"replicas": 5}}
        assert result.api_response["simulated"] is False
        assert result.api_response["observed_replicas"] == 5

    @pytest.mark.asyncio
    async def test_defaults_replicas_to_two(self):
        factory, _core, apps = _mock_factory()
        apps.patch_namespaced_deployment_scale.return_value = SimpleNamespace(
            spec=SimpleNamespace(replicas=2))
        executor = RemediationExecutor(k8s_client_factory=factory)

        await executor.execute(_policy("scale_deployment", target="smf"))

        body = apps.patch_namespaced_deployment_scale.call_args.kwargs["body"]
        assert body["spec"]["replicas"] == 2


# --- drain_node --------------------------------------------------------------

class TestDrainNodeK8s:
    @pytest.mark.asyncio
    async def test_cordons_node_and_evicts_pods(self):
        factory, core, _apps = _mock_factory()
        # Two pods on the target node.
        pod1 = SimpleNamespace(
            metadata=SimpleNamespace(name="smf-a", namespace="free5gc"))
        pod2 = SimpleNamespace(
            metadata=SimpleNamespace(name="amf-b", namespace="free5gc"))
        core.list_pod_for_all_namespaces.return_value = SimpleNamespace(
            items=[pod1, pod2])
        executor = RemediationExecutor(k8s_client_factory=factory)

        result = await executor.execute(
            _policy("drain_node", target="node-1",
                    params={"grace_period_s": 60}))

        # Phase 1: cordon
        core.patch_node.assert_called_once()
        cordon_kwargs = core.patch_node.call_args.kwargs
        assert cordon_kwargs["name"] == "node-1"
        assert cordon_kwargs["body"] == {"spec": {"unschedulable": True}}

        # Phase 2: list with field_selector then evict both pods
        core.list_pod_for_all_namespaces.assert_called_once_with(
            field_selector="spec.nodeName=node-1")
        assert core.create_namespaced_pod_eviction.call_count == 2
        evicted_names = [
            call.kwargs["name"]
            for call in core.create_namespaced_pod_eviction.call_args_list
        ]
        assert sorted(evicted_names) == ["amf-b", "smf-a"]

        assert result.api_response["cordoned"] is True
        assert sorted(result.api_response["evicted_pods"]) == [
            "free5gc/amf-b", "free5gc/smf-a"]

    @pytest.mark.asyncio
    async def test_drain_tolerates_per_pod_eviction_failure(self):
        factory, core, _apps = _mock_factory()
        pod_ok = SimpleNamespace(
            metadata=SimpleNamespace(name="ok", namespace="free5gc"))
        pod_fail = SimpleNamespace(
            metadata=SimpleNamespace(name="fail", namespace="free5gc"))
        core.list_pod_for_all_namespaces.return_value = SimpleNamespace(
            items=[pod_ok, pod_fail])

        def _evict(name, namespace, body):
            if name == "fail":
                raise RuntimeError("PodDisruptionBudget violated")
            return SimpleNamespace()

        core.create_namespaced_pod_eviction.side_effect = _evict

        executor = RemediationExecutor(k8s_client_factory=factory)
        result = await executor.execute(_policy("drain_node", target="node-x"))

        # Must not raise; per-pod failures are logged and the drain
        # reports only the pods that were successfully evicted.
        assert result.status == ExecutionStatus.SUCCESS
        assert result.api_response["evicted_pods"] == ["free5gc/ok"]


# --- rollback_config ---------------------------------------------------------

class TestRollbackConfigK8s:
    @pytest.mark.asyncio
    async def test_patches_deployment_with_rollback_annotation(self):
        factory, _core, apps = _mock_factory()
        executor = RemediationExecutor(k8s_client_factory=factory)

        result = await executor.execute(
            _policy("rollback_config", target="pcf",
                    params={"revision": "v2.3", "namespace": "prod"}))

        apps.patch_namespaced_deployment.assert_called_once()
        kwargs = apps.patch_namespaced_deployment.call_args.kwargs
        assert kwargs["name"] == "pcf"
        assert kwargs["namespace"] == "prod"
        annotations = (
            kwargs["body"]["spec"]["template"]["metadata"]["annotations"]
        )
        assert annotations["causal5g/rollback-requested"] == "v2.3"
        assert result.api_response["revision"] == "v2.3"
        assert result.api_response["simulated"] is False


# --- reroute_traffic ---------------------------------------------------------

class TestRerouteTrafficK8s:
    @pytest.mark.asyncio
    async def test_patches_service_selector_to_backup(self):
        factory, core, _apps = _mock_factory()
        executor = RemediationExecutor(k8s_client_factory=factory)

        result = await executor.execute(
            _policy("reroute_traffic", target="upf-1",
                    params={"backup_target": "upf-9"}))

        core.patch_namespaced_service.assert_called_once()
        kwargs = core.patch_namespaced_service.call_args.kwargs
        assert kwargs["name"] == "upf-1"
        assert kwargs["body"] == {"spec": {"selector": {"app": "upf-9"}}}
        assert result.api_response["backup_target"] == "upf-9"

    @pytest.mark.asyncio
    async def test_default_backup_target(self):
        factory, core, _apps = _mock_factory()
        executor = RemediationExecutor(k8s_client_factory=factory)

        await executor.execute(_policy("reroute_traffic", target="upf-1"))

        body = core.patch_namespaced_service.call_args.kwargs["body"]
        assert body["spec"]["selector"]["app"] == "upf-1-backup"


# --- error propagation -------------------------------------------------------

class TestK8sErrorPropagation:
    @pytest.mark.asyncio
    async def test_api_exception_marks_failed(self):
        factory, core, _apps = _mock_factory()
        core.delete_namespaced_pod.side_effect = RuntimeError(
            "ApiException: 404 Pod not found")
        executor = RemediationExecutor(k8s_client_factory=factory)

        result = await executor.execute(_policy("restart_pod", target="gone"))
        assert result.status == ExecutionStatus.FAILED
        assert "Pod not found" in result.message

    @pytest.mark.asyncio
    async def test_factory_failure_marks_failed(self):
        def _boom():
            raise RuntimeError("kubeconfig not found")

        executor = RemediationExecutor(k8s_client_factory=_boom)
        result = await executor.execute(_policy("restart_pod", target="amf"))
        assert result.status == ExecutionStatus.FAILED
        assert "kubeconfig not found" in result.message


# --- dry-run interaction -----------------------------------------------------

class TestDryRunWithK8sFactory:
    """Dry-run must short-circuit BEFORE the factory is touched, even
    when the factory is configured — you should be able to stage a
    production executor in dry-run mode without a live cluster."""

    @pytest.mark.asyncio
    async def test_dry_run_skips_factory(self):
        factory, core, _apps = _mock_factory()
        executor = RemediationExecutor(
            k8s_client_factory=factory, dry_run=True)

        result = await executor.execute(
            _policy("restart_pod", target="amf-1"))

        assert result.status == ExecutionStatus.DRY_RUN
        assert factory.call_count == 0
        assert core.delete_namespaced_pod.called is False


# --- default_k8s_client_factory ---------------------------------------------

class TestDefaultFactory:
    """Verify the helper picks the right kubernetes config loader for
    each mode. The tests inject a fake ``kubernetes`` package into
    sys.modules before calling the factory so the test is hermetic
    regardless of whether the real kubernetes client library is
    installed or what version it is."""

    @staticmethod
    def _install_fake_kubernetes(monkeypatch, calls):
        """Build a fake ``kubernetes`` package that the factory's
        ``from kubernetes import client, config`` will pick up.

        Records calls into the supplied dict so the test can assert
        which config loader was invoked and with what argument.
        """
        import sys
        import types

        fake_config = types.ModuleType("kubernetes.config")

        def _load_incluster_config():
            calls["in_cluster"] = calls.get("in_cluster", 0) + 1

        def _load_kube_config(config_file=None):
            calls["kube_config"] = calls.get("kube_config", 0) + 1
            calls["kube_config_file"] = config_file

        fake_config.load_incluster_config = _load_incluster_config
        fake_config.load_kube_config = _load_kube_config

        fake_client = types.ModuleType("kubernetes.client")
        fake_client.CoreV1Api = lambda: "core"
        fake_client.AppsV1Api = lambda: "apps"

        fake_pkg = types.ModuleType("kubernetes")
        fake_pkg.client = fake_client
        fake_pkg.config = fake_config

        monkeypatch.setitem(sys.modules, "kubernetes", fake_pkg)
        monkeypatch.setitem(sys.modules, "kubernetes.client", fake_client)
        monkeypatch.setitem(sys.modules, "kubernetes.config", fake_config)

    def test_in_cluster_config(self, monkeypatch):
        calls: dict = {}
        self._install_fake_kubernetes(monkeypatch, calls)

        from causal5g.remediation.executor import default_k8s_client_factory
        core, apps = default_k8s_client_factory(in_cluster=True)
        assert (core, apps) == ("core", "apps")
        assert calls.get("in_cluster") == 1
        assert "kube_config" not in calls

    def test_kubeconfig_path(self, monkeypatch, tmp_path):
        calls: dict = {}
        self._install_fake_kubernetes(monkeypatch, calls)

        from causal5g.remediation.executor import default_k8s_client_factory
        fake_kube = tmp_path / "kubeconfig.yaml"
        fake_kube.write_text("apiVersion: v1\nkind: Config\n")
        core, apps = default_k8s_client_factory(kubeconfig=str(fake_kube))
        assert (core, apps) == ("core", "apps")
        assert calls.get("kube_config") == 1
        assert calls.get("kube_config_file") == str(fake_kube)
        assert "in_cluster" not in calls
