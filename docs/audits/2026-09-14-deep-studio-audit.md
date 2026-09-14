# Deep animation studio audit

Audit scope: current `main` of `DocSentinelX12/Sasquatch-Story-Studio` only.

## Executive result

The repository has strong durable foundations, but it is not yet a fully operational animation studio. The correct production posture is fail-closed: no real AI engine is treated as verified until the configured runtime, exact version, real checkpoint/model, license evidence, and successful real output are observed and recorded.

The audit identified and repaired several integration defects during this pass, including false runtime availability, worker-specific resource overbooking, production routing that could accept merely installed engines, stale zero-cost configuration documentation, and missing durable artifact handoff between adapter output and the content-addressed store.

The latest GitHub CI run after these repairs completed successfully. CI success is treated as a software-integrity floor, not proof that an external AI engine has rendered a production episode.

## Repaired during this audit

1. Engine production eligibility is now separated from catalog/discovery state.
2. Runtime verification now performs a real configured version probe and a real configured execution that must produce a non-empty output. Checkpoint and output hashes are recorded.
3. Runtime verification evidence is durably persisted in SQLite and can promote a catalog engine only from an actual evidence record.
4. The compute broker now requires requested engines to be in an explicit runtime-verified set, in addition to worker-installed state.
5. Scheduler worker-specific leasing now accounts for already leased slots, memory, VRAM, scratch, and pool power.
6. Real adapter output can now be committed to creator-owned content-addressed storage with durable lineage and canonical-source binding.
7. Production adapter execution can run through a worker executor and artifact committer.
8. A distributed stage runner now connects production requests to the broker, worker fabric, real adapter execution, and durable artifact output.
9. Configuration and cost-policy documentation now distinguish local LLM policy from the broader free compute fabric.
10. Superseded experimental runtime draft files were removed rather than left in the production tree.

## Remaining critical work

### A. Real engine runtime integration

The curated engine catalog is not the same thing as a working installed engine. There is no evidence in the repository that Wan, LTX, ComfyUI, OpenToonz, Blender, ACE-Step, Piper, or Rhubarb is currently installed and successfully producing a real production artifact. They must remain unverified until an actual runtime verification record exists.

### B. Local LLM runtime

The LLM architecture and router exist, but there is no production-ready local LLM subprocess/runtime adapter in the current package. Story interpretation therefore cannot yet execute end to end without an external implementation. The next LLM layer must use a real configured local runtime and must preserve structured output and provenance.

### C. Full stage implementation

The pipeline defines the complete sequence, but most stages are orchestration boundaries. A pipeline handler can be supplied, yet the repository does not currently implement the complete real-media work for every stage from story interpretation through archive. The final system must connect every stage to an actual verified capability or explicitly block when that capability is unavailable.

### D. QC depth

Current deterministic QC validates episode-plan structure and required stage output presence. It does not yet inspect actual video/audio media properties, decodeability, frame/audio integrity, duration consistency, corruption, black/frozen output, loudness, clipping, lip-sync alignment, or final-master technical requirements.

### E. Story fidelity depth

Current fidelity checks verify required event coverage. They do not yet verify event order, exact dialogue preservation, dialogue-to-event mapping, character participation, scene ordering, or other semantic constraints. These need explicit deterministic checks before any release claim.

### F. Approval binding

Human approval exists as a record and release gating exists as a boolean policy, but the approval path must be bound to the exact QC result, fidelity result, production manifest, artifact hashes, and final master hash being released. Approval of an older manifest must never authorize a newer artifact set.

### G. Orchestration consolidation

The repository contains `ProductionCoordinator`, `ComputeBroker`, `WorkerFabric`, `Pipeline`, and stage-runner boundaries. These are individually useful, but the canonical production path must have one authoritative lifecycle so jobs, checkpoints, worker leases, artifacts, failures, retries, and approvals cannot diverge between parallel orchestration implementations.

### H. Android command center

The permanent Android creator-control surface is not yet implemented in the repository. The final system needs a phone-safe control API/UI for starting, pausing, inspecting, approving, retrying, and monitoring work without making the phone the sole location of durable state.

### I. Free compute provider adapters

The architecture supports legitimate free remote compute, but provider-specific adapters are not yet production integrations. Discovery must never equal access. Each provider adapter needs real authentication/access behavior where required, quota/session reporting, worker heartbeat, artifact transfer, retry/requeue semantics, and truthful unavailable states.

### J. Publishing

YouTube metadata packaging exists, but external publishing is intentionally not performed. A future publishing integration must remain optional and explicit, with the final master and metadata package bound to the same release manifest.

## Release standard

The studio is not considered fully operational until a real creator story can traverse the authoritative production path, produce real media artifacts through verified engines, pass technical QC and story fidelity checks, receive human approval for the exact manifest, create a reproducible master, and archive all creator-owned provenance without hidden paid dependencies or fabricated runtime claims.
