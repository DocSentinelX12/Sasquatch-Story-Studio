# GPU Capability Architecture Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Sasquatch-Story-Studio from raw NVIDIA host observations and fragmented placement checks to an evidence-backed GPU capability system with NVML-first telemetry, explicit provenance and freshness, workload-specific admission, unified placement authority, and a clean boundary for real CUDA/NCCL/GPU-direct verification.

**Architecture:** Preserve `GpuHostObservation` as the physical evidence record, extend it with explicit per-field telemetry/provenance/freshness, and derive a new canonical `GpuCapabilityRecord` that owns capability state and admission decisions. Existing schedulers, allocators, worker identity, leases, fencing, topology, NCCL, network evidence, and runtime verification remain intact, but their GPU eligibility decisions flow through the canonical capability/admission layer.

**Tech Stack:** Python 3.11+, standard library dataclasses/enums/subprocess, optional NVIDIA NVML integration with explicit `nvidia-smi` fallback, SQLite persistence already used by the worker registry, pytest, GitHub Actions.

## Global Constraints

- Canonical telemetry collection uses **NVML first**, with **nvidia-smi fallback** only when NVML cannot provide a required observation.
- Admission uses a **hybrid model**: every GPU must satisfy a strict base hardware admission contract, while workload-specific capabilities are required only when applicable.
- Existing `GpuObservation`/host observation remains the physical evidence layer; introduce a canonical `GpuCapabilityRecord` derived from verified observations.
- Existing GPU placement, distributed allocation, worker identity, leasing, fencing, topology, NCCL, GPU-direct/network evidence, artifact transport, and runtime verification are preserved.
- Consolidation occurs through authoritative interfaces, not deletion or weakening.
- Missing, unsupported, stale, failed, or contradictory evidence never satisfies a required capability.
- No telemetry value is fabricated.
- Software-only CI must not claim physical NVIDIA GPU, CUDA, NCCL, GPU-direct, or multi-node verification.
- Physical verification must remain separately executable on actual NVIDIA hardware.
- Existing safety behavior, collision protection, lease expiry, fencing, and recovery semantics must remain intact.
- GPU identity remains anchored to worker identity and immutable GPU UUID evidence.
- The implementation must improve placement efficiency by filtering known-busy/ineligible GPUs before allocation where the architecture permits, without removing collision checks.
- No test may be weakened, deleted, bypassed, or changed merely to make implementation pass.
- The approved architecture does not create fictional 12-node/6,912-GPU capacity. That remains a physical deployment target.

---

### Task 1: Make physical GPU observation production-grade and NVML-first

**Files:**
- Modify: `studio/gpu_infrastructure.py`
- Test: `tests/test_gpu_infrastructure.py`
- Test: proposed `tests/test_gpu_telemetry.py` if focused telemetry coverage cannot remain readable in the existing infrastructure test module
- Inspect/modify only if required by serialization compatibility: `studio/worker_registry.py`, `studio/gpu_worker_agent.py`, `studio/worker_control_plane.py`

**Interfaces:**
- Consumes: existing `GpuDeviceObservation`, `GpuHostObservation`, `probe_nvidia_host`, topology parser, and existing NCCL/network evidence types.
- Produces: an expanded immutable observation model containing explicit per-GPU telemetry/evidence provenance and collection freshness, plus an NVML-first probe path with explicit `nvidia-smi` fallback.
- Existing `GpuHostObservation.digest()` and canonical serialization remain deterministic after the model extension.

- [ ] **Step 1: Add focused failing tests**

Cover:
1. NVML supplies all supported fields and is selected before `nvidia-smi`.
2. NVML cannot provide one required observation and the fallback path is explicitly recorded as `nvidia-smi`, rather than silently merging an unmarked source.
3. NVML is unavailable and the complete fallback path records `nvidia-smi` provenance.
4. Temperature, power usage/state, utilization, memory utilization, ECC state/error evidence, MIG state, NVLink state, PCIe information, XID/error evidence, DCGM evidence, collection timestamp, collector identity, and freshness are represented as observed/unsupported/unavailable/error rather than fabricated values.
5. Missing optional vendor fields remain explicit unavailable states.
6. An observation with stale telemetry cannot be treated as fresh.
7. Canonical JSON and digest remain deterministic.
8. GPU UUID identity and inventory uniqueness remain enforced.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_gpu_infrastructure.py tests/test_gpu_telemetry.py`

Expected: new tests fail because the current observation model has no canonical telemetry evidence model and `probe_nvidia_host` is currently nvidia-smi-only.

- [ ] **Step 3: Implement the minimum behavior**

Introduce explicit machine-readable observation structures rather than loose dictionaries. Recommended implementation boundary:
- Keep `GpuDeviceObservation` as the stable identity/inventory object and attach a dedicated immutable telemetry/evidence record to each GPU.
- Represent unavailable/unsupported/error states explicitly with provenance and timestamps instead of null-as-success semantics.
- Add a collector abstraction whose preferred implementation uses NVML when importable and usable.
- Keep `nvidia-smi` as an explicit fallback collector.
- Record the collector/source for every observation and the collection timestamp.
- Preserve the current topology parser and its fail-closed behavior.
- Do not require optional fields merely because a platform may expose them.
- Do not introduce a hard dependency that prevents software-only tests from importing the package.
- Preserve the existing no-synthetic-capacity rule.
- Update serialization/deserialization and identity digest inputs so persisted observations retain the new evidence without losing backward safety. Older persisted observations that lack newly introduced fields must remain explicitly incomplete, not automatically upgraded to verified values.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_gpu_infrastructure.py tests/test_gpu_telemetry.py`

Expected: all focused observation/telemetry tests pass, including NVML-first ordering and explicit fallback provenance.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_gpu_worker_agent.py tests/test_gpu_worker_agent_remote.py tests/test_worker_registry_gpu_persistence.py`

Expected: worker payloads and SQLite persistence round-trip the expanded observation without fabricating verification state.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/gpu_infrastructure.py studio/worker_registry.py studio/gpu_worker_agent.py studio/worker_control_plane.py tests/test_gpu_infrastructure.py tests/test_gpu_telemetry.py
git commit -m "feat: add evidence-backed NVIDIA GPU telemetry"
```

---

### Task 2: Introduce the canonical GPU capability record and admission engine

**Files:**
- Create: `studio/gpu_capabilities.py`
- Modify: `studio/hardware_requirements.py`
- Test: `tests/test_gpu_capabilities.py`
- Test: `tests/test_hardware_requirements.py`
- Inspect/modify for capability persistence only if needed: `studio/worker_registry.py`

**Interfaces:**
- Consumes: `GpuHostObservation`, per-GPU telemetry/evidence, `GpuTopologyEvidence`, `NCCLTestEvidence`, `NetworkFabricObservation`, existing engine verification records, and `HardwareRequirements`.
- Produces: canonical `GpuCapabilityRecord`, capability verification state, capability evidence references, freshness evaluation, and workload admission decisions.
- Proposed public interfaces:
  - `GpuCapabilityState`
  - `GpuCapabilityRecord`
  - `GpuCapabilitySet`
  - `derive_gpu_capabilities(observation, now, verification_context)`
  - `admit_gpu_workload(requirements, capabilities, now)`
- The exact field names should follow existing repository naming conventions after implementation inspection, but the semantic contract must remain explicit and immutable.

- [ ] **Step 1: Add focused failing tests**

Cover:
1. A physically observed GPU can be discovered/identified without being production eligible.
2. A healthy single-GPU capability can become eligible when the strict base contract and required runtime/engine evidence are present.
3. Missing health evidence cannot satisfy a health requirement.
4. Missing topology cannot satisfy a topology/NVLink requirement.
5. Missing NCCL evidence cannot satisfy a multi-GPU/NCCL requirement.
6. Missing GPU-direct evidence cannot satisfy GPU-direct requirements.
7. Stale evidence cannot satisfy current admission.
8. Failed evidence invalidates only the dependent capability while preserving unrelated valid capabilities.
9. Contradictory identity or evidence cannot produce a capability pass.
10. Multi-GPU workloads require the exact selected GPU set to be covered by relevant evidence.
11. Capability lifecycle states distinguish observed, verified, and production-eligible conditions.
12. A single-GPU workload does not require distributed NCCL evidence unless its requirements explicitly request it.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_gpu_capabilities.py tests/test_hardware_requirements.py`

Expected: the capability tests fail because no canonical capability record/admission engine currently exists.

- [ ] **Step 3: Implement the minimum behavior**

Create the canonical capability layer:
- Define explicit capability names for base availability, CUDA/runtime compatibility, health, topology/NVLink, NCCL, GPU-direct/network, and engine runtime capability.
- Give each capability an explicit state plus evidence provenance and verification/freshness timestamps.
- Derive capability state only from evidence already present or explicitly verified by a verifier.
- Treat unknown, unavailable, stale, failed, or contradictory evidence as non-admissible for requirements that depend on it.
- Preserve unrelated capabilities when one capability fails.
- Add workload requirement helpers only where they reduce duplicated admission logic. Do not silently reinterpret existing `HardwareRequirements` fields.
- Keep `HardwareRequirements` as the workload contract and make the canonical admission function the single place that maps those requirements to capability state.
- Do not mark NCCL or GPU-direct as verified from configuration, GPU count, topology text, or interface presence alone.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_gpu_capabilities.py tests/test_hardware_requirements.py`

Expected: all capability lifecycle, freshness, evidence-binding, and workload-specific admission tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_nccl_evidence.py tests/test_gpu_infrastructure.py tests/test_worker_registry_gpu_persistence.py`

Expected: existing evidence contracts and observation persistence remain passing while capability derivation remains fail-closed.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/gpu_capabilities.py studio/hardware_requirements.py tests/test_gpu_capabilities.py tests/test_hardware_requirements.py
git commit -m "feat: add canonical GPU capability admission"
```

---

### Task 3: Route placement and scheduling through the canonical capability authority

**Files:**
- Modify: `studio/gpu_placement.py`
- Modify: `studio/gpu_scheduler.py`
- Modify: `studio/gpu_aware_scheduler.py`
- Modify: `studio/distributed_gpu_scheduler.py`
- Modify: `studio/distributed_gpu.py` only where capability admission must precede existing reservation/fencing logic
- Test: `tests/test_gpu_scheduler.py`
- Test: `tests/test_gpu_aware_scheduler.py`
- Test: `tests/test_distributed_gpu_scheduler.py`
- Test: existing distributed allocator tests covering `DistributedGpuAllocator`

**Interfaces:**
- Consumes: canonical capability/admission interfaces from Task 2 plus existing `GpuHostObservation` and network/NCCL evidence.
- Produces: placement decisions based on canonical capability eligibility, while existing allocators remain authoritative for reservations, leases, fencing, and collision protection.
- `DistributedGpuAllocator` remains the authoritative distributed reservation authority.
- Existing public placement functions remain callable for compatibility, but delegate eligibility decisions rather than maintaining independent capability rules.

- [ ] **Step 1: Add focused failing tests**

Cover:
1. Single-node placement excludes GPUs that are already allocated before attempting scheduler leasing where allocation state is available.
2. Placement does not select a GPU whose required capability is unknown, stale, failed, or unavailable.
3. Same-NVLink placement uses canonical topology capability rather than reparsing raw topology independently.
4. NCCL-required placement consumes exact evidence coverage through canonical admission.
5. GPU-direct-required placement remains rejected until explicit GPU-direct evidence exists.
6. A valid alternative free GPU is selected instead of choosing a busy GPU and allowing the lower scheduler layer to reject it.
7. Existing GPU UUID collision protection remains intact.
8. Existing distributed worker selection still spans distinct workers and preserves exact worker/GPU mappings.
9. Existing fencing, expiry, and durable reservation semantics remain unchanged.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_gpu_scheduler.py tests/test_gpu_aware_scheduler.py tests/test_distributed_gpu_scheduler.py`

Expected: new delegation/eligibility tests fail because placement modules currently contain independent hardware/NCCL checks and `GpuAwareScheduler` can select before the lower lease layer rejects contention.

- [ ] **Step 3: Implement the minimum behavior**

- Make canonical capability admission the eligibility gate.
- Keep existing placement modules as compatibility facades around that authority.
- Remove duplicated eligibility logic only after equivalent behavior is routed through the canonical authority. Do not remove public functionality.
- Make free/busy GPU information an input to candidate filtering where the scheduler has authoritative allocation knowledge.
- Preserve `DistributedGpuAllocator` reservation and SQLite uniqueness as the final concurrency boundary.
- For distributed selection, require canonical per-worker capabilities before building the existing allocation plan.
- Preserve exact NCCL and GPU-direct evidence matching already enforced by the distributed allocator.
- Do not infer physical availability from resource counters alone when GPU evidence says otherwise.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_gpu_scheduler.py tests/test_gpu_aware_scheduler.py tests/test_distributed_gpu_scheduler.py`

Expected: all focused placement/scheduling tests pass, including alternative-GPU selection and fail-closed capability filtering.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_distributed_gpu.py tests/test_distributed_gpu_scheduler.py tests/test_gpu_scheduler_nccl.py tests/test_verified_distributed_runtime.py`

Expected: distributed allocation, exact evidence binding, fencing, and verified launch contracts remain passing.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/gpu_placement.py studio/gpu_scheduler.py studio/gpu_aware_scheduler.py studio/distributed_gpu_scheduler.py studio/distributed_gpu.py tests/test_gpu_scheduler.py tests/test_gpu_aware_scheduler.py tests/test_distributed_gpu_scheduler.py
git commit -m "refactor: route GPU placement through capability admission"
```

---

### Task 4: Bind worker admission and real verification boundaries to capabilities

**Files:**
- Modify: `studio/gpu_worker_agent.py`
- Modify: `studio/worker_control_plane.py`
- Modify: `studio/worker_registry.py`
- Modify: `studio/runtime_verification.py` only for explicit GPU capability evidence linkage
- Modify: `studio/verified_distributed_runtime.py` only where production admission must consume the canonical capability record
- Test: `tests/test_gpu_worker_agent.py`
- Test: `tests/test_gpu_worker_agent_remote.py`
- Test: worker control/registry GPU evidence tests
- Test: `tests/test_runtime_verification.py`
- Test: `tests/test_verified_distributed_runtime.py`

**Interfaces:**
- Consumes: worker observations, canonical capability records, existing immutable hardware identity digest, engine verification records, distributed evidence, and authenticated worker lifecycle.
- Produces: worker admission state derived from capability eligibility, persisted capability/evidence linkage, and explicit production verification prerequisites.
- Existing `WorkerAccess`, registration, heartbeat, revocation, identity digest, and authenticated transport contracts remain intact.

- [ ] **Step 1: Add focused failing tests**

Cover:
1. Worker registration persists the canonical capability state derived from the observation.
2. Worker state cannot become fully verified merely because DCGM reports healthy if required base capability evidence is missing.
3. A worker with only inventory evidence remains limited/unverified for capabilities that require health or runtime verification.
4. Hardware identity mutation invalidates dependent capability evidence.
5. Stale heartbeat evidence cannot refresh a capability without fresh collection timestamps.
6. Engine verification can satisfy only the named engine capability and cannot silently certify unrelated GPU-direct/NCCL capabilities.
7. Verified distributed launch requires both the existing engine verification record and canonical GPU capabilities for the allocation.
8. Revocation/offline transitions preserve capability evidence for audit but prevent production eligibility.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_gpu_worker_agent.py tests/test_gpu_worker_agent_remote.py tests/test_runtime_verification.py tests/test_verified_distributed_runtime.py`

Expected: new capability-linked worker admission assertions fail because `WorkerControlPlane._state()` currently derives broad availability primarily from DCGM health and does not consult a canonical capability record.

- [ ] **Step 3: Implement the minimum behavior**

- Derive capabilities during registration/heartbeat after authenticated observation and identity validation.
- Persist the capability record or a deterministic capability/evidence representation alongside the worker observation.
- Replace broad worker availability decisions with capability-aware state while preserving existing state enum meanings and lifecycle transitions.
- Keep the immutable hardware identity digest as the authority for hardware identity binding.
- Link engine verification evidence to the exact GPU capability requirements it establishes.
- Keep physical NCCL and GPU-direct verification separate from configuration evidence.
- Do not turn CPU-only runtime verification into GPU verification.
- Ensure production execution consumes capability admission rather than merely a worker's generic `healthy` flag.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_gpu_worker_agent.py tests/test_gpu_worker_agent_remote.py tests/test_runtime_verification.py tests/test_verified_distributed_runtime.py`

Expected: worker registration/heartbeat, identity binding, engine verification, and production admission tests pass with explicit capability state.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_worker_registry_gpu_persistence.py tests/test_worker_registry_gpu_evidence_persistence.py tests/test_worker_hardware_observation.py tests/test_verified_distributed_runtime.py`

Expected: persisted worker identity/evidence and distributed runtime contracts remain intact.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/gpu_worker_agent.py studio/worker_control_plane.py studio/worker_registry.py studio/runtime_verification.py studio/verified_distributed_runtime.py tests/test_gpu_worker_agent.py tests/test_gpu_worker_agent_remote.py tests/test_runtime_verification.py tests/test_verified_distributed_runtime.py
git commit -m "feat: bind worker admission to GPU capabilities"
```

---

### Task 5: Add real hardware verification entry points and CI truth boundaries

**Files:**
- Create: `scripts/verify_gpu_runtime.py`
- Create: `scripts/verify_nccl_runtime.py`
- Create: `scripts/verify_gpu_direct.py`
- Create: `.github/workflows/gpu-runtime-verification.yml` as a manually dispatched or explicitly GPU-labelled workflow that requires a real NVIDIA runner
- Modify: `.github/workflows/real-blender-runtime.yml` only if shared runner/version conventions require alignment
- Test: `tests/test_gpu_runtime_verification.py`
- Test: `tests/test_nccl_runtime_verification.py`
- Test: `tests/test_gpu_direct_verification.py`
- Modify: `docs/specs/2026-09-20-gpu-capability-architecture-design.md` only if implementation details need documentation correction

**Interfaces:**
- Consumes: canonical observation/capability records, actual CUDA/NVIDIA runtime, existing NCCL evidence contract, existing network evidence contract, and verified engine runtime boundary.
- Produces: immutable runtime verification evidence with executable/version/output digests and capability-specific verification state.
- CPU-only CI continues testing parsers, contracts, fixtures, and failure handling but never emits a claim of physical GPU/NCCL/multi-node success.

- [ ] **Step 1: Add focused failing tests**

Cover script-level contracts without pretending to execute NVIDIA hardware on CPU runners:
1. GPU runtime verifier refuses to run without an actual NVIDIA device/runtime.
2. CUDA runtime verification records the actual executable/version/output evidence.
3. NCCL verifier requires the exact selected GPU UUID set and successful collective result.
4. NCCL failure produces failed/non-eligible evidence.
5. GPU-direct verifier requires explicit network interface/GPU pair evidence and successful runtime result.
6. Evidence includes command, executable digest where applicable, output digest, worker identity, GPU UUIDs, topology linkage, and timestamps.
7. A CPU-only runner cannot generate a successful physical verification record.
8. Existing fixture-based NCCL/topology tests remain valid and clearly labelled as contract tests.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_gpu_runtime_verification.py tests/test_nccl_runtime_verification.py tests/test_gpu_direct_verification.py`

Expected: new tests fail because real hardware verification entry points do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

- Add explicit runtime probes for CUDA and NCCL that execute real configured binaries and hash their outputs.
- Use actual GPU UUIDs from the physical observation and reject any result whose GPU set cannot be bound to the observation.
- Generate capability-specific evidence only after successful runtime execution.
- Require real NVIDIA hardware for physical verification.
- Keep hardware verification separate from GitHub-hosted CPU CI.
- Make the GPU workflow explicitly depend on a runner label that denotes actual NVIDIA hardware. The workflow must fail if that runner does not expose the required hardware rather than falling back to CPU.
- Do not fabricate a 12-node cluster or multi-node result. Multi-node verification remains a separate execution stage requiring actual participating workers.
- Do not change CPU-only CI to claim GPU success.

- [ ] **Step 4: Verify the focused pass**

Run on CPU CI: `python -m pytest -q tests/test_gpu_runtime_verification.py tests/test_nccl_runtime_verification.py tests/test_gpu_direct_verification.py`

Expected: contract and negative-path tests pass, while physical execution tests are skipped only when explicitly marked hardware-required and the workflow cannot provide NVIDIA hardware.

Run on a real NVIDIA runner: `python scripts/verify_gpu_runtime.py` and `python scripts/verify_nccl_runtime.py`

Expected: successful commands produce evidence tied to real GPU UUIDs, real runtime output, and current observation digests.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_gpu_capabilities.py tests/test_gpu_scheduler.py tests/test_distributed_gpu.py tests/test_nccl_evidence.py tests/test_verified_distributed_runtime.py`

Expected: the canonical capability layer consumes verification evidence without changing existing distributed safety contracts.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add scripts/verify_gpu_runtime.py scripts/verify_nccl_runtime.py scripts/verify_gpu_direct.py .github/workflows/gpu-runtime-verification.yml tests/test_gpu_runtime_verification.py tests/test_nccl_runtime_verification.py tests/test_gpu_direct_verification.py
git commit -m "feat: add truthful GPU runtime verification boundary"
```

---

## Final Verification Gate

After all five tasks are independently passing:

- [ ] Run the full repository test suite: `python -m pytest -q`
- [ ] Run packaging validation: `python -m pip install -e .` followed by `python -m pip check`
- [ ] Run the GPU/distributed focused suite covering observation, capability, scheduling, allocation, worker evidence, topology, NCCL, runtime verification, and distributed execution.
- [ ] Verify that no workflow claims physical GPU/NCCL/multi-node success on CPU-only runners.
- [ ] Verify that the canonical capability path is the only admission authority used by production GPU placement.
- [ ] Verify that `DistributedGpuAllocator` remains the final durable reservation/fencing authority.
- [ ] Verify that all existing safety and evidence-binding tests remain passing.
- [ ] Run the verification-before-completion review before claiming the architecture is complete.

## Unresolved Product Decisions

1. **GPU telemetry freshness windows:** The approved architecture requires freshness, but it does not specify one universal maximum age. The implementation should expose freshness as data and make the threshold workload/capability-specific rather than silently choosing a global number.
2. **Optional telemetry admission:** The approved design says unsupported platform-specific fields remain unavailable. Whether a specific production workload requires temperature, ECC, MIG, NVLink link-state, or XID evidence must remain a workload/capability policy decision, not an unconditional requirement for every GPU.
3. **Real GPU runner provisioning:** The repository does not itself establish a physical NVIDIA GitHub Actions runner. The workflow must require such a runner when physical verification is enabled; provisioning that infrastructure is outside the software-only implementation boundary.
