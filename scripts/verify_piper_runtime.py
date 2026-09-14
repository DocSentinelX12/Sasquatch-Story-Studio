#!/usr/bin/env python3
"""Install Piper and synthesize real speech with a real downloaded voice model."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

from studio.artifact_bridge import ArtifactCommitter, ArtifactLineageStore
from studio.artifacts import ContentAddressedStore
from studio.production import ProductionResponse

VOICE = "en_US-lessac-medium"
MODEL_SHA256 = "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"
MODEL_CARD_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/MODEL_CARD"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, timeout=900)


def main() -> int:
    install = run(sys.executable, "-m", "pip", "install", "piper-tts==1.8.0")
    if install.returncode != 0:
        raise RuntimeError(f"Piper installation failed: {(install.stderr or install.stdout).strip()}")

    data_dir = Path("piper-runtime-data")
    data_dir.mkdir(parents=True, exist_ok=True)
    download = run(
        sys.executable,
        "-m",
        "piper.download_voices",
        VOICE,
        "--data-dir",
        str(data_dir),
    )
    if download.returncode != 0:
        raise RuntimeError(f"Piper voice download failed: {(download.stderr or download.stdout).strip()}")

    model = data_dir / f"{VOICE}.onnx"
    config = data_dir / f"{VOICE}.onnx.json"
    model_card = data_dir / "MODEL_CARD"
    if not model.is_file() or model.stat().st_size == 0:
        raise RuntimeError("Piper voice model was not downloaded as a real non-empty file")
    if not config.is_file() or config.stat().st_size == 0:
        raise RuntimeError("Piper voice configuration was not downloaded")

    actual_model_hash = sha256_file(model)
    if actual_model_hash != MODEL_SHA256:
        raise RuntimeError(
            f"Piper voice checksum mismatch: expected {MODEL_SHA256}, got {actual_model_hash}"
        )

    model_card.write_bytes(urlopen(MODEL_CARD_URL, timeout=30).read())
    if model_card.stat().st_size == 0:
        raise RuntimeError("Piper voice MODEL_CARD download was empty")

    output = Path("piper-runtime.wav")
    synthesis = run(
        sys.executable,
        "-m",
        "piper",
        "-m",
        VOICE,
        "--data-dir",
        str(data_dir),
        "-f",
        str(output),
        "--",
        "This is a real Sasquatch Story Studio voice runtime verification.",
    )
    if synthesis.returncode != 0:
        raise RuntimeError(f"Piper synthesis failed: {(synthesis.stderr or synthesis.stdout).strip()}")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Piper exited successfully but produced no WAV output")

    source_hash = sha256_file(Path(__file__))
    output_hash = sha256_file(output)
    model_card_text = model_card.read_text(errors="replace")
    response = ProductionResponse(
        "piper",
        (str(output),),
        {
            "execution": "subprocess",
            "engine_id": "piper",
            "engine_version": "1.8.0",
            "license": "GPL-3.0-or-later; voice model license requires review",
            "quality_tier": "production_tts",
            "commercial_use_review_required": True,
            "canonical_source_hash": source_hash,
            "output_sha256": output_hash,
            "model_sha256": actual_model_hash,
            "model_card": model_card_text,
            "exit_code": synthesis.returncode,
        },
    )
    cas = ContentAddressedStore("piper-runtime-artifacts")
    lineage = ArtifactLineageStore("piper-runtime-artifacts/lineage.sqlite3")
    committed = ArtifactCommitter(cas, lineage).commit(
        response, stage="dialogue", source_hash=source_hash
    )
    if len(committed) != 1 or not committed[0].startswith("sha256:"):
        raise RuntimeError("real Piper output was not committed to the content-addressed store")

    evidence = {
        "engine_id": "piper",
        "engine_version": "1.8.0",
        "executable": f"{sys.executable} -m piper",
        "version_observation": install.stdout.strip() or install.stderr.strip(),
        "checkpoint_path": str(model),
        "checkpoint_sha256": actual_model_hash,
        "license_source": "https://github.com/OHF-Voice/piper1-gpl",
        "license_evidence": "Piper is GPL-3.0-or-later; this voice's MODEL_CARD is preserved and commercial use remains review-required.",
        "runtime_output_sha256": output_hash,
        "canonical_source_sha256": source_hash,
        "artifact_address": committed[0],
        "artifact_lineage_stage": "dialogue",
        "voice": VOICE,
        "voice_model_card_sha256": sha256_file(model_card),
        "voice_model_card_source": MODEL_CARD_URL,
        "commercial_use_review_required": True,
        "output_bytes": output.stat().st_size,
    }
    Path("piper-runtime-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    shutil.copytree("piper-runtime-artifacts", "piper-runtime-artifacts-evidence", dirs_exist_ok=True)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
