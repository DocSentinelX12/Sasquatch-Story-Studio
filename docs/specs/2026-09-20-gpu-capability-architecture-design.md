# GPU Capability Architecture Design

**Date:** 2026-09-20  
**Repository:** DocSentinelX12/Sasquatch-Story-Studio  
**Status:** Approved design

## Purpose

Establish a production-grade, evidence-backed GPU capability architecture without discarding the existing GPU, distributed execution, topology, NCCL, worker identity, leasing, fencing, or artifact infrastructure.

The architecture must distinguish physical observations from verified capabilities and must never treat missing or unverified evidence as successful capability.

## Locked Decisions

1. Canonical telemetry collection uses **NVML first**, with **nvidia-smi fallback** only when NVML cannot provide a required observation.
2. Admission uses a **hybrid model**: every GPU must satisfy a strict base hardware admission contract, while workload-specific capabilities are required only when applicable.
3. Use a **hybrid evidence/capability architecture**: existing `GpuObservation` remains the physical evidence layer; a canonical `GpuCapabilityRecord` is derived from verified observations and becomes the authority consumed by admission, placement, scheduling, and production execution.
4. Existing functionality is preserved. Consolidation occurs through authoritative interfaces, not deletion or weakening.
5. Software-only CI must not claim physical GPU, NCCL, or multi-node verification that it cannot actually perform.

## Architecture

### 1. Physical observation layer

`GpuObservation` remains the immutable physical observation record.

The observer should collect, where supported:

- GPU UUID and model
- PCI identity
- VRAM
- compute capability
- driver and CUDA compatibility
- temperature
- power state and power usage
- utilization and memory utilization
- ECC state and available error evidence
- MIG state
- NVLink state
- PCIe information
- XID/error evidence where exposed
- DCGM evidence
- topology evidence
- NCCL evidence
- GPU-direct/network evidence
- collection timestamp
- source/collector identity
- evidence freshness
- explicit unavailable/error state

No unavailable value may be fabricated.

NVML is the preferred machine-readable source. Any `nvidia-smi` fallback must be explicit in provenance so downstream code can distinguish the source.

### 2. Canonical capability layer

Introduce a canonical `GpuCapabilityRecord` derived from physical observations and verification evidence.

The record represents what the system has actually established that a GPU can do, rather than merely what configuration claims.

Capabilities may include:

- base GPU availability
- CUDA/runtime compatibility
- health
- multi-GPU participation
- topology/NVLink requirements
- NCCL communication
- GPU-direct/network capability
- engine-specific runtime capability

Each capability has an explicit verification state and evidence provenance.

### 3. Capability lifecycle

Capabilities follow an explicit lifecycle:

`discovered -> identified -> health_verified -> topology_verified -> communication_verified -> engine_verified -> production_eligible -> leased -> executing -> completed`

Invalid, stale, contradictory, or failed evidence must move the affected capability out of eligibility rather than silently passing it.

The lifecycle is capability-specific. A single-GPU workload does not need to complete distributed communication verification merely to use a GPU for which the base contract is satisfied.

### 4. Workload requirements and admission

Workloads declare capability requirements.

Examples:

- Single-GPU workload: base GPU contract plus required CUDA/runtime and engine capability.
- Multi-GPU workload: base contract plus topology and NCCL requirements.
- GPU-direct workload: base contract plus topology/NCCL and verified GPU-direct/network requirements.
- Engine-specific workload: base contract plus verified engine runtime capability.

Admission evaluates requirements against the canonical capability record. `unknown`, stale, failed, or unavailable required capabilities cannot satisfy a requirement.

### 5. Placement authority

Existing GPU placement and scheduling modules are preserved:

- `gpu_scheduler.py`
- `gpu_placement.py`
- `gpu_aware_scheduler.py`
- `distributed_gpu_scheduler.py`
- `distributed_gpu.py`

Their useful responsibilities are consolidated behind the canonical capability/admission path.

`DistributedGpuAllocator` remains a critical allocation authority for distributed reservations, leases, evidence binding, fencing, and collision protection.

Placement should reject ineligible or already-busy GPUs before attempting allocation wherever the architecture permits, improving efficiency without weakening collision protection.

### 6. Evidence binding

Capability evidence remains bound to the worker and physical GPU identity, including:

- immutable worker identity
- GPU UUID
- source observation
- evidence digest
- observation timestamp
- verification timestamp
- verifier/version
- relevant topology, NCCL, and network evidence

Mutated hardware identity or invalidated evidence must prevent reuse of stale capability claims.

### 7. Verification boundary

The architecture explicitly separates:

**Observed:** the machine reported a property.

**Verified:** the system performed the appropriate validation.

**Production eligible:** the evidence satisfies the requirements for the specific workload.

This is especially important for NCCL and GPU-direct capability. Configuration alone is not physical verification.

### 8. Runtime verification progression

The architecture should progressively connect the capability model to real verification:

`physical NVIDIA GPU -> NVML observation -> driver/CUDA verification -> health verification -> topology verification -> NCCL runtime verification -> GPU-direct/network verification -> multi-node verification -> engine runtime verification -> production eligibility`

GitHub-hosted CPU CI may verify contracts, schemas, deterministic logic, failure handling, and fixture boundaries, but must not be presented as proof of physical NVIDIA behavior.

## Error handling

- Missing telemetry is explicit, never synthesized.
- Unsupported platform-specific fields remain unavailable rather than being guessed.
- Stale evidence cannot satisfy a current production requirement.
- Conflicting observations require explicit resolution and cannot silently become a pass.
- Verification failures quarantine or invalidate only the affected capability when safe, while preserving unrelated verified capabilities.
- Hardware identity mutations invalidate dependent evidence.
- Existing lease expiry, fencing, collision protection, and recovery semantics remain intact.

## Testing

Tests must cover:

1. NVML-first collection.
2. Explicit `nvidia-smi` fallback.
3. Provenance for both collection paths.
4. Missing and unsupported telemetry.
5. Observation-to-capability derivation.
6. Capability freshness and invalidation.
7. Base admission.
8. Workload-specific admission.
9. Unknown/failed capability rejection.
10. Placement filtering before allocation where applicable.
11. Existing single-GPU and distributed allocation safety.
12. Worker identity and evidence binding.
13. Topology/NCCL/GPU-direct evidence contracts.
14. Existing distributed artifact and execution contracts.
15. Regression coverage for current GPU architecture.
16. Real hardware verification separately from CPU-only CI.

No test should be weakened, removed, bypassed, or changed merely to make the implementation pass.

## Scope

This design covers the canonical GPU observation, capability, admission, placement, and verification boundary needed to make the existing GPU architecture production-grade.

It does not pretend that physical multi-node GPU infrastructure already exists. Real hardware verification is a subsequent execution layer consuming this capability architecture.

## Success criteria

The resulting system has one authoritative capability/admission path, preserves the existing safety mechanisms, records trustworthy physical evidence, distinguishes observation from verification, supports workload-specific requirements, and provides a clean foundation for real CUDA, NCCL, GPU-direct, multi-node, and engine verification.