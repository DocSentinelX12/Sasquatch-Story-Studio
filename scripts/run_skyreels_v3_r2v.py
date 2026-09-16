#!/usr/bin/env python3
"""Run Skywork's official SkyReels V3 R2V pipeline with an explicit output path."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--ref-imgs", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--resolution", choices=("480P", "540P", "720P"), default="720P")
    parser.add_argument("--offload", action="store_true")
    parser.add_argument("--low-vram", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = Path(args.repository).expanduser().resolve()
    model_path = Path(args.model_path).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not repository.is_dir():
        raise RuntimeError(f"SkyReels source repository does not exist: {repository}")
    if not (repository / "skyreels_v3" / "pipelines" / "reference_to_video_pipeline.py").is_file():
        raise RuntimeError("SkyReels source repository is missing the official R2V pipeline")
    if not model_path.is_dir():
        raise RuntimeError(f"SkyReels model directory does not exist: {model_path}")
    if not args.prompt.strip():
        raise ValueError("SkyReels prompt is required")
    references = [Path(item).expanduser().resolve() for item in args.ref_imgs.split(",") if item.strip()]
    if not 1 <= len(references) <= 4:
        raise ValueError("SkyReels requires 1 to 4 reference images")
    for reference in references:
        if not reference.is_file() or reference.stat().st_size == 0:
            raise RuntimeError(f"SkyReels reference image is missing or empty: {reference}")
    if args.duration < 1:
        raise ValueError("SkyReels duration must be positive")

    sys.path.insert(0, str(repository))
    import imageio
    import torch
    from diffusers.utils import load_image
    from skyreels_v3.pipelines import ReferenceToVideoPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("SkyReels V3 R2V requires a CUDA GPU for real inference")

    pipeline = ReferenceToVideoPipeline(
        model_path=str(model_path),
        use_usp=False,
        offload=args.offload,
        low_vram=args.low_vram,
    )
    ref_images = [load_image(str(reference)) for reference in references]
    video = pipeline.generate_video(
        ref_images,
        args.prompt,
        args.duration,
        args.seed,
        resolution=args.resolution,
    )
    if not video:
        raise RuntimeError("SkyReels R2V returned no video frames")
    output.parent.mkdir(parents=True, exist_ok=True)
    imageio.mimwrite(
        str(output),
        video,
        fps=24,
        quality=8,
        output_params=["-loglevel", "error"],
    )
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("SkyReels R2V completed without a non-empty video output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
