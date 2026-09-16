#!/usr/bin/env python3
"""Execute the official LTX-2.5 distilled pipeline with local, pinned inputs."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STUDIO_ROOT))

from studio.ltx25_runtime import required_model_paths, validate_dimensions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image-path", default="none")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-frames", type=int, default=121)
    parser.add_argument("--height", type=int, default=544)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--frame-rate", type=float, default=24.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    repository = args.repository.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not repository.is_dir():
        raise FileNotFoundError(f"LTX-2 source repository does not exist: {repository}")
    if not args.prompt.strip():
        raise ValueError("prompt is required")
    validate_dimensions(height=args.height, width=args.width, num_frames=args.num_frames)
    paths = required_model_paths(args.model_root)

    image_args: list[str] = []
    if args.image_path != "none":
        image = Path(args.image_path).expanduser().resolve()
        if not image.is_file():
            raise FileNotFoundError(f"image conditioning file does not exist: {image}")
        image_args = ["--image", str(image), "0", "0.8"]

    sys.path.insert(0, str(repository))
    from ltx_pipelines.distilled import main as official_main

    output.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        "ltx_pipelines.distilled",
        "--transformer-path",
        str(paths["transformer"]),
        "--text-encoder-path",
        str(paths["text_encoder"]),
        "--video-vae-path",
        str(paths["video_vae"]),
        "--audio-vae-path",
        str(paths["audio_vae"]),
        "--duration-head-path",
        str(paths["duration_head"]),
        "--spatial-upsampler-path",
        str(paths["spatial_upsampler"]),
        "--num-frames",
        str(args.num_frames),
        "--height",
        str(args.height),
        "--width",
        str(args.width),
        "--frame-rate",
        str(args.frame_rate),
        "--seed",
        str(args.seed),
        "--prompt",
        args.prompt,
        "--output-path",
        str(output),
        "--offload",
        "cpu",
        *image_args,
    ]
    old_argv = sys.argv
    try:
        sys.argv = argv
        official_main()
    finally:
        sys.argv = old_argv

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"LTX-2.5 exited without producing output: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
