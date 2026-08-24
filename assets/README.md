# Asset Library

This library registers creator artwork, approved canon references, AI-generated tests, and final production assets without confusing their authority.

## Required structure

```text
assets/
  asset-manifest.json
  ASSET_POLICY.md
  characters/
    character-catalog.json  scalable index of every character and their references
    families/               family group records (parents/children/pets stay connected)
    records/                structured visual-reference records
    source/                 untouched creator-provided artwork
    approved/               creator-approved canon references
    generated/              AI-generated test material (non-canon, git-ignored)
    reference-sheets/       approved reference-sheet layouts
    expressions/            approved expression references
    poses/                  approved pose/action references
    scale/                  approved character scale references
  locations/             location art and references
  props/                 prop art and references
  animals/               non-character animal art and references
  ai-generated-tests/    non-canon AI experiments
  production/
    final-approved/      creator-approved production outputs
```

There is no artwork in this repository yet. README files and empty tracked character folders only reserve safe import locations.

## Authority

**Creator-provided character artwork is authoritative. AI must preserve the established character designs and must not redesign characters.**

An asset file is not approved merely because it is stored under `assets/`. Every usable reference must have an entry in `asset-manifest.json`, an appropriate asset class, and explicit approval metadata. AI-generated material never automatically becomes canon and never supersedes creator source artwork.

See `ASSET_POLICY.md` for registration and promotion rules.
