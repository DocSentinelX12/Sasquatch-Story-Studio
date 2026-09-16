"""Exact command construction for the official LTX-Video runtime."""
from __future__ import annotations

from pathlib import Path

OFFICIAL_SOURCE = "https://github.com/Lightricks/LTX-Video"
SOURCE_REVISION = "4b2d053057623ddd4d0a1d3e9cd28890e9ef487f"
MODEL_REPOSITORY = "Lightricks/LTX-Video"
MODEL_REVISION = "19560f8b59a58a0431baf39c78cd8a60a86b9c33"
CHECKPOINT_FILENAME = "ltxv-2b-0.9.8-distilled.safetensors"
UPSCALER_FILENAME = "ltxv-spatial-upscaler-0.9.8.safetensors"
CHECKPOINT_SHA256 = "76aa8c4786af752fa6f951947129d5290c3c6c0b2fadcadea6b5e114ae2cad8f"
UPSCALER_SHA256 = "5b076031c6f860db9037a54f3bb819f10bfb5532ea26a6d30062292428a0c208"


def validate_num_frames(num_frames: int) -> None:
    if num_frames < 9 or (num_frames - 1) % 8 != 0:
        raise ValueError("LTX-Video num_frames must be 8N+1 and at least 9")


def build_ltx_video_command(*, python_executable: str, repository: Path, model_path: Path, prompt: str, output_token: str, image_path: str = "{image_path}", num_frames: int = 121, height: int = 704, width: int = 1216, seed: int = 171198) -> tuple[str, ...]:
    validate_num_frames(num_frames)
    if not prompt.strip():
        raise ValueError("prompt is required")
    if not repository.is_absolute() or not model_path.is_absolute():
        raise ValueError("repository and model_path must be absolute paths")
    return (python_executable, "scripts/run_ltx_video.py", "--repository", str(repository), "--model-path", str(model_path), "--prompt", prompt, "--image-path", image_path, "--output", output_token, "--num-frames", str(num_frames), "--height", str(height), "--width", str(width), "--seed", str(seed))
