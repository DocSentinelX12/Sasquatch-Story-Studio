# Self-hosted elastic scale architecture

## Objective

The studio is designed for the highest practical throughput available from hardware the owner controls, without recurring cloud, API, subscription, per-generation, or metered-inference costs.

"Unlimited" is treated as an architectural goal, not a false claim about physics. The system can scale by adding owned or genuinely free compute, storage, and power capacity. The software must not impose an arbitrary production ceiling.

## Core principles

1. **Local/self-hosted first.** Production workloads execute on machines controlled by the studio.
2. **No paid dependency.** A production path may not require a paid API, hosted inference service, subscription, generation credit, or metered cloud resource.
3. **Elastic capacity.** Workers register dynamically. Capacity can grow or shrink without changing story or pipeline code.
4. **Shared resource pool.** Idle capacity returns to a global pool instead of being permanently assigned to one role.
5. **Durable queue.** Work survives worker loss, restart, network interruption, and power interruption.
6. **Storage is content-addressed.** Large assets are deduplicated by cryptographic hash and can be replicated across storage nodes.
7. **Power-aware scheduling.** Compute may advertise available electrical budget, battery state, renewable availability, thermal limits, and shutdown windows. Scheduling can reduce or pause work when power is constrained.
8. **Graceful degradation.** Losing a GPU, storage node, worker, or power source reduces throughput rather than corrupting canonical story data.
9. **No fake capacity.** The scheduler reports observed capacity and health, never theoretical hardware as available compute.
10. **Creator story remains canonical.** Scaling infrastructure can never alter story content or production intent.

## Logical architecture

```text
                         CREATOR / PHONE
                               |
                               v
                     +---------------------+
                     | Studio Coordinator  |
                     | queue + state + API |
                     +----------+----------+
                                |
             +------------------+------------------+
             |                  |                  |
             v                  v                  v
       Compute Pool       Storage Fabric       Power Fabric
             |                  |                  |
       +-----+-----+      +-----+-----+      +-----+-----+
       | GPU node  |      | NVMe node |      | grid      |
       | GPU node  |      | HDD node  |      | solar     |
       | CPU node  |      | archive   |      | battery   |
       | CPU node  |      | replica   |      | generator |
       +-----------+      +-----------+      +-----------+
             |
             v
       Specialized workers
       story / assets / image / video / animation /
       voice / lip-sync / music / composite / edit / QC
```

## Compute fabric

The coordinator maintains a registry of workers and capabilities. Workers advertise:

- CPU architecture and available cores
- RAM
- GPU vendor/model
- VRAM
- accelerator capabilities
- installed verified engines
- engine/model versions
- active jobs
- thermal and utilization telemetry when available
- power budget when available
- local scratch capacity
- network reachability
- health and last heartbeat

A worker may accept a job only when its declared capabilities satisfy the typed production request. Missing engines are hard failures, not automatic substitutions.

The scheduler uses a shared capacity pool. The baseline logical design supports at least 40 concurrent execution slots and is intentionally extensible beyond that. Slots are not permanently tied to a character or pipeline role. Specialized roles consume capacity only while executing work.

Worker-specific scheduling is also available for dispatchers that know the exact target worker. In that mode, slots, memory, VRAM, scratch space, capabilities, and installed engines must fit on that worker itself. Shared power is checked independently against observed sustained power and existing leases.

## Job durability

Every job has:

- immutable job ID
- episode ID
- stage
- canonical source hash
- input artifact hashes
- required capabilities
- resource requirements
- priority
- retry count
- lease owner
- lease expiration
- checkpoint reference
- output artifact hashes
- provenance
- terminal state

A worker lease expires if the worker disappears. The job returns to the durable queue only after lease recovery rules confirm that the previous worker is no longer authoritative. Outputs are committed atomically by hash so a restarted worker cannot corrupt a completed artifact.

## Storage fabric

The studio treats storage as a pool rather than one disk.

### Tiers

- **Hot:** local NVMe/SSD scratch for active generation and compositing.
- **Warm:** large local or network-attached storage for active projects and recent outputs.
- **Archive:** high-capacity storage for masters, source stories, provenance, and historical versions.
- **Replica:** optional independent copies for disaster recovery.

All durable artifacts receive a content hash. Identical artifacts are stored once per storage domain and referenced by hash. The studio never deletes a creator-owned source merely because it is duplicated elsewhere.

Storage nodes expose capacity, free space, health, throughput, and replication status. The scheduler can refuse jobs that cannot safely fit their declared scratch/output requirements.

## Power fabric

The software models power as a resource supplied by one or more independently observable sources. Supported source types are intentionally abstract so the same scheduler can work with grid power, solar, battery storage, generator-backed power, or future local sources.

Each power source may report:

- available watts
- sustained watts
- battery state of charge when applicable
- renewable status when applicable
- minimum reserve
- estimated availability window
- shutdown priority
- telemetry timestamp

Power-aware scheduling is advisory unless an actual hardware controller integration is installed. The studio must never claim that software alone creates electrical capacity.

When power becomes constrained, the scheduler can:

1. finish short checkpoint-safe jobs,
2. stop starting new expensive jobs,
3. checkpoint resumable work,
4. drain workers in configured shutdown order,
5. preserve storage and coordinator services,
6. resume queued work automatically when capacity returns.

The current shutdown coordinator implements the checkpoint-safe drain state machine. It deliberately does not claim physical power-control capability. A real controller can be added only after its hardware interface is verified.

## Scaling model

The target is **practically unbounded horizontal scaling** rather than a fixed machine size.

Adding a worker increases capacity without changing pipeline semantics. Adding storage increases artifact capacity. Adding power sources increases sustainable compute availability. Removing any one noncritical node must not destroy canonical source data or queue state.

The coordinator is designed to avoid a single-worker bottleneck. Queue state and metadata should remain durable and independently backed up. Heavy media data never passes through the coordinator unless explicitly required; workers exchange artifact references through the storage fabric.

## Cost boundary

The production software must remain usable with zero recurring service fees. It may detect optional resources, but it must never require:

- paid cloud GPU time
- paid inference APIs
- paid model APIs
- paid storage services
- paid queues
- paid monitoring services
- subscriptions
- generation credits
- usage-based vendor billing

The only unavoidable physical constraints are available hardware, electrical energy, storage media, network capacity, heat dissipation, and elapsed processing time.

## Safety and integrity

Infrastructure scaling is subordinate to story fidelity. No scheduler optimization may change canonical content, skip required QC, bypass story-fidelity checks, bypass human approval, or replace creator-owned assets without an explicit review item.

## Implementation sequence

1. Define typed compute, storage, and power resource models. **Implemented.**
2. Implement durable worker registration and heartbeat. **Implemented.**
3. Implement shared-capacity scheduler and leases. **Implemented.**
4. Implement content-addressed artifact store and replication metadata. **Implemented.**
5. Implement power telemetry interfaces and power-aware admission control. **Implemented.**
6. Add worker discovery for verified local engines. **Next.**
7. Add checkpoint-aware graceful shutdown and recovery. **Implemented.**
8. Add resource dashboard and mobile control surfaces.
9. Load-test queue, storage, and scheduling behavior with deterministic tests.
10. Validate real engine execution only when the corresponding local runtime is actually installed.
