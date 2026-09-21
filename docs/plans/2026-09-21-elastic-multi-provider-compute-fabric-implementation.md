# Elastic Multi-Provider Compute Fabric Implementation Plan

## Scope

Implement the approved elastic compute fabric on top of the existing GPU capability authority. Preserve all existing GPU observation, capability, worker identity, distributed allocation, fencing, engine verification, and fail-closed contracts.

## Task 1: Canonical provider and resource lifecycle

**Implemented files**
- `studio/compute_provider.py`
- `tests/test_compute_provider.py`

**Interfaces**
- Provider identity.
- Resource identity, lifecycle, acquisition expiry, cost classification, region metadata, worker identity, and capability digest.

**Behavior**
- Resources cannot become usable from discovery alone.
- Free status must be explicit.
- Expired resources leave active capacity.
- No artificial node-count ceiling.

## Task 2: Multi-provider discovery and acquisition contracts

**Implemented files**
- `studio/compute_acquisition.py`
- `tests/test_compute_acquisition.py`

**Interfaces**
- Provider adapter discovery, authorization, acquisition, and release.
- Acquisition manager consuming desired capacity.

**Behavior**
- Multiple provider adapters contribute resources simultaneously.
- Legitimate free resources are acquired through the adapter boundary.
- Provider failures are isolated.
- Acquisition can represent capacity above 12.

## Task 3: Hierarchical elastic scheduler

**Implemented files**
- `studio/fabric_scheduler.py`
- `tests/test_fabric_scheduler.py`

**Interfaces**
- Fabric planner above canonical GPU capability derivation.
- Existing `DistributedGpuAllocator` remains the final reservation and fencing authority.

**Behavior**
- Hard GPU requirements are filters.
- Provider resources must be available and worker-bound.
- GPU admission uses canonical capability records.
- Reliability and startup time participate in deterministic candidate ordering.
- No artificial node ceiling.
- Cross-provider NCCL placement fails closed until distributed cross-provider communication evidence exists.

## Task 4: Elastic capacity and recovery

**Implemented files**
- `studio/compute_capacity_controller.py`
- `studio/compute_recovery.py`
- `tests/test_compute_capacity_controller.py`
- `tests/test_compute_recovery.py`

**Behavior**
- 12 is the minimum verified capacity target, not a maximum.
- Acquired capacity is not falsely counted as verified capacity.
- Failed workers are excluded from recovery candidates.
- Recovery produces a new placement through the fabric scheduler rather than silently substituting an active allocation.

## Remaining implementation boundaries

1. Concrete provider adapters require legitimate provider APIs/accounts and are intentionally not fabricated.
2. Concrete provisioning requires provider-specific infrastructure and authenticated worker deployment.
3. Distributed cross-provider NCCL/GPU-direct execution requires real measured inter-provider fabric evidence before it can be admitted.
4. Control-plane persistence and phone-safe observability still need integration with the existing worker/control-plane persistence layer.
5. Final execution integration must feed fabric plans into `DistributedGpuAllocator` without creating a second reservation authority.

## Verification

- Focused elastic fabric suite: passed.
- Full repository test suite: passed.
- Provider fixtures remain fixtures and do not claim real provider capacity.
- CPU CI remains contract verification only. It does not claim physical CUDA/NCCL hardware verification.
