# Zero-Recurring-Cost Production Policy

Sasquatch Story Studio is designed so production does not depend on paid subscriptions, paid hosted APIs, metered generation credits, or proprietary cloud generation services.

## Required architecture

- Production inference runs locally.
- LLMs are local and license-verified.
- Image, video, animation, voice, lip-sync, music, compositing, editing, and rendering use locally installed verified engines.
- Remote model execution is disabled by policy.
- Paid APIs and paid hosted services are disabled by policy.
- Unknown or unverified licenses are rejected.
- Missing local runtimes fail loudly. The studio never substitutes a paid service or simulates success.

## What this does not promise

Software can be free while the computer running it still has ordinary costs such as electricity, storage, internet access, and hardware. The policy means the studio itself does not require recurring vendor fees or generation credits.

## Licensing rule

Open source does not automatically mean every checkpoint, voice, model weight, dataset, or generated asset has identical commercial permissions. Every integrated engine and model must carry explicit provenance and license metadata before production use. Territory restrictions, attribution requirements, and model-specific terms remain part of the verification gate.
