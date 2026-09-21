#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, time
from pathlib import Path

def _run(command, timeout=60):
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"required executable is unavailable: {command[0]}") from exc

def verify(output_path, *, now=None):
    if shutil.which("nvidia-smi") is None:
        raise RuntimeError("physical NVIDIA verification requires nvidia-smi")
    smi = _run(["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"])
    if smi.returncode != 0 or not smi.stdout.strip():
        raise RuntimeError("nvidia-smi did not report a physical NVIDIA GPU")
    gpu_uuids = tuple(item.strip() for item in smi.stdout.splitlines() if item.strip())
    command = ["python", "-c", "import torch; assert torch.cuda.is_available(); print(torch.version.cuda); print(torch.cuda.device_count())"]
    runtime = _run(command, timeout=120)
    if runtime.returncode != 0:
        detail = (runtime.stderr or runtime.stdout).strip()
        raise RuntimeError(f"CUDA runtime verification failed: {detail}")
    recorded_at = int(time.time()) if now is None else now
    evidence = {"verification":"cuda_runtime","recorded_at":recorded_at,"command":command,"gpu_uuids":list(gpu_uuids),
                "nvidia_smi_output_sha256":hashlib.sha256(smi.stdout.encode()).hexdigest(),
                "runtime_output_sha256":hashlib.sha256(runtime.stdout.encode()).hexdigest(),
                "cuda_runtime_output":runtime.stdout.strip()}
    target=Path(output_path).expanduser().resolve(); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(evidence,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return evidence

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--output",default="gpu-runtime-evidence.json"); args=parser.parse_args()
    verify(args.output); return 0
if __name__=="__main__": raise SystemExit(main())
