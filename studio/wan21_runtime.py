"""Wan2.1 runtime contract for the Sasquatch Story Studio."""
from __future__ import annotations

from pathlib import Path

ENGINE_ID = "wan2.1"
OFFICIAL_REPOSITORY = "https://github.com/Wan-Video/Wan2.1"
OFFICIAL_SOURCE_REVISION = "9737cba9c1c3c4d04b33fcad41c111989865d315"
MODEL_REPOSITORY = "Wan-AI/Wan2.1-T2V-1.3B"
TASK = "t2v-1.3B"


def build_wan21_command(
    *,
    python_executable: str,
    repository: Path,
    model_path: Path,
    prompt: str,
    output_token: str,
    size: str = "832*480",
    frame_num: int = 81,
    base_seed: int = 42,
) -> tuple[str, ...]:
    """Build the official Wan2.1 T2V invocation with Studio request tokens."""
    if frame_num < 5 or (frame_num - 1) % 4 != 0:
        raise ValueError("Wan2.1 frame_num must be 4N+1")
    if not prompt.strip() and prompt != "{prompt}":
        raise ValueError("prompt is required")
    if not output_token:
        raise ValueError("output token is required")
    return (
        python_executable,
        "generate.py",
        "--task", TASK,
        "--size", size,
        "--ckpt_dir", str(model_path.expanduser()),
        "--offload_model", "True",
        "--t5_cpu",
        "--frame_num", str(frame_num),
        "--base_seed", str(base_seed),
        "--prompt", prompt,
        "--save_file", output_token,
    )
