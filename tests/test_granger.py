"""
Regression coverage for causal.engine.granger.GrangerCausalityEngine.

Focus: the zero-variance guard in ``test_pair``. Without it, flat
telemetry columns (e.g. a fault state that pins a metric for longer than
the analysis window) caused adfuller / statsmodels OLS to raise
LinAlgError inside the analyze() loop every cycle, pegging uvicorn at
~100 percent CPU. These tests assert the guard short-circuits before
statsmodels runs.

Patent context: this is the Claim 1(d) / Claim 2 causal-inference edge
path that runs in the live closed-loop pipeline. A crash-free analyze()
is a prerequisite for Claim 3's confidence-gated remediation.
"""
from __future__ import annotations

import numpy as np
import pytest

from causal.engine.granger import GrangerCausalityEngine


# --- fixtures -----------------------------------------------------------------

@pytest.fixture
def engine():
    return GrangerCausalityEngine(max_lag=3, significance=0.05)


def _noisy_series(seed: int, n: int = 40, drift: float = 0.0) -> list[float]:
    """Stationary series with a touch of drift, deterministic per seed."""
    rng = np.random.default_rng(seed)
    return list(rng.normal(loc=drift, scale=1.0, size=n))


# --- _has_variance ------------------------------------------------------------

class TestHasVariance:
    def test_none_input(self, engine):
        assert engine._has_variance(None) is False

    def test_empty(self, engine):
        assert engine._has_variance([]) is False

    def test_single_point(self, engine):
        assert engine._has_variance([1.0]) is False

    def test_constant(self, engine):
        assert engine._has_variance([3.0] * 30) is False

    def test_near_constant_below_tol(self, engine):
        # Variance well below _VAR_TOL (1e-10)
        series = [1.0 + (i * 1e-15) for i in range(30)]
        assert engine._has_variance(series) is False

    def test_nonfinite(self, engine):
        assert engine._has_variance([1.0, 2.0, float("nan"), 4.0]) is False
        assert engine._has_variance([1.0, 2.0, float("inf"), 4.0]) is False

    def test_normal_series(self, engine):
        assert engine._has_variance(_noisy_series(0)) is True

    def test_non_numeric(self, engine):
        assert engine._has_variance(["a", "b", "c"]) is False


# --- test_pair guard ----------------------------------------------------------

class TestConstantColumnGuard:
    """These are the regression cases that pegged uvicorn in live demos."""

    def test_constant_cause_returns_none_without_calling_statsmodels(
        self, engine, monkeypatch
    ):
        # If the guard fires, grangercausalitytests must NEVER be called.
        called = {"count": 0}

        def _boom(*_a, **_kw):  # pragma: no cover - asserts absence of call
            called["count"] += 1
            raise AssertionError("grangercausalitytests should not be invoked")

        monkeypatch.setattr(
            "causal.engine.granger.grangercausalitytests", _boom
        )

        result = engine.test_pair(
            "smf", "session_count", [42.0] * 30,
            "upf", "pdr_hits", _noisy_series(1),
        )
        assert result is None
        assert called["count"] == 0

    def test_constant_effect_returns_none(self, engine):
        result = engine.test_pair(
            "amf", "registrations", _noisy_series(2),
            "nrf", "heartbeat", [7.0] * 30,
        )
        assert result is None

    def test_both_constant_returns_none(self, engine):
        result = engine.test_pair(
            "amf", "x", [1.0] * 25,
            "smf", "y", [2.0] * 25,
        )
        assert result is None

    def test_linear_cause_returns_none_after_post_diff_guard(
        self, engine, monkeypatch
    ):
        # A perfectly linear series has variance > 0 in raw form (so the
        # pre-guard does NOT fire) but its first-difference is constant.
        # The post-differencing guard must catch that path.
        monkeypatch.setattr(
            GrangerCausalityEngine, "is_stationary", lambda self, s: False
        )

        linear = [float(i) for i in range(40)]
        noisy = _noisy_series(3, n=40)

        # Pre-guard must NOT fire on the raw linear series.
        assert engine._has_variance(linear) is True

        # But after first-differencing, linear -> all ones -> zero variance.
        diffed = engine.make_stationary(linear)
        assert engine._has_variance(diffed) is False

        result = engine.test_pair(
            "nrf", "c", linear,
            "upf", "e", noisy,
        )
        assert result is None

    def test_short_series_returns_none(self, engine):
        # Pre-existing min_len < 15 guard still applies.
        result = engine.test_pair(
            "amf", "x", _noisy_series(4, n=10),
            "smf", "y", _noisy_series(5, n=10),
        )
        assert result is None

    def test_valid_pair_can_still_return_link(self, engine):
        # Construct a clear lead-lag relationship so the Granger test is
        # likely to flag the pair. Not strictly deterministic across
        # statsmodels versions, but the path must at minimum run without
        # raising. The guard must NOT short-circuit noisy-but-varying data.
        rng = np.random.default_rng(123)
        n = 60
        x = list(rng.normal(size=n))
        # y[t] depends on x[t-1] with noise — classic Granger setup.
        y = [0.0]
        for i in range(1, n):
            y.append(0.8 * x[i - 1] + rng.normal(scale=0.3))

        # The call must not raise.
        _ = engine.test_pair(
            "cause_nf", "m_cause", x,
            "effect_nf", "m_effect", y,
        )


# --- analyze() resilience -----------------------------------------------------

class TestAnalyzeResilienceOnFlatBuffer:
    """End-to-end: constant series in the TelemetryBuffer should not crash
    analyze() or cause it to spin."""

    def test_analyze_skips_flat_pairs(self, engine):
        from causal.engine.granger import TelemetryBuffer

        class _Evt:
            def __init__(self, nf_id, metric, value, ts):
                self.event_type = "metric"
                self.nf_id = nf_id
                self.signal_name = metric
                self.value = value
                self.timestamp = ts

        buf = TelemetryBuffer(window_size=60)
        # One flat series, one noisy series, across two NFs.
        for i in range(30):
            ts = f"2026-04-18T00:00:{i:02d}Z"
            buf.add_events([
                _Evt("smf", "flat_metric", 5.0, ts),
                _Evt("upf", "noisy_metric", float(np.sin(i / 3.0) + i * 0.01), ts),
            ])

        result = engine.analyze(buf)
        # Must complete without raising and must produce a valid
        # GrangerResult artefact even if no significant links emerged.
        assert result is not None
        assert result.total_pairs_tested >= 0
        assert result.significant_links == len(result.links)
