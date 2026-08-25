# Sasquatch Story Studio

A content-first foundation for an expandable, family-friendly 2D animated series about **Yeti**, a curious young Sasquatch whose big imagination and bigger momentum create funny problems.

This repository is the source of truth for the series bible, story development, continuity, shot planning, generation prompts, audio notes, and completed-episode records. It intentionally contains **no video-provider integrations, external API calls, payment code, or generated media**.

## Creative north star

Every episode should be funny, heartfelt, visually clear, and built around a meaningful lesson that emerges from the characters' choices—not a lecture. Episodes open with a strong hook, escalate through comedy and conflict, reach an emotional turn, resolve satisfyingly, and finish on a memorable image or joke.

> **Visual authority:** Creator-provided character artwork is authoritative. AI must preserve the established character designs and must not redesign characters.
>
> **Barefoot rule:** Every character is always barefoot. No shoes, socks, boots, sandals, slippers, or other footwear may appear.

See [`series-bible/SERIES_BIBLE.md`](series-bible/SERIES_BIBLE.md) for canonical creative rules and [`assets/ASSET_POLICY.md`](assets/ASSET_POLICY.md) for visual asset authority and approval.

## Repository map

```text
series-bible/                 Persistent canon and machine-readable references
  SERIES_BIBLE.md             Human-readable canonical series bible
  series.json                 Core identity, format, and creative rules
  characters/                 Character identity and visual continuity cards
  locations/                  Location identity and visual continuity cards
  world/                      World rules, style, jokes, and open mysteries
  relationships.json          Current relationship states and growth directions
  continuity-log.json         Append-only record of canon-changing decisions

episodes/
  _templates/                 Reusable files for every production stage
  in-development/             Concepts, outlines, scripts, and shot packages
  completed/                  Immutable completion records (not generated assets)

schemas/                      Provider-neutral JSON Schema contracts
studio/providers/             A provider interface only; no provider adapters
assets/
  asset-manifest.json         Provenance, class, links, checksums, and approvals
  characters/                 Creator source, approved references, and records
  locations/ props/ animals/  Expandable non-character visual libraries
  ai-generated-tests/         Explicitly non-canon test material
  production/final-approved/  Explicitly approved production outputs

tools/                        Episode scaffolding and content validation

docs/                         Architecture, workflow, and provider guidance
```

## Start a new episode

```bash
python3 tools/new_episode.py EP-002 "Yeti and the Impossible Picnic"
```

The command creates a complete, editable episode workspace beneath `episodes/in-development/`. It does not generate story content or contact any service.

## The Studio application

A local web application (FastAPI + SQLite + a dark SPA frontend) runs above this
content repository:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh            # or: .venv/bin/uvicorn studio.server:app --host 0.0.0.0 --port 8000
```

It provides the Dashboard; the **Story** workspace (story ideas → development
editor → Story Bible → structured canon system); the **Episode** workspace
(episodes → acts → scenes, scene casting from the Character Library, a script
editor with dialogue/narration/sound/camera lines, continuity events and
warnings, and a Ready-for-Storyboard gate that assembles the Phase 4 reference
package); a cross-episode **Scenes** browser; the **Character Bible** browser;
the **Asset Library** (with the explicit Meta AI import workflow); and
**Locations & Props** libraries. Uploaded binaries live under
`assets/studio-uploads/` (git-ignored); the JSON content in this repository
remains the canon source of truth. AI story/video assistance is architected but
honestly not connected — manual writing always works.

Validate all current canon and episode data:

```bash
python3 tools/validate_content.py
```

Register batches of creator source artwork (nothing is ever auto-approved):

```bash
python3 tools/draft_manifest_entries.py --write
```

The repository includes `EP-001-the-great-moonberry-bounce` as a small **in-development example**, not a completed or generated episode. The character system scales to any number of families, children, adults, pets, and animals — see `docs/CHARACTER_INTAKE.md` and `assets/characters/README.md`.

## Production stages

`concept` → `outline` → `script` → `storyboard` → `prompt-ready` → `production` → `completed`

A stage may advance only after its continuity checks are resolved. The detailed handoff checklist is in [`docs/WORKFLOW.md`](docs/WORKFLOW.md).

## What is not connected

There are currently no Seedance, Veo, Higgsfield, voice, music, storage, or publishing integrations. Generation plans stay provider-neutral. Future providers can implement the interface in `studio/providers/base.py` and translate the stable internal request without changing episode content.
