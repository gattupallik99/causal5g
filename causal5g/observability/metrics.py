"""
causal5g.observability.metrics
==============================
Prometheus exposition for the Causal5G pipeline (Day 15).

Scope
-----
Centralises every metric the control-plane, attribution layer, and
remediation executor emit. The API is deliberately thin — the hot paths
call a single helper (``record_scrape``, ``observe_composite``,
``record_remediation`` and friends) and never touch the underlying
``prometheus_client`` primitives directly. This keeps the instrumentation
patch set small, trivially reversible, and safe across sites that do
not have ``prometheus_client`` installed.

Contract
--------
- ``prometheus_client`` is imported lazily the first time any metric is
  touched. If the import fails, every helper becomes a no-op and
  :func:`render` falls back to the hand-rolled plain-text lines that
  predate Day 15. ``prometheus_client`` is therefore an optional
  dependency, not a hard requirement.
- All metrics live in a private :class:`CollectorRegistry` so unit
  tests can snapshot and reset state without leaking into the process
  default registry (the default registry cannot be cleared, which is
  the origin of most prometheus-in-pytest headaches).
- Every label set is bounded. NF labels are restricted to the eight
  tracked 3GPP NFs (``nrf``, ``amf``, ``smf``, ``pcf``, ``udm``,
  ``udr``, ``ausf``, ``nssf``). Status/severity/decision labels are
  restricted to the enumerations exported by the corresponding
  modules. Unbounded label cardinality is the most common way to DoS a
  Prometheus server; this module refuses to hand operators that rope.

Patent context
--------------
Metrics here are the operational-readiness evidence for Claims 1–4:
- Claim 1 / Claim 4: composite score gauge + attribution latency.
- Claim 2: RCA report severity counter.
- Claim 3: remediation action counter (by action + status) and the
  confidence-gate decision counter (executed vs skipped). Both are
  the production observability hooks for the closed-loop remediation
  limitation.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Tracked NF IDs — the same eight NFs the RCSM reachability gate uses.
TRACKED_NFS: tuple[str, ...] = (
    "nrf", "amf", "smf", "pcf", "udm", "udr", "ausf", "nssf",
)

# Remediation action label values (must match api.rae.ActionType).
ACTIONS: tuple[str, ...] = (
    "restart_pod", "scale_deployment", "drain_node", "rollback_config",
    "reroute_traffic", "notify_operator", "no_op",
)

# Status label values (must match causal5g.remediation.executor.ExecutionStatus).
STATUSES: tuple[str, ...] = (
    "success", "failed", "dry_run", "unknown_action", "timeout",
)

# Severity label values (must match causal5g.rca severities).
SEVERITIES: tuple[str, ...] = ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")

# Gate decision label values.
GATE_DECISIONS: tuple[str, ...] = ("executed", "skipped")


# ---------------------------------------------------------------------------
# Registry materialisation (lazy, optional)
# ---------------------------------------------------------------------------

class _MetricsRegistry:
    """Holds the CollectorRegistry and metric handles.

    Materialised on first use; survives until :func:`reset_for_tests`
    tears it down. Absence of ``prometheus_client`` is tolerated: in
    that case ``available`` stays False and every helper is a no-op.
    """

    def __init__(self) -> None:
        self.available: bool = False
        self.registry: Any = None
        # metric handles
        self.telemetry_scrapes: Any = None
        self.attribution_seconds: Any = None
        self.composite_score: Any = None
        self.rca_reports: Any = None
        self.remediation_actions: Any = None
        self.remediation_seconds: Any = None
        self.gate_decisions: Any = None
        self.pipeline_cycles: Any = None
        self.analyses_total: Any = None
        self.events_ingested: Any = None
        self.buffer_fill_pct: Any = None
        self.active_faults: Any = None

    def ensure(self) -> bool:
        """Instantiate the registry + metrics if not already done.

        Returns True if prometheus_client is available after the call,
        False otherwise. Called from every public helper; the import
        cost is paid exactly once per process (or per
        :func:`reset_for_tests`).
        """
        if self.available and self.registry is not None:
            return True
        if self.registry is not None:  # already tried and failed
            return False
        try:
            from prometheus_client import (  # noqa: WPS433 - lazy
                CollectorRegistry, Counter, Gauge, Histogram,
            )
        except ImportError:
            # Mark as "tried, failed" with a sentinel so we don't
            # re-attempt the import on every call.
            self.registry = _UNAVAILABLE
            self.available = False
            logger.debug(
                "prometheus_client not installed; causal5g metrics disabled"
            )
            return False

        reg = CollectorRegistry()
        self.registry = reg
        self.telemetry_scrapes = Counter(
            "causal5g_telemetry_scrapes_total",
            "Total telemetry scrapes per NF.",
            ["nf"],
            registry=reg,
        )
        self.attribution_seconds = Histogram(
            "causal5g_attribution_seconds",
            "RCSM scoring latency in seconds.",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=reg,
        )
        self.composite_score = Gauge(
            "causal5g_composite_score",
            "Latest RCSM composite score per NF (0..1).",
            ["nf"],
            registry=reg,
        )
        self.rca_reports = Counter(
            "causal5g_rca_reports_total",
            "Total RCA reports emitted, by severity band.",
            ["severity"],
            registry=reg,
        )
        self.remediation_actions = Counter(
            "causal5g_remediation_actions_total",
            "Total remediation actions executed, by action and status.",
            ["action", "status"],
            registry=reg,
        )
        self.remediation_seconds = Histogram(
            "causal5g_remediation_seconds",
            "Remediation action duration in seconds.",
            ["action"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
            registry=reg,
        )
        self.gate_decisions = Counter(
            "causal5g_confidence_gate_decisions_total",
            "Confidence-gate decisions (executed vs skipped).",
            ["decision"],
            registry=reg,
        )
        self.pipeline_cycles = Gauge(
            "causal5g_pipeline_cycles_total",
            "Total pipeline scrape/analyse cycles completed.",
            registry=reg,
        )
        self.analyses_total = Gauge(
            "causal5g_analyses_total",
            "Total RCSM analyses executed.",
            registry=reg,
        )
        self.events_ingested = Gauge(
            "causal5g_events_ingested_total",
            "Total telemetry events ingested into the buffer.",
            registry=reg,
        )
        self.buffer_fill_pct = Gauge(
            "causal5g_buffer_fill_pct",
            "Telemetry buffer fill percentage (0..100).",
            registry=reg,
        )
        self.active_faults = Gauge(
            "causal5g_active_faults",
            "Number of active fault injections.",
            registry=reg,
        )
        self.available = True
        return True


_UNAVAILABLE = object()   # sentinel: prometheus_client import failed
_state = _MetricsRegistry()


# ---------------------------------------------------------------------------
# Public helpers (no-op if prometheus_client missing)
# ---------------------------------------------------------------------------

def _validated(label_value: str, allowed: tuple[str, ...]) -> str:
    """Coerce label value to a bounded set; anything unknown becomes
    ``"other"``. Enforcing this here is cheap and prevents label
    cardinality from ballooning when upstream code drifts."""
    return label_value if label_value in allowed else "other"


def record_scrape(nf_id: str, count: int = 1) -> None:
    """Increment the per-NF scrape counter."""
    if not _state.ensure():
        return
    _state.telemetry_scrapes.labels(nf=_validated(nf_id, TRACKED_NFS)).inc(count)


@contextmanager
def time_attribution():
    """Context manager — observes attribution latency on the
    ``causal5g_attribution_seconds`` histogram. Yields immediately;
    the Observe happens on ``__exit__``.
    """
    if not _state.ensure():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        _state.attribution_seconds.observe(time.perf_counter() - start)


def observe_attribution_seconds(seconds: float) -> None:
    """Direct observe for attribution latency — used by call sites
    that can't wrap their body in a ``with time_attribution()`` block
    (e.g. functions that would need a large indent change)."""
    if not _state.ensure():
        return
    _state.attribution_seconds.observe(seconds)


def observe_composite(nf_id: str, score: float) -> None:
    """Record the latest composite score for ``nf_id``."""
    if not _state.ensure():
        return
    _state.composite_score.labels(nf=_validated(nf_id, TRACKED_NFS)).set(score)


def record_report(severity: str) -> None:
    """Increment the RCA report counter for ``severity``."""
    if not _state.ensure():
        return
    _state.rca_reports.labels(severity=_validated(severity, SEVERITIES)).inc()


def record_remediation(action: str, status: str) -> None:
    """Increment the remediation-action counter."""
    if not _state.ensure():
        return
    _state.remediation_actions.labels(
        action=_validated(action, ACTIONS),
        status=_validated(status, STATUSES),
    ).inc()


@contextmanager
def time_remediation(action: str):
    """Context manager — observes per-action remediation duration."""
    if not _state.ensure():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        _state.remediation_seconds.labels(
            action=_validated(action, ACTIONS),
        ).observe(time.perf_counter() - start)


def observe_remediation_seconds(action: str, seconds: float) -> None:
    """Direct observe for remediation-action duration — used by call
    sites that cannot wrap their body in ``with time_remediation``."""
    if not _state.ensure():
        return
    _state.remediation_seconds.labels(
        action=_validated(action, ACTIONS),
    ).observe(seconds)


def record_gate_decision(decision: str) -> None:
    """Increment the confidence-gate decision counter."""
    if not _state.ensure():
        return
    _state.gate_decisions.labels(
        decision=_validated(decision, GATE_DECISIONS),
    ).inc()


def set_pipeline_cycles(n: int) -> None:
    if not _state.ensure():
        return
    _state.pipeline_cycles.set(n)


def set_analyses_total(n: int) -> None:
    if not _state.ensure():
        return
    _state.analyses_total.set(n)


def set_events_ingested(n: int) -> None:
    if not _state.ensure():
        return
    _state.events_ingested.set(n)


def set_buffer_fill_pct(pct: float) -> None:
    if not _state.ensure():
        return
    _state.buffer_fill_pct.set(pct)


def set_active_faults(n: int) -> None:
    if not _state.ensure():
        return
    _state.active_faults.set(n)


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------

def render() -> tuple[bytes, str]:
    """Render the current metrics snapshot.

    Returns ``(body_bytes, content_type)``. When ``prometheus_client``
    is available the body is standard exposition format
    (``text/plain; version=0.0.4``). When it is not, the body is a
    zero-byte placeholder with ``text/plain``; callers (api/frg.py)
    are expected to fall back to the hand-rolled plain-text lines in
    that case.
    """
    if not _state.ensure():
        return b"", "text/plain; version=0.0.4"
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    body = generate_latest(_state.registry)
    return body, CONTENT_TYPE_LATEST


def is_available() -> bool:
    """Return True if prometheus_client is installed and the registry
    has been materialised."""
    return _state.ensure()


def reset_for_tests() -> None:
    """Tear down and re-create the registry.

    Called by test fixtures between test runs so that counter values
    do not bleed across tests. Cheap — the re-materialisation is the
    same work done on first import.
    """
    global _state
    _state = _MetricsRegistry()


def _name_variants(name: str) -> set[str]:
    """Return all plausible internal sample-name spellings for a
    public metric name. prometheus_client's handling of the ``_total``
    suffix has drifted across versions: some versions keep it on the
    sample name verbatim, others strip it for Gauges, others append
    ``_total`` to Counter names automatically. Checking all three
    variants makes look-up tests version-independent.
    """
    base = name.removesuffix("_total")
    return {name, base, f"{base}_total"}


def get_sample(name: str, **labels: str) -> float | None:
    """Return the current value of a single sample.

    Reads directly from the private CollectorRegistry, so the result
    is independent of the prometheus_client text-exposition format
    (which has drifted slightly across 0.19 -> 0.25).

    Parameters
    ----------
    name : the sample name, e.g. ``"causal5g_telemetry_scrapes_total"``
           or the base form ``"causal5g_telemetry_scrapes"``. The
           lookup tries both forms plus the ``_total`` variant.
    **labels : exact label set to match.

    Returns
    -------
    The sample value, or ``None`` if prometheus_client is not available
    or the (name, labels) pair has not been observed yet.
    """
    if not _state.ensure():
        return None
    candidates = _name_variants(name)
    for metric_family in _state.registry.collect():
        for sample in metric_family.samples:
            if sample.name not in candidates:
                continue
            if dict(sample.labels) != labels:
                continue
            return sample.value
    return None


def metric_family_names() -> set[str]:
    """Return the set of metric family names currently registered.

    Independent of the text-exposition ``# HELP`` line format. The
    result includes both ``foo`` and ``foo_total`` forms for every
    family so callers do not have to care which convention the
    installed prometheus_client version uses.
    """
    if not _state.ensure():
        return set()
    names: set[str] = set()
    for mf in _state.registry.collect():
        names |= _name_variants(mf.name)
    return names


# ---------------------------------------------------------------------------
# Metric-name exports (for tests and docs)
# ---------------------------------------------------------------------------

METRIC_NAMES: tuple[str, ...] = (
    "causal5g_telemetry_scrapes_total",
    "causal5g_attribution_seconds",
    "causal5g_composite_score",
    "causal5g_rca_reports_total",
    "causal5g_remediation_actions_total",
    "causal5g_remediation_seconds",
    "causal5g_confidence_gate_decisions_total",
    "causal5g_pipeline_cycles_total",
    "causal5g_analyses_total",
    "causal5g_events_ingested_total",
    "causal5g_buffer_fill_pct",
    "causal5g_active_faults",
)
