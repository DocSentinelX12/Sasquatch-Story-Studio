#!/usr/bin/env python3
"""Run the official LTX-Video inference code with an exact Studio output path."""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image-path", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-frames", type=int, default=121)
    parser.add_argument("--height", type=int, default=704)
    parser.add_argument("--width", type=int, default=1216)
    parser.add_argument("--seed", type=int, default=171198)
    args = parser.parse_args()

    repository = args.repository.expanduser().resolve()
    model_path = args.model_path.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not repository.is_dir():
        raise RuntimeError(f"LTX-Video repository does not exist: {repository}")
    if not model_path.is_dir():
        raise RuntimeError(f"LTX-Video model directory does not exist: {model_path}")
    raw_image = str(args.image_path) if args.image_path is not None else ""
    image = Path(raw_image).expanduser().resolve() if raw_image and raw_image != "none" else None
    if image is not None and not image.is_file():
        raise RuntimeError(f"conditioning image does not exist: {image}")

    sys.path.insert(0, str(repository))
    from ltx_video.inference import InferenceConfig, infer

    base_config = repository / "configs" / "ltxv-2b-0.9.8-distilled.yaml"
    if not base_config.is_file():
        raise RuntimeError(f"official LTX pipeline config is missing: {base_config}")
    config = yaml.safe_load(base_config.read_text(encoding="utf-8"))
    config["checkpoint_path"] = str(model_path / "ltxv-2b-0.9.8-distilled.safetensors")
    config["spatial_upscaler_model_path"] = str(model_path / "ltxv-spatial-upscaler-0.9.8.safetensors")

    with tempfile.TemporaryDirectory(prefix="ltx-video-") as temp_dir:
        temp = Path(temp_dir)
        pipeline_config = temp / "pipeline.yaml"
        pipeline_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        generated = temp / "generated"
        generated.mkdir()
        infer(
            InferenceConfig(
                prompt=args.prompt,
                output_path=str(generated),
                pipeline_config=str(pipeline_config),
                seed=args.seed,
                height=args.height,
                width=args.width,
                num_frames=args.num_frames,
                frame_rate=30,
                offload_to_cpu=True,
                conditioning_media_paths=[str(image)] if image else None,
                conditioning_start_frames=[0] if image else None,
            )
        )
        candidates = sorted(generated.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise RuntimeError("official LTX-Video inference completed without an MP4 output")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], output)

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("LTX-Video bridge did not produce a non-empty output artifact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
