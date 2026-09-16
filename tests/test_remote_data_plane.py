from pathlib import Path

import pytest

from studio.data_plane import DataPlane, TransferChunk, TransferPlan


def test_remote_receive_resumes_and_verifies_each_chunk(tmp_path: Path) -> None:
    payload = b"remote-artifact-data"
    import hashlib

    reference_digest = hashlib.sha256(payload).hexdigest()
    reference = type("Reference", (), {})
    from studio.data_plane import DataReference

    data_reference = DataReference(reference_digest, len(payload))
    chunks = tuple(
        TransferChunk(index, offset, len(block), hashlib.sha256(block).hexdigest())
        for index, (offset, block) in enumerate(((0, payload[:6]), (6, payload[6:12]), (12, payload[12:])))
    )
    plan = TransferPlan("remote-1", data_reference, "worker://artifact", str(tmp_path / "artifact.bin"), chunks)
    plane = DataPlane(tmp_path / "state", chunk_size=6)

    def fetch(chunk: TransferChunk) -> bytes:
        return payload[chunk.offset:chunk.offset + chunk.size_bytes]

    with pytest.raises(InterruptedError):
        plane.receive_remote(plan, fetch, interrupt_after_chunks=1)

    result = plane.receive_remote(plan, fetch)
    assert result.verified is True
    assert result.resumed is True
    assert (tmp_path / "artifact.bin").read_bytes() == payload
