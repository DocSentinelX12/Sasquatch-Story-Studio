# Character Assets (Scalable System)

This tree supports an unlimited number of creator characters — multiple Sasquatch families, children, adults, different ages, pets, and animals — and scales to many hundreds of reference images. There is no fixed cast size: new characters join by adding catalog entries and folders, never by restructuring.

## Structure

```text
assets/characters/
  character-catalog.json   scalable index: every character, every reference, counts
  families/                family group records (parents, children, pets stay connected)
  records/                 one visual reference record per identified character
  source/                  untouched creator-provided artwork (visual source of truth)
  approved/                creator-approved canon references
  generated/               AI-generated test material (NON-CANON, git-ignored)
  reference-sheets/        approved shared reference-sheet layouts
  expressions/             approved expression references
  poses/                   approved pose/action references
  scale/                   approved character scale references
```

Per-character folders use the character slug (`source/yeti/`). Family intake folders (`source/dark-chocolate-brown-sasquatch-family/`) hold sheets whose individual characters are not yet identified.

## Character records cover

Unique ID, name, species, family, age group, approximate age, role, relationships, parent/child and pet links, source/approved/expression/pose/scale/clothing/color references, personality, animation behavior, master visual prompt, negative prompt, continuity rules, approval status, plus `character_versions` for canonical ages or story periods.

## The catalog/index

`character-catalog.json` answers "where is every image for character X?" Every entry lists source/approved/generated folders and asset counts that must match `assets/asset-manifest.json`. Entries with `catalog_status: registered_shell` flexibly hold not-yet-identified characters without inventing canon.

- `tools/draft_manifest_entries.py` drafts manifest entries for new source files (checksums included) — nothing is ever auto-approved.
- `tools/validate_content.py` enforces the whole system. Run it after any change.

## Authority (never negotiable)

Creator-provided character artwork is authoritative. AI must preserve the established character designs and must not redesign characters. AI-generated material stays separate from approved creator references until the creator explicitly approves it — and even then follows the promotion rules in `assets/ASSET_POLICY.md`.

ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, SANDALS, SLIPPERS, OR ANY OTHER FOOTWEAR.
