"""Declarative two-set, six-node GPU fabric contract.

This describes the intended 12-node fabric without fabricating hardware. A node
becomes schedulable only after its authenticated worker registration supplies
real GPU evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GpuNodeSet(StrEnum):
    A = "set_a"
    B = "set_b"


@dataclass(frozen=True)
class GpuNodeSpec:
    node_id: str
    node_set: GpuNodeSet
    ordinal: int

    def __post_init__(self) -> None:
        if self.node_id != self.node_id.strip() or not self.node_id:
            raise ValueError("node_id is required")
        if not 1 <= self.ordinal <= 6:
            raise ValueError("node ordinal must be between 1 and 6")
        expected_set = GpuNodeSet.A if self.node_id[0] <= "F" else GpuNodeSet.B
        if self.node_set is not expected_set:
            raise ValueError("node ID does not belong to the declared node set")


SET_A = tuple(GpuNodeSpec(chr(ord("A") + i), GpuNodeSet.A, i + 1) for i in range(6))
SET_B = tuple(GpuNodeSpec(chr(ord("G") + i), GpuNodeSet.B, i + 1) for i in range(6))
ALL_NODES = SET_A + SET_B


def node_spec(node_id: str) -> GpuNodeSpec:
    for node in ALL_NODES:
        if node.node_id == node_id:
            return node
    raise KeyError(f"unknown GPU fabric node: {node_id}")


def validate_registered_nodes(registered_node_ids: set[str]) -> None:
    """Reject unknown identities; missing nodes remain unscheduled."""
    unknown = registered_node_ids.difference(node.node_id for node in ALL_NODES)
    if unknown:
        raise ValueError(f"unrecognized GPU fabric nodes: {sorted(unknown)}")
