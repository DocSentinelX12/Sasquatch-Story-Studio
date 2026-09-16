# Sasquatch Story Studio Build Rules

## Status

These rules are mandatory engineering constraints for Sasquatch Story Studio. They exist to protect the studio's long-term production capability, creative fidelity, and reliability.

## Non-negotiable engineering rules

### 1. Inspect before every fix

Before changing code, configuration, workflows, schemas, tests, or production contracts, inspect the complete affected path and its dependencies.

At minimum, determine:

- what consumes the affected behavior
- what the affected behavior consumes
- which interfaces and contracts connect the pieces
- which tests exercise the path
- which integrations or runtime assumptions depend on it
- which existing capabilities could be affected by the change

Do not make a surgical fix based only on the first failing line or first visible symptom.

### 2. Never chase green tests

Tests are a safety mechanism, not the objective.

Never:

- weaken a test merely to make it pass
- delete a test because it exposes a defect
- skip a test to obtain a green suite
- change expected behavior solely to satisfy an existing assertion
- remove working functionality because it is inconvenient to test
- fabricate evidence, mocks, placeholders, or simulated production behavior and call it integration

If a test is wrong, prove why it is wrong from the surrounding contract and then correct the test and implementation together as appropriate.

### 3. Test behavior, not execution

A command completing successfully is not proof that the feature works.

Verification must test the actual behavior and, where relevant, the real runtime, integration boundary, produced artifact, continuity contract, or user-visible result.

A green unit test does not by itself establish production correctness.

### 4. Establish the failure before fixing it

For a bug or regression, reproduce or otherwise establish the failing behavior before implementing the fix whenever practical. Identify the actual root cause rather than treating a symptom.

If reproduction is impossible, record the evidence and uncertainty explicitly rather than inventing a reproduction.

### 5. Make the smallest correct change

Prefer the smallest change that correctly fixes the root cause while preserving all unrelated behavior.

Smallest does not mean simplistic. Do not remove advanced capabilities, bypass architecture, or reduce functionality merely to reduce test or implementation complexity.

### 6. Preserve existing capabilities

Every change must protect working functionality unless the creator explicitly approves a behavior change.

Before and after a change, consider adjacent capabilities, compatibility contracts, persistence, recovery, provenance, continuity, and real-engine behavior.

### 7. Verify broadly after focused verification

After implementation:

1. run focused tests for the changed behavior
2. run tests covering affected dependencies and integration boundaries
3. run the broader relevant suite
4. verify real runtime behavior when the change crosses a runtime or engine boundary
5. inspect failures instead of modifying tests blindly

Verification must be fresh. Previous green results are not evidence for a new change.

### 8. Never claim completion without evidence

Do not describe a fix, integration, feature, or build step as complete, working, passing, or production-ready without current verification evidence supporting that claim.

If verification is blocked by infrastructure, dependency, credential, provider, or environment failure, state that limitation precisely and distinguish it from application correctness.

### 9. No fake integrations

Never invent or guess:

- APIs
- credentials
- provider endpoints
- selectors
- runtime commands
- model identifiers
- engine behavior
- installation results
- production artifacts
- integration success

A provider or engine is integrated only after its real workflow has been verified. A documented future provider is not the same thing as an implemented provider.

### 10. Preserve provenance and reproducibility

Production changes must preserve the studio's provenance, versioning, hashes, approvals, and durable state contracts. Existing approved artifacts must not be silently overwritten when versioned preservation is required.

### 11. Creative intent is canonical

Creator instructions are the authoritative creative contract. Engineering changes must not silently rewrite, reinterpret, or weaken creator intent.

Consequential creative changes follow the approval workflow defined in `docs/CREATIVE_CONTROL.md`.

### 12. Protect episodic independence

Episodes are independently producible. Episode-local story state must not leak into another episode merely because assets, characters, voices, locations, or visual language are reused.

Continuity is enforced strongly within an episode and across connected shots, while cross-episode continuity exists only when the creator explicitly makes it canonical.

### 13. Surgical creative changes

When a creator requests a correction, identify the smallest affected production scope and explicitly protect unrelated approved material.

Regenerate or edit only what is necessary, reconnect it to neighboring material, and validate continuity before accepting the result.

### 14. Keep building forward

Debugging and CI repair must not become the purpose of the project. Once the affected issue is correctly diagnosed and contained, continue advancing the studio's actual production capabilities.

Infrastructure failures must be distinguished from application failures. Do not rewrite sound application architecture merely because an external CI runner or service is unhealthy.

## Required operating sequence

The default engineering sequence is:

> **Inspect first. Fix second. Verify third. Build forward fourth.**

This sequence applies to every future change in Sasquatch Story Studio.

## Definition of success

The goal is a durable, creator-controlled cartoon production studio capable of supporting decades of independent episodes, not a repository optimized for passing CI at the expense of production capability.
