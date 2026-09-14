from pathlib import Path

import pytest

from studio.data_plane import DataPlane, DataReference


def test_content_reference_and_chunk_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"abcdefghij")
    plane = DataPlane(tmp_path / "state", chunk_size=4)

    reference = plane.reference_for(source)
    plan = plane.plan(reference, source, tmp_path / "destination.bin", transfer_id="transfer-1")

    assert reference.size_bytes == 10
    assert [chunk.size_bytes for chunk in plan.chunks] == [4, 4, 2]
    assert [chunk.index for chunk in plan.chunks] == [0, 1, 2]
    assert all(chunk.digest for chunk in plan.chunks)


def test_transfer_resumes_after_interruption_and_verifies_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "nested" / "destination.bin"
    source.write_bytes(b"0123456789abcdef")
    plane = DataPlane(tmp_path / "state", chunk_size=4)
    reference = plane.reference_for(source)
    plan = plane.plan(reference, source, destination, transfer_id="resume-1")

    with pytest.raises(InterruptedError):
        plane.transfer(plan, interrupt_after_chunks=1)

    result = plane.transfer(plan)
    assert result.verified is True
    assert result.resumed is True
    assert result.completed_chunks == (0, 1, 2, 3)
    assert destination.read_bytes() == source.read_bytes()
    assert source.exists()


def test_corrupt_destination_chunk_is_repaired_from_source(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"abcdefgh")
    plane = DataPlane(tmp_path / "state", chunk_size=4)
    reference = plane.reference_for(source)
    plan = plane.plan(reference, source, destination, transfer_id="repair-1")
    plane.transfer(plan)

    destination.write_bytes(b"XXXXefgh")
    result = plane.transfer(plan)
    assert result.verified is True
    assert destination.read_bytes() == source.read_bytes()


def test_source_mismatch_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    plane = DataPlane(tmp_path / "state", chunk_size=4)
    reference = DataReference("0" * 64, source.stat().st_size)

    with pytest.raises(ValueError, match="source does not match"):
        plane.plan(reference, source, tmp_path / "destination.bin")


def test_retain_never_deletes_creator_history(tmp_path: Path) -> None:
    source = tmp_path / "canonical.asset"
    destination = tmp_path / "production.asset"
    source.write_bytes(b"canonical")
    destination.write_bytes(b"production")
    plane = DataPlane(tmp_path / "state")

    retained = plane.retain(source, destination)
    assert retained == (str(source), str(destination))
    assert source.read_bytes() == b"canonical"
    assert destination.read_bytes() == b"production"
