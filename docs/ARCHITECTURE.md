# Studio architecture

## Canonical hierarchy

1. Creator story
2. Creator scene and shot instructions
3. Series and character bibles
4. Production constraints
5. AI-generated production detail

A lower layer may not silently override a higher layer.

## Pipeline contract

Every episode passes through named stages. Each stage has durable state and outputs. A completed stage is not rerun during resume unless explicitly invalidated. A failed stage remains retryable.

The planned stages are:

1. Interpret the source story
2. Build an episode plan
3. Build scenes
4. Build shots
5. Resolve canonical assets
6. Animate
7. Generate or import dialogue
8. Lip sync
9. Produce sound and music
10. Composite
11. Edit and pace
12. Automated QC
13. Compare against source story
14. Human approval
15. Render master
16. Archive provenance

## Model adapter boundary

AI engines are adapters, not the source of truth. An adapter receives a typed shot or asset request and returns a versioned output plus provenance. The core system must remain usable when an adapter is unavailable.

Future adapters should cover text interpretation, image generation, video generation, character animation, voice, lip sync, music, sound effects, upscaling, and quality analysis. Each adapter must declare license, model version, runtime requirements, input/output contract, and deterministic controls where available.

## Episode independence

An episode may reuse characters, locations, props, rigs, voices, and visual language from the studio library without inheriting plot consequences from another episode. Continuity is asset-level unless the creator explicitly makes story continuity canonical.

## Reproducibility

Each production run should record source hashes, plan hashes, asset IDs, adapter/model versions, prompts, parameters, seeds, environment information, stage outputs, failures, approvals, and final checksums.

## Release gate

No episode is considered releasable merely because rendering succeeded. QC and story-fidelity checks must pass, followed by explicit human approval.
