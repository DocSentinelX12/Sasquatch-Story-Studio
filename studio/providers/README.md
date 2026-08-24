# Provider Boundary

`base.py` is an interface, not an integration. There are currently no adapters, credentials, endpoint URLs, SDKs, or API calls.

The provider-neutral `ReferenceImage` type carries manifest asset ID, entity, purpose, immutable source class, file/path, checksum, explicit approval status, and order. Its asset-class enum permits only creator source artwork and approved canon references; AI-generated test material cannot be represented as a character identity input. `validate_reference_images()` adds a pre-adapter approval/checksum gate.

When a real provider is selected, add one isolated module beneath `adapters/` that translates the normalized request and ordered reference images. Do not leak provider-specific fields into the series bible or story documents, and never allow adapter behavior to redesign or supersede creator artwork. See `docs/PROVIDER_INTEGRATION.md`.
