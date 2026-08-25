# Video Provider Setup (Phase 5)

This guide covers connecting real AI video providers to Sasquatch Story
Studio, the capability system, the generation workflow, and testing.

---

## 1. Which providers are supported?

Three real adapters ship, implemented against their **verified, current REST
contracts** (researched from official documentation — nothing invented):

| Provider | Adapter | API contract | Docs |
| --- | --- | --- | --- |
| Google Veo | `studio/providers/adapters/veo.py` | Gemini API `models/{model}:predictLongRunning`, operation polling, `generatedSamples[0].video.uri` download | https://ai.google.dev/gemini-api/docs/veo |
| Seedance (ByteDance) | `studio/providers/adapters/seedance.py` | Volcano Engine Ark `contents/generations/tasks` (create + poll), `content.video_url` | https://www.volcengine.com/docs/85621 |
| Wan (Alibaba) | `studio/providers/adapters/wan.py` | DashScope async `video-synthesis` (`X-DashScope-Async`), `tasks/{id}` poll, `output.video_url`; custom base URL for self-hosted endpoints | https://www.alibabacloud.com/help/en/model-studio/ |

A fourth **TEST adapter** (`test-echo`) exists for development/testing. It is
disabled by default, clearly labelled everywhere, performs no network calls,
and its outputs are marker files explicitly marked
"TEST ADAPTER OUTPUT — NOT A REAL VIDEO". It is never presented as real AI
generation.

## 2. Environment variables (server-side only)

Copy `.env.example` to `.env` (git-ignored) and fill in only what you have:

```bash
# Google Veo (Gemini API)
GEMINI_API_KEY=...
VEO_MODEL=veo-3.1-generate-preview        # optional

# Seedance (Volcano Engine Ark)
SEEDANCE_API_KEY=...
SEEDANCE_MODEL=doubao-seedance-2-0-260128 # optional
SEEDANCE_API_BASE_URL=https://ark.cn-beijing.volces.com/api/v3  # optional

# Wan (Alibaba Model Studio / DashScope, or self-hosted)
WAN_API_KEY=...                            # or DASHSCOPE_API_KEY
WAN_REGION=singapore                       # beijing | singapore | virginia
WAN_API_BASE_URL=...                       # optional: self-hosted endpoint
WAN_T2V_MODEL=wan2.2-t2v-plus
WAN_I2V_MODEL=wan2.2-i2v-plus

# Development test adapter (clearly marked; no network)
STUDIO_TEST_PROVIDER=1
```

**Security rules enforced by the architecture:**
- Credentials are read only on the server (process env / `.env`).
- API responses include env variable **names** (e.g. "missing GEMINI_API_KEY"),
  never values.
- "Connected" status appears **only** after a real, free validation call
  succeeds (Settings → Validate Connection). Credential presence alone is
  reported as "Available", never "Connected".

## 3. Capabilities (what each provider supports)

Capabilities are declared from provider documentation in
`studio/providers/capabilities.py` and surfaced via `GET /api/providers`.
The Generate dialog **disables unsupported options automatically**:

| | Veo | Seedance | Wan |
| --- | --- | --- | --- |
| Text → video | ✓ | ✓ | ✓ |
| Image → video (first frame) | ✓ (local file, base64) | ✓ (public URL) | ✓ (public URL) |
| Last frame / start-end | — | ✓ | — |
| Extra reference images | — | — | — |
| Audio generation | ✓ | ✓ | — |
| Seed | — | ✓ | — |
| Durations | 4/6/8 s | 4/5/8/10 s | ~5 s |
| Resolutions | 480p/720p/1080p | 480p/720p/1080p | 480P/720P/1080P |
| Aspect ratios | 16:9, 9:16 | 16:9…21:9, adaptive | 16:9, 9:16, 1:1 |

Reference limits are respected automatically: if a provider has fewer
reference slots than the universal generation package contains, references
are prioritized (first frame > last frame > primary character > expressions >
poses > location > storyboard) and **skipped references are recorded** on the
job (`submitted_references`). Note: Seedance/Wan require publicly accessible
URLs for reference images — local repo files are skipped with an explanatory
reason (Veo consumes local files via base64).

**Automatic provider mode** selects a configured provider whose capabilities
match the shot's requirements (aspect ratio, duration, frames). The settings
dialog in Automatic mode offers only the **intersection** of available
providers' options. No cost or performance claims are made.

## 4. Generation workflow

```
Shot approved + Ready for Generation
  → Scene Director → shot → Generate tab
  → choose provider (or Automatic) + capability-gated settings
  → Preview exact request (provider-translated; nothing submitted)
  → Generate now  → job created (draft → submitting → submitted)
  → async poll worker (server-side thread; resumes on reboot)
  → result downloaded to renders/shots/<shot>/… (versioned per shot)
  → job Needs Review → Generation Queue → Video Review
  → Approve (shot → complete) / Reject (reason required; shot → needs_revision)
  → Retry = NEW attempt (provider/settings changeable; failures preserved)
```

Every job stores: provider, provider job id, attempt number, generation
package version, the exact translated request, submitted/skipped references,
usage metadata (only what the provider reports — costs are never invented),
timestamps, and structured error codes
(`provider_not_configured`, `authentication_failed`, `invalid_request`,
`api_error`, `generation_failed`, `provider_timeout`).

## 5. Testing

```bash
# Complete Phase 5 suite — mocked providers only, no paid API calls
.venv/bin/python tools/test_phase5.py

# Canon content validator (repository JSON)
python3 tools/validate_content.py
```

The suite covers adapter contracts (against `httpx.MockTransport`),
capability gating, automatic-mode intersection, security, the full shot
workflow (draft → … → approved, second version on a complete shot), retry,
versioning, review rules, and Phase 1–4 endpoint regression.

## 6. Current limitations

- **No credentials are configured in this environment** — all three real
  providers honestly report "Not Configured". Add keys to `.env` and restart;
  adapters are ready.
- Polling is a per-job background thread (single-creator scale). Webhook
  support and a central worker can be added without changing the contract.
- Veo first-frame images are uploaded as base64 (local files work); Seedance
  and Wan reference images must be public URLs — a media-hosting step can be
  added later.
- Model identifiers default to the documented versions at research time and
  are overridable via env; verify current model names with your account.
- No automatic publishing, no automatic approvals — by design.
