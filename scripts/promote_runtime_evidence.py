#!/usr/bin/env python3
"""Promote externally observed runtime evidence into the creator-owned registry.

This script never verifies an engine by itself. It only accepts a complete evidence
record produced by an actual runtime verification procedure and persists it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio.engine_registry import EngineVerificationRecord, SQLiteEngineVerificationStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("registry", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.evidence.read_text())
    required = {
        "engine_id",
        "engine_version",
        "executable",
        "version_observation",
        "checkpoint_path",
        "checkpoint_sha256",
        "license_source",
        "license_evidence",
        "runtime_output_sha256",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"runtime evidence is incomplete: {', '.join(missing)}")
    if "recorded_at" not in payload:
        raise ValueError("runtime evidence must contain recorded_at from the real observation time")

    record = EngineVerificationRecord(
        engine_id=payload["engine_id"],
        engine_version=payload["engine_version"],
        executable=payload["executable"],
        version_observation=payload["version_observation"],
        checkpoint_path=payload["checkpoint_path"],
        checkpoint_sha256=payload["checkpoint_sha256"],
        license_source=payload["license_source"],
        license_evidence=payload["license_evidence"],
        runtime_output_sha256=payload["runtime_output_sha256"],
        recorded_at=int(payload["recorded_at"]),
        source_revision=payload.get("source_revision"),
    )
    store = SQLiteEngineVerificationStore(args.registry)
    store.save(record)
    print(json.dumps(record.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
