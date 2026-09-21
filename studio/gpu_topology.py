"""Structured NVIDIA GPU topology evidence for truthful placement decisions.

The parser only turns observed ``nvidia-smi topo -m`` text into explicit
relationships. Unsupported or ambiguous topology is represented as unknown,
not as an inferred fast path.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GpuTopologyEvidence:
    gpu_uuids: tuple[str, ...]
    gpu_matrix: tuple[tuple[str, ...], ...]
    cpu_affinity: tuple[tuple[str, str], ...]
    nic_paths: tuple[tuple[str, str, str], ...]
    raw_text_sha256: str

    def __post_init__(self) -> None:
        if len(set(self.gpu_uuids)) != len(self.gpu_uuids):
            raise ValueError("topology GPU UUIDs must be unique")
        if len(self.gpu_matrix) != len(self.gpu_uuids):
            raise ValueError("topology matrix must have one row per GPU")
        if any(len(row) != len(self.gpu_uuids) for row in self.gpu_matrix):
            raise ValueError("topology matrix must be square")
        if len(self.raw_text_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.raw_text_sha256):
            raise ValueError("topology text digest must be SHA-256")

    def relationship(self, left: str, right: str) -> str | None:
        try:
            i = self.gpu_uuids.index(left)
            j = self.gpu_uuids.index(right)
        except ValueError:
            return None
        return self.gpu_matrix[i][j]

def topology_digest(evidence: GpuTopologyEvidence) -> str:
    """Return the canonical digest for structured GPU topology evidence."""
    payload = {
        "gpu_uuids": list(evidence.gpu_uuids),
        "gpu_matrix": [list(row) for row in evidence.gpu_matrix],
        "cpu_affinity": [list(item) for item in evidence.cpu_affinity],
        "nic_paths": [list(item) for item in evidence.nic_paths],
        "raw_text_sha256": evidence.raw_text_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


    def same_nvlink_domain(self, gpu_uuids: tuple[str, ...]) -> bool:
        if not gpu_uuids:
            return False
        if any(uuid not in self.gpu_uuids for uuid in gpu_uuids):
            return False
        for i, left in enumerate(gpu_uuids):
            for right in gpu_uuids[i + 1 :]:
                relation = self.relationship(left, right)
                if relation is None or not re.fullmatch(r"NV\d+", relation):
                    return False
        return True


def parse_nvidia_smi_topology(output: str, gpu_uuids_by_index: dict[int, str]) -> GpuTopologyEvidence:
    """Parse the GPU, NIC, CPU-affinity, and NUMA columns of ``nvidia-smi topo -m``.

    Header tokens are used only to identify the GPU and NIC column names.
    Row offsets are derived from those column counts because ``CPU Affinity``
    and ``NUMA Affinity`` are multi-token labels while the data rows are fixed
    columns. Unknown or incomplete rows fail closed.
    """
    if not output.strip():
        raise ValueError("topology output is empty")
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    header_index = next((i for i, line in enumerate(lines) if re.search(r"GPU\d+", line) and "CPU Affinity" in line), None)
    if header_index is None:
        raise ValueError("nvidia-smi topology header was not found")
    header = lines[header_index].split()
    gpu_tokens = [token for token in header if re.fullmatch(r"GPU\d+", token)]
    if not gpu_tokens:
        raise ValueError("nvidia-smi topology did not expose GPU columns")
    indices = [int(token[3:]) for token in gpu_tokens]
    if any(index not in gpu_uuids_by_index for index in indices):
        raise ValueError("topology references a GPU absent from the observed inventory")

    try:
        cpu_header_index = header.index("CPU")
        if header[cpu_header_index + 1] != "Affinity":
            raise ValueError
    except (ValueError, IndexError):
        raise ValueError("nvidia-smi topology CPU affinity columns were not found") from None

    nic_columns = tuple(header[len(gpu_tokens) : cpu_header_index])
    nic_start = 1 + len(gpu_tokens)
    cpu_value_index = nic_start + len(nic_columns)
    matrix_rows: list[tuple[int, tuple[str, ...]]] = []
    cpu_affinity: list[tuple[str, str]] = []
    nic_paths: list[tuple[str, str, str]] = []
    for line in lines[header_index + 1 :]:
        fields = line.split()
        if not fields or not re.fullmatch(r"GPU\d+", fields[0]):
            continue
        row_index = int(fields[0][3:])
        if row_index not in indices:
            continue
        required_fields = cpu_value_index + 1
        if len(fields) < required_fields:
            raise ValueError("nvidia-smi topology GPU row is incomplete")
        matrix_values = tuple(fields[1 : 1 + len(gpu_tokens)])
        if len(matrix_values) != len(gpu_tokens):
            raise ValueError("nvidia-smi topology GPU matrix row is incomplete")
        matrix_rows.append((row_index, matrix_values))
        cpu_value = fields[cpu_value_index]
        cpu_affinity.append((gpu_uuids_by_index[row_index], cpu_value))
        for offset, column in enumerate(nic_columns, start=nic_start):
            nic_value = fields[offset]
            nic_paths.append((gpu_uuids_by_index[row_index], column, nic_value))

    if len(matrix_rows) != len(indices):
        raise ValueError("nvidia-smi topology did not expose every observed GPU row")
    if len({row_index for row_index, _ in matrix_rows}) != len(indices):
        raise ValueError("nvidia-smi topology contains duplicate GPU rows")
    matrix_rows.sort(key=lambda item: indices.index(item[0]))
    matrix = tuple(row for _, row in matrix_rows)
    uuids = tuple(gpu_uuids_by_index[index] for index in indices)
    return GpuTopologyEvidence(
        gpu_uuids=uuids,
        gpu_matrix=matrix,
        cpu_affinity=tuple(cpu_affinity),
        nic_paths=tuple(nic_paths),
        raw_text_sha256=hashlib.sha256(output.encode("utf-8")).hexdigest(),
    )
