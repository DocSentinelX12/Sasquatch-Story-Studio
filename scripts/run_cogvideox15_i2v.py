"""Execute the official CogVideoX1.5-5B-I2V Diffusers pipeline locally."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-frames", type=int, default=81)
    parser.add_argument("--num-inference-steps", type=int, default=50)
    parser.add_argument("--guidance-scale", type=float, default=6.0)
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--sequential-cpu-offload", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = Path(args.repository).expanduser().resolve()
    model_path = Path(args.model_path).expanduser().resolve()
    image_path = Path(args.image).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    if not repository.is_dir():
        raise SystemExit(f"CogVideoX repository does not exist: {repository}")
    if not (repository / "inference" / "cli_demo.py").is_file():
        raise SystemExit("Pinned CogVideoX repository is missing the official inference entrypoint")
    if not model_path.is_dir() or not any(model_path.iterdir()):
        raise SystemExit(f"CogVideoX model directory is missing or empty: {model_path}")
    if not image_path.is_file() or image_path.stat().st_size == 0:
        raise SystemExit(f"CogVideoX reference image is missing or empty: {image_path}")
    if not args.prompt.strip():
        raise SystemExit("CogVideoX prompt is required")
    if args.num_frames < 1 or (args.num_frames - 1) % 8 != 0:
        raise SystemExit("CogVideoX1.5 I2V frame count must be 8N+1")
    if args.num_inference_steps < 1:
        raise SystemExit("CogVideoX inference steps must be positive")
    if args.guidance_scale <= 0:
        raise SystemExit("CogVideoX guidance scale must be positive")
    if args.fps < 1:
        raise SystemExit("CogVideoX FPS must be positive")

    repository_text = str(repository)
    if repository_text not in sys.path:
        sys.path.insert(0, repository_text)

    import torch
    from diffusers import CogVideoXImageToVideoPipeline, CogVideoXDPMScheduler
    from diffusers.utils import export_to_video, load_image

    if not torch.cuda.is_available():
        raise SystemExit("CogVideoX1.5 I2V requires CUDA for actual inference")

    pipe = CogVideoXImageToVideoPipeline.from_pretrained(
        str(model_path),
        torch_dtype=torch.bfloat16,
    )
    pipe.scheduler = CogVideoXDPMScheduler.from_config(
        pipe.scheduler.config,
        timestep_spacing="trailing",
    )
    if args.sequential_cpu_offload:
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to("cuda")
    pipe.vae.enable_slicing()
    pipe.vae.enable_tiling()

    image = load_image(image=str(image_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = pipe(
        height=image.height,
        width=image.width,
        prompt=args.prompt,
        image=image,
        num_videos_per_prompt=1,
        num_inference_steps=args.num_inference_steps,
        num_frames=args.num_frames,
        use_dynamic_cfg=True,
        guidance_scale=args.guidance_scale,
        generator=torch.Generator(device="cuda").manual_seed(args.seed),
    ).frames[0]
    if not frames:
        raise SystemExit("CogVideoX returned no video frames")

    export_to_video(frames, str(output), fps=args.fps)
    if not output.is_file() or output.stat().st_size == 0:
        raise SystemExit("CogVideoX did not produce a non-empty video output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
