"""Tests for GrangerPCFusionRecalibrator — Day 10"""
import pytest
from causal.engine.recalibrator import (
    GrangerPCFusionRecalibrator, RecalibrationConfig, FeedbackEntry
)
import time

@pytest.fixture
def recal():
    return GrangerPCFusionRecalibrator()

@pytest.fixture
def fb_success():
    return [{"fault_scenario":"nrf_crash","root_cause_nf":"nrf","action":"restart_pod",
             "outcome":1.0,"timestamp":time.time(),"slice_id":"1-000001"}]

@pytest.fixture
def fb_failure():
    return [{"fault_scenario":"amf_crash","root_cause_nf":"amf","action":"restart_pod",
             "outcome":0.0,"timestamp":time.time(),"slice_id":None}]

def test_skipped_below_min_feedback(recal):
    result = recal.recalibrate([{"fault_scenario":"nrf_crash","root_cause_nf":"nrf",
                                  "action":"restart_pod","outcome":1.0,
                                  "timestamp":time.time(),"slice_id":None}])
    assert result["skipped"] is True

def test_recalibrate_fires_with_sufficient_feedback(recal, fb_success):
    fb = fb_success * 3
    result = recal.recalibrate(fb)
    assert result["skipped"] is False
    assert result["cycle"] == 1
    assert result["entries_consumed"] == 3

def test_success_reinforces_outgoing_edges(recal, fb_success):
    fb = fb_success * 3
    recal.recalibrate(fb)
    # nrf → amf should be reinforced (weight > 1.0)
    w = recal.get_edge_weight("nrf", "amf")
    assert w > 1.0

def test_failure_penalises_outgoing_edges(recal, fb_failure):
    fb = fb_failure * 3
    recal.recalibrate(fb)
    # amf → smf should be penalised (weight < 1.0)
    w = recal.get_edge_weight("amf", "smf")
    assert w < 1.0

def test_weights_clamped_to_floor(recal):
    fb = [{"fault_scenario":"amf_crash","root_cause_nf":"amf","action":"restart_pod",
            "outcome":0.0,"timestamp":time.time(),"slice_id":None}] * 50
    recal.recalibrate(fb)
    for (c, e), w in recal.get_all_weights().items():
        assert w >= recal.config.weight_floor

def test_weights_clamped_to_ceiling(recal):
    fb = [{"fault_scenario":"nrf_crash","root_cause_nf":"nrf","action":"restart_pod",
            "outcome":1.0,"timestamp":time.time(),"slice_id":None}] * 50
    recal.recalibrate(fb)
    for (c, e), w in recal.get_all_weights().items():
        assert w <= recal.config.weight_ceiling

def test_neutral_edge_returns_1_0(recal):
    w = recal.get_edge_weight("smf", "upf")
    assert w == 1.0

def test_decay_applied_on_second_cycle(recal, fb_success):
    fb = fb_success * 3
    recal.recalibrate(fb)
    w1 = recal.get_edge_weight("nrf", "amf")
    recal.recalibrate(fb)
    w2 = recal.get_edge_weight("nrf", "amf")
    # Weight should still be > 1 but decay brings it slightly back toward 1
    assert w2 > 1.0

def test_cycle_count_increments(recal, fb_success):
    fb = fb_success * 3
    recal.recalibrate(fb)
    recal.recalibrate(fb)
    assert recal.state.cycle_count == 2

def test_total_entries_consumed(recal, fb_success):
    fb = fb_success * 3
    recal.recalibrate(fb)
    assert recal.state.total_entries_consumed == 3

def test_stats_structure(recal, fb_success):
    recal.recalibrate(fb_success * 3)
    stats = recal.get_stats()
    assert "cycle_count" in stats
    assert "edges_tracked" in stats
    assert "reinforced_edges" in stats
    assert "penalised_edges" in stats
    assert "config" in stats

def test_reset_clears_state(recal, fb_success):
    recal.recalibrate(fb_success * 3)
    recal.reset()
    assert recal.state.cycle_count == 0
    assert len(recal.state.edge_weights) == 0

def test_feedback_entry_from_dict():
    d = {"fault_scenario":"smf_crash","root_cause_nf":"smf","action":"restart_pod",
         "outcome":1.0,"timestamp":1234567890.0,"slice_id":"2-000001"}
    e = FeedbackEntry.from_dict(d)
    assert e.fault_scenario == "smf_crash"
    assert e.outcome == 1.0
    assert e.slice_id == "2-000001"

def test_custom_config():
    cfg = RecalibrationConfig(learning_rate=0.10, min_feedback_count=1)
    recal = GrangerPCFusionRecalibrator(config=cfg)
    fb = [{"fault_scenario":"nrf_crash","root_cause_nf":"nrf","action":"restart_pod",
            "outcome":1.0,"timestamp":time.time(),"slice_id":None}]
    result = recal.recalibrate(fb)
    assert result["skipped"] is False
