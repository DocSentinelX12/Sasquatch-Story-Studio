#!/usr/bin/env python3
"""Install one catalog engine on a Linux worker using its official source.

The default CI path installs and smoke-checks the engine software without
requiring multi-gigabyte checkpoints. Model acquisition is opt-in because
GitHub-hosted standard runners have limited local storage and are not the
studio's permanent production workers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path("engine-installations")


def run(*args: str, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    result = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=True, timeout=timeout)
    if result.stdout:
        print(result.stdout[-8000:], flush=True)
    if result.returncode:
        if result.stderr:
            print(result.stderr[-8000:], file=sys.stderr, flush=True)
        raise RuntimeError(f"command failed with exit code {result.returncode}: {' '.join(args)}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clone(url: str, destination: Path) -> None:
    run("git", "clone", "--depth", "1", url, str(destination), timeout=1800)


def evidence(engine_id: str, source: str, root: Path, model_paths: list[Path], notes: list[str] | None = None) -> None:
    executable_candidates = {
        "blender": ["blender"],
        "opentoonz": ["/opt/opentoonz/bin/opentoonz"],
        "rhubarb-lip-sync": ["rhubarb"],
        "piper": [sys.executable, "-m", "piper"],
        "comfyui": [sys.executable, "ComfyUI/main.py"],
        "wan2.1": [sys.executable, "Wan2.1/generate.py"],
        "wan2.2": [sys.executable, "Wan2.2/generate.py"],
        "ltx-video": [sys.executable, "LTX-Video/inference.py"],
        "ace-step-1.5": [sys.executable, "-m", "acestep.api_server"],
    }
    files = []
    for path in model_paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"declared model/checkpoint is not a real non-empty file: {path}")
        files.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    root.mkdir(parents=True, exist_ok=True)
    record = {
        "engine_id": engine_id,
        "source": source,
        "worker_installation_root": str(root.resolve()),
        "executable": executable_candidates[engine_id],
        "models": files,
        "runtime_verified": False,
        "notes": notes or [],
        "note": "Installation evidence only. A successful installation is not a runtime-generation verification.",
    }
    (root / "installation-evidence.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def hf_download(repo: str, destination: Path, *patterns: str) -> None:
    run(sys.executable, "-m", "pip", "install", "huggingface_hub[cli]", timeout=1200)
    run("hf", "download", repo, *patterns, "--local-dir", str(destination), timeout=3600)


def install_wan_dependencies(root: Path) -> None:
    """Install Wan dependencies without forcing flash-attn on CPU-only workers."""
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    lines = [line.strip() for line in (root / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    portable = [line for line in lines if not line.lower().startswith("flash_attn")]
    run(sys.executable, "-m", "pip", "install", *portable, timeout=3600)
    run(sys.executable, "-c", "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())", timeout=120)


def install_comfyui_dependencies(root: Path) -> None:
    """Install ComfyUI on a CPU CI worker without pulling CUDA wheels."""
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    lines = [line.strip() for line in (root / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    portable = [line for line in lines if not line.lower().startswith(("torch", "torchvision", "torchaudio"))]
    run(sys.executable, "-m", "pip", "install", *portable, timeout=3600)
    run(sys.executable, "-c", "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())", timeout=120)


def install_ltx_dependencies(root: Path) -> None:
    """Install LTX's Python dependencies with the CPU torch already selected."""
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    run(sys.executable, "-m", "pip", "install",
        "diffusers>=0.28.2", "transformers>=4.47.2,<4.52.0", "sentencepiece>=0.1.96",
        "huggingface-hub~=0.30", "einops", "timm", "imageio[ffmpeg]", "av", timeout=3600)
    run(sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps", cwd=root, timeout=1200)
    run(sys.executable, "-c", "import ltx_video; print('ltx_video', ltx_video.__file__)", cwd=root, timeout=120)


def install(engine_id: str, with_models: bool) -> None:
    ROOT.mkdir(exist_ok=True)
    if engine_id == "blender":
        run("sudo", "apt-get", "update", timeout=1800)
        run("sudo", "apt-get", "install", "-y", "blender", timeout=1800)
        run("blender", "--version")
        evidence(engine_id, "https://github.com/blender/blender", ROOT / engine_id, [])
        return

    if engine_id == "opentoonz":
        run("sudo", "apt-get", "update", timeout=1800)
        packages = "build-essential git cmake pkg-config libboost-all-dev qtbase5-dev libqt5svg5-dev qtscript5-dev qttools5-dev qttools5-dev-tools libqt5opengl5-dev qtmultimedia5-dev libqt5multimedia5-plugins libqt5serialport5-dev libsuperlu-dev liblz4-dev libusb-1.0-0-dev liblzo2-dev libpng-dev libjpeg-dev libtiff-dev libglew-dev freeglut3-dev libfreetype6-dev libjson-c-dev qtwayland5 libmypaint-dev libopencv-dev libturbojpeg-dev"
        run("sudo", "apt-get", "install", "-y", *packages.split(), timeout=1800)
        source_dir = ROOT / engine_id / "source"
        clone("https://github.com/opentoonz/opentoonz.git", source_dir)
        build = source_dir / "toonz" / "build"
        build.mkdir(parents=True, exist_ok=True)
        run("cmake", "../sources", "-DTIFF_LIBRARY=/usr/lib/x86_64-linux-gnu/libtiff.so", "-DWITH_TRANSLATION=OFF", cwd=build, timeout=1800)
        run("cmake", "--build", ".", "--parallel", str(max(2, os.cpu_count() or 2)), cwd=build, timeout=3600)
        run("sudo", "cmake", "--install", ".", cwd=build, timeout=1800)
        run("/opt/opentoonz/bin/opentoonz", "--version", timeout=120)
        evidence(engine_id, "https://github.com/opentoonz/opentoonz", ROOT / engine_id, [], ["TIFF library path is supplied explicitly for the upstream CMake finder.", "Translation generation is disabled for the CI software build because upstream documents WITH_TRANSLATION=OFF as the workaround for duplicate Qt translation build rules."])
        return

    if engine_id == "rhubarb-lip-sync":
        run("sudo", "apt-get", "update", timeout=1800)
        run("sudo", "apt-get", "install", "-y", "build-essential", "cmake", "libboost-all-dev", "openjdk-17-jdk", timeout=1800)
        source_dir = ROOT / engine_id / "source"
        clone("https://github.com/DanielSWolf/rhubarb-lip-sync.git", source_dir)
        build = source_dir / "build"
        build.mkdir(parents=True, exist_ok=True)
        run("cmake", "..", "-DCMAKE_BUILD_TYPE=Release", cwd=build, timeout=1800)
        run("cmake", "--build", ".", "--target", "rhubarb", "--config", "Release", "--parallel", str(max(2, os.cpu_count() or 2)), cwd=build, timeout=3600)
        binary = next((p for p in build.rglob("rhubarb") if p.is_file()), None)
        if binary is None:
            raise RuntimeError("Rhubarb build completed but no rhubarb executable was found")
        run("sudo", "cp", str(binary), "/usr/local/bin/rhubarb")
        run("rhubarb", "--version", timeout=120)
        evidence(engine_id, "https://github.com/DanielSWolf/rhubarb-lip-sync", ROOT / engine_id, [], ["Built the core rhubarb target; optional Spine integration is not required for lip-sync runtime."])
        return

    if engine_id == "piper":
        run(sys.executable, "-m", "pip", "install", "piper-tts==1.8.0", timeout=1800)
        data_dir = ROOT / engine_id / "voices"
        data_dir.mkdir(parents=True, exist_ok=True)
        run(sys.executable, "-m", "piper.download_voices", "en_US-lessac-medium", "--data-dir", str(data_dir), timeout=1800)
        model = data_dir / "en_US-lessac-medium.onnx"
        if not model.is_file() or model.stat().st_size == 0:
            raise RuntimeError("Piper voice model was not downloaded")
        run(sys.executable, "-m", "piper", "--help", timeout=120)
        evidence(engine_id, "https://github.com/OHF-Voice/piper1-gpl", ROOT / engine_id, [model])
        return

    if engine_id == "comfyui":
        root = ROOT / engine_id / "ComfyUI"
        clone("https://github.com/Comfy-Org/ComfyUI.git", root)
        install_comfyui_dependencies(root)
        run(sys.executable, "main.py", "--help", cwd=root, timeout=180)
        evidence(engine_id, "https://github.com/Comfy-Org/ComfyUI", ROOT / engine_id, [], ["CPU PyTorch wheels were used on the standard CI worker; model checkpoints are not part of this software-installation job."])
        return

    if engine_id in {"wan2.1", "wan2.2"}:
        root = ROOT / engine_id
        repo = "Wan2.1" if engine_id == "wan2.1" else "Wan2.2"
        clone(f"https://github.com/Wan-Video/{repo}.git", root / repo)
        install_wan_dependencies(root / repo)
        if with_models:
            model_dir = root / ("Wan2.1-T2V-1.3B" if engine_id == "wan2.1" else "Wan2.2-TI2V-5B")
            hf_download("Wan-AI/Wan2.1-T2V-1.3B" if engine_id == "wan2.1" else "Wan-AI/Wan2.2-TI2V-5B", model_dir)
            models = [p for p in model_dir.rglob("*") if p.is_file()]
            if not models:
                raise RuntimeError(f"{engine_id} model download produced no files")
        else:
            models = []
        run(sys.executable, "-m", "py_compile", "generate.py", cwd=root / repo, timeout=180)
        evidence(engine_id, f"https://github.com/Wan-Video/{repo}", root, models, ["Model download is opt-in because standard GitHub-hosted workers have limited disk. flash_attn is omitted on CPU-only installation workers.", "The CI software check compiles the real entrypoint without importing it, because the upstream entrypoint initializes CUDA at module import and a standard CPU worker cannot honestly be treated as a Wan runtime worker."])
        return

    if engine_id == "ltx-video":
        root = ROOT / engine_id
        source = root / "LTX-Video"
        clone("https://github.com/Lightricks/LTX-Video.git", source)
        install_ltx_dependencies(source)
        if with_models:
            hf_download("Lightricks/LTX-Video", source, "ltxv-2b-0.9.8-distilled.safetensors")
            model = source / "ltxv-2b-0.9.8-distilled.safetensors"
            if not model.is_file() or model.stat().st_size == 0:
                raise RuntimeError("LTX-Video checkpoint was not downloaded")
            models = [model]
        else:
            models = []
        run(sys.executable, "inference.py", "--help", cwd=source, timeout=180)
        evidence(engine_id, "https://github.com/Lightricks/LTX-Video", root, models, ["Checkpoint download is opt-in because the standard GitHub-hosted worker does not have enough disk for the current 2B checkpoint plus its Python environment."])
        return

    if engine_id == "ace-step-1.5":
        root = ROOT / engine_id / "ACE-Step-1.5"
        clone("https://github.com/ACE-Step/ACE-Step-1.5.git", root)
        if with_models:
            run(sys.executable, "-m", "pip", "install", "uv", timeout=600)
            run("uv", "sync", cwd=root, timeout=3600)
            run("uv", "run", "acestep-download", cwd=root, timeout=3600)
            checkpoints = root / "checkpoints"
            models = [p for p in checkpoints.rglob("*") if p.is_file()] if checkpoints.exists() else []
            if not models:
                raise RuntimeError("ACE-Step model download produced no checkpoint files")
            run("uv", "run", "acestep-api", "--help", cwd=root, timeout=180)
        else:
            run(sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps", cwd=root, timeout=1200)
            run(sys.executable, "-c", "import importlib.metadata; print('ace-step', importlib.metadata.version('ace-step'))", cwd=root, timeout=120)
            models = []
        evidence(engine_id, "https://github.com/ACE-Step/ACE-Step-1.5", ROOT / engine_id, models, ["Full dependency and model installation is reserved for a resource-matched worker because the upstream Linux environment selects CUDA PyTorch and core models are about 10 GB."])
        return

    raise ValueError(f"unsupported engine: {engine_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=("blender", "opentoonz", "rhubarb-lip-sync", "piper", "comfyui", "wan2.1", "wan2.2", "ltx-video", "ace-step-1.5"))
    parser.add_argument("--with-models", action="store_true", help="Download engine checkpoints/models on a worker with sufficient storage.")
    args = parser.parse_args()
    install(args.engine, args.with_models)
    print(json.dumps({"engine_id": args.engine, "status": "installed", "runtime_verified": False, "models_requested": args.with_models}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
