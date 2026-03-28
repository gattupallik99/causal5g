"""
PolicyStore — Causal5G Day 10
Full CRUD policy management for remediation action policies.
Patent claim 3: persistent, versioned action policy table.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/policy", tags=["policy-store"])


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PolicyEntry:
    """A single action policy rule."""
    policy_id:      str
    fault_scenario: str
    action:         str
    target:         str
    params:         dict[str, Any]
    priority:       int             # lower = higher priority (0 = preferred)
    enabled:        bool
    created_at:     float
    updated_at:     float
    version:        int
    description:    str = ""


@dataclass
class PolicyStore:
    """
    In-memory policy store with versioning and CRUD.
    Initialized with the same defaults as ACTION_POLICY in rae.py,
    making it the single source of truth for remediation policies.
    """
    _policies:  dict[str, PolicyEntry] = field(default_factory=dict)
    _version:   int = 0
    _audit_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self._load_defaults()

    def _load_defaults(self) -> None:
        defaults = [
            # NRF
            ("nrf_crash", "restart_pod",    "nrf",      {"namespace": "free5gc", "grace_period": 10}, 0, "Restart NRF pod on crash"),
            ("nrf_crash", "notify_operator","ops-team",  {"severity": "critical", "nf": "nrf"},        1, "Alert ops if restart fails"),
            # AMF
            ("amf_crash", "restart_pod",    "amf",      {"namespace": "free5gc", "grace_period": 5},  0, "Restart AMF pod on crash"),
            ("amf_crash", "scale_deployment","amf",     {"namespace": "free5gc", "replicas": 2},       1, "Scale AMF if restart insufficient"),
            # SMF
            ("smf_crash", "restart_pod",    "smf",      {"namespace": "free5gc", "grace_period": 5},  0, "Restart SMF pod on crash"),
            ("smf_crash", "reroute_traffic","smf",      {"backup_smf": "smf-backup"},                  1, "Reroute to backup SMF"),
            # PCF
            ("pcf_timeout","rollback_config","pcf",     {"namespace": "free5gc", "revision": -1},      0, "Rollback PCF config on timeout"),
            ("pcf_timeout","restart_pod",   "pcf",      {"namespace": "free5gc", "grace_period": 10}, 1, "Restart PCF after rollback"),
            # UDM
            ("udm_crash", "restart_pod",    "udm",      {"namespace": "free5gc", "grace_period": 5},  0, "Restart UDM pod on crash"),
            ("udm_crash", "scale_deployment","udm",     {"namespace": "free5gc", "replicas": 2},       1, "Scale UDM if restart insufficient"),
            # Default
            ("_default",  "notify_operator","ops-team", {"severity": "warning", "nf": "unknown"},      0, "Fallback operator notification"),
        ]
        now = time.time()
        for (scenario, action, target, params, priority, desc) in defaults:
            entry = PolicyEntry(
                policy_id=str(uuid.uuid4())[:8],
                fault_scenario=scenario,
                action=action,
                target=target,
                params=params,
                priority=priority,
                enabled=True,
                created_at=now,
                updated_at=now,
                version=1,
                description=desc,
            )
            self._policies[entry.policy_id] = entry
        logger.info("[PolicyStore] Loaded %d default policies", len(defaults))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        fault_scenario: str,
        action:         str,
        target:         str,
        params:         dict[str, Any],
        priority:       int = 0,
        description:    str = "",
    ) -> PolicyEntry:
        now = time.time()
        entry = PolicyEntry(
            policy_id=str(uuid.uuid4())[:8],
            fault_scenario=fault_scenario,
            action=action,
            target=target,
            params=params,
            priority=priority,
            enabled=True,
            created_at=now,
            updated_at=now,
            version=1,
            description=description,
        )
        self._policies[entry.policy_id] = entry
        self._audit("create", entry.policy_id, None, entry)
        self._version += 1
        logger.info("[PolicyStore] Created policy %s for %s", entry.policy_id, fault_scenario)
        return entry

    def get(self, policy_id: str) -> PolicyEntry | None:
        return self._policies.get(policy_id)

    def list_all(self, fault_scenario: str | None = None, enabled_only: bool = False) -> list[PolicyEntry]:
        entries = list(self._policies.values())
        if fault_scenario:
            entries = [e for e in entries if e.fault_scenario == fault_scenario]
        if enabled_only:
            entries = [e for e in entries if e.enabled]
        return sorted(entries, key=lambda e: (e.fault_scenario, e.priority))

    def update(
        self,
        policy_id: str,
        **kwargs: Any,
    ) -> PolicyEntry:
        entry = self._policies.get(policy_id)
        if entry is None:
            raise KeyError(f"Policy {policy_id} not found")
        old = self._snapshot(entry)
        allowed = {"action", "target", "params", "priority", "enabled", "description"}
        for k, v in kwargs.items():
            if k in allowed:
                setattr(entry, k, v)
        entry.updated_at = time.time()
        entry.version   += 1
        self._audit("update", policy_id, old, entry)
        self._version += 1
        return entry

    def delete(self, policy_id: str) -> bool:
        entry = self._policies.pop(policy_id, None)
        if entry:
            self._audit("delete", policy_id, self._snapshot(entry), None)
            self._version += 1
        return entry is not None

    def disable(self, policy_id: str) -> PolicyEntry:
        return self.update(policy_id, enabled=False)

    def enable(self, policy_id: str) -> PolicyEntry:
        return self.update(policy_id, enabled=True)

    # ------------------------------------------------------------------
    # Query helpers used by RAE
    # ------------------------------------------------------------------

    def get_ordered_actions(self, fault_scenario: str) -> list[PolicyEntry]:
        """
        Return enabled policies for a fault scenario sorted by priority.
        Used by RAE to replace the static ACTION_POLICY dict lookup.
        """
        entries = [
            e for e in self._policies.values()
            if e.fault_scenario == fault_scenario and e.enabled
        ]
        if not entries:
            entries = [
                e for e in self._policies.values()
                if e.fault_scenario == "_default" and e.enabled
            ]
        return sorted(entries, key=lambda e: e.priority)

    # ------------------------------------------------------------------
    # Audit + versioning
    # ------------------------------------------------------------------

    def _snapshot(self, entry: PolicyEntry) -> dict[str, Any]:
        return {
            "policy_id":      entry.policy_id,
            "fault_scenario": entry.fault_scenario,
            "action":         entry.action,
            "target":         entry.target,
            "params":         dict(entry.params),
            "priority":       entry.priority,
            "enabled":        entry.enabled,
            "version":        entry.version,
        }

    def _audit(self, op: str, policy_id: str, before: Any, after: Any) -> None:
        self._audit_log.append({
            "op":        op,
            "policy_id": policy_id,
            "timestamp": time.time(),
            "before":    before,
            "after":     self._snapshot(after) if after else None,
        })
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]

    def get_audit_log(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._audit_log[-limit:][::-1]

    def store_version(self) -> int:
        return self._version

    def to_dict(self) -> dict[str, Any]:
        return {
            "store_version": self._version,
            "policy_count":  len(self._policies),
            "policies": [self._snapshot(e) for e in self.list_all()],
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store = PolicyStore()


def get_store() -> PolicyStore:
    return _store


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------

class CreatePolicyRequest(BaseModel):
    fault_scenario: str
    action:         str
    target:         str
    params:         dict[str, Any] = {}
    priority:       int = 0
    description:    str = ""


class UpdatePolicyRequest(BaseModel):
    action:      str | None = None
    target:      str | None = None
    params:      dict[str, Any] | None = None
    priority:    int | None = None
    enabled:     bool | None = None
    description: str | None = None


def _entry_to_dict(e: PolicyEntry) -> dict[str, Any]:
    return {
        "policy_id":      e.policy_id,
        "fault_scenario": e.fault_scenario,
        "action":         e.action,
        "target":         e.target,
        "params":         e.params,
        "priority":       e.priority,
        "enabled":        e.enabled,
        "version":        e.version,
        "description":    e.description,
        "created_at":     e.created_at,
        "updated_at":     e.updated_at,
    }


@router.get("")
async def list_policies(fault_scenario: str | None = None, enabled_only: bool = False):
    entries = _store.list_all(fault_scenario=fault_scenario, enabled_only=enabled_only)
    return {
        "store_version":  _store.store_version(),
        "policy_count":   len(entries),
        "policies":       [_entry_to_dict(e) for e in entries],
    }


@router.post("", status_code=201)
async def create_policy(req: CreatePolicyRequest):
    entry = _store.create(
        fault_scenario=req.fault_scenario,
        action=req.action,
        target=req.target,
        params=req.params,
        priority=req.priority,
        description=req.description,
    )
    return _entry_to_dict(entry)


@router.get("/{policy_id}")
async def get_policy(policy_id: str):
    entry = _store.get(policy_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return _entry_to_dict(entry)


@router.patch("/{policy_id}")
async def update_policy(policy_id: str, req: UpdatePolicyRequest):
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        entry = _store.update(policy_id, **updates)
        return _entry_to_dict(entry)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{policy_id}")
async def delete_policy(policy_id: str):
    if not _store.delete(policy_id):
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return {"deleted": policy_id}


@router.post("/{policy_id}/disable")
async def disable_policy(policy_id: str):
    try:
        entry = _store.disable(policy_id)
        return _entry_to_dict(entry)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{policy_id}/enable")
async def enable_policy(policy_id: str):
    try:
        entry = _store.enable(policy_id)
        return _entry_to_dict(entry)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/scenario/{fault_scenario}/actions")
async def get_ordered_actions(fault_scenario: str):
    """Return enabled policies for a scenario in priority order — used by RAE."""
    entries = _store.get_ordered_actions(fault_scenario)
    return {
        "fault_scenario": fault_scenario,
        "actions": [_entry_to_dict(e) for e in entries],
    }


@router.get("/audit/log")
async def get_audit_log(limit: int = 20):
    return {"entries": _store.get_audit_log(limit)}
