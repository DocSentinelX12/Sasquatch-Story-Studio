# Animation Studio Compute Fabric Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved Compute Fabric architecture into a truthful, durable, capability-based production system that can route animation and media work across heterogeneous verified workers while remaining Android-controlled and zero-dollar at the core.

**Architecture:** Extend the existing scheduler/coordinator/resource abstractions rather than replacing them. Add durable worker and engine capability registries, a broker that converts production tasks into resource-aware leases, portable artifact/data movement contracts, and failure/recovery semantics; then connect those contracts to the existing checkpointed pipeline, adapter boundary, QC/approval system, and a thin Android-facing control API. Heavy AI runtimes remain adapters behind verified capability records, not assumptions embedded in orchestration.

**Tech Stack:** Python 3.11, standard-library SQLite/JSON/dataclasses/protocols, existing pytest suite and GitHub Actions CI; external engines and distributed runtimes are integrated only through explicit adapters and verified execution paths.

## Global Constraints

- Only `DocSentinelX12/Sasquatch-Story-Studio` is in scope.
- Android is the permanent creator command center; the phone is not assumed to be the rendering machine.
- The core production path must require $0 in subscriptions, per-generation fees, API credits, paid GPU rental, mandatory proprietary software, mandatory cloud storage, or mandatory hosted services.
- Free resources are treated as bounded and volatile. Quotas, session limits, availability, concurrency, storage, bandwidth, and provider restrictions must be represented when observed.
- Paid or proprietary services may exist only as explicitly enabled optional adapters and may never become hidden fallbacks.
- Scheduling is capability-based, not machine-name based.
- Creator intent, canon, approved assets, dialogue, and explicit decisions cannot be silently rewritten by AI or orchestration.
- Production state is durable and creator-owned; workers, models, engines, providers, hardware, storage, and orchestration runtimes are replaceable.
- No fabricated credentials, endpoints, selectors, capabilities, artifacts, execution results, QC results, approvals, or resource availability.
- Episodes remain independent unless the creator explicitly establishes a cross-episode relationship.
- Every substantial task has durable identity, requirements, selected resource, engine/model identity where applicable, input hashes, output references, provenance, checkpoint state, failure information, and retry history.
- Maximum Quality remains the default quality objective. Quality ordering is: creative fidelity, visual quality, character consistency, animation quality, audio/performance quality, story fidelity, reliability, efficiency, speed.
- Production eligibility for an engine requires actual execution-path verification plus capability and licensing/provenance verification.
- Software tests do not count as proof that an AI model actually rendered a production artifact.
- The existing checkpointed pipeline, coordinator, scheduler, resources, adapters, assets, approvals, provenance, archive, and CI contracts remain authoritative unless a task explicitly extends them.
- Existing observed files include `studio/resources.py`, `studio/scheduler.py`, `studio/coordinator.py`, `studio/pipeline.py`, `studio/adapters.py`, and `.github/workflows/studio-ci.yml`.

---

### Task 1: Durable resource and worker registry

**Files:**
- Create: `studio/worker_registry.py`
- Create: `tests/test_worker_registry.py`
- Modify: `studio/resources.py` only when the registry needs a missing observed-capacity field

**Interfaces:**
- Consumes: `ComputeResource`, `ResourceSnapshot` from `studio.resources`.
- Produces: `WorkerRecord`, `WorkerState`, `WorkerRegistry.register()`, `WorkerRegistry.update()`, `WorkerRegistry.get()`, `WorkerRegistry.snapshot()`, `WorkerRegistry.mark_unavailable()`, and a SQLite persistence implementation.

- [ ] **Step 1: Add the focused failing test**

Cover registration of a valid heterogeneous worker; update of observed CPU/GPU/VRAM/capability/engine information; transitions among verified available, limited, unavailable, quota-exhausted, offline, capability-mismatch, unverified, and retired states; rejection of an empty worker ID; preservation of last-observed information when a worker becomes unavailable; and round-trip persistence through SQLite.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_worker_registry.py`
Expected: collection or assertion failures because the registry interfaces do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Create immutable worker identity/capability records plus mutable registry state. Persist observed capability data, quota/limit information, health state, last observation time, and provenance of the observation. Do not invent resource capacity when an observation is absent. A worker marked unavailable must remain represented so jobs can be reassigned without losing history.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_worker_registry.py`
Expected: all registry tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_resources.py tests/test_scheduler.py tests/test_coordinator.py tests/test_worker_registry.py` if `tests/test_resources.py` exists; otherwise run the existing resource/scheduler/coordinator tests plus the new registry test.
Expected: existing tests remain green and registry persistence integrates without changing current scheduler semantics.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/worker_registry.py studio/resources.py tests/test_worker_registry.py
git commit -m "feat: add durable worker registry"
```

### Task 2: Capability-aware compute broker and scheduling policy

**Files:**
- Create: `studio/compute_broker.py`
- Create: `tests/test_compute_broker.py`
- Modify: `studio/scheduler.py` only where a broker-facing primitive is required
- Modify: `studio/coordinator.py` only where broker integration requires a stable handoff

**Interfaces:**
- Consumes: `Job`, `JobRequirements`, `Scheduler`, `ComputeResource`, `ResourceSnapshot`, `WorkerRegistry`, and `ProductionCoordinator`.
- Produces: `ProductionTask`, `BrokerDecision`, `ComputeBroker.submit()`, `ComputeBroker.select_worker()`, `ComputeBroker.lease()`, `ComputeBroker.release_or_requeue()`, and deterministic route evidence.

- [ ] **Step 1: Add the focused failing test**

Test that a task requiring specific VRAM/capabilities/engine is routed only to a worker that actually reports them; a healthy but underpowered worker is rejected; an unavailable or unverified worker is never selected; higher quality-ranked eligible capacity beats faster but lower-quality capacity according to the approved hierarchy; concurrent leases account for already reserved capacity; and no eligible worker produces a truthful no-route decision rather than a fabricated assignment.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_compute_broker.py`
Expected: failures because the broker and route-evidence interfaces do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Implement deterministic capability matching on top of the existing scheduler. Keep machine identity separate from task requirements. A broker decision must record the requirement snapshot, candidate workers considered, selected worker if any, rejection reasons for non-selected candidates where observable, and the policy outcome. Preserve the scheduler's lease ownership and expiry semantics. Do not claim global multi-worker capacity can satisfy a single task unless the task explicitly supports decomposition.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_compute_broker.py`
Expected: all broker tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_scheduler.py tests/test_coordinator.py tests/test_compute_broker.py`
Expected: scheduler/coordinator behavior remains compatible and broker decisions are deterministic.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/compute_broker.py studio/scheduler.py studio/coordinator.py tests/test_compute_broker.py
git commit -m "feat: add capability-aware compute broker"
```

### Task 3: Portable worker execution contract and checkpoint-aware reassignment

**Files:**
- Create: `studio/worker.py`
- Create: `tests/test_worker.py`
- Modify: `studio/coordinator.py`
- Modify: `studio/pipeline.py`

**Interfaces:**
- Consumes: `ProductionTask`, broker leases, existing `StageJob`, `RunState`, and checkpoint writer behavior.
- Produces: `WorkerTask`, `WorkerResult`, `WorkerExecutor` protocol, `WorkerHeartbeat`, `WorkerFailure`, and coordinator operations for acknowledge/start/complete/fail/requeue.

- [ ] **Step 1: Add the focused failing test**

Test idempotent task identity; start/heartbeat/complete lifecycle; worker loss before completion; lease expiry followed by reassignment; completion by the wrong worker; duplicate completion; preservation of checkpointed outputs after failure; and a failed task that cannot be rerouted because no equivalent capability exists.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_worker.py tests/test_coordinator.py`
Expected: new worker lifecycle assertions fail before the contract exists.

- [ ] **Step 3: Implement the minimum behavior**

Define a worker-neutral task envelope containing stable task ID, episode/stage/shot identity, input references and hashes, requirements, provenance context, and checkpoint references. Define explicit result states for completed, failed, unavailable, and rejected execution. Reuse existing scheduler lease ownership rather than creating a second lease system. A lost worker leaves durable queued/checkpoint state and permits another verified compatible worker to acquire the task. Duplicate completion must not create a second production result.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_worker.py tests/test_coordinator.py`
Expected: lifecycle, loss, reassignment, and idempotency tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_pipeline.py tests/test_coordinator_persistence.py tests/test_worker.py tests/test_coordinator.py` using only paths that exist in the repository.
Expected: checkpoint resume remains intact and worker failure does not erase completed stages or durable handoffs.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/worker.py studio/coordinator.py studio/pipeline.py tests/test_worker.py
git commit -m "feat: add portable worker execution contract"
```

### Task 4: Creator-owned data movement, artifact lineage, and durable fabric state

**Files:**
- Create: `studio/data_plane.py`
- Create: `tests/test_data_plane.py`
- Modify: `studio/artifacts.py`
- Modify: `studio/archive.py` only where durable fabric metadata must be archived

**Interfaces:**
- Consumes: existing artifact/provenance/archive references and worker task envelopes.
- Produces: `DataReference`, `TransferPlan`, `TransferChunk`, `TransferResult`, `DataPlane.plan()`, `DataPlane.transfer()`, and resumable checksum verification.

- [ ] **Step 1: Add the focused failing test**

Test content-addressed references, SHA-256 verification, chunked transfer planning, resumable transfer after an interrupted chunk, rejection of checksum mismatch, retention of source and destination references, and prevention of automatic destructive deletion of creator history.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_data_plane.py`
Expected: failures because the portable data-plane interfaces do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Represent assets and intermediate artifacts by stable references plus hashes and provenance rather than machine-local absolute paths. Transfer only task-required inputs. Make transfer chunks independently checkable and resumable. Preserve existing asset lineage and archive records. Cleanup operations must be explicit and must not silently delete canonical assets, approvals, rejected candidates, or historical production state.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_data_plane.py`
Expected: all data-plane tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_artifacts.py tests/test_data_plane.py` and the existing archive/provenance tests.
Expected: artifact identity and provenance remain compatible while new transfer metadata is durable.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/data_plane.py studio/artifacts.py studio/archive.py tests/test_data_plane.py
git commit -m "feat: add portable creator-owned data plane"
```

### Task 5: Universal engine registry and verified adapter routing

**Files:**
- Create: `studio/engine_registry.py`
- Create: `tests/test_engine_registry.py`
- Modify: `studio/adapters.py`
- Modify: existing engine/licensing modules only where required to connect verified records

**Interfaces:**
- Consumes: `AdapterInfo`, `ProductionAdapter`, existing licensing/provenance checks, and worker capability records.
- Produces: `EngineRecord`, `EngineState`, `EngineRegistry.register()`, `EngineRegistry.verify()`, `EngineRegistry.eligible()`, and `EngineRoute`.

- [ ] **Step 1: Add the focused failing test**

Test that an adapter with unverified licensing/capability/execution state is ineligible; a verified adapter can be selected only when the worker also satisfies its hardware requirements; optional external providers remain disabled unless explicitly enabled; exact version and provenance are retained; and multiple compatible engines can be represented without making one engine the permanent default.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_engine_registry.py`
Expected: failures because registry and eligibility interfaces do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Keep `AdapterInfo` as the stable identity surface and extend it with evidence-backed execution/licensing state only where necessary. Separate discovered, installed, adapter-supported, verified, optional-external, and unsupported states. Production routing must require explicit verification. A software test or metadata declaration alone cannot elevate an engine to production-verified. Preserve the existing `require_verified()` guard.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_engine_registry.py tests/test_engine_licensing.py`
Expected: registry and licensing tests pass without weakening existing verification gates.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_engines.py tests/test_engine_licensing.py tests/test_engine_registry.py`
Expected: current engine abstractions remain valid and no unverified engine becomes routable.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/engine_registry.py studio/adapters.py tests/test_engine_registry.py
# Include only additional engine/licensing files actually changed by the task
git commit -m "feat: add verified engine registry"
```

### Task 6: Multi-agent LLM Director and structured production intent

**Files:**
- Create: `studio/director.py`
- Create: `studio/director_roles.py`
- Create: `tests/test_director.py`
- Modify: existing interpreter/director modules only where the new structured intent contract must be shared

**Interfaces:**
- Consumes: creator natural-language intent, series/character/asset knowledge, engine/resource capabilities, and existing production stage contracts.
- Produces: `ProductionIntent`, `DirectorProposal`, `DirectorRole`, `DirectorCoordinator`, `DirectorCoordinator.interpret()`, `DirectorCoordinator.plan()`, and explicit creator-review records for proposals that would affect canon.

- [ ] **Step 1: Add the focused failing test**

Test that creator instructions become structured intent; the role set includes Story, Character, Scene, Animation, Voice, Music/Sound, Continuity, Technical, QC, Compute, and Archive responsibilities; roles can produce proposals without silently mutating canonical data; conflicting proposals are surfaced; and an unavailable local/free LLM route is reported rather than replaced with an unapproved paid service.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_director.py`
Expected: failures because the unified Director interfaces do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Build a model-neutral director contract. LLM backends are adapters, not hard-coded providers. Structured intent must distinguish explicit creator instructions from AI proposals. Director output must identify affected episodes/scenes/shots/assets and required capabilities. No proposal may become canonical without the existing approval gate. Preserve the existing interpreter provenance policy and evidence requirements.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_director.py tests/test_interpreter.py`
Expected: new director tests pass and existing interpreter provenance tests remain green.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_director.py tests/test_interpreter.py tests/test_guards.py`
Expected: creator authority and provenance guards remain intact.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/director.py studio/director_roles.py tests/test_director.py
# Include only actually modified existing interpreter/director files
git commit -m "feat: add structured multi-agent director"
```

### Task 7: End-to-end brokered pipeline execution and quality-first fan-out

**Files:**
- Create: `studio/fabric.py`
- Create: `tests/test_fabric.py`
- Modify: `studio/pipeline.py`
- Modify: `studio/coordinator.py`

**Interfaces:**
- Consumes: `ProductionIntent`, `ComputeBroker`, `WorkerExecutor`, `EngineRegistry`, `DataPlane`, checkpoints, and existing `STAGES`.
- Produces: `FabricRun`, `FabricTaskGraph`, `FabricRun.submit()`, `FabricRun.status()`, `FabricRun.resume()`, and shot/task dependency records.

- [ ] **Step 1: Add the focused failing test**

Test decomposition of an episode into stage/scene/shot tasks; dependency ordering; parallel execution of independent tasks; reuse of completed checkpointed work; targeted rerender of a failed shot without rerunning unaffected shots; worker disappearance and reassignment; engine selection based on verified capability; and preservation of independent episode state.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_fabric.py`
Expected: failures because the fabric task graph and run interfaces do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Create the production-level orchestration layer above the existing stage pipeline. It must turn creator intent into a durable dependency graph, fan out independent work, checkpoint every completed task, and route each task through the broker and verified engine registry. Revisions must invalidate only affected descendants. The system must prefer reusable approved assets and prior valid outputs. A lack of eligible compute must pause/report the work without losing the run.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_fabric.py`
Expected: fan-out, resume, reassignment, and targeted-revision tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_pipeline.py tests/test_coordinator.py tests/test_fabric.py` using only files that exist.
Expected: existing stage checkpoint semantics remain intact and the fabric adds orchestration without bypassing them.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/fabric.py studio/pipeline.py studio/coordinator.py tests/test_fabric.py
git commit -m "feat: add brokered production fabric"
```

### Task 8: Continuous QC, story fidelity, creator approval, and publication gate integration

**Files:**
- Create: `studio/qc_pipeline.py`
- Create: `tests/test_qc_pipeline.py`
- Modify: existing `studio/approval.py` only where needed to connect evidence-backed fabric results

**Interfaces:**
- Consumes: rendered artifacts, deterministic media metadata, story/intent manifests, provenance, and candidate sets.
- Produces: `QCReport`, `QCCheck`, `QCResult`, `QCReporter.evaluate()`, `StoryFidelityResult`, and an approval eligibility decision.

- [ ] **Step 1: Add the focused failing test**

Test deterministic frame/fps/resolution/container/audio/sync/integrity checks; explicit separation of deterministic validity from subjective artistic review; hard blocking failures; story-fidelity mismatches; provenance gaps; candidate comparison; and the rule that creator approval is required before master publication.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_qc_pipeline.py`
Expected: failures because the integrated QC evidence contract does not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Create a report that distinguishes machine-checkable failures from review-required artistic judgments. QC cannot convert an invalid artifact into a valid one. Story-fidelity checks compare production output against structured creator intent and canonical script/shot records. Approval remains explicit and separate from creation. Publication/master stages cannot proceed when a hard QC failure or missing approval exists.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_qc_pipeline.py tests/test_guards.py`
Expected: QC and approval gating tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_approval.py tests/test_qc_pipeline.py` using the existing approval test path if present.
Expected: existing creator-approval semantics remain intact.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/qc_pipeline.py studio/approval.py tests/test_qc_pipeline.py
# Include approval.py only if it was actually modified
git commit -m "feat: integrate production QC and approval gates"
```

### Task 9: Android-first control surface and truthful status API

**Files:**
- Create: `studio/control_api.py`
- Create: `tests/test_control_api.py`
- Create: `docs/android-control.md`
- Modify: `studio/cli.py` only if an existing command surface can safely share the control contract

**Interfaces:**
- Consumes: `DirectorCoordinator`, `FabricRun`, worker/resource registry, QC/approval status, and durable production state.
- Produces: `CreatorCommand`, `StudioStatus`, `ControlApi.submit_command()`, `ControlApi.get_status()`, `ControlApi.list_candidates()`, `ControlApi.approve()`, `ControlApi.request_revision()`, and notification events.

- [ ] **Step 1: Add the focused failing test**

Test natural-language command submission into structured intent; status responses that distinguish queued/running/blocked/failed/completed/awaiting-approval; approval and targeted revision commands; phone disconnect/reconnect against durable state; and refusal to report completion when only planning or software tests succeeded.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_control_api.py`
Expected: failures because the Android-facing control contract does not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Provide a transport-neutral control API so an Android client can be built without coupling the creator experience to worker internals. Keep Simple mode as the default and expose Director/Advanced data only when requested. Return evidence-backed state and human-readable blockers. The control API must not require the phone to stay connected while production runs.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_control_api.py`
Expected: all control contract tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_control_api.py tests/test_fabric.py tests/test_qc_pipeline.py`
Expected: the control layer accurately reflects durable fabric/QC state without adding a second source of truth.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/control_api.py tests/test_control_api.py docs/android-control.md
# Include studio/cli.py only if actually modified
git commit -m "feat: add Android-first studio control API"
```

### Task 10: Self-healing, security/provenance enforcement, archive durability, and CI verification

**Files:**
- Create: `studio/recovery.py`
- Create: `tests/test_recovery.py`
- Create: `tests/test_security_boundaries.py`
- Modify: `studio/archive.py`
- Modify: `studio/coordinator.py` only for recovery evidence integration
- Modify: `.github/workflows/studio-ci.yml` only to add deterministic test coverage that requires no external credentials or paid services

**Interfaces:**
- Consumes: worker leases, fabric task state, data-plane references, engine provenance, QC/approval records, and archive manifests.
- Produces: `RecoveryPlan`, `RecoveryAction`, `RecoveryManager.recover()`, durable failure classification, archive completeness checks, and CI-enforced zero-dollar/no-fabrication contract tests.

- [ ] **Step 1: Add the focused failing test**

Test worker crash recovery, expired lease recovery, missing output detection, corrupted artifact detection, unavailable storage handling, unavailable engine handling, non-retryable licensing failures, retry limits/idempotency, archive manifest completeness, secret redaction from persisted records, and rejection of fabricated execution evidence.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_recovery.py tests/test_security_boundaries.py`
Expected: failures because the integrated recovery/security contracts do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Classify failures as system/resource/engine/data/production-quality rather than treating all failures as retryable. Requeue only when a compatible verified route exists. Preserve diagnostics and retry history. Require hashes and provenance for durable production artifacts. Keep secrets outside code/manifests/prompts/logs. Extend archive manifests to preserve creator inputs, canonical assets, production manifests, hashes, provenance, approvals, important intermediates, masters, and migration metadata. Add only deterministic CI checks that can execute in the repository's current GitHub Actions environment without external service credentials.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_recovery.py tests/test_security_boundaries.py`
Expected: all recovery and security tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q`
Expected: the complete repository test suite passes with no external API credentials, paid service, model download, or proprietary runtime required for the deterministic test path.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add studio/recovery.py tests/test_recovery.py tests/test_security_boundaries.py studio/archive.py studio/coordinator.py .github/workflows/studio-ci.yml
git commit -m "feat: harden fabric recovery and provenance"
```

---

## Integration and verification gates

After the ten deliverables, the implementation must be verified in layers rather than treating one green test run as proof of animation capability:

1. **Contract layer:** all deterministic unit and contract tests pass.
2. **Persistence layer:** scheduler, coordinator, worker, fabric, artifact, and archive state survive process restart and worker loss.
3. **Routing layer:** only observed, verified capabilities can receive work; no hidden paid fallback exists.
4. **Adapter layer:** each actual animation/media engine gets its own explicit execution verification and licensing/provenance record before production eligibility.
5. **Runtime layer:** actual model/engine execution is tested separately from deterministic orchestration tests and is reported with exact engine/model/resource evidence.
6. **Quality layer:** real artifacts pass deterministic media checks, story-fidelity review, provenance checks, and creator approval before publication.
7. **Android layer:** the phone can submit commands, observe durable state, review candidates, approve, and request targeted revisions without becoming a production dependency.
8. **Failure layer:** worker loss, quota exhaustion, network interruption, unavailable engine, corrupted artifact, and process restart all preserve recoverable state.
9. **Long-term layer:** manifests and archive records remain portable without requiring any particular model, GPU, cloud, or orchestration provider.

## Proposed external engine/resource integration boundary

The architecture deliberately does **not** hard-code specific free GPU providers or video engines into the first fabric implementation. Provider/engine adapters should be added only after current access, terms, capability, licensing, actual runtime behavior, and hardware requirements are verified. This keeps the core fabric truthful and prevents a provider that changes quotas or availability from becoming an architectural dependency.

## Unresolved externally observable product decisions

- **Android transport:** the control contract is transport-neutral in this plan. Before implementing a production Android client, choose whether the first client communicates with a local/self-hosted control endpoint, a user-managed server endpoint, or another explicitly creator-configured transport. This changes deployment and authentication work but does not change the core production contracts.
- **Fabric persistence topology:** the initial durable contracts are compatible with local SQLite and portable manifests. Before distributed deployment, choose whether the first multi-worker deployment uses a single authoritative coordinator store or a replicated coordinator service. This changes operational deployment but not task identity or worker contracts.
- **Remote free-provider enrollment:** each provider requires an explicit creator-enabled adapter after verification. The creator has not yet selected which currently available free provider should be the first live remote worker, so the implementation must not silently select one.
- **Actual animation engine order:** the approved architecture requires multiple interchangeable engines, but it does not dictate which verified engine is integrated first. Engine order should be chosen after the adapter boundary is implemented and current licenses/capabilities/runtime requirements are verified.

## Plan self-review

- Specification coverage: the plan maps zero-dollar resource handling, capability scheduling, distributed execution, storage/data movement, multi-agent LLM direction, universal engine adapters, QC, creator approval, recovery, security/provenance, Android control, knowledge-facing state, scale, and future replacement boundaries to concrete deliverables.
- Placeholder scan: no `TODO`, `TBD`, invented endpoint, fake engine capability, fake resource, or assumed production-runtime result is specified.
- Interface consistency: worker records feed the broker; broker leases feed workers/coordinator; data references feed tasks/artifacts; engine records gate adapter routing; Director output feeds fabric intent; fabric output feeds QC/approval; control API reads durable state rather than creating a second state store.
- Repository grounding: existing observed paths are named as existing; new paths are explicitly listed as files to create. Existing CI uses Python 3.11 and `python -m pytest -q`, which the plan preserves.
- Scope boundary: only `DocSentinelX12/Sasquatch-Story-Studio` is part of this plan. No other repository is required or authorized by this implementation plan.
