# LLM architecture

LLMs are a replaceable production-intelligence layer. They do not own canon and they do not directly mutate creator stories.

## Responsibilities

The LLM layer may assist with:

- story ingestion and classification
- structured story interpretation
- character, location, prop, event, and dialogue extraction
- episode planning
- scene and shot planning
- production prompt construction
- asset matching
- dialogue and performance analysis
- QC analysis
- story-fidelity comparison
- creative-review proposals
- production orchestration
- publishing metadata

## Canonical authority

The hierarchy is:

1. Creator story
2. Creator scene and shot instructions
3. Series and character bibles
4. Production constraints
5. AI production detail

An LLM must not silently override a higher-priority layer. Any unresolved creative choice must be represented as a review item.

## Provider policy

Every integrated LLM must have a recorded model identity, version, license, capabilities, runtime requirements, and verification status. Unknown or unverified models are not eligible for production routing.

The production policy is local and zero-recurring-cost only. Remote providers and paid APIs are rejected at policy construction time rather than being allowed as fallback behavior. Missing local model runtimes are hard failures, never silent provider substitutions.

## Structured output and provenance

When a production request declares a structured output schema, the adapter must return structured output. The router also requires provider ID, model ID, model version, and the SHA-256 hash of the canonical source in the returned provenance. Missing or mismatched provenance is a hard failure.

## Reproducibility

LLM requests should record task, canonical-source hash, model identity/version, system instruction, user input, output schema, sampling parameters, seed where supported, and resulting output hash.

## Model replacement

The studio must not encode a specific model into canonical story or episode schemas. Models are adapters. Replacing an LLM must not require rewriting creator-owned story data.
