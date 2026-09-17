import hashlib

import pytest

from studio.gpu_topology import parse_nvidia_smi_topology


TOPOLOGY = """        GPU0 GPU1 GPU2 mlx5_0 CPU Affinity NUMA Affinity
GPU0      X  NV4  SYS  PIX   0-31        0
GPU1    NV4    X  SYS  NODE  0-31        0
GPU2    SYS  SYS    X  NODE  32-63       1
mlx5_0   PIX  NODE NODE   X
"""


def test_topology_parser_preserves_gpu_relationships_affinity_and_nic_locality():
    evidence = parse_nvidia_smi_topology(
        TOPOLOGY,
        {0: "GPU-A", 1: "GPU-B", 2: "GPU-C"},
    )

    assert evidence.gpu_uuids == ("GPU-A", "GPU-B", "GPU-C")
    assert evidence.relationship("GPU-A", "GPU-B") == "NV4"
    assert evidence.relationship("GPU-A", "GPU-C") == "SYS"
    assert evidence.same_nvlink_domain(("GPU-A", "GPU-B"))
    assert not evidence.same_nvlink_domain(("GPU-A", "GPU-C"))
    assert evidence.cpu_affinity == (
        ("GPU-A", "0-31"),
        ("GPU-B", "0-31"),
        ("GPU-C", "32-63"),
    )
    assert evidence.nic_paths == (
        ("GPU-A", "mlx5_0", "PIX"),
        ("GPU-B", "mlx5_0", "NODE"),
        ("GPU-C", "mlx5_0", "NODE"),
    )
    assert evidence.raw_text_sha256 == hashlib.sha256(TOPOLOGY.encode()).hexdigest()


def test_topology_parser_fails_closed_when_a_gpu_row_is_missing():
    with pytest.raises(ValueError, match="every observed GPU row"):
        parse_nvidia_smi_topology(
            """        GPU0 GPU1 CPU Affinity NUMA Affinity
GPU0      X  NV4  0-31        0
""",
            {0: "GPU-A", 1: "GPU-B"},
        )
