// Post-production: Audio (voices, dialogue, narration) — phone-friendly.
import { el, ICONS, statusPill, pretty, loadingState, errorState, toast, openModal, field, fmtWhen } from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let tab = "lines";
let data = { recordings: [], voices: [], episode: null };
let episodeId = 1;

export async function render(c, params = new URLSearchParams()) {
  container = c;
  tab = params.get("tab") || "lines";
  await refresh();
}

async function refresh() {
  container.replaceChildren(loadingState("Loading audio…"));
  try {
    const [recordings, voices, episodes] = await Promise.all([
      getJSON(`/api/audio/recordings?episode_id=${episodeId}`),
      getJSON(`/api/voices?project_id=${localStorage.getItem("studio.projectId") || 1}`),
      getJSON("/api/episodes"),
    ]);
    data = { recordings: recordings.recordings, voices: voices.voices, episode: episodes.episodes[0] };
    draw();
  } catch (error) { container.replaceChildren(errorState(error, refresh)); }
}

function draw() {
  const { tabBar } = window.__ui;
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, el("h2", {}, "Audio"),
        el("div", { class: "desc" }, "Voices, dialogue and narration. Local/self-hosted lane first; approvals explicit."))),
    tabBar([
      { id: "lines", label: "Dialogue & Narration", count: data.recordings.length },
      { id: "voices", label: "Voice Profiles", count: data.voices.length },
    ], tab, (id) => { tab = id; draw(); }));
  const panel = el("div", {});
  container.append(panel);
  if (tab === "lines") linesPanel(panel); else voicesPanel(panel);
}

async function linesPanel(panel) {
  panel.append(loadingState("Loading script lines…"));
  const ep = await getJSON(`/api/episodes/${episodeId}`);
  panel.replaceChildren();
  const voicesSel = data.voices;
  for (const scene of ep.scenes) {
    const spoken = scene.script.filter((e) => e.element_type === "dialogue" || e.element_type === "narration");
    if (!spoken.length) continue;
    panel.append(el("h3", { style: "margin:14px 0 6px; font-size:13px" }, `${scene.scene_ref} — ${scene.title || ""}`));
    for (const element of spoken) {
      const recording = data.recordings.find((r) => r.script_element_id === element.id && r.is_current);
      const speaker = element.element_type === "dialogue" ? `Character #${element.character_id}` : "Narrator";
      panel.append(lineCard(element, recording, speaker, voicesSel));
    }
  }
  if (!panel.querySelector(".card")) panel.append(el("div", { class: "empty" },
    el("div", { class: "big" }, "No spoken lines"), el("div", { class: "small" }, "Write dialogue/narration in the episode script first.")));
}

function lineCard(element, recording, speaker, voices) {
  const card = el("div", { class: "card", style: "margin-bottom:9px; padding:11px 14px" },
    el("div", { style: "display:flex; gap:9px; align-items:center; flex-wrap:wrap" },
      el("span", { class: "pill s-outline" }, pretty(element.element_type)),
      el("b", {}, speaker),
      recording ? statusPill(recording.status, pretty(recording.status)) : el("span", { class: "pill s-amber" }, "no recording"),
      recording?.duration_seconds ? el("span", { class: "muted", style: "font-size:11px" }, `${recording.duration_seconds}s · v${recording.version_number}`) : null),
    el("div", { style: "font-size:13px; margin-top:6px" }, element.text),
    el("div", { style: "display:flex; gap:7px; margin-top:9px; flex-wrap:wrap" },
      el("button", { class: "btn small primary", onclick: () => generateLine(element, voices) }, el("span", { html: ICONS.spark }),
        recording ? "Regenerate (new version)" : "Generate"),
      recording?.repo_path ? el("button", { class: "btn small ghost", onclick: () => previewRecording(recording) }, "▶ Preview") : null,
      recording && recording.status !== "approved"
        ? el("button", { class: "btn small", onclick: async () => {
            await postJSON(`/api/audio/recordings/${recording.id}/review?decision=approved`);
            toast("Recording approved.", "ok"); refresh();
          } }, el("span", { html: ICONS.check }), "Approve") : null,
      recording && recording.status !== "rejected"
        ? el("button", { class: "btn small danger", onclick: () => rejectRecording(recording) }, "Reject") : null));
  return card;
}

async function generateLine(element, voices) {
  let voiceId = null;
  if (voices.length) {
    const sel = el("select", {}, el("option", { value: "" }, "— no voice profile —"),
      voices.map((v) => el("option", { value: v.id }, v.name)));
    openModal({ title: "Generate audio", sub: element.text.slice(0, 80),
      body: field("Voice profile", sel),
      actions: [{ label: "Cancel" }, { label: "Generate", kind: "primary", onClick: async (e, close) => {
        await runGenerate(element.id, sel.value || null); close();
      } }] });
  } else {
    await runGenerate(element.id, null);
  }
}

async function runGenerate(elementId, voiceId) {
  try {
    const recording = (await postJSON(`/api/audio/recordings/from-script/${elementId}${voiceId ? `?voice_profile_id=${voiceId}` : ""}`));
    await postJSON(`/api/audio/recordings/${recording.id}/generate?provider_key=auto`);
    toast("Generating audio — refresh in a moment.", "ok");
    setTimeout(refresh, 2500);
  } catch (error) { toast(error.message, "error", "Audio refused"); }
}

function previewRecording(recording) {
  openModal({ title: `v${recording.version_number} preview`, wide: true,
    body: el("audio", { src: `/api/audio/recordings/${recording.id}/file`, controls: "", style: "width:100%" }),
    actions: [{ label: "Close" }] });
}

function rejectRecording(recording) {
  const input = el("textarea", { rows: 2, placeholder: "Reason (required)", style: "width:100%; font-size:16px" });
  openModal({ title: "Reject recording", body: field("Reason *", input),
    actions: [{ label: "Cancel" }, { label: "Reject", kind: "danger", onClick: async (e, close) => {
      if (!input.value.trim()) return toast("Reason required.", "warn");
      await postJSON(`/api/audio/recordings/${recording.id}/review?decision=rejected&reason=${encodeURIComponent(input.value.trim())}`);
      close(); toast("Rejected.", "ok"); refresh();
    } }] });
}

function voicesPanel(panel) {
  const audioProviders = "Local / Self-Hosted (LOCAL_AUDIO_API_URL) or TEST adapter";
  for (const voice of data.voices) {
    panel.append(el("div", { class: "card", style: "margin-bottom:9px" },
      el("b", {}, voice.name), " ", statusPill(voice.status, pretty(voice.status)),
      el("div", { class: "muted", style: "font-size:12px; margin-top:4px" },
        [voice.voice_id && `voice id: ${voice.voice_id}`, voice.voice_style, voice.pitch != null && `pitch ${voice.pitch}`].filter(Boolean).join(" · ") || "—")));
  }
  panel.append(el("button", { class: "btn", style: "margin-top:8px", onclick: () => {
    const name = el("input", { type: "text", placeholder: "e.g. Yeti voice" });
    const vid = el("input", { type: "text", placeholder: "voice id from your local audio server" });
    const style = el("input", { type: "text", placeholder: "bright kid energy" });
    openModal({ title: "New voice profile", sub: `Reusable across episodes. Provider lane: ${audioProviders}`,
      body: el("div", {}, field("Name *", name), field("Voice ID", vid), field("Style", style)),
      actions: [{ label: "Cancel" }, { label: "Create", kind: "primary", onClick: async (e, close) => {
        if (!name.value.trim()) return toast("Name required.", "warn");
        await postJSON("/api/voices", { project_id: Number(localStorage.getItem("studio.projectId")) || 1,
          name: name.value.trim(), voice_id: vid.value.trim() || null, voice_style: style.value.trim() || null, provider_key: "local-audio" });
        close(); toast("Voice profile created.", "ok"); refresh();
      } }] });
  } }, el("span", { html: ICONS.plus }), "New Voice Profile"),
  el("div", { class: "callout", style: "margin-top:12px; font-size:12px" },
    "No cloud audio provider is configured (honest). Set LOCAL_AUDIO_API_URL for the self-hosted TTS lane."));
}
