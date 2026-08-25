# Sasquatch Story Studio — Application Implementation Plan

Status: **Phase 8 (automation, multi-series, templates, backups, control center) — complete**
Owner: Creator (single-user studio)
Scope of this document: the *application* being built on top of the existing
content repository. It does not replace the content system; it runs above it.

---

## 1. What already exists (inspection results)

The repository already contains a complete **content foundation** built around
portable JSON documents:

| Area | Location | State |
| --- | --- | --- |
| Series bible | `series-bible/` (series.json, characters, locations, world, relationships, continuity log) | Complete, validated |
| Episode planning | `episodes/` (templates, `in-development/EP-001-the-great-moonberry-bounce/`) | EP-001 outlined: 6 scenes, storyboard, dialogue, prompts, continuity |
| Schemas | `schemas/` (16 JSON Schema documents) | Complete |
| Character consistency system | `assets/characters/` (catalog, families, records, source/approved/generated/expressions/poses/scale folders), `assets/asset-manifest.json` | Complete, scales to hundreds of characters |
| Provider contracts | `studio/providers/base.py` (provider-neutral `GenerationProvider` protocol, `GenerationRequest`, `ReferenceImage`, approval gates) | Interface only — intentionally no adapters |
| CLI tools | `tools/new_episode.py`, `tools/validate_content.py`, `tools/draft_manifest_entries.py` | Working, stdlib-only |
| Docs | `docs/` (ARCHITECTURE, WORKFLOW, PROVIDER_INTEGRATION, CHARACTER_INTAKE) | Complete |

Important facts discovered during inspection:

- `assets/characters/source/` currently contains **only README/guidance files and
  `.gitkeep` placeholders in this sandbox — no image files**. When actual creator
  artwork lands in those folders, the app's library scanner registers it without
  modifying anything.
- No AI provider is connected, and none will be pretended to be.
- The repository remains the source of truth for canon. The application database
  is a *working index and production tracker*, never a second canon.

## 2. What can be reused directly

- **`studio/providers/base.py`** — the app's video-generation subsystem is built
  on this exact protocol (`GenerationProvider`, `GenerationRequest`, `JobState`).
- **`assets/asset-manifest.json` + `tools/draft_manifest_entries.py`** — the
  scanner service follows the same asset classes and approval vocabulary
  (`creator_source_artwork`, `approved_canon_reference`, `ai_generated_test_material`).
- **`series-bible/` + `assets/characters/` JSON** — the database seeds from these
  files on first run and links every seeded row back to its `source_path`.
- **`tools/validate_content.py`** — exposed through the app's Settings page as a
  one-click canon validation report.
- **Folder conventions** — the asset library grows the existing tree
  (`assets/characters/source|references|expressions|poses`, `assets/environments`,
  `assets/props`, `assets/episodes`, `assets/music`, `assets/sound-effects`,
  `assets/voice`) without moving anything that already exists.

## 3. What needs to be created (Phase 1 deliverables)

1. **Application shell** — dark cinematic single-page UI with production
   navigation: Dashboard, Projects, Episodes, Characters, Assets, Story, Scenes,
   Shots, Generation Queue, Audio, Timeline, Exports, Settings. Sections not yet
   implemented show an honest "coming in a later phase" state.
2. **Database foundation** — SQLite (WAL) via SQLAlchemy 2.0, ~24 related tables
   (see §4). Zero-config, scales to tens of thousands of rows.
3. **Project system** — multiple projects, each with its own seasons, episodes,
   characters, locations, props, and assets. No cross-project mixing.
4. **Asset foundation** — categories, upload (Meta AI output lands here), versioning,
   tags, favorites, approve/obsolete workflow, search/filter, and *referencing
   existing repo files in place* (no copy, no modify).
5. **Provider architecture** — adapter registry + status + env-var credential
   contract for Seedance / Google Veo / Wan (+ future). Adapters exist as honest
   stubs: they declare required credentials and fail loudly with
   `ProviderNotConfigured` when used. No simulated success.
6. **Generation-job foundation** — job records with the full status lifecycle
   (draft → queued → generating → completed/failed → needs review → approved /
   rejected) so Phase 2+ workers have a ready queue.
7. **Security** — all provider credentials live in server-side environment
   variables (`.env`, git-ignored). The API never returns key values, only
   configured/missing status.

## 4. Database architecture

Engine: **SQLite** at `.data/studio.db` (override with `STUDIO_DB_PATH`),
WAL journal, foreign keys enforced. SQLAlchemy 2.0 ORM models in
`studio/models/`. Tables (FKs → related rows, no large duplication):

```
projects        1─┬─* seasons ─* episodes ─* acts ─* scenes ─* shots
                  ├─* characters ─* character_references ─→ asset_versions
                  ├─* locations          (scenes.location_id)
                  ├─* props
                  ├─* voice_profiles ─→ characters (nullable)
                  ├─* audio_tracks ─→ episodes/scenes/shots (nullable)
                  ├─* generation_jobs ─* generation_results
                  ├─* exports ─→ assets (thumbnail, nullable)
                  ├─* continuity_records
                  └─1 story_bibles / * character_bibles

assets ─* asset_versions          (versioning; old versions never deleted)
assets ─→ characters|locations|episodes|scenes (nullable link)
generation_jobs ─→ providers (by key), shots (nullable)
approvals        (generic ledger: entity_type + entity_id + decision)
providers        (mirror of the code registry; status recomputed from env)
timeline_items ─→ episodes, scenes, shots (Phase 5; table ready now)
```

Key policies encoded in the schema:

- Asset `storage_mode` distinguishes `repo_reference` (file lives in git, never
  touched), `upload` (app-managed file under `assets/studio-uploads/`), and
  `provider_result` (downloaded generation output).
- Asset `asset_class` reuses the manifest vocabulary so the app and the JSON
  manifest system stay interoperable.
- Approval status is explicit everywhere; nothing flips to "approved" by itself.
- `source_path` columns keep every seeded row traceable to its canon JSON file.

## 5. Asset architecture

```
assets/characters/source/        creator artwork (protected, read-only via app)
assets/characters/references/    approved canon references (created on demand)
assets/characters/expressions/   expression sheets
assets/characters/poses/         pose sheets
assets/environments/             environment/background art
assets/props/                    prop art
assets/episodes/<ep>/            per-episode production media
assets/music/  assets/sound-effects/  assets/voice/
assets/studio-uploads/<category>/<yyyy-mm>/   app uploads (git-ignored binaries)
```

- Uploads never overwrite: every upload creates a new `asset_versions` row.
- Marking an asset obsolete hides it from generation input; it is never deleted.
- The scanner registers existing repo files in place with SHA-256 checksums and
  classifies them by folder (source → `creator_source_artwork`, approved →
  `approved_canon_reference`, ai-generated trees → `ai_generated_test_material`).
- Meta AI remains the creator's external image tool: images generated there are
  uploaded/imported into the library and turned into structured production assets.

## 6. Provider architecture

```
studio/providers/base.py         existing provider-neutral protocol (unchanged)
studio/providers/registry.py     definitions: required env vars, capabilities, docs
studio/providers/adapters/       one isolated module per provider (stub → real)
```

- Each adapter declares: `name`, `kind` (video/voice/music), required env vars
  (e.g. `SEEDANCE_API_KEY`), capability notes, and a `submit()` that raises
  `ProviderNotConfigured` until credentials exist.
- `GET /api/providers` reports per-provider status (`not_configured` | `ready`
  | `error`) plus **which env var names are missing — never their values**.
- Generation jobs reference providers by key and store the full normalized
  prompt package (positive/negative, reference images with approval class) so a
  future worker can execute them unchanged.
- The rest of the app talks to the generic interface only. Adding a provider =
  one adapter module + one registry entry.

## 7. Production workflow (target state)

```
Story idea → Story bible → Episode → Acts → Scenes → Shots
   → Reference packages (character/location/prop)
   → Video generation (provider queue) → Voice → Audio
   → Timeline edit → QC gates → Final episode → Shorts/clips → Export
```

Every arrow passes through an explicit approval step. Phase 1 ships the spine
(projects, episodes/scenes/shots scaffold, assets, references, queue records,
exports skeleton) plus the QC/continuity table structure.

## 8. Implementation phases

| Phase | Content | Status |
| --- | --- | --- |
| 0 | Content repository, schemas, character consistency system, provider contracts | **Done (pre-existing)** |
| 1 | App shell, projects, database, asset library + uploads, provider registry/status, generation-job records, dashboard, settings | **Done** |
| 2 | Character & Asset Studio: character profiles/lifecycle, references with categories, relationships, continuity fields, full asset library (search/filter/sort/tags/favorites/versions/approvals/archive), Meta AI import workflow | **Done** |
| 3 | Story layer: Story Bible (versioned, approved-canon guard), canon system (draft→proposed→canon→deprecated), story ideas + development editor, episodes → acts → scenes, scene casting/props from the library, script editor (dialogue/narration/sound/camera with reorder/duplicate/transfer), continuity events + rule-based canon warnings, Ready-for-Storyboard with Phase 4 reference packages, global search, honest AI-assist hooks | **Done** |
| 4 | Storyboard & Shot layer: Scene Director workspace (build-from-script, drag-drop storyboard), full Shot Builder (shot types/camera vocab + natural-language direction), approved reference gathering (characters/locations/props), rule-based validation with audited overrides, approval → Ready-for-Generation gate, 19-section provider-neutral prompt packages + generation packages (frame references, prev/next shot links), append-only shot versions, episode board overview | **Done** |
| 5 | Video-generation provider system: capability-declared adapters for Veo (Gemini API), Seedance (Volcano Ark) and Wan (DashScope/self-hosted) with verified REST contracts, honest connection validation, async generation queue with retries/timeouts, reference prioritization, per-shot versioned results, video review with approve/reject-reasons, usage recording, translated-request preview, provider settings UI + queue + review views | **Done** |
| 6 | Post-production: local/self-hosted audio lane (Local Audio Server contract v1) + honest cloud audio boundaries, character voice profiles, versioned dialogue/narration recordings with approvals, episode timeline (6 mixer tracks, auto-assembly from approved material, non-destructive clip editing), rule-based QC with PASS/WARNING/BLOCKED, Ready-for-Render gate with audited overrides, async ffmpeg render queue (self-hosted free path; honest renderer_not_available), exports + shorts with approval-only publishing | **Done** |
| 7 | Mass production: scale audit + indexed migrations (query-plan verified), cursor pagination, lazy libraries, batch video/audio generation with audited auto-prepare, Production Assistant (READY/MISSING/BLOCKED), configurable worker concurrency, retry classification, storage manager with orphan/duplicate detection and explicit-only cleanup, checksum duplicate detection on import | **Done** |
| 8 | Automation engine (safe, audited rules — prepare/queue only, never approve/publish), notifications, multi-series management with isolation checks, episode templates (capture + instantiate as drafts), full-series JSON backups (media by path), production pause control, Control Center UI | **Done** |
| 9 | Future growth | Next |
| 7 | Scale hardening, automation, multi-series growth | Later |

## 9. Phase 1 acceptance checks

- `python -m tools.validate_content` (repo content) still passes — untouched.
- Server boots with `./run.sh`; UI reachable; all 13 sections render.
- Creating a project, uploading an asset, versioning it, and queueing a draft
  generation job all work end-to-end against SQLite.
- Submitting a generation with no configured provider returns a structured,
  honest error; no fake results anywhere.
- `assets/characters/source/` unchanged (verified by git diff).
