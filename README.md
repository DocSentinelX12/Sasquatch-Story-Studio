# Sasquatch Story Studio

A local-first, reproducible production system for turning the creator's stories into independently producible animated cartoon episodes.

## Creative authority

The creator's story and explicit scene instructions are canonical. The studio may interpret and expand production details, but it must never silently rewrite story events, dialogue, characters, outcomes, or continuity. Proposed creative changes are emitted as review items. The creator remains the final approval gate for episode changes and release.

## Episodic independence

Every episode is independently producible. Recurring characters and a stable visual language do not require serialized plot continuity. An episode may establish its own season, setting, wardrobe, props, timing, circumstances, and story without inheriting those episode-local states from another episode.

Continuity is therefore enforced strongly **within an episode**, while cross-episode story continuity is optional and creator-directed.

## Surgical episode changes

The studio is designed around creator-directed, surgical corrections. A creator can describe a desired change in ordinary language. The system identifies the smallest affected production scope, records what must remain protected, proposes the resulting change for approval when required, regenerates only the affected material, reconnects it to neighboring material, and validates the result before the revised episode can pass the release gate.

Protected continuity includes dialogue identity and timing, character identity, actions, physical state, props, environment, camera relationships, audio, music, sound effects, scene transitions, and the entry/exit state required for neighboring shots. Nothing unrelated should be silently regenerated or changed.

## Production flow

`story -> interpretation -> episode plan -> scenes -> shots -> assets -> animation -> dialogue -> lip sync -> sound/music -> compositing -> edit -> continuity QC -> story fidelity -> creator approval -> master -> archive`

## Design principles

- Free/open-source first, with license verification recorded before integration.
- Model-agnostic interfaces so better models can replace older ones without changing canon assets.
- Deterministic manifests, seeds, inputs, outputs, and tool versions for reproducibility.
- Checkpointed execution so failed shots can be retried without rerendering completed work.
- Human approval remains the release gate.
- No fake integrations, credentials, selectors, URLs, model capabilities, or placeholder production data.
- Image-art providers are replaceable production backends and must not become the canonical story or character data model.
- Meta AI can be used as a creator-selected image-art provider only where a real, verified workflow exists. The studio must never claim an API, automation path, credentials, selectors, or integration that has not been verified.

## Repository map

- `studio/` core Python package
- `schemas/` canonical JSON schemas
- `docs/` architecture and operating rules
- `tests/` executable contract tests
- `config/` non-secret studio configuration
- `episodes/` future episode manifests and production state
- `assets/` creator-owned visual source material and derived assets

## Local development

Python 3.11+ is the initial target. Run the test suite with `python -m pytest`.

The implementation establishes durable production contracts before heavyweight AI runtimes are coupled to the system. This prevents model churn from changing the studio's permanent creative data model.
