"""
Tests for causal5g.graph.topology_prior — Claim 1 structural prior.
"""
from causal5g.graph.topology_prior import TopologyPrior, STANDARD_SBI_EDGES


class TestTopologyPrior:
    def test_standard_sbi_edges_loaded(self):
        prior = TopologyPrior()
        assert ("AMF", "SMF") in prior.allowed_nf_type_edges
        assert ("SMF", "UPF") in prior.allowed_nf_type_edges
        assert ("SMF", "PCF") in prior.allowed_nf_type_edges

    def test_pfcp_binding_registered(self):
        prior = TopologyPrior(pfcp_bindings=[("smf-1", "upf-1")])
        assert prior.is_valid_pfcp_edge("smf-1", "upf-1")
        assert not prior.is_valid_pfcp_edge("smf-1", "upf-99")

    def test_instance_edge_registration(self):
        prior = TopologyPrior()
        prior.register_instance_edge("amf-1", "smf-1")
        assert prior.is_valid_sbi_edge("amf-1", "smf-1")

    def test_nf_type_edge_validation(self):
        prior = TopologyPrior()
        nf_type_map = {"amf-1": "AMF", "smf-1": "SMF", "upf-1": "UPF"}
        assert prior.is_valid_sbi_edge("amf-1", "smf-1", nf_type_map)
        assert not prior.is_valid_sbi_edge("upf-1", "amf-1", nf_type_map)

    def test_custom_sbi_edges(self):
        prior = TopologyPrior(custom_sbi_edges=[("NWDAF", "AMF")])
        assert ("NWDAF", "AMF") in prior.allowed_nf_type_edges

    def test_get_allowed_edges_for_node(self):
        prior = TopologyPrior()
        prior.register_instance_edge("amf-1", "smf-1")
        prior.register_instance_edge("amf-1", "pcf-1")
        allowed = prior.get_allowed_edges_for_node("amf-1")
        assert "smf-1" in allowed
        assert "pcf-1" in allowed
