# Creative Control and Episodic Continuity

## Purpose

Sasquatch Story Studio is an episodic cartoon production system. Each episode is independently producible and does not inherit plot chronology, wardrobe, setting, season, props, or other story-state assumptions from another episode unless the creator explicitly chooses to reuse them.

## Creator authority

The creator is the final creative authority and release gate. Story, dialogue, character instructions, scene instructions, and explicitly requested changes are canonical.

The studio must never silently rewrite or reinterpret a creator-requested story change. When a production change is needed, the studio records the requested scope, the protected content that must remain unchanged, and the resulting verification evidence. The creator approves the change before it becomes part of the approved episode.

## Surgical change contract

A requested episode change is scoped to the smallest affected production units. A change may target dialogue, performance, action, prop, character appearance, camera, timing, audio, transition, shot, or scene. Unrelated approved material is protected by default.

The production system should regenerate only the affected material and reconnect it to its neighboring material through continuity checks. A correction must preserve the established story, character identity, visual language, timing relationships, audio relationships, and physical state except where the creator explicitly requested a change.

## Continuity contract

Continuity is enforced within an episode, not between independent episodes.

For each shot, the production state tracks the information needed to preserve flow, including:

- dialogue identity and timing
- speaker and listener state
- pauses, interruptions, and performance intent
- character positions and actions
- object and prop state
- character appearance and wardrobe for the episode
- environment, lighting, and time-of-day state
- camera framing and movement
- audio, music, ambience, and sound-effect timing
- entry and exit state required to connect adjacent shots

A subsequent shot must be compatible with the approved end state of the preceding shot unless the creator explicitly defines a transition or discontinuity.

## Approval workflow

1. The creator describes the desired change in ordinary language.
2. The studio identifies the smallest affected scope.
3. The studio identifies protected material and intended continuity constraints.
4. The studio presents the proposed change for creator approval when the change is not already explicitly approved for execution.
5. After approval, only the affected production state is regenerated or edited.
6. The studio validates the corrected material against adjacent shots and the episode's continuity state.
7. The corrected episode remains subject to the normal final creator approval gate.

## Image-art provider boundary

Image generation providers are replaceable production backends. Meta AI may be used as a creator-selected image-art provider when a real supported workflow is available, but provider-specific behavior must not become the canonical story, character, or episode data model.

The studio must never claim a Meta AI integration, API, credential flow, selector, or automation path exists until it has been verified in the repository and the actual provider workflow.

## Quality principle

The goal is not merely to produce a technically valid clip. The goal is a connected cartoon episode in which dialogue, acting, movement, camera, scene breaks, sound, and visual identity flow naturally enough that corrections do not look like an AI-generated interruption.
