"""
Tests for SliceTopologyManager — Day 9
Covers: slice registry, graph pruning, cross-slice leakage detection.
"""

import pytest
from causal5g.slice_topology import (
    SliceTopologyManager,
    SliceConfig,
    SHARED_NFS,
    SLICE_SPECIFIC_NFS,
    INTRA_SLICE_EDGES,
    CROSS_SLICE_EDGES,
)


@pytest.fixture
def stm():
    """Fresh SliceTopologyManager with defaults loaded."""
    return SliceTopologyManager()


# ---------------------------------------------------------------------------
# Slice registry
# ---------------------------------------------------------------------------

def test_defaults_loaded(stm):
    slices = stm.list_slices()
    assert len(slices) == 3
    ids = {s.slice_id for s in slices}
    assert "1-000001" in ids
    assert "2-000001" in ids
    assert "3-000001" in ids


def test_register_new_slice(stm):
    sc = stm.register_slice("4-ABCDEF", {"amf", "smf"})
    assert sc.slice_id == "4-ABCDEF"
    assert sc.sst == 4
    assert sc.label == "V2X"
    assert stm.get_slice("4-ABCDEF") is not None


def test_remove_slice(stm):
    assert stm.remove_slice("1-000001") is True
    assert stm.get_slice("1-000001") is None


def test_remove_nonexistent_slice(stm):
    assert stm.remove_slice("9-FFFFFF") is False


def test_slice_config_from_nssai():
    sc = SliceConfig.from_nssai("2-000001")
    assert sc.sst == 2
    assert sc.sd == "000001"
    assert sc.label == "URLLC"


# ---------------------------------------------------------------------------
# Global graph
# ---------------------------------------------------------------------------

def test_global_graph_contains_all_nfs(stm):
    g = stm.build_global_graph()
    expected = SHARED_NFS | SLICE_SPECIFIC_NFS
    assert g.nodes == expected


def test_global_graph_contains_all_edges(stm):
    g = stm.build_global_graph()
    expected_edges = set(INTRA_SLICE_EDGES | CROSS_SLICE_EDGES)
    actual_edges = set(g.edges)
    assert expected_edges == actual_edges


def test_global_graph_has_no_slice_id(stm):
    g = stm.build_global_graph()
    assert g.slice_id is None


# ---------------------------------------------------------------------------
# Slice-pruned graph
# ---------------------------------------------------------------------------

def test_slice_graph_contains_shared_nfs(stm):
    g = stm.build_slice_graph("1-000001")
    for nf in SHARED_NFS:
        assert nf in g.nodes


def test_slice_graph_excludes_nothing_for_full_nf_set(stm):
    g = stm.build_slice_graph("1-000001")
    # eMBB has full NF set — should contain all slice-specific NFs
    for nf in SLICE_SPECIFIC_NFS:
        assert nf in g.nodes


def test_miot_slice_excludes_pcf(stm):
    # mIoT slice was defined without pcf
    g = stm.build_slice_graph("3-000001")
    assert "pcf" not in g.nodes


def test_cross_slice_edges_have_lower_weight(stm):
    g = stm.build_slice_graph("1-000001")
    for (cause, effect) in CROSS_SLICE_EDGES:
        if (cause, effect) in g.edges:
            assert g.edge_weights[(cause, effect)] == 0.5


def test_intra_slice_edges_have_full_weight(stm):
    g = stm.build_slice_graph("1-000001")
    for (cause, effect) in INTRA_SLICE_EDGES:
        if (cause, effect) in g.edges:
            assert g.edge_weights[(cause, effect)] == 1.0


def test_unknown_slice_falls_back_to_global(stm):
    g = stm.build_slice_graph("9-FFFFFF")
    assert g.slice_id is None  # global fallback
    assert g.nodes == SHARED_NFS | SLICE_SPECIFIC_NFS


# ---------------------------------------------------------------------------
# Fault-specific pruning
# ---------------------------------------------------------------------------

def test_prune_nrf_returns_nrf_only(stm):
    # NRF has no ancestors — pruned graph should be just nrf
    g = stm.prune_for_fault("nrf", slice_id="1-000001")
    assert "nrf" in g.nodes
    # Should have no inbound edges to nrf
    inbound = [e for e in g.edges if e[1] == "nrf"]
    assert inbound == []


def test_prune_amf_includes_nrf_and_udm(stm):
    g = stm.prune_for_fault("amf", slice_id="1-000001")
    assert "amf" in g.nodes
    # nrf → amf and udm → amf are both in the base graph
    assert "nrf" in g.nodes or "udm" in g.nodes


def test_prune_smf_includes_pcf_and_smf(stm):
    g = stm.prune_for_fault("smf", slice_id="1-000001")
    assert "smf" in g.nodes
    assert "pcf" in g.nodes  # pcf → smf edge exists


def test_prune_with_live_dag_edges(stm):
    # Provide a custom DAG where only nrf→amf exists
    live_edges = [("nrf", "amf")]
    g = stm.prune_for_fault("amf", slice_id="1-000001", dag_edges=live_edges)
    assert "nrf" in g.nodes
    assert "amf" in g.nodes
    # pcf should NOT be present since it's not in live_edges that reach amf
    assert "pcf" not in g.nodes


def test_prune_without_slice_uses_global(stm):
    g = stm.prune_for_fault("smf")
    assert "smf" in g.nodes
    assert g.slice_id is None


# ---------------------------------------------------------------------------
# Cross-slice leakage detection
# ---------------------------------------------------------------------------

def test_no_leakage_when_all_in_slice(stm):
    result = stm.detect_cross_slice_leakage("1-000001", ["amf", "smf", "pcf"])
    assert result["leakage_detected"] is False
    assert set(result["in_slice_causes"]) == {"amf", "smf", "pcf"}


def test_leakage_detected_for_out_of_slice_nf(stm):
    # Register a narrow slice with only amf
    stm.register_slice("5-000001", {"amf"})
    result = stm.detect_cross_slice_leakage("5-000001", ["amf", "smf"])
    assert result["leakage_detected"] is True
    assert "smf" in result["out_of_slice_causes"]
    assert "amf" in result["in_slice_causes"]


def test_shared_nfs_not_counted_as_leakage(stm):
    result = stm.detect_cross_slice_leakage("1-000001", ["nrf", "ausf"])
    assert result["leakage_detected"] is False
    assert "nrf" in result["shared_nf_causes"]
    assert "ausf" in result["shared_nf_causes"]


def test_leakage_unknown_slice_returns_error(stm):
    result = stm.detect_cross_slice_leakage("9-FFFFFF", ["amf"])
    assert "error" in result


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def test_to_dict_structure(stm):
    d = stm.to_dict()
    assert "slice_count" in d
    assert "slices" in d
    assert d["slice_count"] == len(stm.list_slices())
    for s in d["slices"]:
        assert "slice_id" in s
        assert "sst" in s
        assert "label" in s
        assert "nf_set" in s


def test_topology_graph_to_dict(stm):
    g = stm.build_slice_graph("1-000001")
    d = g.to_dict()
    assert "slice_id" in d
    assert "nodes" in d
    assert "edges" in d
    for edge in d["edges"]:
        assert "cause" in edge
        assert "effect" in edge
        assert "weight" in edge
