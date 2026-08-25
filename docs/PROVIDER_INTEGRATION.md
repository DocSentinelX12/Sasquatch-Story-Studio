# Future Provider Integration

No external provider is connected in this repository.

## Stable internal boundary

Episode prompt files should be parsed into `GenerationRequest` from `studio/providers/base.py`. A real provider adapter will be responsible for:

1. validating which request features it supports;
2. translating the internal prompt to the provider's current API shape;
3. submitting with credentials supplied at runtime (never committed);
4. reporting a normalized job state;
5. returning asset metadata and provenance;
6. preserving the original prompt and reference IDs for reproducibility.

Seedance, Veo, Higgsfield, or any later service should each live in a separate adapter module. Episode files must not contain SDK objects, endpoint URLs, model-specific field names, or secrets.

## Normalized lifecycle

`validate → submit → poll/status → retrieve metadata → record asset`

A provider may be synchronous or asynchronous internally; the adapter normalizes that behavior. Retries, cost controls, moderation responses, and provider terms belong in the integration layer when a real provider is selected.

## Reference images

Character visual records list stable manifest asset IDs and an ordered provider-neutral reference policy. `assets/asset-manifest.json` resolves those IDs to verified local files or future remote storage without hard-coding temporary URLs into stories.

Before submission, the integration layer must verify that every character identity reference is either creator source artwork explicitly approved for provider use or an approved canon reference. It must reject AI-generated test material, unregistered files, missing checksums, and missing required reference coverage. Provider-specific image handles are created only inside the adapter and never written back into canon.

## Adding the first real adapter

When a provider is chosen:

- pin and document its official SDK/version;
- add environment-variable configuration and an `.env.example` with names only;
- implement the protocol in `studio/providers/adapters/`;
- add contract tests using fakes local to the test suite;
- never describe the adapter as connected until an authenticated end-to-end test succeeds;
- map ordered normalized `ReferenceImage` values to the provider's real reference-image API;
- record provider, model, parameters, seed (when available), request ID, source reference IDs, and output asset class in the asset manifest.

---
**Phase 5 update:** the real adapters now exist (Veo / Seedance / Wan) with
verified REST contracts, a capability system, an async generation queue, and
versioned results. See **[PROVIDER_SETUP.md](PROVIDER_SETUP.md)** for setup,
capabilities, workflow, and testing. The rules above still apply: never fake a
generation, never auto-approve, creator artwork remains authoritative.
