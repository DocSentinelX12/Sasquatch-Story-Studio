# Character Artwork Intake (Built for Hundreds of Images)

The studio expects large creator collections: multiple Sasquatch families, children, adults, different ages, pets, and animals. This workflow imports them without redesigning, reinterpreting, or re-encoding anything.

## Golden rules

1. **Creator art is never touched.** Copy files in unchanged. Never overwrite; add new files.
2. **Nothing is auto-approved.** Import creates `registered` entries only. The creator alone approves.
3. **Unknown characters stay unknown.** Unidentified sheets register against a `FAMILY-*` id, not a guessed `CHAR-*` id.
4. **AI output never enters this pipeline as canon.** AI tests live only under `assets/characters/generated/` or `assets/ai-generated-tests/`.

## Batch workflow

1. **Choose the destination folder**
   - Identified character → `assets/characters/source/<character-slug>/`
   - Not yet identified → a family intake folder, e.g. `assets/characters/source/dark-chocolate-brown-sasquatch-family/`
   - New family → first add a record in `assets/characters/families/`, then create the matching intake folder.

2. **Copy the original files in.** Hundreds at a time is fine; subfolders are allowed for organization (e.g. per-sheet batches).

3. **Draft manifest entries**
   ```bash
   python3 tools/draft_manifest_entries.py            # show what would be registered
   python3 tools/draft_manifest_entries.py --write    # append creator_source_artwork entries
   ```
   The tool checksums every file, assigns `ASSET-SRC-*` ids, sets approval to `registered`, and links entries to the owning `CHAR-*` or `FAMILY-*` id from the folder location. It never approves anything and never re-registers an existing file.

4. **Validate**
   ```bash
   python3 tools/validate_content.py
   ```
   Validation fails if any file under `source/` is unregistered, if catalog counts drift from the manifest, or if family/character links disagree.

5. **Creator identification and approval**
   - Confirm which characters (and ages/story periods) each sheet depicts.
   - Move metadata from the family entry into character records: update `assets/characters/character-catalog.json`, create or extend `assets/characters/records/<character>.json`, and update the manifest `entity_ids`/`family_id`/`character_version_id` fields.
   - Mark verified sources `creator_verified`; approve canon references only from creator source artwork.

## Adding a new pet or animal

Pets and animals are full characters:

1. Add the character to `character-catalog.json` with `character_kind: "animal"`.
2. Create `assets/characters/records/<animal>.json` (`character_kind: "animal"`, `caretaker_character_ids` set to the owning people, and `species` from creator confirmation).
3. Link it to its family record via the family's `pet_character_ids`.
4. The barefoot rule still applies in spirit: bare paws/claws/hooves, no pet shoes or booties.

## Adding a canonical character version (age/story period)

Only when creator artwork shows a different canonical age or story period:

1. Add a `character_versions` entry in the character's record (unique `VER-*` id, `age_group`, `story_period`, one primary version).
2. Register that version's references with `character_version_id` in the manifest.
3. Never create a version from AI output or inference.
