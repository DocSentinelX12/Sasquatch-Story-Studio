# Visual Asset Authority and Approval Policy

## Authority order

When visual instructions conflict, use this order:

1. **Creator source artwork** — the authoritative character design.
2. **Approved canon references** — creator-approved views, crops, sheets, color keys, or annotations derived from and consistent with source artwork.
3. **Written continuity** — personality, relationships, scene state, and the global barefoot rule.
4. **Shot prompts** — action and camera instructions that may not alter character design.
5. **AI-generated tests** — non-canon experiments with no authority.

Final approved production assets document a released shot or episode. They do not replace source artwork as the character-design authority.

## Immutable asset classes

Every manifest entry uses exactly one class:

- `creator_source_artwork`
- `approved_canon_reference`
- `ai_generated_test_material`
- `final_approved_production_asset`

An asset class is historical provenance and must not be changed to “promote” a file. If an AI test is selected for production, create a separate final-production entry with explicit creator approval and a `derived_from_asset_ids` link. The original remains an AI test. An AI test can never become the authoritative character design.

## Import workflow

1. Copy the creator's original file unchanged into the character's `source/<character>/` folder.
2. Add a manifest entry with class `creator_source_artwork`, checksum, creator ownership/provenance, and `registered` approval state.
3. The creator verifies identity and design. Record the reviewer and date; never infer approval.
4. Add any approved turnaround, expression, pose, scale, clothing, or color references to the matching approved folder and register each as `approved_canon_reference`.
5. Link approved asset IDs in the character's record under `assets/characters/records/`.
6. Run `python3 tools/validate_content.py`.

Do not modify source files to make them easier for a provider. Create a derived working file with its own manifest entry and provenance.

## Scale rules (multiple families, children, pets, animals)

- **No fixed cast size.** Any number of characters and families may exist. Add characters via `assets/characters/character-catalog.json`, families via `assets/characters/families/`.
- **Characters may be identified later.** Family intake folders under `source/` hold sheets that are not yet tied to named characters; manifest entries link to the `FAMILY-*` id until the creator identifies each character. Never guess which sheet depicts which character.
- **Versions preserve age canon.** One character may have several `character_versions` (different canonical ages or story periods). Each version may carry its own approved references; only creator artwork defines a version.
- **Pets and animals are full characters.** They get `character_kind: animal`, their own folders, records, versions, and continuity — including the barefoot rule where applicable (bare paws, hooves, or claws).
- **AI tests stay separated.** `ai_generated_test_material` may only live under `assets/characters/generated/` or `assets/ai-generated-tests/` — never in source or approved trees.

## Reference-image rules for future providers

- Resolve IDs through `asset-manifest.json`; never pass an unregistered path or temporary URL from story content.
- Send only creator source artwork explicitly approved for provider use and approved canon references.
- Keep reference order and purpose (`identity`, `turnaround`, `expression`, `pose`, `scale`, `clothing`, `color`) in the normalized request.
- Block generation when a required character reference is missing. Do not ask a model to invent the missing view.
- Never use `ai_generated_test_material` as a character identity reference.
- Provider adapters may resize or encode a file for transport, but may not alter its design, colors, proportions, clothing, or barefoot state.

## Barefoot lock

ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, SANDALS, SLIPPERS, OR ANY OTHER FOOTWEAR.

This rule applies to creator-reference review, AI tests, background characters, sports, costumes, weather scenes, final production assets, and every future provider request.
