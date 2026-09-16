"""Exact runtime contract for the official LTX-2.5 distilled pipeline."""
from __future__ import annotations

from pathlib import Path

OFFICIAL_SOURCE = "https://github.com/Lightricks/LTX-2"
SOURCE_REVISION = "598ab41247a77dbfe29b5186e915bcf4f9040ec7"
MODEL_REPOSITORY = "Lightricks/LTX-2.5"
MODEL_REVISION: str | None = None
LICENSE_NAME = "LTX-2.x Community License Agreement"
LICENSE_SOURCE = "https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x"
TRANSFORMER_FILENAME = "ltx-2.5-22b-distilled-transformer-bf16.safetensors"
TEXT_ENCODER_FILENAME = "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"
VIDEO_VAE_FILENAME = "ltx-2.5-video-vae-bf16.safetensors"
AUDIO_VAE_FILENAME = "ltx-2.5-audio-vae-bf16.safetensors"
SPATIAL_UPSAMPLER_FILENAME = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
DURATION_HEAD_FILENAME = "ltx-2.5-duration-head-bf16.safetensors"
DEFAULT_NUM_FRAMES = 121
DEFAULT_HEIGHT = 544
DEFAULT_WIDTH = 960
DEFAULT_FRAME_RATE = 24.0
DEFAULT_SEED = 42


def required_model_paths(model_root: Path) -> dict[str, Path]:
    root = model_root.expanduser().resolve()
    paths = {
        "transformer": root / "diffusion_models" / TRANSFORMER_FILENAME,
        "text_encoder": root / "text_encoders" / TEXT_ENCODER_FILENAME,
        "video_vae": root / "vae" / VIDEO_VAE_FILENAME,
        "audio_vae": root / "vae" / AUDIO_VAE_FILENAME,
        "spatial_upsampler": root / "latent_upscale_models" / SPATIAL_UPSAMPLER_FILENAME,
        "duration_head": root / "model_patches" / DURATION_HEAD_FILENAME,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing LTX-2.5 model components: " + ", ".join(missing))
    return paths


def validate_dimensions(*, height: int, width: int, num_frames: int) -> None:
    if height < 32 or width < 32 or height % 32 or width % 32:
        raise ValueError("LTX-2.5 height and width must be positive multiples of 32")
    if num_frames < 9 or (num_frames - 1) % 8:
        raise ValueError("LTX-2.5 num_frames must be 8N+1 and at least 9")


def build_ltx25_command(
    *,
    python_executable: str,
    studio_root: Path,
    source_repository: Path,
    model_root: Path,
    prompt: str,
    output_token: str,
    image_path: str = "{image_path}",
    num_frames: int = DEFAULT_NUM_FRAMES,
    height: int = DEFAULT_HEIGHT,
    width: int = DEFAULT_WIDTH,
    frame_rate: float = DEFAULT_FRAME_RATE,
    seed: int = DEFAULT_SEED,
) -> tuple[str, ...]:
    validate_dimensions(height=height, width=width, num_frames=num_frames)
    if not prompt.strip():
        raise ValueError("prompt is required")
    if not source_repository.is_absolute() or not model_root.is_absolute() or not studio_root.is_absolute():
        raise ValueError("studio_root, source_repository, and model_root must be absolute paths")
    bridge = studio_root / "scripts" / "run_ltx25.py"
    if not bridge.is_file():
        raise FileNotFoundError(f"LTX-2.5 bridge does not exist: {bridge}")
    return (
        python_executable,
        str(bridge),
        "--repository",
        str(source_repository),
        "--model-root",
        str(model_root),
        "--prompt",
        prompt,
        "--image-path",
        image_path,
        "--output",
        output_token,
        "--num-frames",
        str(num_frames),
        "--height",
        str(height),
        "--width",
        str(width),
        "--frame-rate",
        str(frame_rate),
        "--seed",
        str(seed),
    )
