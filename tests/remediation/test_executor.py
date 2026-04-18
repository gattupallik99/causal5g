"""
Tests for causal5g.remediation.executor — Day 11, Claim 3 executor.
Covers all seven default handlers, dry_run mode, unknown action,
timeout and exception paths, handler registration, and context merging.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from causal5g.remediation.executor import (
    ExecutionResult,
    ExecutionStatus,
    RemediationExecutor,
)
from causal5g.remediation.policy_store import PolicyEntry


# ── fixtures ────────────────────────────────────────────────────────────────

def _policy(action: str, target: str = "amf-1",
            params: dict | None = None) -> PolicyEntry:
    now = time.time()
    return PolicyEntry(
        policy_id=f"pol-{action}", fault_scenario="test",
        action=action, target=target, params=params or {},
        priority=0, enabled=True, created_at=now, updated_at=now, version=1,
    )


@pytest.fixture
def executor():
    return RemediationExecutor(namespace="free5gc", dry_run=False)


@pytest.fixture
def dry_executor():
    return RemediationExecutor(namespace="free5gc", dry_run=True)


# ── default handlers ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restart_pod_success(executor):
    result = await executor.execute(_policy("restart_pod", target="amf-1"))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.success is True
    assert result.api_response["verb"] == "DELETE"
    assert result.api_response["name"] == "amf-1"
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_scale_deployment_uses_replicas_param(executor):
    result = await executor.execute(
        _policy("scale_deployment", target="smf", params={"replicas": 5}))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.api_response["replicas"] == 5
    assert result.api_response["verb"] == "PATCH"


@pytest.mark.asyncio
async def test_scale_deployment_defaults_to_two(executor):
    result = await executor.execute(_policy("scale_deployment", target="smf"))
    assert result.api_response["replicas"] == 2


@pytest.mark.asyncio
async def test_drain_node(executor):
    result = await executor.execute(
        _policy("drain_node", target="node-1", params={"grace_period_s": 60}))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.api_response["grace_period_s"] == 60


@pytest.mark.asyncio
async def test_rollback_config(executor):
    result = await executor.execute(
        _policy("rollback_config", target="pcf",
                params={"revision": "v2.3"}))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.api_response["revision"] == "v2.3"


@pytest.mark.asyncio
async def test_reroute_traffic_default_backup(executor):
    result = await executor.execute(_policy("reroute_traffic", target="upf-1"))
    assert result.api_response["backup_target"] == "upf-1-backup"


@pytest.mark.asyncio
async def test_notify_operator(executor):
    result = await executor.execute(
        _policy("notify_operator", target="nrf",
                params={"channel": "slack", "severity": "high"}))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.api_response["channel"] == "slack"
    assert result.api_response["severity"] == "high"


@pytest.mark.asyncio
async def test_no_op(executor):
    result = await executor.execute(
        _policy("no_op", target="amf",
                params={"reason": "confidence below threshold"}))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.api_response["reason"] == "confidence below threshold"


# ── dry-run mode ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_skips_handler(dry_executor):
    result = await dry_executor.execute(_policy("restart_pod", target="amf-1"))
    assert result.status == ExecutionStatus.DRY_RUN
    assert result.success is True
    assert "dry-run" in result.message
    assert result.api_response["simulated"] is True


@pytest.mark.asyncio
async def test_dry_run_includes_merged_params(dry_executor):
    policy = _policy("scale_deployment", target="smf",
                     params={"replicas": 3})
    result = await dry_executor.execute(policy, context={"namespace": "prod"})
    assert result.api_response["params"]["replicas"] == 3
    assert result.api_response["params"]["namespace"] == "prod"


# ── unknown action / error paths ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_action(executor):
    result = await executor.execute(_policy("teleport_pod", target="amf-1"))
    assert result.status == ExecutionStatus.UNKNOWN
    assert result.success is False
    assert "no handler" in result.message


@pytest.mark.asyncio
async def test_handler_exception_captured(executor):
    async def boom(target, params):
        raise RuntimeError("k8s API unreachable")

    executor.register("restart_pod", boom)
    result = await executor.execute(_policy("restart_pod"))
    assert result.status == ExecutionStatus.FAILED
    assert result.success is False
    assert "k8s API unreachable" in result.message


@pytest.mark.asyncio
async def test_handler_timeout():
    executor = RemediationExecutor(timeout_s=0.05)

    async def slow(target, params):
        await asyncio.sleep(1.0)
        return {}

    executor.register("restart_pod", slow)
    result = await executor.execute(_policy("restart_pod"))
    assert result.status == ExecutionStatus.TIMEOUT
    assert "timed out" in result.message


# ── context merging ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_overrides_policy_params(executor):
    policy = _policy("scale_deployment", target="smf",
                     params={"replicas": 2, "namespace": "free5gc"})
    result = await executor.execute(policy, context={"replicas": 10})
    assert result.api_response["replicas"] == 10


@pytest.mark.asyncio
async def test_context_augments_policy_params(executor):
    policy = _policy("reroute_traffic", target="upf-1", params={})
    result = await executor.execute(
        policy, context={"backup_target": "upf-9"})
    assert result.api_response["backup_target"] == "upf-9"


# ── introspection helpers ──────────────────────────────────────────────────

def test_supports_reports_registered_actions(executor):
    assert executor.supports("restart_pod")
    assert executor.supports("no_op")
    assert not executor.supports("teleport_pod")


def test_register_adds_new_handler(executor):
    async def custom(target, params):
        return {"custom": True}

    executor.register("custom_action", custom)
    assert executor.supports("custom_action")


@pytest.mark.asyncio
async def test_register_overrides_existing(executor):
    async def replacement(target, params):
        return {"overridden": True, "target": target}

    executor.register("restart_pod", replacement)
    result = await executor.execute(_policy("restart_pod", target="amf"))
    assert result.api_response == {"overridden": True, "target": "amf"}


# ── ExecutionResult helpers ────────────────────────────────────────────────

def test_execution_result_duration_ms_nonnegative():
    r = ExecutionResult(
        status=ExecutionStatus.SUCCESS, action="restart_pod", target="amf",
        started_at=1000.0, finished_at=1000.050)
    assert r.duration_ms == 50.0


def test_execution_result_success_flag_for_dry_run():
    r = ExecutionResult(
        status=ExecutionStatus.DRY_RUN, action="restart_pod", target="amf",
        started_at=1.0, finished_at=1.0)
    assert r.success is True


def test_execution_result_success_flag_for_failure():
    r = ExecutionResult(
        status=ExecutionStatus.FAILED, action="restart_pod", target="amf",
        started_at=1.0, finished_at=1.0)
    assert r.success is False
