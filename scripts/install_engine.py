#!/usr/bin/env python3
"""Install one catalog engine on a Linux worker using its official source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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


def verify_opentoonz_version(executable: Path) -> str:
    """Verify the installed OpenToonz binary reports a real version.

    OpenToonz's command-line version probe on the CI Linux worker reports the
    version text but exits with status 1. That nonzero status is therefore not
    treated as success by the generic command runner. We accept only that exact
    observed CLI behavior: exit 0 or 1 plus a parseable OpenToonz version line.
    Any other exit code, or missing/invalid version output, remains a failure.
    """
    result = subprocess.run(
        [str(executable), "-version"],
        check=False,
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.stdout:
        print(result.stdout[-8000:], flush=True)
    if result.stderr:
        print(result.stderr[-8000:], file=sys.stderr, flush=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"OpenToonz version probe failed with exit code {result.returncode}"
        )
    match = re.search(r"OpenToonz\\s+v?(\\d+\\.\\d+(?:\\.\\d+)?)", result.stdout)
    if not match:
        raise RuntimeError(
            "OpenToonz version probe did not report a parseable OpenToonz version"
        )
    return match.group(1)


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
        "ace-step-1.5": [sys.executable, "-m", "acestep.api_server"],
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
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    lines = [line.strip() for line in (root / "requirements.txt").read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    portable = [line for line in lines if not line.lower().startswith("flash_attn")]
    run(sys.executable, "-m", "pip", "install", *portable, timeout=3600)
    run(sys.executable, "-c", "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())", timeout=120)


def verify_wan_software(root: Path) -> str:
    run(sys.executable, "-m", "compileall", "-q", ".", cwd=root, timeout=600)
    cuda = run(sys.executable, "-c", "import torch; print('1' if torch.cuda.is_available() else '0')", cwd=root, timeout=120).stdout.strip()
    if cuda == "1":
        run(sys.executable, "generate.py", "--help", cwd=root, timeout=180)
        return "CUDA is available; the real Wan generator entrypoint was smoke-checked."
    return "CUDA is unavailable; all Wan Python sources were compiled, and generator import was not attempted because upstream initializes CUDA at import time."


def install_comfyui_dependencies(root: Path) -> None:
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    lines = [line.strip() for line in (root / "requirements.txt").read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    portable = [line for line in lines if not line.lower().startswith(("torch", "torchvision", "torchaudio"))]
    run(sys.executable, "-m", "pip", "install", *portable, timeout=3600)
    run(sys.executable, "-c", "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())", timeout=120)


def install_ltx_dependencies(root: Path) -> None:
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=3600)
    run(sys.executable, "-m", "pip", "install", "diffusers>=0.28.2", "transformers>=4.47.2,<4.52.0", "sentencepiece>=0.1.96", "huggingface-hub~=0.30", "einops", "timm", "imageio[ffmpeg]", "av", timeout=3600)
    run(sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps", cwd=root, timeout=1200)
    run(sys.executable, "-c", "import ltx_video; print('ltx_video', ltx_video.__file__)", cwd=root, timeout=120)


def install(engine_id: str, with_models: bool) -> None:
    ROOT.mkdir(exist_ok=True)
    if engine_id == "blender":
        run("sudo", "apt-get", "update", timeout=1800); run("sudo", "apt-get", "install", "-y", "blender", timeout=1800); run("blender", "--version")
        evidence(engine_id, "https://github.com/blender/blender", ROOT / engine_id, []); return

    if engine_id == "opentoonz":
        run("sudo", "apt-get", "update", timeout=1800)
        packages = "build-essential git cmake pkg-config libboost-all-dev qtbase5-dev libqt5svg5-dev qtscript5-dev qttools5-dev qttools5-dev-tools libqt5opengl5-dev qtmultimedia5-dev libqt5multimedia5-plugins libqt5serialport5-dev libsuperlu-dev liblz4-dev libusb-1.0-0-dev liblzo2-dev libpng-dev libjpeg-dev libglew-dev freeglut3-dev libfreetype6-dev libjson-c-dev qtwayland5 libmypaint-dev libopencv-dev libturbojpeg-dev"
        run("sudo", "apt-get", "install", "-y", *packages.split(), timeout=1800)
        source_dir = ROOT / engine_id / "source"; clone("https://github.com/opentoonz/opentoonz.git", source_dir)
        tiff_dir = source_dir / "thirdparty" / "tiff-4.0.3"; tiff_prefix = (tiff_dir / "ci-install").resolve()
        run("./configure", "--with-pic", "--disable-jbig", f"--prefix={tiff_prefix}", cwd=tiff_dir, timeout=1800)
        run("make", "-j", str(max(2, os.cpu_count() or 2)), cwd=tiff_dir, timeout=3600); run("make", "install", cwd=tiff_dir, timeout=1800)
        build = source_dir / "toonz" / "build"; build.mkdir(parents=True, exist_ok=True)
        tiff_lib = tiff_prefix / "lib" / "libtiff.so"; tiff_include = tiff_prefix / "include"; tiff_private_include = (tiff_dir / "libtiff").resolve()
        if not tiff_lib.is_file() or not tiff_include.is_dir() or not (tiff_private_include / "tiffiop.h").is_file(): raise RuntimeError("bundled OpenToonz TIFF outputs are incomplete")
        run("cmake", "../sources", f"-DTIFF_LIBRARY={tiff_lib}", f"-DTIFF_INCLUDE_DIR={tiff_include}", f"-DCMAKE_C_FLAGS=-I{tiff_private_include}", f"-DCMAKE_CXX_FLAGS=-I{tiff_private_include}", "-DWITH_TRANSLATION=OFF", cwd=build, timeout=1800)
        run("cmake", "--build", ".", "--parallel", str(max(2, os.cpu_count() or 2)), cwd=build, timeout=3600)
        run("sudo", "cmake", "--install", ".", cwd=build, timeout=1800)
        opentoonz = Path("/opt/opentoonz/bin/opentoonz")
        if not opentoonz.is_file() or not os.access(opentoonz, os.X_OK): raise RuntimeError(f"OpenToonz install completed without an executable at {opentoonz}")
        version = verify_opentoonz_version(opentoonz)
        evidence(engine_id, "https://github.com/opentoonz/opentoonz", ROOT / engine_id, [], ["Bundled TIFF was configured with an absolute CI prefix and private include path.", "Translation generation disabled for the CI software build.", "Installed OpenToonz executable was required before evidence was written.", f"OpenToonz version probe reported {version}; the probe exited with its observed status and produced parseable version output."]); return

    if engine_id in {"wan2.1", "wan2.2"}:
        root = ROOT / engine_id; repo = "Wan2.1" if engine_id == "wan2.1" else "Wan2.2"; clone(f"https://github.com/Wan-Video/{repo}.git", root / repo); install_wan_dependencies(root / repo)
        models = []
        if with_models:
            model_dir = root / (("Wan2.1-T2V-1.3B" if engine_id == "wan2.1" else "Wan2.2-TI2V-5B")); hf_download("Wan-AI/" + model_dir.name, model_dir); models = [p for p in model_dir.rglob("*") if p.is_file()]
        note = verify_wan_software(root / repo); evidence(engine_id, f"https://github.com/Wan-Video/{repo}", root, models, [note]); return

    if engine_id == "comfyui":
        root = ROOT / engine_id / "ComfyUI"; clone("https://github.com/Comfy-Org/ComfyUI.git", root); install_comfyui_dependencies(root); run(sys.executable, "main.py", "--help", cwd=root, timeout=180); evidence(engine_id, "https://github.com/Comfy-Org/ComfyUI", ROOT / engine_id, [], ["CPU PyTorch wheels used for software installation smoke check; model checkpoints are separate."]); return

    if engine_id == "ltx-video":
        root = ROOT / engine_id / "LTX-Video"; clone("https://github.com/Lightricks/LTX-Video.git", root); install_ltx_dependencies(root)
        models = []
        if with_models:
            model = root / "ltxv-2b-0.9.8-distilled.safetensors"; hf_download("Lightricks/LTX-Video", root, "ltxv-2b-0.9.8-distilled.safetensors"); models = [model]
        run(sys.executable, "inference.py", "--help", cwd=root, timeout=180); evidence(engine_id, "https://github.com/Lightricks/LTX-Video", ROOT / engine_id, models, []); return

    if engine_id == "piper":
        run(sys.executable, "-m", "pip", "install", "piper-tts==1.8.0", timeout=1800); data_dir = ROOT / engine_id / "voices"; data_dir.mkdir(parents=True, exist_ok=True); run(sys.executable, "-m", "piper.download_voices", "en_US-lessac-medium", "--data-dir", str(data_dir), timeout=1800); model = data_dir / "en_US-lessac-medium.onnx"; run(sys.executable, "-m", "piper", "--help", timeout=120); evidence(engine_id, "https://github.com/OHF-Voice/piper1-gpl", ROOT / engine_id, [model], []); return

    if engine_id == "rhubarb-lip-sync":
        run("sudo", "apt-get", "update", timeout=1800); run("sudo", "apt-get", "install", "-y", "build-essential", "cmake", "libboost-all-dev", "openjdk-17-jdk", timeout=1800); source_dir = ROOT / engine_id / "source"; clone("https://github.com/DanielSWolf/rhubarb-lip-sync.git", source_dir); build = source_dir / "build"; build.mkdir(parents=True, exist_ok=True); run("cmake", "..", "-DCMAKE_BUILD_TYPE=Release", cwd=build, timeout=1800); run("cmake", "--build", ".", "--target", "rhubarb", "--config", "Release", "--parallel", str(max(2, os.cpu_count() or 2)), cwd=build, timeout=3600); binary = next((p for p in build.rglob("rhubarb") if p.is_file()), None); 
        if binary is None: raise RuntimeError("Rhubarb build completed but no executable was found")
        run("sudo", "cp", str(binary), "/usr/local/bin/rhubarb"); run("rhubarb", "--version", timeout=120); evidence(engine_id, "https://github.com/DanielSWolf/rhubarb-lip-sync", ROOT / engine_id, [], []); return

    if engine_id == "ace-step-1.5":
        root = ROOT / engine_id / "ACE-Step-1.5"; clone("https://github.com/ACE-Step/ACE-Step-1.5.git", root); run(sys.executable, "-m", "pip", "install", "uv", timeout=600); run("uv", "sync", cwd=root, timeout=3600)
        if with_models: run("uv", "run", "acestep-download", cwd=root, timeout=3600)
        else: run("uv", "run", "acestep-api", "--help", cwd=root, timeout=180)
        models = [p for p in (root / "checkpoints").rglob("*") if p.is_file()] if with_models and (root / "checkpoints").exists() else []
        evidence(engine_id, "https://github.com/ACE-Step/ACE-Step-1.5", ROOT / engine_id, models, []); return

    raise ValueError(f"unsupported engine: {engine_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one Studio engine and record installation evidence.")
    parser.add_argument("engine_id", choices=["blender", "opentoonz", "rhubarb-lip-sync", "piper", "comfyui", "wan2.1", "wan2.2", "ltx-video", "ace-step-1.5"])
    parser.add_argument("--with-models", action="store_true")
    args = parser.parse_args(); install(args.engine_id, args.with_models); return 0

if __name__ == "__main__":
    raise SystemExit(main())
