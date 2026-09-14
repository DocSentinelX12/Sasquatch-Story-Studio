# Zero-Recurring-Cost Production Policy

Sasquatch Story Studio is designed so production does not depend on paid subscriptions, paid hosted APIs, metered generation credits, or proprietary cloud generation services.

## Required architecture

- Production work may run on locally controlled machines or on explicitly configured, genuinely free remote compute resources.
- Remote resources are optional and may have quotas, session limits, queues, storage limits, bandwidth limits, or availability restrictions.
- LLMs remain local and license-verified under the separate LLM policy.
- Image, video, animation, voice, lip-sync, music, compositing, editing, and rendering use verified engines and explicit runtime evidence.
- Paid APIs and paid hosted services are disabled by policy.
- Unknown or unverified licenses are rejected.
- Missing runtimes fail loudly. The studio never substitutes a paid service or simulates success.
- Free remote access is never assumed merely because a provider offers a free tier. The resource must be explicitly configured, reachable, and observed as available before work is routed there.

## Zero-dollar boundary

The studio itself does not require recurring vendor fees, generation credits, paid GPU rental, paid hosted storage, or metered inference. This does not make hardware, electricity, storage media, internet access, or third-party free-tier availability unlimited.

## Licensing rule

Open source does not automatically mean every checkpoint, voice, model weight, dataset, or generated asset has identical commercial permissions. Every integrated engine and model must carry explicit provenance and license metadata before production use. Territory restrictions, attribution requirements, and model-specific terms remain part of the verification gate.
