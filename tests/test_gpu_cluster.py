import pytest

from studio.gpu_cluster import ALL_NODES, SET_A, SET_B, GpuNodeSet, node_spec, validate_registered_nodes


def test_fabric_has_two_sets_of_six_distinct_nodes():
    assert tuple(node.node_id for node in SET_A) == ("A", "B", "C", "D", "E", "F")
    assert tuple(node.node_id for node in SET_B) == ("G", "H", "I", "J", "K", "L")
    assert len(ALL_NODES) == 12
    assert len({node.node_id for node in ALL_NODES}) == 12
    assert all(node.node_set is GpuNodeSet.A for node in SET_A)
    assert all(node.node_set is GpuNodeSet.B for node in SET_B)


def test_unknown_node_is_rejected():
    with pytest.raises(KeyError):
        node_spec("M")


def test_partial_registration_does_not_fabricate_nodes():
    validate_registered_nodes({"A", "F", "G", "L"})


def test_unknown_registered_node_is_rejected():
    with pytest.raises(ValueError, match="unrecognized GPU fabric nodes"):
        validate_registered_nodes({"A", "M"})
