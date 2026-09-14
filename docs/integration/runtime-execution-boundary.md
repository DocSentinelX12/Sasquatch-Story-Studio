# Runtime execution boundary

Production execution must pass through four evidence gates before an engine may run:

1. Engine registry verification: the engine is explicitly runtime-verified, not merely catalogued.
2. Adapter verification: the configured adapter declares verified identity and capabilities.
3. Compute routing: the task is leased to a worker satisfying the task's actual capabilities and resource requirements.
4. Artifact evidence: the adapter must return real output references and provenance from the execution.

Failure at any gate is terminal for that attempt and must not be represented as a successful render. A worker lease is released as completed only after real output references are returned. Failures are requeued through the broker lifecycle.
