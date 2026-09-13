# Sasquatch Story Studio

A local-first, reproducible production system for turning the creator's stories into independently producible animated cartoon episodes.

## Creative authority

The creator's story and explicit scene instructions are canonical. The studio may interpret and expand production details, but it must never silently rewrite story events, dialogue, characters, outcomes, or continuity. Proposed creative changes are emitted as review items.

## Production flow

`story -> interpretation -> episode plan -> scenes -> shots -> assets -> animation -> dialogue -> lip sync -> sound/music -> compositing -> edit -> QC -> story fidelity -> approval -> master -> archive`

Episodes are intentionally independent. Recurring characters and a stable visual language do not require serialized plot continuity.

## Design principles

- Free/open-source first, with license verification recorded before integration.
- Model-agnostic interfaces so better models can replace older ones without changing canon assets.
- Deterministic manifests, seeds, inputs, outputs, and tool versions for reproducibility.
- Checkpointed execution so failed shots can be retried without rerendering completed work.
- Human approval remains the release gate.
- No fake integrations, credentials, selectors, URLs, model capabilities, or placeholder production data.

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

The first implementation establishes the durable production contracts before heavyweight AI runtimes are coupled to the system. This prevents model churn from changing the studio's permanent creative data model.
