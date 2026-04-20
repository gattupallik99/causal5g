"""
Regression coverage for causal.engine.rcsm.RootCauseScoringModule
attribution behaviour under weak-Granger conditions.

Background: in live demos with a single-NF crash (SMF, UDR, ...) the
composite scorer was consistently surfacing NRF at rank 1 with
byte-identical scores across unrelated faults. The root cause was that,
in the first ~50 seconds post-injection, Granger emits few or no edges
and the Bayesian posterior stays near its prior, so the composite
collapses to a pure-centrality ranking where NRF (hub of the 3GPP SBI
topology prior and parent of every node in the Bayesian network) always
wins.

Day 13 fix (rcsm.py):
  - Reachability boost: an NF whose nf_reachability has averaged below
    0.5 across the last _UNREACHABLE_CYCLES cycles has its composite
    floored at _REACHABILITY_FLOOR + 0.2 * centrality. This surfaces the
    actual crashed NF at rank 1 while preserving NRF supremacy during
    cascade faults (multiple unreachable NFs, centrality breaks ties).
  - Pipeline-not-ready gate: when no NF is unreachable AND Granger has
    < _MIN_GRANGER_EDGES_FOR_SIGNAL edges, generate_report returns an
    informational severity="INFO" placeholder instead of a false
    topology-prior attribution.

Patent coverage: these tests protect Claim 1(g)/Claim 4 composite
scoring from regressing into a default-topology ranker, and protect
Claim 1(h)'s fault-report contract against false positives during
quiescent windows.
"""
from __future__ import annotations

import pytest

from causal.engine.granger import TelemetryBuffer, GrangerCausalityEngine
from causal.engine.rcsm import (
    RootCauseScoringModule,
    BayesianRootCauseLayer,
)
from causal.graph.dcgm import DynamicCausalGraphManager


# --- fixtures -----------------------------------------------------------------

class _Evt:
    """Minimal telemetry event matching TelemetryBuffer.add_events()."""
    def __init__(self, nf_id, signal_name, value, ts):
        self.event_type = "metric"
        self.nf_id = nf_id
        self.signal_name = signal_name
        self.value = value
        self.timestamp = ts


def _ts(i: int) -> str:
    return f"2026-04-19T00:{i // 60:02d}:{i % 60:02d}Z"


def _healthy_reach(buffer: TelemetryBuffer, nf_ids, cycles: int = 20) -> None:
    """Populate the buffer with `cycles` all-healthy reachability samples."""
    for i in range(cycles):
        events = [_Evt(nf, "nf_reachability", 1.0, _ts(i)) for nf in nf_ids]
        buffer.add_events(events)


def _kill_nf(buffer: TelemetryBuffer, nf_id: str, cycles: int = 5) -> None:
    """Append `cycles` of reachability=0 for a single NF."""
    offset = len(buffer.timestamps)
    for i in range(cycles):
        buffer.add_events([_Evt(nf_id, "nf_reachability", 0.0, _ts(offset + i))])


@pytest.fixture
def rcsm():
    return RootCauseScoringModule()


@pytest.fixture
def dcgm():
    return DynamicCausalGraphManager()


@pytest.fixture
def empty_granger_result():
    """Granger result with zero links - the exact conditional under which
    the misattribution reproduces live."""
    from causal.engine.granger import GrangerResult
    return GrangerResult(
        links=[],
        total_pairs_tested=0,
        significant_links=0,
        analysis_window_size=20,
        timestamp="2026-04-19T00:00:00Z",
    )


@pytest.fixture
def sparse_granger_result():
    """One-edge Granger result - below the pipeline-not-ready threshold."""
    from causal.engine.granger import GrangerResult, CausalLink
    return GrangerResult(
        links=[CausalLink(
            cause_nf="amf", cause_metric="m1",
            effect_nf="smf", effect_metric="m2",
            p_value=0.01, f_statistic=5.0, lag=1,
            confidence=0.99, direction="amf->smf",
        )],
        total_pairs_tested=2,
        significant_links=1,
        analysis_window_size=20,
        timestamp="2026-04-19T00:00:00Z",
    )


# --- _is_unreachable ---------------------------------------------------------

class TestIsUnreachableHelper:
    def test_empty_buffer(self, rcsm):
        buf = TelemetryBuffer(window_size=60)
        assert rcsm._is_unreachable(buf, "nrf") is False

    def test_short_buffer(self, rcsm):
        buf = TelemetryBuffer(window_size=60)
        buf.add_events([_Evt("nrf", "nf_reachability", 0.0, _ts(0))])
        # < _UNREACHABLE_CYCLES samples -> undecided, treat as reachable
        assert rcsm._is_unreachable(buf, "nrf") is False

    def test_all_healthy(self, rcsm):
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, ["nrf"], cycles=10)
        assert rcsm._is_unreachable(buf, "nrf") is False

    def test_recently_crashed(self, rcsm):
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, ["smf"], cycles=10)
        _kill_nf(buf, "smf", cycles=5)
        assert rcsm._is_unreachable(buf, "smf") is True

    def test_transient_blip_does_not_trip(self, rcsm):
        # 2 healthy, then 1 zero, then healthy again -> recent 3 cycles
        # average = (1 + 1 + 1) / 3 = 1.0 (not a crash).
        buf = TelemetryBuffer(window_size=60)
        for i in range(10):
            buf.add_events([_Evt("pcf", "nf_reachability", 1.0, _ts(i))])
        buf.add_events([_Evt("pcf", "nf_reachability", 0.0, _ts(10))])
        for i in range(11, 14):
            buf.add_events([_Evt("pcf", "nf_reachability", 1.0, _ts(i))])
        assert rcsm._is_unreachable(buf, "pcf") is False


# --- score() attribution -----------------------------------------------------

class TestScoreAttributionWithReachabilityBoost:
    """The live-demo regression: SMF crashes, NRF healthy, empty Granger.
    Without the boost, NRF ranks 1. With the boost, SMF ranks 1."""

    def test_smf_crash_with_empty_granger_surfaces_smf(
        self, rcsm, dcgm, empty_granger_result
    ):
        buf = TelemetryBuffer(window_size=60)
        all_nfs = list(RootCauseScoringModule._TRACKED_NFS)
        _healthy_reach(buf, all_nfs, cycles=10)
        _kill_nf(buf, "smf", cycles=5)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        top = candidates[0]
        assert top.nf_id == "smf", (
            f"Expected SMF at rank 1 (only unreachable NF); "
            f"got {top.nf_id} with score {top.composite_score}. "
            f"Full ranking: "
            f"{[(c.nf_id, c.composite_score) for c in candidates]}"
        )
        # The boost must floor at or above _REACHABILITY_FLOOR.
        assert top.composite_score >= RootCauseScoringModule._REACHABILITY_FLOOR

    def test_udr_crash_surfaces_udr_not_nrf(
        self, rcsm, dcgm, empty_granger_result
    ):
        # UDR is the subtlest case: it's NOT in the Bayesian network
        # (hard-coded to 0.3 prior) and has low centrality. Without the
        # boost, NRF wins by a wide margin.
        buf = TelemetryBuffer(window_size=60)
        all_nfs = list(RootCauseScoringModule._TRACKED_NFS)
        _healthy_reach(buf, all_nfs, cycles=10)
        _kill_nf(buf, "udr", cycles=5)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        assert candidates[0].nf_id == "udr", (
            f"Expected UDR at rank 1; got {candidates[0].nf_id}. "
            f"Ranking: {[(c.nf_id, c.composite_score) for c in candidates]}"
        )

    def test_nrf_cascade_still_ranks_nrf_first(
        self, rcsm, dcgm, empty_granger_result
    ):
        # When NRF crashes, downstream NFs also go unreachable. The boost
        # should apply to all of them, but centrality must still put NRF
        # on top (NRF = hub of 3GPP topology prior).
        buf = TelemetryBuffer(window_size=60)
        all_nfs = list(RootCauseScoringModule._TRACKED_NFS)
        _healthy_reach(buf, all_nfs, cycles=10)
        # NRF + all downstream fail in the cascade
        cascade = ["nrf", "amf", "smf", "pcf", "udm", "ausf", "nssf"]
        for i in range(5):
            buf.add_events([
                _Evt(nf, "nf_reachability", 0.0, _ts(100 + i))
                for nf in cascade
            ])

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        assert candidates[0].nf_id == "nrf", (
            f"NRF cascade should rank NRF #1; got {candidates[0].nf_id}"
        )

    def test_healthy_pipeline_unboosted(
        self, rcsm, dcgm, empty_granger_result
    ):
        # No NF unreachable. Every NF composite should stay below the
        # boost floor (ceiling of pure topology ranking).
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=15)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        for c in candidates:
            assert c.composite_score < RootCauseScoringModule._REACHABILITY_FLOOR, (
                f"Healthy {c.nf_id} was boosted to {c.composite_score}"
            )

    def test_boost_tie_breaks_by_centrality(
        self, rcsm, dcgm, empty_granger_result
    ):
        # Two unreachable NFs: AMF (higher centrality as parent of AUSF)
        # and UDR (low centrality leaf). AMF should rank higher.
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=10)
        for i in range(5):
            buf.add_events([
                _Evt("amf", "nf_reachability", 0.0, _ts(100 + i)),
                _Evt("udr", "nf_reachability", 0.0, _ts(100 + i)),
            ])

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        # Find the rank of each
        ranks = {c.nf_id: c.rank for c in candidates}
        assert ranks["amf"] < ranks["udr"], (
            f"AMF (higher centrality) should outrank UDR. "
            f"Got AMF={ranks['amf']}, UDR={ranks['udr']}"
        )


# --- generate_report() pipeline-not-ready gate -------------------------------

class TestPipelineNotReadyGate:
    def test_quiescent_pipeline_returns_info(
        self, rcsm, dcgm, empty_granger_result
    ):
        # Healthy buffer, zero Granger edges. The gate MUST fire and
        # return an INFO report instead of a topology-prior attribution.
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=15)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        report = rcsm.generate_report(candidates, buf, empty_granger_result)

        assert report.severity == "INFO"
        assert report.root_cause.nf_id == "none"
        assert report.fault_category.startswith("Informational")
        assert report.affected_nfs == []

    def test_sparse_granger_still_gates_when_healthy(
        self, rcsm, dcgm, sparse_granger_result
    ):
        # One edge is below _MIN_GRANGER_EDGES_FOR_SIGNAL (=2).
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=15)

        candidates = rcsm.score(sparse_granger_result, dcgm, buf)
        report = rcsm.generate_report(candidates, buf, sparse_granger_result)
        assert report.severity == "INFO"

    def test_unreachable_nf_bypasses_gate(
        self, rcsm, dcgm, empty_granger_result
    ):
        # Even with zero Granger edges, if any NF is unreachable we must
        # produce a real attribution - the reachability signal is
        # authoritative.
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=10)
        _kill_nf(buf, "pcf", cycles=5)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        report = rcsm.generate_report(candidates, buf, empty_granger_result)
        assert report.severity != "INFO"
        assert report.root_cause.nf_id == "pcf"

    def test_sufficient_granger_bypasses_gate(self, rcsm, dcgm):
        # Two+ Granger edges is enough signal for a real attribution.
        from causal.engine.granger import GrangerResult, CausalLink

        def _link(c, e, p=0.01):
            return CausalLink(
                cause_nf=c, cause_metric="m1",
                effect_nf=e, effect_metric="m2",
                p_value=p, f_statistic=6.0, lag=1,
                confidence=1 - p, direction=f"{c}->{e}",
            )

        gr = GrangerResult(
            links=[_link("amf", "smf"), _link("smf", "pcf")],
            total_pairs_tested=4,
            significant_links=2,
            analysis_window_size=20,
            timestamp="2026-04-19T00:00:00Z",
        )
        dcgm.update_from_granger(gr)

        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=15)

        candidates = rcsm.score(gr, dcgm, buf)
        report = rcsm.generate_report(candidates, buf, gr)
        assert report.severity != "INFO"


# --- invariants --------------------------------------------------------------

class TestScoreInvariants:
    def test_all_candidates_returned(
        self, rcsm, dcgm, empty_granger_result
    ):
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=10)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        # One candidate per NF node in the DCGM graph.
        assert len(candidates) == dcgm.graph.number_of_nodes()
        ranks = [c.rank for c in candidates]
        assert ranks == sorted(ranks)  # rank 1..N
        assert ranks[0] == 1

    def test_candidates_sorted_descending_by_score(
        self, rcsm, dcgm, empty_granger_result
    ):
        buf = TelemetryBuffer(window_size=60)
        _healthy_reach(buf, list(RootCauseScoringModule._TRACKED_NFS), cycles=10)
        _kill_nf(buf, "smf", cycles=5)

        candidates = rcsm.score(empty_granger_result, dcgm, buf)
        scores = [c.composite_score for c in candidates]
        assert scores == sorted(scores, reverse=True)
