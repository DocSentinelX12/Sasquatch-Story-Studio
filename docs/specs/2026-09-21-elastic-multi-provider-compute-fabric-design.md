# Elastic Multi-Provider Compute Fabric Design

## Status

Approved architectural direction. This document extends the GPU capability architecture with an elastic compute fabric that can assemble verified free compute from multiple legitimate providers.

## Goals

- Maintain a target baseline of at least 12 verified compute nodes whenever sufficient legitimate capacity exists.
- Permit unbounded expansion at the software architecture level. There is no arbitrary maximum node count.
- Combine heterogeneous NVIDIA CUDA capable resources from multiple legitimate providers.
- Treat provider identity, authorization, terms, resource lifecycle, reliability, and observed capability as first-class data.
- Discover, acquire, provision, verify, admit, lease, execute, monitor, recover, and release compute without requiring the creator to own a compute machine.
- Optimize placement using workload requirements and measured capabilities rather than node count alone.
- Fail closed on unverified hardware or unsupported capabilities.
- Preserve the existing GPU capability authority and distributed allocation/fencing model.
- Keep the phone as a control-plane client only.

## Non-Goals

- Fabricating capacity when fewer than 12 legitimate verified nodes are available.
- Treating CPU GitHub-hosted runners as physical NVIDIA GPU verification.
- Bypassing provider authorization, quotas, terms, or authentication.
- Locking the system to one provider.
- Imposing a software maximum such as 12, 100, or 500 nodes.

## Architecture

The fabric is hierarchical:

1. **Control plane**
   Maintains desired capacity, workload requirements, provider policies, resource inventory, leases, evidence, health, and recovery state. The phone communicates with this plane and never acts as a compute worker.

2. **Provider adapters**
   Each adapter discovers and acquires only resources that are legitimately available to the configured account or provider interface. Adapters expose a common lifecycle interface and never assert hardware capability without worker-side verification.

3. **Resource acquisition manager**
   Continuously evaluates legitimate available capacity against the desired baseline and queued workloads. It may combine resources across providers and may use more than the baseline when useful and available.

4. **Provisioning manager**
   Installs or activates the worker agent and required runtime components, establishes authenticated identity, and triggers capability verification.

5. **Worker agents**
   Observe physical hardware and runtime state, execute verification probes, report immutable evidence, receive leases, execute work, stream telemetry, and support checkpoint/recovery.

6. **Capability authority**
   The existing canonical GPU capability layer remains authoritative for GPU admission. Provider and node metadata augment it but cannot override physical evidence.

7. **Topology and fabric registry**
   Records node-local topology, inter-node links, measured network characteristics, NCCL evidence, GPU-direct evidence, locality, and communication domains.

8. **Hierarchical scheduler**
   A global scheduler first selects provider/resource groups and fabric domains, then regional/fabric schedulers select workers and GPUs, and finally the existing GPU allocator performs exact reservations and fencing.

9. **Execution and recovery**
   Distributed jobs bind to exact worker IDs, GPU UUIDs, capability/evidence digests, ranks, leases, and fencing epochs. Checkpoints and artifact transport allow recovery when a node or provider disappears.

## Capacity Semantics

`minimum_verified_nodes = 12` is a desired minimum baseline, not a claim that capacity exists.

`maximum_verified_nodes` is unbounded by software architecture.

The scheduler may use any number of verified nodes above 12 when workload requirements and available resources justify it. A cluster with fewer than 12 verified nodes remains explicitly under target rather than being represented as a complete 12-node cluster.

A node counts toward the baseline only after worker identity, physical GPU observation, required health, CUDA/runtime, and workload-relevant capabilities have been verified.

## Multi-Provider Resource Model

Every resource belongs to a provider record containing:

- provider identity
- authorization/account context
- resource identifier
- lifecycle state
- quota/availability information when legitimately observable
- acquisition timestamp and expiry
- region/location metadata when legitimately supplied
- cost classification
- provider reliability observations
- provisioning method
- worker identity binding
- capability/evidence references

Free resources are accepted only when their zero-cost availability is legitimate under the provider's applicable access model. The system must not automate abuse, evade quotas, bypass authentication, or misrepresent identity.

Providers are not required to expose identical hardware. The scheduler compares actual capabilities and measured behavior.

## Intelligent Placement

Placement is multi-objective. The scheduler considers, where relevant:

- GPU model and compute capability
- available and total VRAM
- CUDA and driver compatibility
- GPU utilization and health
- temperature, power, ECC, MIG, XID, PCIe, NVLink
- intra-node topology
- inter-node topology
- NCCL capability and measured communication
- GPU-direct capability
- network bandwidth and latency
- CPU and system memory
- local storage and model/cache locality
- worker startup time
- provider availability and resource expiry
- reliability and recent failure history
- current reservations
- checkpoint/restart cost
- artifact transfer cost
- workload parallelism and communication intensity
- engine/model compatibility

The objective is not a single static score. Workload requirements define hard constraints. Among eligible candidates, scheduling heuristics may optimize estimated execution time, communication cost, startup cost, reliability, and resource waste.

## Elastic Lifecycle

`discovered -> authorized -> acquired -> provisioned -> identified -> health_verified -> topology_verified -> communication_verified -> engine_verified -> production_eligible -> available -> leased -> executing -> result_verified -> released`

Failure or disappearance transitions resources to an unavailable/quarantined state until fresh verification succeeds.

Acquisition failure does not invalidate already verified resources from other providers.

## Distributed Execution

Distributed workloads are planned across compatible workers and communication domains.

The global scheduler chooses a feasible fabric group. The regional/fabric scheduler chooses exact workers. The existing `DistributedGpuAllocator` remains the final atomic reservation authority.

Every distributed allocation binds:

- task ID
- worker IDs
- exact GPU UUIDs
- ranks
- hardware observation digests
- topology evidence digests
- NCCL evidence when required
- GPU-direct evidence when required
- lease expiry
- fencing epoch

A node cannot be substituted silently after execution begins. Recovery creates a new explicitly verified allocation.

## Failure and Recovery

The system must handle:

- provider capacity disappearing
- worker startup failure
- worker authentication failure
- GPU verification failure
- stale capability evidence
- network degradation
- NCCL failure
- GPU-direct failure
- worker heartbeat loss
- provider-level outage
- partial distributed job failure

A failed worker is removed from active capacity immediately according to observed heartbeat/lease state. Checkpointed work is rescheduled onto another eligible group when the workload supports recovery.

The system must never count a failed or stale worker toward the 12-node baseline.

## Security and Trust

Provider credentials remain outside worker-reported capability evidence.

Workers authenticate to the control plane. Hardware identity is immutable for the evidence lifetime. Capability evidence is bound to the observed GPU identity and freshness window.

Provider adapters may request or manage resources only through legitimate configured authorization. No provider-specific bypass is part of the architecture.

## Testing and Truth Boundaries

CPU CI tests contracts, lifecycle state machines, scheduling logic, persistence, failure handling, and deterministic evidence binding.

Physical NVIDIA verification requires an actual NVIDIA environment.

Multi-node NCCL and GPU-direct verification requires actual participating workers and network paths.

Provider integration tests use explicit provider fixtures or provider-supported test/sandbox environments. A fixture cannot claim real provider capacity.

Scaling tests must verify that the scheduler has no artificial node-count ceiling and can reason about at least the 12-node baseline plus larger synthetic fabrics.

## Integration Boundary

This fabric extends the existing GPU capability architecture. It does not replace:

- `GpuObservation`
- `GpuCapabilityRecord`
- canonical capability admission
- `DistributedGpuAllocator`
- worker identity and fencing
- existing engine verification contracts

New provider/acquisition/scheduling layers must route through those existing authorities rather than creating parallel admission or reservation systems.
