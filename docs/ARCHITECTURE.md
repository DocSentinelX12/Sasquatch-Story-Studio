# Architecture

Sasquatch Story Studio uses a content-first architecture. Canon and episode plans are durable data; generation vendors are replaceable adapters.

## Layers

1. **Creator visual canon** — imported creator artwork is the highest authority for character design. `assets/asset-manifest.json` records provenance, class, links, checksums, and explicit approvals. `assets/characters/character-catalog.json` is the scalable index locating every character and reference (one entry per character, animals included, `registered_shell` entries for not-yet-identified artwork); `assets/characters/families/` keeps parent, child, sibling, and pet relationships connected as the cast grows to hundreds of characters.
2. **Series canon** — `series-bible/` is the source of truth for character personality, relationships, location, world, story, tone, and links to visual records.
3. **Episode content** — each episode owns its outline, scenes, dialogue, storyboards, generation prompts, audio notes, and continuity report.
4. **Schemas and validation** — `schemas/` describes interchange formats; `tools/validate_content.py` performs fast repository-specific checks without external packages.
5. **Provider boundary** — `studio/providers/base.py` defines the internal generation request, normalized reference-image inputs, and adapter protocol. It has no network implementation.
6. **Media storage** — `assets/` physically separates creator source, approved canon references, AI tests, and final approved production output. Large generated media is ignored by Git; manifests and completion records remain versioned.

## Source-of-truth rules

- Creator-provided artwork wins when any written file or generated image conflicts with character design.
- The series bible wins when episode files conflict with non-visual canon.
- A visual asset is usable only when registered in the manifest with the correct immutable class and explicit approval.
- AI-generated test material is always non-canon and can never automatically replace creator artwork.
- A new canon fact must be added to the relevant reference card and the append-only continuity log.
- An episode may temporarily propose a fact in its continuity report, but the fact is not canon until accepted into the bible.
- Completed records are historical manifests. Fixes create a new revision rather than silently changing what was released.
- Stable IDs (`CHAR-*`, `LOC-*`, `EP-*`, `SC-*`, `SHOT-*`, `PROMPT-*`) are used instead of display names for references.

## Episode package

```text
EP-###-slug/
  episode.json                 identity, status, premise, lesson, cast, locations
  story/outline.json           hook, escalation, emotional turn, resolution, ending
  scenes/SC-###.json           scene intent, action, continuity, transitions
  dialogue/dialogue.json       speaker-attributed lines and performance intent
  storyboards/storyboard.json  ordered visual shots and staging
  prompts/generation-prompts.json
  audio/audio-notes.json
  continuity/continuity-check.json
```

These are planning files, not media. A future renderer resolves approved reference-image IDs through the asset manifest, rejects missing or non-canon character identity references, maps the normalized prompt and ordered references to a provider request, and records returned asset provenance without changing story files.

## Why JSON and Markdown

- JSON gives tools stable fields, references, and validation.
- Markdown keeps creative canon comfortable for humans to review.
- The Markdown bible summarizes the structured cards. If they diverge, resolve the difference immediately and log the decision.

## Deliberate non-goals

The foundation does not include a database, web framework, queue, cloud storage, authentication, payments, or speculative provider SDKs. Those should be added only when a real production requirement exists.
