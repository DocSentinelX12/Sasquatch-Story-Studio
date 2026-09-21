# Elastic Multi-Provider Compute Fabric Implementation Plan

## Scope

Implement the approved elastic compute fabric on top of the existing GPU capability authority. Preserve all existing GPU observation, capability, worker identity, distributed allocation, fencing, engine verification, and fail-closed contracts.

## Task 1: Canonical provider and resource lifecycle

**Proposed files**
- Create: `studio/compute_provider.py`
- Create: `studio/compute_resources.py`
- Create: `tests/test_compute_provider.py`
- Create: `tests/test_compute_resources.py`

**Interfaces**
- Provider identity and authorization context.
- Resource identity, lifecycle, acquisition expiry, cost classification, region metadata, provisioning state, worker identity, capability digest, and reliability observations.
- Lifecycle: discovered, authorized, acquired, provisioned, verified, available, leased, executing, released, unavailable, quarantined.

**Behavior**
- Resources cannot become usable from discovery alone.
- Free status must be explicit and legitimate.
- Provider authorization failures are distinct from capacity absence.
- Expired resources leave active capacity.
- A provider failure does not invalidate resources from other providers.
- No artificial node-count ceiling.

**Tests**
- Lifecycle transitions.
- Provider isolation.
- Expiry.
- Authorization failure.
- Free-resource classification.
- 12-node minimum target semantics.
- 13, 100, and larger synthetic resource sets remain representable.

## Task 2: Multi-provider discovery, acquisition, and provisioning contracts

**Proposed files**
- Create: `studio/provider_adapters.py`
- Create: `studio/compute_acquisition.py`
- Create: `studio/compute_provisioning.py`
- Create: `tests/test_provider_adapters.py`
- Create: `tests/test_compute_acquisition.py`
- Create: `tests/test_compute_provisioning.py`

**Interfaces**
- Provider adapter discovery and acquisition interfaces.
- Acquisition manager consuming desired capacity and queued workload requirements.
- Provisioning manager producing authenticated workers ready for physical verification.

**Behavior**
- Multiple provider adapters may contribute resources simultaneously.
- Acquisition seeks enough legitimate resources to maintain the 12-node baseline when available.
- Acquisition can continue above 12 when workloads justify additional capacity and legitimate resources exist.
- Provider quotas, authorization, and lifecycle expiry are respected.
- Provisioning failure quarantines only the affected resource.
- Provisioning never claims GPU capability before worker-side verification.
- No provider-specific bypasses or invented credentials.

**Tests**
- Mixed-provider discovery.
- Acquisition from multiple providers.
- Partial provider outage.
- Provider quota exhaustion.
- Provisioning success/failure.
- Dynamic node joining.
- Capacity below, at, and above 12.
- No fixed maximum.

## Task 3: Hierarchical elastic scheduler

**Proposed files**
- Create: `studio/fabric_scheduler.py`
- Create: `studio/fabric_topology.py`
- Modify: existing scheduling entry points only to route eligible distributed workloads through the fabric scheduler.
- Create: `tests/test_fabric_scheduler.py`
- Create: `tests/test_fabric_topology.py`

**Interfaces**
- Global fabric scheduler selects eligible provider/resource groups.
- Fabric-domain scheduler selects compatible workers.
- Existing `DistributedGpuAllocator` remains final reservation/fencing authority.
- Fabric topology records communication domains and measured links.

**Behavior**
- Hard workload requirements are filters, never soft preferences.
- Candidate selection considers GPU compute, VRAM, CUDA compatibility, topology, NCCL, GPU-direct, network behavior, locality, startup time, reliability, resource expiry, current reservations, checkpoint cost, artifact transfer cost, and engine/model compatibility when relevant.
- Scheduling can combine providers for a workload when communication and workload requirements permit.
- Communication-intensive jobs prefer compatible fabric domains when evidence supports them.
- Cross-provider execution is rejected when required communication capability is absent rather than guessed.
- Scheduler remains scalable without an artificial node ceiling.
- Existing GPU UUID and lease constraints remain authoritative.

**Tests**
- Heterogeneous GPUs.
- Mixed-provider groups.
- Hard capability rejection.
- Communication-aware placement.
- Reliability-aware candidate selection.
- Resource-expiry avoidance.
- 12-node baseline and larger synthetic fabrics.
- Reservation collision and fencing preservation.

## Task 4: Elastic execution, recovery, and capacity controller

**Proposed files**
- Create: `studio/compute_capacity_controller.py`
- Create: `studio/compute_recovery.py`
- Modify: existing distributed execution integration only where required to consume fabric allocations.
- Create: `tests/test_compute_capacity_controller.py`
- Create: `tests/test_compute_recovery.py`

**Interfaces**
- Desired capacity controller.
- Worker health and heartbeat integration.
- Checkpoint-aware recovery planner.
- Provider/resource release interface.

**Behavior**
- Maintains desired minimum of 12 verified nodes whenever legitimate resources permit.
- Expands beyond 12 when queued work or explicit capacity policy justifies it.
- Detects lost workers and removes them from active capacity.
- Redistributes recoverable work to a newly verified eligible group.
- Never silently substitutes GPUs inside an active allocation.
- New allocations bind fresh worker, GPU, topology, communication, capability, lease, and fencing evidence.
- Releases temporary provider resources when no longer needed according to provider lifecycle rules.
- Keeps failed resources quarantined until fresh verification.

**Tests**
- Scale from 0 to 12 to above 12.
- Provider loss.
- Worker loss.
- Recovery onto another provider.
- Partial distributed failure.
- Checkpoint recovery.
- Lease expiry.
- No stale worker counted toward baseline.

## Task 5: Control-plane observability and phone-safe status surface

**Proposed files**
- Modify existing worker/control-plane status models as required.
- Create focused tests for capacity status and evidence provenance.

**Interfaces**
- Read-only status model for current verified node count, provider distribution, available GPUs, active leases, degraded providers, verification age, and recovery state.

**Behavior**
- Status distinguishes desired capacity from verified capacity.
- Reports provider/resource states without exposing secrets.
- Never represents unverified capacity as usable.
- Works when capacity is below 12.
- Shows elastic capacity above 12 without truncation or fixed-size assumptions.

**Tests**
- Accurate under provider failure.
- Accurate under stale evidence.
- Accurate during acquisition.
- Accurate above 12 nodes.
- No credential leakage.

## Task 6: Integration and production truth gates

**Files**
- Modify existing production scheduling and runtime verification boundaries only where needed.
- Add focused integration tests.

**Behavior**
- Canonical GPU capability authority remains the sole GPU admission authority.
- DistributedGpuAllocator remains the final reservation/fencing authority.
- Physical CUDA/NCCL/GPU-direct verification remains hardware-backed.
- CPU CI cannot claim physical GPU capacity.
- Provider fixtures cannot claim real provider capacity.
- Multi-node verification requires real participating workers.

**Verification**
- Focused provider/fabric suite.
- Existing GPU capability and distributed suites.
- Full repository test suite.
- Packaging validation.
- Static inspection for artificial node-count limits and parallel admission paths.
- Hardware-required tests run only on actual NVIDIA infrastructure.

## Explicit unresolved product decisions

1. Provider-specific adapters require concrete provider APIs/accounts before they can perform real acquisition. The architecture defines the interface but does not invent provider access.
2. The exact policy for when to scale above 12 nodes should be workload-driven by default. Any additional user-configurable budget or quota policy is a separate product decision.
3. Cross-provider distributed communication remains capability-dependent. Providers may be combined for independent or weakly coupled work even when they cannot form a valid high-bandwidth distributed fabric.
