# Sasquatch Story Studio Supercomputer Architecture

## Status

This document is the approved target architecture for the Studio's GPU infrastructure.

It is an architecture target, not a claim that the physical hardware currently exists.
The Studio must discover and verify real hardware before advertising or scheduling any
capacity. No fake GPU inventory, placeholder hardware, guessed capacity, or simulated
production capability is permitted.

## Design objective

Build the most advanced NVIDIA-oriented GPU infrastructure that the Studio's software
can safely support while preserving the existing production foundation, zero-recurring-
cost policy, verified-engine requirements, provenance, resumability, and failure-safe
execution model.

The software must be hardware-generation agnostic. It should be able to use a future
NVIDIA accelerator that exceeds the reference architecture without requiring a rewrite.

## Reference architecture

The current NVIDIA Vera Rubin reference architecture establishes a 72-GPU NVL72 rack-
scale AI supercomputer. NVIDIA documents the Vera Rubin POD as five rack-scale systems
with 1,152 Rubin GPUs. The Studio therefore treats a 1,152-GPU POD as the reference
unit for a maximum-scale supercomputer cell, rather than limiting the design to an
8-GPU server.

Reference target per Studio supercomputer cell:

- 1,152 NVIDIA Rubin-class GPUs
- 16 x 72-GPU NVLink domains
- NVLink 6 scale-up inside each domain
- high-speed GPU-direct scale-out fabric between domains
- NVIDIA Vera-class CPU infrastructure
- NVIDIA ConnectX-class SuperNICs
- NVIDIA BlueField-class DPUs
- NVIDIA Spectrum-X-class scale-out networking
- liquid-cooled rack-scale infrastructure where required by the physical platform
- GPU-aware storage and artifact fabric
- redundant control, scheduling, health, and data-plane services

This is a software architecture target. The actual registered hardware may be smaller,
different, or a later NVIDIA generation. The scheduler must use observed capabilities,
not this target document, when admitting work.

## Six supercomputer cells

The Studio reserves six independent supercomputer cells:

| Cell | Target role | Reference scale |
| --- | --- | --- |
| Node A | primary extreme-model production | 1,152 GPUs |
| Node B | independent extreme-model production | 1,152 GPUs |
| Node C | large-model and multi-GPU production | 1,152 GPUs |
| Node D | high-throughput animation production | 1,152 GPUs |
| Node E | high-throughput animation and media production | 1,152 GPUs |
| Node F | overflow, redundancy, recovery, and production | 1,152 GPUs |

The six cells represent a maximum architectural target of 6,912 GPUs. This number is
never treated as current capacity unless real worker registration and hardware probes
establish it.

## Hierarchy

The Studio must model compute at every level:

GPU -> GPU group -> NVLink domain -> supercomputer cell -> multi-cell cluster.

A workload may therefore request one GPU, a topology-qualified group of GPUs, a complete
NVLink domain, multiple NVLink domains, one supercomputer cell, or a coordinated set of
cells.

## GPU admission requirements

A GPU worker cannot enter production capacity merely because a process reports that
CUDA is installed. Admission requires observed evidence for, as applicable:

- GPU identity and UUID
- exact GPU model
- memory capacity
- CUDA driver/runtime compatibility
- compute capability
- health state
- temperature and power telemetry
- ECC or equivalent memory-health information where exposed
- PCIe topology
- NVLink topology and link health where exposed
- NCCL availability and compatibility where required
- network interfaces and GPU-direct capability where required
- local scratch capacity
- installed engine and model revisions
- license and model-policy eligibility

Missing evidence must reduce capability or prevent admission. It must never be filled
with guessed defaults.

## Scale-up

Within a topology-qualified GPU group, the scheduler must understand the difference
between ordinary PCIe-connected GPUs and GPUs belonging to the same NVLink domain.

For distributed workloads, topology is a placement requirement, not a descriptive hint.
The scheduler must not place a topology-sensitive job across an arbitrary set of GPUs.

## Scale-out

Multi-domain and multi-cell execution requires explicit distributed-job semantics:

- worker group identity
- world size
- rank allocation
- rendezvous information
- network-interface selection
- NCCL capability evidence
- topology evidence
- lease generation
- coordinated start
- coordinated cancellation
- failure and retry semantics
- artifact ownership and final commit semantics

An engine that does not explicitly declare distributed execution support must remain a
single-worker execution target even when more GPUs are available.

## Storage and data movement

The existing content-addressed artifact/data plane remains authoritative. The
supercomputer fabric must add transport around it rather than replace it.

Large models and generated artifacts must support:

- content hashes
- chunk hashes
- resumable transfer
- interruption recovery
- final integrity verification
- local model caching
- cache provenance
- deduplicated immutable artifacts

A disconnected Android client must not interrupt an executing production job.

## Health and fault handling

NVIDIA DCGM is the preferred NVIDIA-aware host health and inventory integration where
available, with truthful `nvidia-smi` and other supported local probes as fallbacks.

Health observation, readiness validation, and destructive/diagnostic testing are separate
operations. Heavy diagnostics must never run against GPUs that are currently executing
production work.

A worker with failed health evidence must be quarantined from new production leases.
Existing work must follow explicit failure and recovery rules.

## Security boundary

The worker network is a production trust boundary. Future remote workers must use real
transport security and authenticated registration. Enrollment credentials and private
keys must never be committed to the repository.

The Android control surface is a control-plane client. It is not a compute worker and is
not required to stay connected while production executes.

## Authoritative lifecycle

The authoritative production flow remains:

Production State -> Coordinator -> Compute Broker -> Placement -> Worker Lease ->
Verified Engine -> Artifact Commit -> Provenance -> Production State transition.

The supercomputer layer must not replace the canonical episode, scene, shot, asset, job,
or approval graph.

## Zero-cost rule

This architecture does not authorize paid cloud GPU services, paid APIs, subscriptions,
credits, or per-generation services.

Remote compute is usable only when it is genuinely available under the Studio's existing
zero-recurring-cost policy. The software must not silently introduce a paid dependency.

Physical NVIDIA supercomputer hardware, electrical power, cooling, networking, and data-
center infrastructure are real-world requirements. The Studio must never claim that such
hardware has been obtained merely because the software supports it.

## Implementation order

The architecture is implemented incrementally and safely:

1. CUDA/GPU resource contract and truthful hardware probe.
2. NVIDIA-aware inventory, health, driver/runtime, topology, and evidence.
3. One authoritative worker registry, preserving compatibility where required.
4. Real GPU worker agent and lifecycle state machine.
5. Authenticated network registration, heartbeat, and remote leases.
6. Resumable network artifact transport around the existing content-addressed data plane.
7. Engine/model hardware placement requirements.
8. GPU-level allocation, NVLink-aware placement, and CUDA device binding.
9. NCCL capability verification and multi-GPU execution semantics.
10. Multi-node coordination, failure recovery, and distributed-job lifecycle.
11. Authoritative production lifecycle integration.
12. Android control API and reconnect-safe control operations.
13. Full integration verification against actual `main`.
14. Final production runtime evidence only after infrastructure and model paths are verified.

Video evidence remains a final-phase activity and is not part of infrastructure/model
installation verification.

## Non-negotiable engineering rules

- `main` is the only development and integration branch.
- No pull requests for Studio development.
- No feature branches or stacked branches.
- Inspect every connected path before changing it.
- Make the smallest safe change that satisfies the requirement.
- Never weaken or delete tests to obtain green CI.
- Never manufacture hardware, model, runtime, health, or production evidence.
- Never replace a working production contract without tracing every consumer first.
- Verify affected behavior and then the relevant full matrix before declaring completion.
