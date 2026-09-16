"""Exact local execution contract for SkyReels V3 Reference-to-Video 14B."""
from __future__ import annotations

from pathlib import Path

ENGINE_ID = "skyreels-v3-r2v-14b"
OFFICIAL_REPOSITORY = "https://github.com/SkyworkAI/SkyReels-V3"
MODEL_REPOSITORY = "https://huggingface.co/Skywork/SkyReels-V3-R2V-14B"
OFFICIAL_SOURCE_REVISION = "28c771e8456341be6a213e3d1133ed1fd19bf75d"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "720P"
MAX_REFERENCE_IMAGES = 4


def build_skyreels_r2v_command(
    *,
    python_executable: str,
    repository: Path,
    model_path: Path,
    prompt: str,
    reference_images: tuple[str | Path, ...],
    output_token: str,
    seed: int = 42,
    duration: int = DEFAULT_DURATION,
    resolution: str = DEFAULT_RESOLUTION,
    offload: bool = True,
    low_vram: bool = False,
) -> tuple[str, ...]:
    """Build the local studio bridge command around Skywork's R2V pipeline.

    The bridge imports and executes the official SkyReels V3
    ``ReferenceToVideoPipeline`` from the pinned source tree. It exists only to
    give the studio an explicit output path because the upstream convenience
    script creates timestamped output names internally.
    """
    repository = repository.expanduser().resolve()
    model_path = model_path.expanduser().resolve()
    if not str(python_executable).strip():
        raise ValueError("Python executable is required")
    if not prompt.strip():
        raise ValueError("SkyReels prompt is required")
    if not output_token:
        raise ValueError("SkyReels output token is required")
    if not 1 <= len(reference_images) <= MAX_REFERENCE_IMAGES:
        raise ValueError("SkyReels requires 1 to 4 reference images")
    if duration < 1:
        raise ValueError("SkyReels duration must be positive")
    if resolution not in {"480P", "540P", "720P"}:
        raise ValueError("SkyReels resolution must be 480P, 540P, or 720P")
    if low_vram and offload:
        raise ValueError("SkyReels low_vram and offload are mutually exclusive in the studio bridge")

    if len(reference_images) == 1 and str(reference_images[0]) == "{reference_images}":
        refs = "{reference_images}"
    else:
        refs = ",".join(str(Path(path).expanduser().resolve()) for path in reference_images)

    command = [
        python_executable,
        "scripts/run_skyreels_v3_r2v.py",
        "--repository",
        str(repository),
        "--model-path",
        str(model_path),
        "--ref-imgs",
        refs,
        "--prompt",
        prompt,
        "--output",
        output_token,
        "--seed",
        str(seed),
        "--duration",
        str(duration),
        "--resolution",
        resolution,
    ]
    if offload:
        command.append("--offload")
    if low_vram:
        command.append("--low-vram")
    return tuple(command)
