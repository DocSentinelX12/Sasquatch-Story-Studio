# Episode Workflow

## 1. Begin from canon

Read the series bible, character visual records, asset policy, and the cards for every planned character and location. Creator-provided artwork is authoritative for design. Start with `tools/new_episode.py`; do not copy an old episode because accidental continuity travels with copied files.

## 2. Concept

Fill in `episode.json`:

- a one-sentence comic premise;
- the character want and emotional need;
- a lesson expressed as an experience, not a slogan;
- cast and location IDs;
- a closing image or joke.

A concept should create a problem that only these characters would create.

## 3. Outline

Use `story/outline.json` to lock the story spine:

1. immediate visual hook;
2. understandable goal;
3. at least three escalating complications;
4. a low point caused by a character choice;
5. an honest emotional turn;
6. a resolution that uses something planted earlier;
7. a final image or joke.

## 4. Scenes and dialogue

Create one scene file per scene. Describe what changes, what the audience learns visually, and any continuity requirements. Then draft concise, speakable dialogue. Let action carry information whenever possible. Avoid characters stating the lesson directly.

## 5. Storyboard

Break scenes into shots. Every shot must have a story purpose, readable staging, and continuity notes. Vary shot size only when it helps the joke or emotion. Preserve screen direction, props, damage, weather, and time of day.

## 6. Prompt package

Generation prompts are shot-specific and provider-neutral. Include:

- stable character and location IDs;
- ordered, manifest-resolved creator/approved reference-image bindings;
- only the action visible in that shot;
- camera/framing and timing;
- an instruction to preserve—not reinterpret—the official creator design;
- required continuity from the prior shot;
- the global barefoot lock and footwear exclusions;
- dialogue/audio references rather than baked-in assumptions.

If required approved character art is unavailable, the package is blocked. Do not invent missing angles, colors, clothing, accessories, or anatomy.

Do not put provider credentials or endpoint details in story data.

## 7. Audio notes

Plan dialogue performance, ambience, foley, and music intent separately. Music notes describe emotion and pacing, not copyrighted songs or imitation requests.

## 8. Continuity gate

Complete the continuity checklist. Any failed item blocks `prompt-ready`. New facts remain proposals until approved in the series bible and continuity log.

## 9. Production and completion

Future provider adapters may consume prompt records. When all final media exists, create a record from `episodes/_templates/completed-record.json` in `episodes/completed/records/`. Record exact revisions, assets, approvals, release details, and any canon changes.

A completed record does not contain binary video. It is the durable account of what was produced and released.

## Status definitions

| Status | Meaning |
|---|---|
| `concept` | Premise and lesson are being tested |
| `outline` | Story spine exists; script is not locked |
| `script` | Scenes and dialogue are under review |
| `storyboard` | Visual staging is under review |
| `prompt-ready` | Continuity passed; shot prompts are locked |
| `production` | Real media generation/assembly is underway |
| `completed` | A completion record exists |
