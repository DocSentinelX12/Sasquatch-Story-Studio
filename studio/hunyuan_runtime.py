"""Exact local execution contract for HunyuanVideo-1.5 source inference."""
from __future__ import annotations

from pathlib import Path

ENGINE_ID = "hunyuanvideo-1.5"
OFFICIAL_REPOSITORY = "https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5"
DEFAULT_RESOLUTION = "480p"
DEFAULT_FRAMES = 9
DEFAULT_INFERENCE_STEPS = 50


def build_hunyuan_command(
    *,
    torchrun_executable: str,
    repository: Path,
    model_path: Path,
    prompt: str,
    image_path: str | Path | None,
    output_token: str,
    seed: int,
    num_inference_steps: int = DEFAULT_INFERENCE_STEPS,
    video_length: int = DEFAULT_FRAMES,
) -> tuple[str, ...]:
    """Build the official source-code inference command without inventing flags.

    The default configuration targets the documented 480p base model at 50
    inference steps. A reference image switches the upstream generator into I2V
    mode. The command remains fully local and does not enable prompt rewriting or
    any hosted service.
    """
    repository = repository.expanduser().resolve()
    model_path = model_path.expanduser().resolve()
    if not repository.is_dir():
        raise ValueError(f"Hunyuan repository does not exist: {repository}")
    if not (repository / "generate.py").is_file():
        raise ValueError(f"Hunyuan generator is missing: {repository / 'generate.py'}")
    if not model_path.exists():
        raise ValueError(f"Hunyuan model path does not exist: {model_path}")
    if not prompt.strip():
        raise ValueError("Hunyuan prompt is required")
    if not output_token:
        raise ValueError("Hunyuan output token is required")
    if num_inference_steps < 1:
        raise ValueError("num_inference_steps must be positive")
    if video_length < 1:
        raise ValueError("video_length must be positive")

    image_value = "none" if image_path is None else str(Path(image_path).expanduser().resolve())
    return (
        torchrun_executable,
        "--nproc_per_node=1",
        "generate.py",
        "--prompt",
        prompt,
        "--image_path",
        image_value,
        "--resolution",
        DEFAULT_RESOLUTION,
        "--aspect_ratio",
        "16:9",
        "--seed",
        str(seed),
        "--num_inference_steps",
        str(num_inference_steps),
        "--video_length",
        str(video_length),
        "--sr",
        "false",
        "--rewrite",
        "false",
        "--offloading",
        "true",
        "--output_path",
        output_token,
        "--model_path",
        str(model_path),
    )
