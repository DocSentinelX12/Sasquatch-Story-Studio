// Mobile-first generation experience: Episode → Scene → Shot → Generate.
// Works at every viewport; designed for thumbs (provider cards, bottom sheets,
// big Generate button). No raw JSON required.
import {
  el, ICONS, statusPill, pretty, loadingState, errorState, toast, field, openModal,
} from "../ui.js";
import { getJSON, postJSON } from "../api.js";

let container;
let shotId;
let shot = null;
let providers = [];
let selected = "auto";
let settings = { duration_seconds: null, resolution: null, aspect_ratio: "16:9", seed: null, generate_audio: null };
let advancedOpen = false;
let pollTimer = null;

export async function render(c, id) {
  container = c;
  shotId = Number(id);
  container.replaceChildren(loadingState("Loading shot…"));
  try {
    const projectId = localStorage.getItem("studio.projectId");
    const [shotData, providerData] = await Promise.all([
      getJSON(`/api/shots/${shotId}`),
      getJSON("/api/providers"),
    ]);
    shot = shotData;
    providers = providerData.providers.filter((p) => p.kind === "video");
    draw();
    startPolling();
  } catch (error) {
    container.replaceChildren(errorState(error, () => render(c, id)),
      el("div", { style: "margin-top:10px" }, el("a", { class: "btn ghost small", href: "#/shots" }, "← All Shots")));
  }
}

function availableProviders() {
  return providers.filter((p) => p.key !== "test-echo" || true);
}

function selectedCaps() {
  if (selected === "auto") return autoCaps();
  const provider = providers.find((p) => p.key === selected);
  return provider?.caps || null;
}

function autoCaps() {
  const available = providers.filter((p) => p.status !== "not_configured" && p.caps);
  if (!available.length) return null;
  const intersect = (lists) => lists.reduce((acc, list) => acc.filter((v) => list.includes(v)));
  return {
    durations: intersect(available.map((p) => p.caps.durations || [])),
    resolutions: intersect(available.map((p) => p.caps.resolutions || [])),
    aspect_ratios: intersect(available.map((p) => p.caps.aspect_ratios || [])),
    seed_support: available.every((p) => p.caps.seed_support),
    audio_generation: available.every((p) => p.caps.audio_generation),
  };
}

function capsFor(providerKey) {
  if (providerKey === "auto") return autoCaps();
  return providers.find((p) => p.key === providerKey)?.caps || null;
}

function draw() {
  const best = shot.references?.find((r) => r.purpose === "storyboard_image" && r.asset);
  const thumb = best?.asset && (best.asset.mime_type || "").startsWith("image/")
    ? `/api/assets/${best.asset.id}/file` : null;

  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("h2", {}, "Generate Video"),
        el("div", { class: "desc" }, `${shot.shot_ref || `Shot ${shot.number}`} · ${shot.title || "Untitled"}`)),
      el("div", { class: "actions" },
        el("a", { class: "btn ghost small", href: `#/scenes/${shot.scene_id}/director`, style: "text-decoration:none" }, "Scene Director ↗"))),
    el("div", { class: "card", style: "margin-bottom:14px" },
      el("div", { style: "display:flex; gap:12px; align-items:flex-start" },
        thumb ? el("img", { src: thumb, style: "width:120px; border-radius:10px", alt: "" }) : null,
        el("div", { style: "flex:1; min-width:0" },
          statusPill(shot.status),
          el("div", { style: "margin-top:7px; font-size:13px" }, shot.description || shot.action || "No description."),
          el("div", { style: "display:flex; gap:6px; flex-wrap:wrap; margin-top:8px" },
            el("span", { class: "pill s-outline" }, [pretty(shot.shot_type || "type?"), pretty(shot.camera_movement || "—"), `${shot.duration_seconds || 0}s`].join(" · ")),
            (shot.cast || []).map((l) => el("span", { class: "pill s-outline" }, l.character?.name || "")).filter(Boolean)))),
      shot.status !== "ready_for_generation" && !["generating", "generated", "complete", "needs_revision"].includes(shot.status)
        ? el("div", { class: "callout", style: "margin-top:10px; font-size:12.5px" },
            "This shot isn't ready yet — approve it in the Scene Director first. Generation requires the Ready for Generation status.")
        : null),
    providerSection(),
    advancedSection(),
    el("div", { style: "height:86px" }), // spacer for sticky bar
    el("div", { class: "sticky-actions" },
      el("button", {
        class: "btn-generate",
        disabled: !["ready_for_generation", "generating", "generated", "complete", "needs_revision"].includes(shot.status) ? "" : null,
        onclick: generate,
      }, el("span", { html: ICONS.spark }), "Generate Video")),
    resultSectionMount());
}

/* ---------------- provider cards ---------------- */
function providerSection() {
  const cards = el("div", { class: "provider-cards" });

  const autoCard = el("button", {
    class: `provider-card-tap ${selected === "auto" ? "selected" : ""}`,
    onclick: () => { selected = "auto"; draw(); },
  },
    el("div", { class: "radio" }),
    el("div", { class: "meta" },
      el("div", { class: "name" }, "⚡ Automatic Best Match"),
      el("div", { class: "sub" }, "Matches capabilities: image-to-video, references, frames, duration, ratio, audio, availability"),
      el("div", { class: "tags" }, tagPills(autoCaps()))));

  cards.append(autoCard);
  for (const provider of providers) {
    const caps = provider.caps;
    const unavailable = provider.status === "not_configured";
    cards.append(el("button", {
      class: `provider-card-tap ${selected === provider.key ? "selected" : ""}`,
      onclick: () => { selected = provider.key; draw(); },
    },
      el("div", { class: "radio" }),
      el("div", { class: "meta" },
        el("div", { class: "name" }, `${provider.is_test ? "🧪 " : ""}${provider.display_name}`),
        el("div", { class: "sub" },
          unavailable
            ? `Not configured${provider.missing_env?.length ? ` — needs ${provider.missing_env.join(", ")}` : ""}`
            : `Available${provider.caps ? "" : " — adapter pending verified API contract"}`),
        el("div", { class: "tags" },
          provider.key === "local" ? el("span", { class: "pill s-purple", style: "padding:1px 7px; font-size:10px" }, "self-hosted · no per-video credits") : null,
          tagPills(caps)))));
  }
  return el("div", { class: "card" },
    el("h3", {}, "Provider"),
    cards,
    el("div", { class: "muted", style: "font-size:11px; margin-top:10px" },
      "Cloud providers bill per their own pricing. Local / Self-Hosted runs on your hardware — the studio adds no limits."));
}

function tagPills(caps) {
  if (!caps) return [el("span", { class: "pill s-outline", style: "padding:1px 7px; font-size:10px" }, "capabilities pending verified contract")];
  const chips = [];
  if (caps.text_to_video) chips.push(pill10("T2V"));
  if (caps.image_to_video) chips.push(pill10("I2V"));
  if (caps.last_frame || caps.start_end_frames) chips.push(pill10("first/last frame"));
  if (caps.audio_generation) chips.push(pill10("audio"));
  if (caps.seed_support) chips.push(pill10("seed"));
  if (caps.durations?.length) chips.push(pill10(`${caps.durations.slice(0, 4).join("/")}s`, true));
  if (caps.aspect_ratios?.length) chips.push(pill10(caps.aspect_ratios.slice(0, 3).join(" "), true));
  return chips;
}
const pill10 = (label, outline) => el("span", { class: `pill ${outline ? "s-outline" : "s-green"}`, style: "padding:1px 7px; font-size:10px" }, label);

/* ---------------- advanced settings (capability-gated) ---------------- */
function advancedSection() {
  const caps = selected === "auto" ? autoCaps() : selectedCaps();
  const usable = caps || { durations: [], resolutions: [], aspect_ratios: ["16:9", "9:16"], seed_support: false, audio_generation: false };

  const durSel = el("select", {},
    (usable.durations?.length ? usable.durations : [4, 5, 6, 8, 10]).map((d) =>
      el("option", { value: String(d), selected: Number(d) === (shot.duration_seconds || 6) ? "" : null }, `${d} seconds`)));
  const resSel = el("select", {},
    (usable.resolutions?.length ? usable.resolutions : ["480p", "720p", "1080p"]).map((r) => el("option", { value: r, selected: r === "720p" ? "" : null }, r)));
  const arSel = el("select", {},
    (usable.aspect_ratios?.length ? usable.aspect_ratios : ["16:9", "9:16"]).map((a) =>
      el("option", { value: a, selected: a === (settings.aspect_ratio || "16:9") ? "" : null }, a)));
  const seedInput = el("input", { type: "number", placeholder: usable.seed_support ? "optional" : "unsupported", disabled: usable.seed_support ? null : "" });
  const audioSel = el("select", { disabled: usable.audio_generation ? null : "" },
    el("option", { value: "" }, usable.audio_generation ? "provider default" : "unsupported"),
    el("option", { value: "true" }, "with audio"), el("option", { value: "false" }, "no audio"));

  collectSettings = () => {
    const payload = {
      duration_seconds: parseFloat(durSel.value) || shot.duration_seconds || 6,
      resolution: resSel.value, aspect_ratio: arSel.value,
    };
    if (seedInput.value && usable.seed_support) payload.seed = parseInt(seedInput.value, 10);
    if (audioSel.value && usable.audio_generation) payload.generate_audio = audioSel.value === "true";
    return payload;
  };

  const body = el("div", { style: advancedOpen ? "display:block" : "display:none" },
    el("div", { class: "grid cols-3" },
      field("Duration", durSel), field("Resolution", resSel), field("Aspect ratio", arSel)),
    el("div", { class: "form-row" }, field("Seed", seedInput), field("Audio", audioSel)),
    referenceSummary());

  return el("div", { class: "card", style: "margin-top:14px" },
    el("div", {
      style: "display:flex; align-items:center; gap:10px; cursor:pointer; min-height:44px",
      onclick: () => { advancedOpen = !advancedOpen; draw(); },
    },
      el("h3", { style: "margin:0" }, "Advanced settings"),
      el("span", { class: "muted", style: "font-size:11.5px" }, "only what the selected provider supports"),
      el("span", { style: "margin-left:auto; color:var(--text-dim)" }, advancedOpen ? "▲" : "▼")),
    body);
}

let collectSettings = () => ({});

function referenceSummary() {
  const refs = shot.references || [];
  if (!refs.length) return el("div", { class: "muted", style: "font-size:12px" },
    "No frame references attached. (First/last-frame images are managed in the Scene Director.)");
  return el("div", {},
    el("div", { class: "muted", style: "font-size:12px; margin-bottom:6px" }, "References submitted with this shot:"),
    el("div", { style: "display:flex; gap:6px; flex-wrap:wrap" },
      refs.map((r) => el("span", { class: "pill s-outline" }, pretty(r.purpose)))));
}

/* ---------------- generation + progress ---------------- */
async function generate() {
  const payloadSettings = collectSettings();
  try {
    const job = await postJSON(`/api/shots/${shotId}/generate`, { provider_key: selected, settings: payloadSettings });
    const submitted = await postJSON(`/api/generation/jobs/${job.id}/submit`);
    if (["failed"].includes(submitted.status)) {
      toast(submitted.error || "Submission failed.", "error");
      return;
    }
    toast("Generation submitted — progress below.", "ok", "Generating");
    shot = await getJSON(`/api/shots/${shotId}`);
    draw();
    startPolling();
  } catch (error) {
    const detail = error.detail || {};
    toast(detail.message || error.message, "error", "Generation refused");
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!document.contains(container)) { clearInterval(pollTimer); return; }
    try {
      shot = await getJSON(`/api/shots/${shotId}`);
      const jobs = await getJSON(`/api/generation/jobs?shot_id=${shotId}&limit=1`);
      latestJob = jobs.jobs[0] || null;
      renderProgress();
    } catch { /* transient */ }
  }, 4000);
}

let latestJob = null;
let progressMount = null;

function resultSectionMount() {
  progressMount = el("div", { style: "margin-top:16px" });
  renderProgress();
  return progressMount;
}

async function renderProgress() {
  if (!progressMount) return;
  const results = await getJSON(`/api/generation/results?shot_id=${shotId}`).catch(() => ({ results: [] }));
  progressMount.replaceChildren();
  if (latestJob && ["submitting", "submitted", "generating"].includes(latestJob.status)) {
    const label = latestJob.status === "generating" ? "Generating…" : "Submitting…";
    progressMount.append(el("div", { class: "card", style: "margin-bottom:12px" },
      el("div", { style: "display:flex; align-items:center; gap:10px; margin-bottom:8px" },
        el("span", { html: ICONS.clock, style: "color:var(--amber)" }),
        el("b", {}, label),
        el("span", { class: "muted", style: "font-size:12px" }, pretty(latestJob.provider_key)),
        el("span", { class: "pill s-outline", style: "margin-left:auto" }, `attempt ${latestJob.attempt}`)),
      el("div", { class: "progress-track" },
        el("div", { class: "progress-fill", style: "width:45%; animation: sheet-up 1s infinite alternate" }))));
  }
  if (latestJob?.status === "failed") {
    progressMount.append(el("div", { class: "callout", style: "margin-bottom:12px; font-size:12.5px" },
      el("b", {}, "Generation failed — ", latestJob.error_code || ""),
      latestJob.error || "",
      el("div", { style: "margin-top:8px" },
        el("button", { class: "btn small", onclick: retry }, "Retry"),
        el("button", { class: "btn small ghost", style: "margin-left:6px", onclick: () => { selected = "auto"; draw(); } }, "Try another provider"))));
  }
  for (const result of results.results || []) renderResultCard(result);
}

function renderResultCard(result) {
  progressMount.append(el("div", { class: "card", style: "margin-bottom:12px" },
    el("video", { src: `/api/generation/results/${result.id}/file`, controls: "", preload: "metadata",
      style: "width:100%; border-radius:10px; background:#000; aspect-ratio:16/9; margin-bottom:10px" }),
    el("div", { style: "display:flex; gap:7px; align-items:center; flex-wrap:wrap; margin-bottom:10px" },
      el("b", {}, `Version ${result.version_number}`),
      statusPill(result.status, pretty(result.status)),
      el("span", { class: "pill s-outline" }, pretty(result.provider_key || "")),
      result.test_adapter ? el("span", { class: "pill s-purple" }, "TEST OUTPUT") : null,
      el("span", { class: "muted", style: "font-size:11px" },
        [result.resolution, result.duration_seconds ? `${result.duration_seconds}s` : null].filter(Boolean).join(" · "))),
    el("div", { style: "display:flex; gap:8px; flex-wrap:wrap" },
      result.status !== "approved"
        ? el("button", { class: "btn small primary", onclick: () => review(result, "approved") }, el("span", { html: ICONS.check }), "Approve") : null,
      result.status !== "rejected"
        ? el("button", { class: "btn small danger", onclick: () => review(result, "rejected") }, "Reject") : null,
      el("button", { class: "btn small ghost", onclick: () => generateAnother(result) }, "Generate another version"),
      el("a", { class: "btn small ghost", href: "#/queue", style: "text-decoration:none" }, "Queue ↗"))));
}

async function review(result, decision) {
  let reason = null;
  if (decision === "rejected") {
    reason = await collectRejectionReason(result);
    if (reason === null) return;                       // cancelled
    if (!reason.trim()) return toast("A rejection reason is required.", "warn");
  }
  try {
    await postJSON(`/api/generation/results/${result.id}/review`, { decision, reason });
    toast(decision === "approved" ? "Approved — shot complete." : "Rejected — shot needs revision.", "ok");
    shot = await getJSON(`/api/shots/${shotId}`);
    draw(); renderProgress();
  } catch (error) { toast(error.message, "error"); }
}

function collectRejectionReason(result) {
  // Mobile-friendly bottom sheet (modal becomes a sheet on phone widths).
  return new Promise((resolve) => {
    const input = el("textarea", {
      rows: 3, placeholder: "Why is this rejected? (required — becomes part of the audit trail)",
      style: "width:100%; font-size:16px", // 16px prevents iOS zoom-on-focus
    });
    openModal({
      title: `Reject version ${result.version_number}`,
      sub: "A reason is required.",
      body: el("div", { class: "field" }, el("label", {}, "Reason"), input),
      actions: [
        { label: "Cancel", onClick: () => resolve(null) },
        { label: "Reject", kind: "danger", onClick: (e, close) => { close(); resolve(input.value); } },
      ],
    });
    setTimeout(() => input.focus(), 120);
  });
}

async function retry() {
  if (!latestJob) return;
  try {
    const newJob = await postJSON(`/api/generation/jobs/${latestJob.id}/retry`, {});
    await postJSON(`/api/generation/jobs/${newJob.id}/submit`);
    toast("Retrying — new attempt started.", "ok");
    startPolling(); renderProgress();
  } catch (error) { toast(error.message, "error"); }
}

async function generateAnother() {
  selected = "auto";
  await generate();
}
