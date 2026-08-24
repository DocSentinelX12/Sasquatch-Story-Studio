# AI-Generated Character Test Material (Non-Canon)

One optional subfolder per character holds AI-generated character experiments (image or video tests): `generated/<character-slug>/`.

Hard rules:

- Everything here is `ai_generated_test_material` — non-canon, never authoritative.
- Generated material NEVER becomes the character design source and NEVER replaces creator artwork, even by accident.
- Nothing here may be used as a character identity reference for providers.
- If the creator approves a generated output for production, it gets a separate `final_approved_production_asset` manifest entry with a `derived_from_asset_ids` link; the original remains an AI test.
- Generated files are excluded from version control (see root `.gitignore`); register any kept test in `assets/asset-manifest.json` with origin `ai_generation`.
- Promotion to canon is impossible from this folder. Only the creator can approve canon, from creator source artwork, under `assets/characters/source/` and `assets/characters/approved/`.

ALL CHARACTERS ARE ALWAYS BAREFOOT — including in AI tests. If a test shows footwear, reject it.
