"""
Tests for causal5g.graph.bilevel_dag — Claim 1 bi-level DAG.
"""
import pytest
from causal5g.graph.bilevel_dag import BiLevelCausalDAG, NFNode, SliceSubgraph


class TestNFNode:
    def test_nf_node_creation(self):
        node = NFNode(nf_id="amf-1", nf_type="AMF", instance_id="amf-1")
        assert node.nf_id == "amf-1"
        assert node.nf_type == "AMF"
        assert len(node.shared_across_slices) == 0

    def test_nf_types(self):
        for nf_type in ["AMF", "SMF", "UPF", "PCF", "NRF", "AUSF", "UDM"]:
            node = NFNode(nf_id=f"{nf_type.lower()}-1",
                          nf_type=nf_type, instance_id=f"{nf_type.lower()}-1")
            assert node.nf_type == nf_type


class TestBiLevelCausalDAG:
    def test_add_nf_node(self, two_slice_dag):
        assert "amf-1" in two_slice_dag.nf_nodes
        assert "smf-1" in two_slice_dag.nf_nodes
        assert two_slice_dag.level1_graph.number_of_nodes() == 5

    def test_slice_subgraph_registration(self, two_slice_dag):
        assert "1:1" in two_slice_dag.level2_subgraphs
        assert "1:2" in two_slice_dag.level2_subgraphs

    def test_shared_nf_nodes(self, two_slice_dag):
        """amf-1, smf-1, pcf-1 are shared across both slices."""
        shared = two_slice_dag.get_shared_nf_nodes()
        assert "amf-1" in shared
        assert "smf-1" in shared
        assert "pcf-1" in shared

    def test_dedicated_nf_nodes_not_shared(self, two_slice_dag):
        """upf-1 is dedicated to slice 1:1, upf-2 to slice 1:2."""
        shared = two_slice_dag.get_shared_nf_nodes()
        assert "upf-1" not in shared
        assert "upf-2" not in shared

    def test_slice_subgraph_view(self, two_slice_dag):
        view = two_slice_dag.get_slice_subgraph_view("1:1")
        assert "amf-1" in view.nodes()
        assert "upf-1" in view.nodes()
        assert "upf-2" not in view.nodes()

    def test_invalid_snssai_raises(self, two_slice_dag):
        with pytest.raises(KeyError):
            two_slice_dag.get_slice_subgraph_view("9:99")

    def test_sbi_edge_respects_topology_prior(self, two_slice_dag):
        """Edges violating topology prior should raise ValueError."""
        with pytest.raises(ValueError):
            # UPF -> AMF is not a valid SBI edge
            two_slice_dag.add_sbi_edge("upf-1", "amf-1", "invalid_service")

    def test_valid_sbi_edge_added(self, two_slice_dag, standard_prior):
        """AMF -> SMF is a valid 3GPP SBI edge."""
        standard_prior.register_instance_edge("amf-1", "smf-1")
        two_slice_dag.add_sbi_edge("amf-1", "smf-1",
                                   "Namf_Communication_N1N2MessageTransfer",
                                   weight=0.75)
        assert two_slice_dag.level1_graph.has_edge("amf-1", "smf-1")
