"""
Tests for SliceEnsembleAttributor — Day 18
Patent Claim 1: bi-level DAG, Level-2 (slice sub-DAG) attribution.

Covers:
  - slice_breadth calculation for all five fault NFs
  - isolation_type classification
  - ensemble_score formula
  - per-slice path weights
  - pcf_timeout discriminating-power scenario (the Day 18 headline)
  - sweep() method
  - edge cases (no slices, shared NF, dag_edges override)
"""

from __future__ import annotations

import pytest
from causal5g.causal.slice_ensemble import SliceEnsembleAttributor, SliceAttribution
from causal5g.slice_topology import SliceTopologyManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stm() -> SliceTopologyManager:
    """Fresh STM with the default 3-slice topology (eMBB, URLLC, mIoT)."""
    return SliceTopologyManager()


def make_sea(stm: SliceTopologyManager | None = None) -> SliceEnsembleAttributor:
    return SliceEnsembleAttributor(stm=stm or make_stm())


# ---------------------------------------------------------------------------
# 1. Basic contract
# ---------------------------------------------------------------------------

class TestSliceAttributionBasicContract:
    def test_returns_slice_attribution(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        assert isinstance(result, SliceAttribution)

    def test_n_slices_total_matches_default_topology(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.0)
        assert result.n_slices_total == 3

    def test_per_slice_length_matches_n_slices(self):
        sea = make_sea()
        result = sea.attribute("nrf", 1.0)
        assert len(result.per_slice) == result.n_slices_total

    def test_ensemble_score_is_nonnegative(self):
        sea = make_sea()
        result = sea.attribute("amf", 0.5)
        assert result.ensemble_score >= 0.0

    def test_ensemble_score_does_not_exceed_one(self):
        # nf_layer_score capped at 1.0 inside the formula
        sea = make_sea()
        result = sea.attribute("nrf", 1.5)
        assert result.ensemble_score <= 1.0 + 1e-6


# ---------------------------------------------------------------------------
# 2. PCF timeout — the Day 18 headline scenario
# ---------------------------------------------------------------------------

class TestPCFTimeoutDiscrimination:
    """
    Default topology:
      1-000001 eMBB   → {amf, smf, pcf, udm, upf}   ← PCF present
      2-000001 URLLC  → {amf, smf, pcf, udm, upf}   ← PCF present
      3-000001 mIoT   → {amf, smf,      udm, upf}   ← PCF ABSENT

    Expected:
      n_slices_affected = 2
      slice_breadth     ≈ 0.667
      isolation_type    = "slice-isolated"
    """

    def test_pcf_affects_only_two_slices(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        assert result.n_slices_affected == 2

    def test_pcf_slice_breadth_is_two_thirds(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        assert abs(result.slice_breadth - 2 / 3) < 1e-4

    def test_pcf_isolation_type_is_slice_isolated(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        assert result.isolation_type == "slice-isolated"

    def test_miot_slice_pcf_not_present(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        miot = next(r for r in result.per_slice if r.slice_id == "3-000001")
        assert miot.nf_present is False

    def test_embb_and_urllc_pcf_present(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        for r in result.per_slice:
            if r.slice_id in ("1-000001", "2-000001"):
                assert r.nf_present is True

    def test_miot_slice_path_weight_is_zero(self):
        """mIoT has no PCF so the pruned sub-DAG has no PCF-involving edges."""
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        miot = next(r for r in result.per_slice if r.slice_id == "3-000001")
        assert miot.path_weight == 0.0

    def test_pcf_breadth_lower_than_nrf_breadth(self):
        """
        The key discriminating power of Level-2: PCF breadth < NRF breadth.
        PCF timeout (slice-isolated, breadth=0.67) and NRF crash
        (infrastructure-wide, breadth=1.0) are unambiguously separated by
        the slice_breadth metric even when both score identically at Level-1.
        """
        sea = make_sea()
        pcf_result = sea.attribute("pcf", 1.01)
        nrf_result = sea.attribute("nrf", 1.01)
        assert pcf_result.slice_breadth < nrf_result.slice_breadth

    def test_pcf_and_nrf_have_different_isolation_types(self):
        """PCF and NRF must map to different isolation_type values."""
        sea = make_sea()
        pcf_result = sea.attribute("pcf", 1.01)
        nrf_result = sea.attribute("nrf", 1.01)
        assert pcf_result.isolation_type != nrf_result.isolation_type


# ---------------------------------------------------------------------------
# 3. NRF crash — infrastructure-wide reference
# ---------------------------------------------------------------------------

class TestNRFCrashInfrastructureWide:
    def test_nrf_affects_all_slices(self):
        sea = make_sea()
        result = sea.attribute("nrf", 1.01)
        assert result.n_slices_affected == 3

    def test_nrf_slice_breadth_is_one(self):
        sea = make_sea()
        result = sea.attribute("nrf", 1.01)
        assert result.slice_breadth == 1.0

    def test_nrf_isolation_type_is_infrastructure_wide(self):
        sea = make_sea()
        result = sea.attribute("nrf", 1.01)
        assert result.isolation_type == "infrastructure-wide"

    def test_nrf_present_in_every_per_slice_result(self):
        sea = make_sea()
        result = sea.attribute("nrf", 1.01)
        assert all(r.nf_present for r in result.per_slice)


# ---------------------------------------------------------------------------
# 4. All-slice NFs: AMF, SMF, UDM (present in all three default slices)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nf", ["amf", "smf", "udm"])
class TestAllSliceNFs:
    def test_breadth_is_one(self, nf):
        sea = make_sea()
        result = sea.attribute(nf, 1.01)
        assert result.slice_breadth == 1.0

    def test_isolation_type_is_all_slice_nf(self, nf):
        sea = make_sea()
        result = sea.attribute(nf, 1.01)
        assert result.isolation_type == "all-slice-nf"

    def test_affects_all_slices(self, nf):
        sea = make_sea()
        result = sea.attribute(nf, 1.01)
        assert result.n_slices_affected == 3


# ---------------------------------------------------------------------------
# 5. Ensemble score formula
# ---------------------------------------------------------------------------

class TestEnsembleScoreFormula:
    def test_ensemble_is_weighted_combination(self):
        sea = make_sea()
        result = sea.attribute("pcf", 1.0)
        expected = 0.7 * 1.0 + 0.3 * result.slice_discriminant
        assert abs(result.ensemble_score - expected) < 1e-4

    def test_higher_nf_score_raises_ensemble(self):
        sea = make_sea()
        r_low  = sea.attribute("pcf", 0.5)
        r_high = sea.attribute("pcf", 1.0)
        assert r_high.ensemble_score > r_low.ensemble_score

    def test_custom_weights_respected(self):
        stm = make_stm()
        sea = SliceEnsembleAttributor(stm=stm, nf_weight=0.5, slice_weight=0.5)
        result = sea.attribute("pcf", 1.0)
        expected = 0.5 * 1.0 + 0.5 * result.slice_discriminant
        assert abs(result.ensemble_score - expected) < 1e-4


# ---------------------------------------------------------------------------
# 6. Sweep method
# ---------------------------------------------------------------------------

FIVE_SCENARIOS = [
    {"scenario": "nrf_crash",   "expected_nf": "nrf", "detected_nf": "nrf", "nf_layer_score": 1.01},
    {"scenario": "amf_crash",   "expected_nf": "amf", "detected_nf": "amf", "nf_layer_score": 1.01},
    {"scenario": "smf_crash",   "expected_nf": "smf", "detected_nf": "smf", "nf_layer_score": 1.01},
    {"scenario": "pcf_timeout", "expected_nf": "pcf", "detected_nf": "pcf", "nf_layer_score": 1.01},
    {"scenario": "udm_crash",   "expected_nf": "udm", "detected_nf": "udm", "nf_layer_score": 1.01},
]


class TestSweep:
    def test_sweep_returns_five_results(self):
        sea = make_sea()
        results = sea.sweep(FIVE_SCENARIOS)
        assert len(results) == 5

    def test_sweep_all_matches(self):
        sea = make_sea()
        results = sea.sweep(FIVE_SCENARIOS)
        assert all(r["match"] for r in results)

    def test_sweep_pcf_is_only_slice_isolated(self):
        sea = make_sea()
        results = sea.sweep(FIVE_SCENARIOS)
        isolated = [r for r in results if r["isolation_type"] == "slice-isolated"]
        assert len(isolated) == 1
        assert isolated[0]["scenario"] == "pcf_timeout"

    def test_sweep_nrf_is_infrastructure_wide(self):
        sea = make_sea()
        results = sea.sweep(FIVE_SCENARIOS)
        nrf_row = next(r for r in results if r["scenario"] == "nrf_crash")
        assert nrf_row["isolation_type"] == "infrastructure-wide"

    def test_sweep_pcf_breadth_is_two_thirds(self):
        sea = make_sea()
        results = sea.sweep(FIVE_SCENARIOS)
        pcf_row = next(r for r in results if r["scenario"] == "pcf_timeout")
        assert abs(pcf_row["slice_breadth"] - 2/3) < 1e-4

    def test_sweep_each_result_has_per_slice(self):
        sea = make_sea()
        results = sea.sweep(FIVE_SCENARIOS)
        for r in results:
            assert len(r["per_slice"]) == 3


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_stm_returns_trivial_attribution(self):
        stm = SliceTopologyManager()
        # Remove all slices
        for sc in stm.list_slices():
            stm.remove_slice(sc.slice_id)
        sea = SliceEnsembleAttributor(stm=stm)
        result = sea.attribute("pcf", 1.0)
        assert result.n_slices_total == 0
        assert result.isolation_type == "no-slices"

    def test_dag_edges_override_respected(self):
        """Passing dag_edges=[] should yield empty pruned subgraphs (no paths)."""
        sea = make_sea()
        result = sea.attribute("pcf", 1.0, dag_edges=[])
        # With no edges, PCF can still be a node but has no path weight
        for r in result.per_slice:
            assert r.path_weight == 0.0

    def test_unknown_nf_does_not_raise(self):
        sea = make_sea()
        result = sea.attribute("xyz_unknown_nf", 0.5)
        assert isinstance(result, SliceAttribution)

    def test_slice_discriminant_range(self):
        sea = make_sea()
        for nf in ["nrf", "amf", "smf", "pcf", "udm"]:
            r = sea.attribute(nf, 1.0)
            assert 0.0 <= r.slice_discriminant <= 1.0

    def test_to_dict_is_json_serialisable(self):
        import json
        sea = make_sea()
        result = sea.attribute("pcf", 1.01)
        blob = json.dumps(result.to_dict())
        assert "pcf" in blob
        assert "slice_breadth" in blob
