#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shlex, shutil, subprocess, time
from pathlib import Path

def verify(output_path, command_text, *, now=None):
    if shutil.which("nvidia-smi") is None: raise RuntimeError("physical GPU-direct verification requires nvidia-smi")
    if not command_text.strip(): raise ValueError("an explicit GPU-direct verification command is required")
    smi=subprocess.run(["nvidia-smi","--query-gpu=uuid","--format=csv,noheader"],check=False,capture_output=True,text=True,timeout=60)
    if smi.returncode != 0: raise RuntimeError("nvidia-smi failed while collecting GPU identity")
    gpu_uuids=tuple(x.strip() for x in smi.stdout.splitlines() if x.strip())
    if len(gpu_uuids)<2: raise RuntimeError("GPU-direct verification requires at least two physical GPUs/workload endpoints")
    command=shlex.split(command_text)
    result=subprocess.run(command,check=False,capture_output=True,text=True,timeout=900,env=os.environ.copy())
    output=(result.stdout or "")+(result.stderr or "")
    if result.returncode != 0: raise RuntimeError(f"GPU-direct verification failed with exit code {result.returncode}: {output[-4000:]}")
    recorded_at=int(time.time()) if now is None else now
    evidence={"verification":"gpu_direct_network","recorded_at":recorded_at,"command":command,"gpu_uuids":list(gpu_uuids),
              "output_sha256":hashlib.sha256(output.encode()).hexdigest(),"exit_code":result.returncode}
    target=Path(output_path).expanduser().resolve(); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(evidence,sort_keys=True,indent=2)+"\n",encoding="utf-8"); return evidence

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--output",default="gpu-direct-runtime-evidence.json"); parser.add_argument("--command",required=True); args=parser.parse_args()
    verify(args.output,args.command); return 0
if __name__=="__main__": raise SystemExit(main())
