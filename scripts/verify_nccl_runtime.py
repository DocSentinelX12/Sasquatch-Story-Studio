#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, time
from pathlib import Path

def verify(output_path, *, worker_id, executable="all_reduce_perf", now=None):
    if not worker_id.strip(): raise ValueError("worker identity is required")
    if shutil.which("nvidia-smi") is None: raise RuntimeError("physical NCCL verification requires nvidia-smi")
    if shutil.which(executable) is None: raise RuntimeError(f"NCCL test executable is unavailable: {executable}")
    smi=subprocess.run(["nvidia-smi","--query-gpu=uuid","--format=csv,noheader"],check=False,capture_output=True,text=True,timeout=60)
    if smi.returncode != 0: raise RuntimeError("nvidia-smi failed while collecting NCCL GPU identity")
    gpu_uuids=tuple(x.strip() for x in smi.stdout.splitlines() if x.strip())
    if len(gpu_uuids)<2: raise RuntimeError("NCCL distributed verification requires at least two physical GPUs")
    command=[executable,"-b","8","-e","8M","-f","2","-g",str(len(gpu_uuids))]
    env=os.environ.copy(); env["CUDA_VISIBLE_DEVICES"]=",".join(gpu_uuids)
    result=subprocess.run(command,check=False,capture_output=True,text=True,timeout=900,env=env)
    output=(result.stdout or "")+(result.stderr or "")
    if result.returncode != 0: raise RuntimeError(f"NCCL test failed with exit code {result.returncode}: {output[-4000:]}")
    topology=subprocess.run(["nvidia-smi","topo","-m"],check=False,capture_output=True,text=True,timeout=60)
    if topology.returncode != 0 or not topology.stdout.strip(): raise RuntimeError("NCCL verification requires observed GPU topology output")
    recorded_at=int(time.time()) if now is None else now
    executable_path=Path(shutil.which(executable)).resolve()
    executable_sha256=hashlib.sha256(executable_path.read_bytes()).hexdigest()
    evidence={"verification":"nccl_collective","recorded_at":recorded_at,"worker_id":worker_id,"command":command,"executable":str(executable_path),"executable_sha256":executable_sha256,"gpu_uuids":list(gpu_uuids),
              "topology_sha256":hashlib.sha256(topology.stdout.encode()).hexdigest(),
              "output_sha256":hashlib.sha256(output.encode()).hexdigest(),"exit_code":result.returncode}
    target=Path(output_path).expanduser().resolve(); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(evidence,sort_keys=True,indent=2)+"\n",encoding="utf-8"); return evidence

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--output",default="nccl-runtime-evidence.json"); parser.add_argument("--executable",default="all_reduce_perf"); parser.add_argument("--worker-id",required=True); args=parser.parse_args()
    verify(args.output,worker_id=args.worker_id,executable=args.executable); return 0
if __name__=="__main__": raise SystemExit(main())
