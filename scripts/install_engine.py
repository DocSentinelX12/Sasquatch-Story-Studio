#!/usr/bin/env python3
"""Install one catalog engine on a Linux worker using its official source."""
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
        "blender": ["blender"], "opentoonz": ["/opt/opentoonz/bin/opentoonz"],
        "rhubarb-lip-sync": ["rhubarb"], "piper": [sys.executable, "-m", "piper"],
        "comfyui": [sys.executable, "ComfyUI/main.py"], "wan2.1": [sys.executable, "Wan2.1/generate.py"],
        "wan2.2": [sys.executable, "Wan2.2/generate.py"], "ltx-video": [sys.executable, "LTX-Video/inference.py"],
        "ace-step-1.5": ["uv", "run", "acestep-api"],
    }
    files = []
    for path in model_paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"declared model/checkpoint is not a real non-empty file: {path}")
        files.append({"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    root.mkdir(parents=True, exist_ok=True)
    record = {"engine_id": engine_id, "source": source, "worker_installation_root": str(root.resolve()),
              "executable": executable_candidates[engine_id], "models": files, "runtime_verified": False,
              "notes": notes or [], "note": "Installation evidence only. A successful installation is not a runtime-generation verification."}
    (root / "installation-evidence.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def hf_download(repo: str, destination: Path, *patterns: str) -> None:
    run(sys.executable, "-m", "pip", "install", "huggingface_hub[cli]", timeout=1200)
    run("hf", "download", repo, *patterns, "--local-dir", str(destination), timeout=3600)


def install_wan_dependencies(root: Path) -> None:
    """Install Wan dependencies without forcing flash-attn on CPU-only CI workers."""
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    lines = [line.strip() for line in (root / "requirements.txt").read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    portable = [line for line in lines if not line.lower().startswith("flash_attn")]
    run(sys.executable, "-m", "pip", "install", *portable, timeout=3600)
    run(sys.executable, "-c", "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())", timeout=120)


def install(engine_id: str) -> None:
    ROOT.mkdir(exist_ok=True)
    if engine_id == "blender":
        run("sudo", "apt-get", "update", timeout=1800); run("sudo", "apt-get", "install", "-y", "blender", timeout=1800); run("blender", "--version")
        evidence(engine_id, "https://github.com/blender/blender", ROOT / engine_id, []); return

    if engine_id == "opentoonz":
        run("sudo", "apt-get", "update", timeout=1800)
        packages = "build-essential git cmake pkg-config libboost-all-dev qtbase5-dev libqt5svg5-dev qtscript5-dev qttools5-dev qttools5-dev-tools libqt5opengl5-dev qtmultimedia5-dev libqt5multimedia5-plugins libqt5serialport5-dev libsuperlu-dev liblz4-dev libusb-1.0-0-dev liblzo2-dev libpng-dev libjpeg-dev libtiff-dev libglew-dev freeglut3-dev libfreetype6-dev libjson-c-dev qtwayland5 libmypaint-dev libopencv-dev libturbojpeg-dev"
        run("sudo", "apt-get", "install", "-y", *packages.split(), timeout=1800)
        source_dir = ROOT / engine_id / "source"; clone("https://github.com/opentoonz/opentoonz.git", source_dir)
        build = source_dir / "toonz" / "build"; build.mkdir(parents=True, exist_ok=True)
        run("cmake", "../sources", cwd=build, timeout=1800); run("cmake", "--build", ".", "--parallel", str(max(2, os.cpu_count() or 2)), cwd=build, timeout=3600)
        run("sudo", "cmake", "--install", ".", cwd=build, timeout=1800); run("/opt/opentoonz/bin/opentoonz", "--version", timeout=120)
        evidence(engine_id, "https://github.com/opentoonz/opentoonz", ROOT / engine_id, []); return

    if engine_id == "rhubarb-lip-sync":
        run("sudo", "apt-get", "update", timeout=1800); run("sudo", "apt-get", "install", "-y", "build-essential", "cmake", "libboost-all-dev", "openjdk-17-jdk", timeout=1800)
        source_dir = ROOT / engine_id / "source"; clone("https://github.com/DanielSWolf/rhubarb-lip-sync.git", source_dir)
        build = source_dir / "build"; build.mkdir(parents=True, exist_ok=True)
        run("cmake", "..", "-DCMAKE_BUILD_TYPE=Release", cwd=build, timeout=1800)
        run("cmake", "--build", ".", "--target", "rhubarb", "--config", "Release", "--parallel", str(max(2, os.cpu_count() or 2)), cwd=build, timeout=3600)
        binary = next((p for p in build.rglob("rhubarb") if p.is_file()), None)
        if binary is None: raise RuntimeError("Rhubarb build completed but no rhubarb executable was found")
        run("sudo", "cp", str(binary), "/usr/local/bin/rhubarb"); run("rhubarb", "--version", timeout=120)
        evidence(engine_id, "https://github.com/DanielSWolf/rhubarb-lip-sync", ROOT / engine_id, [], ["Built the core rhubarb target; optional Spine integration is not required for lip-sync runtime."]); return

    if engine_id == "piper":
        run(sys.executable, "-m", "pip", "install", "piper-tts==1.8.0", timeout=1800)
        data_dir = ROOT / engine_id / "voices"; data_dir.mkdir(parents=True, exist_ok=True)
        run(sys.executable, "-m", "piper.download_voices", "en_US-lessac-medium", "--data-dir", str(data_dir), timeout=1800)
        model = data_dir / "en_US-lessac-medium.onnx"
        if not model.is_file() or model.stat().st_size == 0: raise RuntimeError("Piper voice model was not downloaded")
        run(sys.executable, "-m", "piper", "--help", timeout=120); evidence(engine_id, "https://github.com/OHF-Voice/piper1-gpl", ROOT / engine_id, [model]); return

    if engine_id == "comfyui":
        clone("https://github.com/Comfy-Org/ComfyUI.git", ROOT / engine_id / "ComfyUI")
        run(sys.executable, "-m", "pip", "install", "-r", "requirements.txt", cwd=ROOT / engine_id / "ComfyUI", timeout=3600)
        run(sys.executable, "main.py", "--help", cwd=ROOT / engine_id / "ComfyUI", timeout=180); evidence(engine_id, "https://github.com/Comfy-Org/ComfyUI", ROOT / engine_id, []); return

    if engine_id in {"wan2.1", "wan2.2"}:
        root = ROOT / engine_id; repo = "Wan2.1" if engine_id == "wan2.1" else "Wan2.2"
        clone(f"https://github.com/Wan-Video/{repo}.git", root / repo); install_wan_dependencies(root / repo)
        model_dir = root / ("Wan2.1-T2V-1.3B" if engine_id == "wan2.1" else "Wan2.2-TI2V-5B")
        hf_download("Wan-AI/Wan2.1-T2V-1.3B" if engine_id == "wan2.1" else "Wan-AI/Wan2.2-TI2V-5B", model_dir)
        models = [p for p in model_dir.rglob("*") if p.is_file()]
        if not models: raise RuntimeError(f"{engine_id} model download produced no files")
        run(sys.executable, "generate.py", "--help", cwd=root / repo, timeout=180)
        evidence(engine_id, f"https://github.com/Wan-Video/{repo}", root, models, ["flash_attn was intentionally omitted on CPU-only installation workers; Wan source supports CPU compatibility paths. GPU workers may install the optional accelerator separately."]); return

    if engine_id == "ltx-video":
        root = ROOT / engine_id; clone("https://github.com/Lightricks/LTX-Video.git", root / "LTX-Video")
        run(sys.executable, "-m", "pip", "install", "-e", ".[inference-script]", cwd=root / "LTX-Video", timeout=3600)
        model_dir = root / "LTX-Video"; hf_download("Lightricks/LTX-Video", model_dir, "ltxv-2b-0.9.8-distilled.safetensors")
        model = model_dir / "ltxv-2b-0.9.8-distilled.safetensors"
        if not model.is_file() or model.stat().st_size == 0: raise RuntimeError("LTX-Video checkpoint was not downloaded")
        run(sys.executable, "inference.py", "--help", cwd=root / "LTX-Video", timeout=180); evidence(engine_id, "https://github.com/Lightricks/LTX-Video", root, [model]); return

    if engine_id == "ace-step-1.5":
        root = ROOT / engine_id / "ACE-Step-1.5"; clone("https://github.com/ace-step/ACE-Step-1.5.git", root)
        run(sys.executable, "-m", "pip", "install", "uv", timeout=600); run("uv", "sync", cwd=root, timeout=3600); run("uv", "run", "acestep-download", cwd=root, timeout=3600)
        checkpoints = root / "checkpoints"; models = [p for p in checkpoints.rglob("*") if p.is_file()] if checkpoints.exists() else []
        if not models: raise RuntimeError("ACE-Step model download produced no checkpoint files")
        run("uv", "run", "acestep-api", "--help", cwd=root, timeout=180); evidence(engine_id, "https://github.com/ace-step/ACE-Step-1.5", ROOT / engine_id, models); return

    raise ValueError(f"unsupported engine: {engine_id}")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("engine", choices=("blender", "opentoonz", "rhubarb-lip-sync", "piper", "comfyui", "wan2.1", "wan2.2", "ltx-video", "ace-step-1.5"))
    args = parser.parse_args(); install(args.engine)
    print(json.dumps({"engine_id": args.engine, "status": "installed", "runtime_verified": False}, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
