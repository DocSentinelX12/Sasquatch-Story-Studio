# Sasquatch Story Studio — Series Bible

**Canon version:** 1.1.0  
**Established:** 2026-08-24  
**Status:** Foundation canon with creator-art authority

This document is the persistent creative source of truth for the series. Structured reference cards beside it are the machine-readable form of the same canon. Any lasting change must update both the relevant card and `continuity-log.json`.

---

## Series identity

**Title:** Sasquatch Story Studio  
**Format:** Repeatable 7–9 minute, family-friendly 2D animated episodes  
**Audience:** Kids and families; jokes should reward adults without excluding children  
**Setting:** Mossy Hollow, a warm, hidden forest community built at Sasquatch scale  
**Logline:** In the hidden forest town of Mossy Hollow, an imaginative young Sasquatch named Yeti turns everyday goals into gloriously oversized adventures, then learns how curiosity, honesty, and kindness can help put things right.

### Creative promise

The audience comes for a specific comic disaster and stays because the characters care about one another. Yeti does not become less curious or energetic when he learns; he learns to use those qualities with a little more awareness. Consequences are real enough to matter, never frightening, cruel, or permanent.

---

## Non-negotiable rules

1. **All characters are always barefoot.** No character ever wears shoes, socks, boots, sandals, slippers, skates, cleats, or any other footwear. If lower bodies are on screen, bare feet or natural paws are visible and unobstructed.
2. **Creator-provided character artwork is authoritative. AI must preserve the established character designs and must not redesign characters.** Creator artwork may not be reinterpreted, replaced, simplified, or overridden by written guesses, prompts, AI tests, or production outputs.
3. The series is always family friendly. It is never horror, disturbing, cruel, cynical, or mean-spirited.
4. Every episode has a meaningful life lesson revealed through choices and consequences. No sermon, moral speech, or preachy summary.
5. Every episode has a strong opening hook, escalating comedy and conflict, an emotional turning point, a satisfying resolution, and a memorable ending.
6. Dialogue is concise, natural, character-specific, and playable. Visual action carries as much story as possible.
7. Character identity is stable: official design, personality, speech, relationships, and signature behavior do not drift between scenes or episodes.
8. Problems may become ridiculous, but danger stays mild, readable, and emotionally safe. Adults are not foolish obstacles; children still have agency.
9. Kindness is never treated as weakness. Mistakes can be funny; humiliation and cruelty are not the joke.

### Generation lock

Every visual prompt must resolve creator-approved character reference images through `assets/asset-manifest.json` before generation. Missing character identity references block generation rather than inviting a model to invent the missing design. Every visual prompt must also include a positive continuity statement that all visible characters have bare feet or natural bare paws, plus explicit negative exclusions for footwear. Never rely on a provider to infer either rule.

---

## Tone and story engine

### Tone

- Warm, playful, quick, sincere, and visually inventive
- Big physical comedy balanced by small truthful reactions
- Heartfelt without sentimentality or lectures
- Cozy wonder rather than fantasy danger
- Surprises that follow character logic, not random chaos

### Repeatable story engine

1. **Hook:** Open on an unusual image, urgent comic result, or unanswered question.
2. **Want:** Yeti wants something understandable and emotionally specific.
3. **Shortcut:** His imagination finds a clever approach with one overlooked flaw.
4. **Escalation:** Each attempted fix makes the visual problem larger or stranger.
5. **Choice and low point:** Yeti's flaw—not bad luck alone—creates an emotional cost.
6. **Turn:** He recognizes what another person needs or admits what he avoided.
7. **Resolution:** Characters solve the problem together using a planted object, skill, or idea.
8. **Button:** End with a fresh visual joke, warm callback, or tiny mystery.

Lessons may include asking for help, telling the truth, listening, patience, sharing credit, including others, adapting plans, caring for a place, handling jealousy, or trying again. Vary them. The lesson must change a choice in the climax.

### Comedy tools

Use anticipation, scale contrast, awkward pauses, reversals, escalating props, background reactions, Yeti's overcommitment, and quiet callbacks. Avoid sarcasm aimed at vulnerable characters, pain as the only punchline, bodily gross-out focus, trendy references, and jokes that require a character to break personality.

---

## Visual language

### Character design authority

Creator-provided artwork defines each character's exact silhouette, construction, anatomy, proportions, features, markings, palette, clothing, accessories, hands, bare feet or paws, and relative scale. No written description in this repository may replace or reinterpret that artwork. Until source artwork is imported and approved references are linked, visual description fields remain intentionally deferred.

- Match the line, shape, texture, and color treatment demonstrated by approved creator artwork; do not impose a conflicting house style.
- Preserve official character construction in every angle, expression, pose, shot, and episode.
- Use expressive, readable acting only within the official design and approved pose/expression range.
- Environments remain clear, warm, and family-friendly while supporting—not altering—the official character art.
- Camera is clear and motivated. Wider frames carry physical comedy; closer frames protect emotional truth.
- No uncanny anatomy, unapproved style conversion, gritty rendering, aggressive contrast, or horror lighting.
- Weather, damage, props, clothing, and character state persist through consecutive scenes until the story visibly changes them.
- Official scale relationships come from creator-approved scale references and remain fixed.

The structured records under `assets/characters/records/` link each character to creator source artwork and approved references through `assets/asset-manifest.json`. AI-generated tests are non-canon. Final approved production assets document finished output but never supersede creator source artwork. Footwear can never be added.

---

## The world

### Mossy Hollow

Mossy Hollow sits in a broad, old-growth valley hidden by ordinary geography, mist, and dense tree cover—not a threatening magical barrier. Sasquatches and woodland neighbors live in a close community. Human civilization is only a distant curiosity and never a source of pursuit or horror.

The world follows warm cartoon physics. A berry cart can bounce through three awnings and land intact if the setup is clear, but emotional and practical consequences remain. Overt magic is rare and ambiguous. Wonder usually comes from nature, imagination, unusual forest science, or an unanswered mystery.

Technology is tactile and repairable: pulleys, waterwheels, baskets, chalkboards, hand tools, lanterns, simple radios, and whimsical contraptions. Screens do not solve plots. Food, plants, and weather follow recognizable patterns with one playful forest twist.

### Community rules

- Children can roam familiar paths and solve age-appropriate problems.
- Adults provide safety and perspective without taking over the climax.
- Nobody is irredeemably villainous. Opposing goals and misunderstandings create conflict.
- Property can be mussed, spilled, tangled, or broken, then repaired or made right.
- Canonical emotional growth accumulates gently; each episode remains accessible to a new viewer.

---

## Established characters

### Yeti — `CHAR-YETI`

A young Sasquatch and the protagonist. Yeti is curious, funny, awkward, energetic, kind, imaginative, and prone to causing ridiculous problems by acting one beat before thinking. He wants to be useful and capable. Under pressure he talks faster, adds unnecessary steps, and insists a wobbling plan is “almost working.” His growth is not toward caution; it is toward noticing others, asking for help, and taking honest responsibility.

**Visual authority:** Yeti's exact design is defined only by creator-provided artwork and approved references linked in `assets/characters/records/yeti.json`. Do not infer colors, proportions, features, clothing, accessories, anatomy, or unseen views. Preserve the creator's exact bare-foot design; no footwear, ever.  
**Voice:** buoyant, sincere, quick when excited; pauses rather than quips when feelings become real.  
**Signature behavior:** starts moving before finishing a sentence; braces as if he can physically hold a plan together.  
**Repeatable line shape (not a catchphrase quota):** “I absolutely meant the first half of that.”

### Juniper “June” — `CHAR-JUNIPER`

Yeti's older sister. Observant, capable, artistic, dryly funny, and protective without wanting to be a substitute parent. June notices the flaw in Yeti's plan early, but her own flaw is assuming that seeing the answer is the same as explaining it kindly. Her arc makes room for patience, collaboration, and letting Yeti surprise her.

**Visual authority:** Juniper's exact design is defined only by creator-provided artwork and approved references linked in `assets/characters/records/juniper.json`. Do not infer colors, proportions, features, clothing, accessories, anatomy, or unseen views. Preserve the creator's exact bare-foot design; no footwear, ever.  
**Voice:** economical and warm; a tiny pause before a deadpan observation.

### Mara — `CHAR-MARA`

Yeti and June's mother, a community baker and practical improviser. Mara is affectionate, busy, perceptive, and comfortable letting children attempt things within safe boundaries. She names feelings plainly but never delivers the episode's moral. Her limitation is trying to do too much herself.

**Visual authority:** Mara's exact design is defined only by creator-provided artwork and approved references linked in `assets/characters/records/mara.json`. Do not infer colors, proportions, features, clothing, accessories, anatomy, or unseen views. Preserve the creator's exact bare-foot design; no footwear, ever.  
**Voice:** grounded, bright, and direct; laughter comes easily.

### Tumble — `CHAR-TUMBLE`

A young raccoon and Yeti's best friend. Tumble is inventive, loyal, fast-talking, and thrilled by any plan with wheels. He can identify twelve ways a machine might fail and still choose the funniest thirteenth. He provides momentum, not blind agreement, and must have wants and choices of his own.

**Visual authority:** Tumble's exact design is defined only by creator-provided artwork and approved references linked in `assets/characters/records/tumble.json`. Do not infer colors, proportions, markings, features, clothing, accessories, anatomy, or unseen views. Preserve the creator's exact uncovered natural bare paws; no footwear, ever.  
**Voice:** quick, precise bursts; delighted whisper when a plan becomes spectacular.

### Ms. Bramble — `CHAR-MS-BRAMBLE`

The fox teacher at Canopy Creek School. Ms. Bramble is calm, curious, playfully rigorous, and difficult to rattle. She responds to an absurd mess by asking the one question that makes children look again. She can be wrong and happily revise her view.

**Visual authority:** Ms. Bramble's exact design is defined only by creator-provided artwork and approved references linked in `assets/characters/records/ms-bramble.json`. Do not infer colors, proportions, markings, features, clothing, accessories, anatomy, or unseen views. Preserve the creator's exact uncovered natural bare paws; no footwear, ever.  
**Voice:** calm and lightly amused, with crisp questions and no baby talk.

---

## Established relationships

- **Yeti and June:** loving siblings. He wants her respect; she wants him safe. Their friction comes from speed versus foresight, never contempt.
- **Yeti and Mara:** secure, affectionate parent-child bond. Mara expects honesty and repair, not perfection.
- **Yeti and Tumble:** best friends and creative accelerants. Either can say no. Tumble is not merely a sidekick or cleanup helper.
- **Yeti and Ms. Bramble:** student and teacher. She channels his curiosity by asking for observations, not by suppressing it.
- **June and Tumble:** friendly rivals over whose practical method is actually practical.

Relationship changes should be incremental and recorded in `relationships.json` after they become canon.

---

## Recurring locations

### Mossy Hollow — `LOC-MOSSY-HOLLOW`

The walkable forest town: giant cedar trunks, rope railings, root bridges, cloth awnings, creek-stone paths, and a circular gathering green. It should feel cozy and busy, never medieval or urban. A carved wooden bell marks community announcements.

### Big Cedar Home — `LOC-BIG-CEDAR-HOME`

Yeti's family home built into the sheltered base of a living cedar. The round kitchen is the visual hub: crescent window, blue kettle, heavy table, peg wall, and a height-mark post. Yeti's loft contains drawings, string, cardboard prototypes, and one tidy shelf June maintains by negotiated border.

### Canopy Creek School — `LOC-CANOPY-CREEK-SCHOOL`

An open, welcoming schoolhouse beside a shallow creek. Half-log classroom, broad windows, chalk wall, mismatched stump seats, covered experiment porch, and a foot-washing pump near the entrance. The pump reinforces muddy bare feet without introducing footwear.

### Moonberry Market — `LOC-MOONBERRY-MARKET`

A weekly market under patchwork awnings around the gathering green. Stalls use baskets, slate signs, hanging scales, and rolling handcarts. Ripe moonberries are purple-blue, faintly luminous at dusk, and comically springy when overripe. They are not magical and do not speak.

---

## Running jokes and recurring threads

Running jokes are ingredients, not obligations:

- Yeti enters with too much momentum and needs three small steps to stop.
- A patient woodpecker taps once after especially awkward silences.
- Yeti's first plan often has a confidently labeled lever whose label becomes inaccurate.
- June quietly finds an unexpected practical use for an ordinary scene prop established earlier.
- Tumble gives overly specific odds that are immediately disproved.

Open gentle mysteries:

- Why do moonberries hum faintly only on the first cool evening of autumn?
- Who made the tiny, careful trail markers beyond Whispering Falls?
- Why does the old community bell sometimes ring once when there is no wind?

Mysteries should produce wonder and adventure, never dread. Do not answer one casually; update the open-thread registry when clues or answers become canon.

---

## Continuity checklist

Before an episode becomes prompt-ready, confirm:

- [ ] Every character has manifest-registered creator source artwork and the required creator-approved references.
- [ ] Every provider reference resolves through the manifest and excludes AI-generated test material.
- [ ] Every visible character is explicitly barefoot or shown with natural bare paws.
- [ ] Every prompt excludes all footwear.
- [ ] Character design, silhouette, palette, scale, clothing, accessories, voice, and behavior exactly match creator-approved references and canon records.
- [ ] Relationship behavior matches the latest state.
- [ ] Location landmarks, layout, season, weather, and time of day are consistent.
- [ ] Props, stains, damage, carried objects, and entrances/exits persist between shots.
- [ ] The hook is immediate and visual.
- [ ] Comedy escalates rather than repeats.
- [ ] A character choice creates the emotional turn.
- [ ] The lesson changes the resolution and is not spoken as a sermon.
- [ ] The final beat is memorable and tonally warm.
- [ ] Nothing is frightening, disturbing, cruel, or visually uncanny.
- [ ] Any new canon proposal is reviewed and logged.

---

## Canon maintenance

The bible may grow, but should remain specific and usable. Add new characters and locations through their structured cards. Character visual facts enter canon only from creator-provided artwork or explicit creator approval recorded in the asset manifest; AI-generated material cannot establish or revise character design. Record accepted changes in the append-only continuity log with the episode or creator decision that established them. Never rewrite a prior event merely to simplify a new story; either honor it or make a deliberate, documented revision.
