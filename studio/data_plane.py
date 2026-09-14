"""Portable, checksum-verified data movement for creator-owned artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class DataReference:
    """Stable content identity independent of the machine holding the bytes."""

    digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        if len(self.digest) != 64 or any(c not in "0123456789abcdef" for c in self.digest):
            raise ValueError("data digest must be a lowercase SHA-256 hex digest")
        if self.size_bytes < 0:
            raise ValueError("data size cannot be negative")


@dataclass(frozen=True)
class TransferChunk:
    index: int
    offset: int
    size_bytes: int
    digest: str | None = None


@dataclass(frozen=True)
class TransferPlan:
    transfer_id: str
    reference: DataReference
    source: str
    destination: str
    chunks: tuple[TransferChunk, ...]


@dataclass(frozen=True)
class TransferResult:
    transfer_id: str
    reference: DataReference
    completed_chunks: tuple[int, ...]
    resumed: bool
    verified: bool
    source: str
    destination: str


class DataPlane:
    """Plans and executes resumable local transfers without deleting creator data."""

    def __init__(self, state_root: str | Path, chunk_size: int = 4 * 1024 * 1024):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.root = Path(state_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.root / "transfers"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.chunk_size = chunk_size

    @staticmethod
    def reference_for(path: str | Path, chunk_size: int = 4 * 1024 * 1024) -> DataReference:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as handle:
            while block := handle.read(chunk_size):
                digest.update(block)
                size += len(block)
        return DataReference(digest.hexdigest(), size)

    def plan(self, reference: DataReference, source: str | Path, destination: str | Path, transfer_id: str | None = None) -> TransferPlan:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        actual = self.reference_for(source_path, self.chunk_size)
        if actual != reference:
            raise ValueError("source does not match the supplied content reference")
        transfer_id = transfer_id or uuid.uuid4().hex
        chunks = []
        offset = 0
        with source_path.open("rb") as handle:
            index = 0
            while block := handle.read(self.chunk_size):
                chunks.append(TransferChunk(index, offset, len(block), hashlib.sha256(block).hexdigest()))
                offset += len(block)
                index += 1
        return TransferPlan(transfer_id, reference, str(source_path), str(destination), tuple(chunks))

    def _state_path(self, transfer_id: str) -> Path:
        if not transfer_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in transfer_id):
            raise ValueError("invalid transfer id")
        return self.state_dir / f"{transfer_id}.json"

    def _load_completed(self, transfer_id: str) -> set[int]:
        path = self._state_path(transfer_id)
        if not path.exists():
            return set()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {int(index) for index in payload.get("completed_chunks", [])}

    def _save_completed(self, transfer_id: str, completed: set[int]) -> None:
        target = self._state_path(transfer_id)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps({"completed_chunks": sorted(completed)}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)

    @staticmethod
    def _verify_chunk(handle: BinaryIO, chunk: TransferChunk) -> bool:
        handle.seek(chunk.offset)
        data = handle.read(chunk.size_bytes)
        return len(data) == chunk.size_bytes and (chunk.digest is None or hashlib.sha256(data).hexdigest() == chunk.digest)

    def transfer(self, plan: TransferPlan, interrupt_after_chunks: int | None = None) -> TransferResult:
        source = Path(plan.source)
        destination = Path(plan.destination)
        if not source.is_file():
            raise FileNotFoundError(source)
        if self.reference_for(source, self.chunk_size) != plan.reference:
            raise ValueError("source changed after transfer planning")
        destination.parent.mkdir(parents=True, exist_ok=True)
        completed = self._load_completed(plan.transfer_id)
        resumed = bool(completed)
        mode = "r+b" if destination.exists() else "w+b"
        with source.open("rb") as source_handle, destination.open(mode) as destination_handle:
            if destination.exists() and destination_handle.seek(0, os.SEEK_END) < plan.reference.size_bytes:
                destination_handle.truncate(plan.reference.size_bytes)
            for chunk in plan.chunks:
                if chunk.index in completed:
                    if not self._verify_chunk(destination_handle, chunk):
                        completed.remove(chunk.index)
                    else:
                        continue
                source_handle.seek(chunk.offset)
                data = source_handle.read(chunk.size_bytes)
                if len(data) != chunk.size_bytes or hashlib.sha256(data).hexdigest() != chunk.digest:
                    raise IOError(f"source chunk {chunk.index} failed checksum verification")
                destination_handle.seek(chunk.offset)
                destination_handle.write(data)
                destination_handle.flush()
                destination_handle.seek(chunk.offset)
                if not self._verify_chunk(destination_handle, chunk):
                    raise IOError(f"destination chunk {chunk.index} failed checksum verification")
                completed.add(chunk.index)
                self._save_completed(plan.transfer_id, completed)
                if interrupt_after_chunks is not None and interrupt_after_chunks <= len(completed) and len(completed) < len(plan.chunks):
                    raise InterruptedError("transfer interrupted after requested checkpoint")
        if self.reference_for(destination, self.chunk_size) != plan.reference:
            raise IOError("destination failed final content verification")
        self._save_completed(plan.transfer_id, completed)
        return TransferResult(plan.transfer_id, plan.reference, tuple(sorted(completed)), resumed, True, plan.source, plan.destination)

    def retain(self, *paths: str | Path) -> tuple[str, ...]:
        """Validate and return retained source paths; this API never deletes data."""
        retained = []
        for path in paths:
            candidate = Path(path)
            if not candidate.exists():
                raise FileNotFoundError(candidate)
            retained.append(str(candidate))
        return tuple(retained)
