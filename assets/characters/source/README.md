# Creator Source Artwork (Visual Source of Truth)

Place untouched creator-provided character artwork here. Nothing in this folder may ever be AI-generated, edited, or "cleaned up" — import the original file exactly as the creator supplied it.

## Layout

- `source/<character-slug>/` — artwork for an identified character (e.g. `source/yeti/`).
- `source/<family-intake>/` — artwork for a family whose individual characters are not yet identified. Current intake folders:
  - `dark-chocolate-brown-sasquatch-family/`
  - `family-06-abominable-white-yeti/`

Add as many characters and families as the creator needs; the system has no fixed cast size. Create a family record in `assets/characters/families/` for every intake folder so relationships stay connected even before members are identified.

## Registration

1. Copy files in unchanged.
2. Run `python3 tools/draft_manifest_entries.py` (drafts `creator_source_artwork` manifest entries with SHA-256 checksums; family-folder files register against the `FAMILY-*` id until the creator identifies the characters).
3. Creator verifies identity/design; only then may references be approved and linked in character records.

Never overwrite an imported source file — add a new file and a new manifest entry. Source artwork is authoritative, but it must still be registered and verified in `assets/asset-manifest.json` before any automated or provider use. See `docs/CHARACTER_INTAKE.md` for the full batch workflow.
