"""
CIE - Causal Inference Engine: Granger Causality Module
Patent Claim Reference:
  Claim 1(d) - applying causal inference algorithms to the normalized data
  Claim 2    - Granger causality tests between NF metric pairs
  Claim 4    - graph-theoretic scoring using causal relationships
"""

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests
from statsmodels.tsa.stattools import adfuller
from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class CausalLink:
    """A directed causal relationship between two NF metrics."""
    cause_nf: str           # e.g. "nrf"
    cause_metric: str       # e.g. "free5gc_sbi_inbound_request_duration"
    effect_nf: str          # e.g. "amf"
    effect_metric: str      # e.g. "free5gc_amf_business_active_pdu_session"
    p_value: float          # Granger test p-value (< 0.05 = significant)
    f_statistic: float      # F-statistic
    lag: int                # Best lag in samples
    confidence: float       # 1 - p_value
    direction: str          # "cause->effect" always


@dataclass
class GrangerResult:
    """Results from a full Granger causality analysis run."""
    links: list[CausalLink]
    total_pairs_tested: int
    significant_links: int
    analysis_window_size: int
    timestamp: str


class TelemetryBuffer:
    """
    Circular buffer that stores time series per (nf_id, metric_name).
    Feeds the Granger causality engine.
    Patent: normalizing ingested data to a unified timestamp domain
    """

    def __init__(self, window_size: int = 60):
        """
        window_size: number of scrape cycles to keep (60 cycles x 5s = 5min)
        """
        self.window_size = window_size
        self.series: dict[str, list[float]] = {}  # key: "nf_id::metric_name"
        self.timestamps: list[str] = []

    def add_events(self, events: list) -> None:
        """Add a batch of TelemetryEvents from one scrape cycle."""
        if not events:
            return

        ts = events[0].timestamp
        self.timestamps.append(ts)
        if len(self.timestamps) > self.window_size:
            self.timestamps.pop(0)

        # Group by nf+metric, take latest value per cycle
        cycle_data: dict[str, float] = {}
        for e in events:
            if e.event_type == "metric" and isinstance(e.value, (int, float)):
                key = f"{e.nf_id}::{e.signal_name}"
                cycle_data[key] = float(e.value)

        # Append to each series
        for key, value in cycle_data.items():
            if key not in self.series:
                self.series[key] = []
            self.series[key].append(value)
            if len(self.series[key]) > self.window_size:
                self.series[key].pop(0)

        logger.debug(
            f"Buffer: {len(self.series)} series, "
            f"{len(self.timestamps)} cycles"
        )

    def get_series(self, nf_id: str, metric: str) -> Optional[list[float]]:
        key = f"{nf_id}::{metric}"
        return self.series.get(key)

    def get_all_nf_series(self, nf_id: str) -> dict[str, list[float]]:
        """Return all metric series for a given NF."""
        return {
            k.split("::")[1]: v
            for k, v in self.series.items()
            if k.startswith(f"{nf_id}::")
            and len(v) >= 20  # need minimum samples
        }

    def get_cross_nf_pairs(
        self, min_samples: int = 20
    ) -> list[tuple[str, str, str, str]]:
        """
        Return all (nf1, metric1, nf2, metric2) pairs across different NFs
        with sufficient samples for Granger testing.
        """
        pairs = []
        keys = [
            k for k, v in self.series.items()
            if len(v) >= min_samples
        ]
        for i, k1 in enumerate(keys):
            for k2 in keys[i+1:]:
                nf1 = k1.split("::")[0]
                nf2 = k2.split("::")[0]
                if nf1 != nf2:  # only cross-NF pairs
                    m1 = k1.split("::")[1]
                    m2 = k2.split("::")[1]
                    pairs.append((nf1, m1, nf2, m2))
        return pairs

    @property
    def ready(self) -> bool:
        """True when we have enough samples to run Granger tests."""
        return len(self.timestamps) >= 20

    @property
    def fill_pct(self) -> float:
        return len(self.timestamps) / self.window_size * 100


class GrangerCausalityEngine:
    """
    Implements Granger causality testing between NF metric pairs.

    Granger causality: X Granger-causes Y if past values of X
    significantly improve prediction of Y beyond Y's own past values.

    Patent Claim 2: applying Granger causality tests to identify
    temporal precedence relationships between NF telemetry streams.
    """

    # Any std below this is treated as "constant" for Granger purposes.
    # adfuller and statsmodels OLS both raise LinAlgError on zero-variance
    # columns, which in the live pipeline produced a tight retry loop that
    # pegged uvicorn at 100% CPU when a fault stayed injected long enough
    # for a telemetry column to flatline. See test_granger.py
    # TestConstantColumnGuard for regression coverage.
    _VAR_TOL = 1e-10

    def __init__(self, max_lag: int = 5, significance: float = 0.05):
        self.max_lag = max_lag
        self.significance = significance

    @classmethod
    def _has_variance(cls, series) -> bool:
        """True iff the series has non-trivial, finite variance."""
        if series is None:
            return False
        try:
            arr = np.asarray(series, dtype=float)
        except (TypeError, ValueError):
            return False
        if arr.size < 2:
            return False
        if not np.isfinite(arr).all():
            return False
        return float(np.std(arr)) > cls._VAR_TOL

    def is_stationary(self, series: list[float]) -> bool:
        """
        Augmented Dickey-Fuller test for stationarity.
        Granger causality requires stationary time series.
        """
        try:
            result = adfuller(series, autolag='AIC')
            return result[1] < 0.05  # p-value < 0.05 means stationary
        except Exception:
            return False

    def make_stationary(self, series: list[float]) -> list[float]:
        """First-difference the series to achieve stationarity."""
        return [series[i] - series[i-1] for i in range(1, len(series))]

    def test_pair(
        self,
        cause_nf: str, cause_metric: str, cause_series: list[float],
        effect_nf: str, effect_metric: str, effect_series: list[float],
    ) -> Optional[CausalLink]:
        """
        Test if cause_series Granger-causes effect_series.
        Returns CausalLink if significant, None otherwise.
        """
        # Zero-variance guard (input). adfuller and grangercausalitytests
        # both hit LinAlgError on flat input, and the bare except below was
        # catching it but leaving the caller to retry on every analyze()
        # cycle. Short-circuit here so flat telemetry never reaches
        # statsmodels.
        if not self._has_variance(cause_series) or not self._has_variance(effect_series):
            return None

        try:
            # Ensure stationarity
            x = cause_series if self.is_stationary(cause_series) \
                else self.make_stationary(cause_series)
            y = effect_series if self.is_stationary(effect_series) \
                else self.make_stationary(effect_series)

            # Zero-variance guard (post-differencing). A perfectly linear
            # input becomes constant after first-differencing; catch that
            # second failure mode before statsmodels does.
            if not self._has_variance(x) or not self._has_variance(y):
                return None

            # Align lengths
            min_len = min(len(x), len(y))
            if min_len < 15:
                return None
            x, y = x[-min_len:], y[-min_len:]

            # Build DataFrame for statsmodels
            df = pd.DataFrame({"y": y, "x": x})

            # Run Granger test
            results = grangercausalitytests(
                df[["y", "x"]], maxlag=self.max_lag, verbose=False
            )

            # Find best lag by minimum p-value
            best_lag = 1
            best_p = 1.0
            best_f = 0.0
            for lag, result in results.items():
                p = result[0]["ssr_ftest"][1]  # p-value
                f = result[0]["ssr_ftest"][0]  # F-statistic
                if p < best_p:
                    best_p = p
                    best_f = f
                    best_lag = lag

            if best_p < self.significance:
                return CausalLink(
                    cause_nf=cause_nf,
                    cause_metric=cause_metric,
                    effect_nf=effect_nf,
                    effect_metric=effect_metric,
                    p_value=round(best_p, 6),
                    f_statistic=round(best_f, 4),
                    lag=best_lag,
                    confidence=round(1 - best_p, 6),
                    direction=f"{cause_nf}->{effect_nf}",
                )
        except Exception as e:
            logger.debug(f"Granger test failed {cause_nf}/{effect_nf}: {e}")
        return None

    def analyze(
        self, buffer: TelemetryBuffer
    ) -> GrangerResult:
        """
        Run Granger causality analysis across all cross-NF metric pairs.
        This is the core of patent claim 1(d) and claim 2.
        """
        from datetime import datetime, timezone
        logger.info(
            f"Starting Granger analysis | "
            f"buffer={len(buffer.timestamps)} cycles | "
            f"series={len(buffer.series)}"
        )

        pairs = buffer.get_cross_nf_pairs(min_samples=20)
        logger.info(f"Testing {len(pairs)} cross-NF metric pairs")

        links = []
        for cause_nf, cause_metric, effect_nf, effect_metric in pairs:
            cause_series = buffer.get_series(cause_nf, cause_metric)
            effect_series = buffer.get_series(effect_nf, effect_metric)
            if not cause_series or not effect_series:
                continue

            # Test both directions
            link = self.test_pair(
                cause_nf, cause_metric, cause_series,
                effect_nf, effect_metric, effect_series,
            )
            if link:
                links.append(link)
                logger.info(
                    f"CAUSAL LINK: {link.direction} | "
                    f"{cause_metric[:30]} -> {effect_metric[:30]} | "
                    f"p={link.p_value} lag={link.lag}"
                )

            # Reverse direction
            link_rev = self.test_pair(
                effect_nf, effect_metric, effect_series,
                cause_nf, cause_metric, cause_series,
            )
            if link_rev:
                links.append(link_rev)
                logger.info(
                    f"CAUSAL LINK: {link_rev.direction} | "
                    f"{effect_metric[:30]} -> {cause_metric[:30]} | "
                    f"p={link_rev.p_value} lag={link_rev.lag}"
                )

        result = GrangerResult(
            links=links,
            total_pairs_tested=len(pairs) * 2,
            significant_links=len(links),
            analysis_window_size=len(buffer.timestamps),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            f"Granger analysis complete | "
            f"tested={result.total_pairs_tested} | "
            f"significant={result.significant_links}"
        )
        return result


if __name__ == "__main__":
    import sys
    import time
    sys.path.insert(0, '/Users/krishnakumargattupalli/causal5g')
    from telemetry.collector.nf_scraper import NFScraper

    logger.info("CIE Day 3 - Collecting telemetry for Granger analysis...")
    logger.info("Need 20 scrape cycles (~100s). Collecting now...")

    scraper = NFScraper(scrape_interval=5)
    buffer = TelemetryBuffer(window_size=60)
    engine = GrangerCausalityEngine(max_lag=5, significance=0.05)

    cycle = 0
    while not buffer.ready:
        events = scraper.scrape_all()
        buffer.add_events(events)
        cycle += 1
        logger.info(
            f"Cycle {cycle} | events={len(events)} | "
            f"buffer={buffer.fill_pct:.0f}% full | "
            f"series={len(buffer.series)}"
        )
        time.sleep(5)

    logger.info("Buffer ready! Running Granger causality analysis...")
    result = engine.analyze(buffer)

    print("\n" + "="*60)
    print("CAUSAL LINKS DISCOVERED")
    print("="*60)
    if result.links:
        for link in sorted(result.links, key=lambda x: x.p_value):
            print(
                f"  {link.cause_nf:6} --> {link.effect_nf:6} | "
                f"p={link.p_value:.4f} | "
                f"F={link.f_statistic:.2f} | "
                f"lag={link.lag} | "
                f"{link.cause_metric[:25]} -> {link.effect_metric[:25]}"
            )
    else:
        print("  No significant causal links found in this window.")
        print("  (This is normal with idle 5G core - no traffic = flat metrics)")

    print("="*60)
    print(f"Tested: {result.total_pairs_tested} pairs")
    print(f"Significant: {result.significant_links} links")
    print(f"Window: {result.analysis_window_size} cycles")
