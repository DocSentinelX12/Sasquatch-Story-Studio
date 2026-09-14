# Elastic zero-recurring-cost scale architecture

## Objective

The studio is designed for the highest practical throughput available from hardware the owner controls plus legitimately free compute resources, without recurring cloud, API, subscription, per-generation, or metered-inference costs.

"Unlimited" is treated as an architectural goal, not a false claim about physics or provider quotas. Capacity grows by adding observed owned resources or genuinely free resources that are actually available. The software must not impose an arbitrary production ceiling.

## Core principles

1. **Local and free-resource first.** Production workloads execute on owner-controlled machines or explicitly verified free remote workers.
2. **No paid dependency.** A production path may not require a paid API, hosted inference service, subscription, generation credit, or metered cloud resource.
3. **Elastic capacity.** Workers register dynamically. Capacity can grow or shrink without changing story or pipeline code.
4. **Shared resource pool.** Idle capacity returns to a global pool instead of being permanently assigned to one role.
5. **Durable queue.** Work survives worker loss, restart, network interruption, and power interruption.
6. **Storage is content-addressed.** Large assets are deduplicated by cryptographic hash and can be replicated across storage nodes.
7. **Power-aware scheduling.** Compute may advertise available electrical budget, battery state, renewable availability, thermal limits, and shutdown windows. Scheduling can reduce or pause work when power is constrained.
8. **Graceful degradation.** Losing a GPU, storage node, worker, or power source reduces throughput rather than corrupting canonical story data.
9. **No fake capacity.** The scheduler reports observed capacity and health, never theoretical hardware or advertised free-tier capacity as available compute.
10. **Creator story remains canonical.** Scaling infrastructure can never alter story content or production intent.

## Compute fabric

The coordinator maintains a registry of workers and capabilities. Workers advertise CPU architecture, RAM, GPU/accelerator information, verified engines and versions, active jobs, telemetry, power budget, scratch capacity, network reachability, health, and heartbeat time.

Free remote resources are treated exactly like scarce resources: the studio records their actual availability and restrictions and routes work only when a live worker registration proves that the resource is usable. Discovery of a provider or free tier is never treated as access.

## Job durability

Every job has an immutable job ID, episode ID, stage, canonical source hash, input artifact hashes, required capabilities, resource requirements, priority, lease state, checkpoint reference, output artifact hashes, provenance, and terminal state.

A worker lease expires if the worker disappears. Outputs are committed atomically by content hash. Restarted work cannot silently replace an already committed artifact.

## Cost boundary

The production software must remain usable with zero recurring service fees. It may detect optional free resources, but it must never require paid cloud GPU time, paid inference APIs, paid model APIs, paid storage services, paid queues, paid monitoring services, subscriptions, generation credits, or usage-based vendor billing.

Physical hardware, electricity, storage media, network capacity, heat dissipation, and elapsed processing time remain real constraints.

## Verification boundary

An engine is production-eligible only after the studio records real runtime evidence, including an observed version, executable identity, checkpoint/model hash, license evidence, and a successful configured execution that produced a non-empty output whose hash is recorded. Catalog entries and executable discovery alone do not qualify.
