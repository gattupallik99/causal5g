"""
Shared pytest fixtures for Causal5G test suite.
"""
import pytest
import numpy as np

from causal5g.graph.bilevel_dag import BiLevelCausalDAG, NFNode, SliceSubgraph
from causal5g.graph.topology_prior import TopologyPrior
from causal5g.telemetry.sbi_collector import SBICollector, SBICallRecord
from causal5g.telemetry.pfcp_collector import PFCPCollector, PFCPSessionBinding
from causal5g.telemetry.slice_kpi import SliceKPICollector, SliceKPI


@pytest.fixture
def standard_prior():
    """TopologyPrior with standard 3GPP SBI edges and two PFCP bindings."""
    return TopologyPrior(
        pfcp_bindings=[("smf-1", "upf-1"), ("smf-1", "upf-2")]
    )


@pytest.fixture
def two_slice_dag(standard_prior):
    """
    Bi-level DAG with:
      Level 1: AMF, SMF, UPF-1, UPF-2, PCF
      Level 2: slice 1:1 (eMBB) with upf-1, slice 1:2 (URLLC) with upf-2
      Shared: amf-1, smf-1 across both slices
    """
    dag = BiLevelCausalDAG(topology_prior=standard_prior)
    nfs = [
        ("amf-1", "AMF"), ("smf-1", "SMF"),
        ("upf-1", "UPF"), ("upf-2", "UPF"), ("pcf-1", "PCF"),
    ]
    for nf_id, nf_type in nfs:
        dag.add_nf_node(NFNode(nf_id=nf_id, nf_type=nf_type, instance_id=nf_id))

    dag.add_slice_subgraph(SliceSubgraph(
        snssai="1:1",
        nf_nodes=["amf-1", "smf-1", "upf-1", "pcf-1"],
        dedicated_nf_nodes=["upf-1"],
        shared_nf_nodes=["amf-1", "smf-1", "pcf-1"],
    ))
    dag.add_slice_subgraph(SliceSubgraph(
        snssai="1:2",
        nf_nodes=["amf-1", "smf-1", "upf-2", "pcf-1"],
        dedicated_nf_nodes=["upf-2"],
        shared_nf_nodes=["amf-1", "smf-1", "pcf-1"],
    ))
    return dag


@pytest.fixture
def sample_telemetry():
    """300-step random telemetry array for 5 NF metric variables."""
    np.random.seed(42)
    return np.random.randn(300, 5)


@pytest.fixture
def variable_names():
    return ["amf-1", "smf-1", "upf-1", "upf-2", "pcf-1"]


@pytest.fixture
def sbi_collector():
    return SBICollector(window_ms=60_000)


@pytest.fixture
def pfcp_collector():
    return PFCPCollector(window_ms=60_000)


@pytest.fixture
def slice_kpi_collector():
    return SliceKPICollector(snssai_list=["1:1", "1:2", "1:3"])


@pytest.fixture
def sample_sbi_record():
    return SBICallRecord(
        timestamp_ms=1_700_000_000_000,
        producer_nf_id="smf-1",
        consumer_nf_id="amf-1",
        sbi_service="Nsmf_PDUSession_CreateSMContext",
        http_method="POST",
        http_status=201,
        latency_ms=12.5,
        snssai="1:1",
    )


@pytest.fixture
def sample_pfcp_binding():
    return PFCPSessionBinding(
        pdu_session_id="pdu-001",
        supi="imsi-001",
        snssai="1:1",
        smf_id="smf-1",
        upf_id="upf-1",
        seid=100001,
        established_ms=1_700_000_000_000,
    )


@pytest.fixture
def sample_slice_kpi():
    return SliceKPI(
        snssai="1:1",
        timestamp_ms=1_700_000_000_000,
        window_ms=60_000,
        pdu_session_establishment_success_rate=0.98,
        user_plane_latency_ms=4.2,
        packet_loss_ratio=0.001,
        active_pdu_sessions=150,
    )
