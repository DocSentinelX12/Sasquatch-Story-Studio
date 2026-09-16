"""Exact local execution contract for CogVideoX1.5-5B-I2V."""
from __future__ import annotations

from pathlib import Path

ENGINE_ID = "cogvideox1.5-5b-i2v"
OFFICIAL_REPOSITORY = "https://github.com/zai-org/CogVideo"
MODEL_REPOSITORY = "https://huggingface.co/zai-org/CogVideoX1.5-5B-I2V"
MODEL_REPO_ID = "zai-org/CogVideoX1.5-5B-I2V"
OFFICIAL_SOURCE_REVISION = "7a1af7154511e0ce4e4be8d62faa8c5e5a3532d2"
MODEL_REVISION = "e724b279e89c204de20b66d8c09317a5d0d1b6f6"
DEFAULT_FRAMES = 81
DEFAULT_STEPS = 50
DEFAULT_GUIDANCE = 6.0
DEFAULT_FPS = 16


def build_cogvideox15_i2v_command(
    *,
    python_executable: str,
    repository: Path,
    model_path: Path,
    prompt: str,
    image_path: str | Path,
    output_token: str,
    seed: int = 42,
    num_frames: int = DEFAULT_FRAMES,
    num_inference_steps: int = DEFAULT_STEPS,
    guidance_scale: float = DEFAULT_GUIDANCE,
    fps: int = DEFAULT_FPS,
    sequential_cpu_offload: bool = True,
) -> tuple[str, ...]:
    """Build the local studio bridge command around the official Diffusers pipeline."""
    repository = repository.expanduser().resolve()
    model_path = model_path.expanduser().resolve()
    image_path_value = str(image_path) if str(image_path) == "{image_path}" else str(Path(image_path).expanduser().resolve())
    if not str(python_executable).strip():
        raise ValueError("Python executable is required")
    if not prompt.strip():
        raise ValueError("CogVideoX prompt is required")
    if not output_token:
        raise ValueError("CogVideoX output token is required")
    if num_frames < 1 or (num_frames - 1) % 8 != 0:
        raise ValueError("CogVideoX1.5 I2V frame count must be 8N+1")
    if num_inference_steps < 1:
        raise ValueError("CogVideoX inference steps must be positive")
    if guidance_scale <= 0:
        raise ValueError("CogVideoX guidance scale must be positive")
    if fps < 1:
        raise ValueError("CogVideoX FPS must be positive")

    command = [
        python_executable,
        "scripts/run_cogvideox15_i2v.py",
        "--repository", str(repository),
        "--model-path", str(model_path),
        "--image", image_path_value,
        "--prompt", prompt,
        "--output", output_token,
        "--seed", str(seed),
        "--num-frames", str(num_frames),
        "--num-inference-steps", str(num_inference_steps),
        "--guidance-scale", str(guidance_scale),
        "--fps", str(fps),
    ]
    if sequential_cpu_offload:
        command.append("--sequential-cpu-offload")
    return tuple(command)
