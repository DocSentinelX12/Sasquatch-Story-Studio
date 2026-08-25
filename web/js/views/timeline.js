// Timeline + QC + renders: phone-friendly episode assembly.
import { el, ICONS, statusPill, pretty, loadingState, errorState, toast, openModal } from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let episodeId = 1;
let data = null;
let pxPerSecond = 14;

export async function render(c) {
  container = c;
  await refresh();
}

async function refresh() {
  container.replaceChildren(loadingState("Loading timeline…"));
  try {
    data = await getJSON(`/api/episodes/${episodeId}/timeline`);
    draw();
  } catch (error) { container.replaceChildren(errorState(error, refresh)); }
}

function draw() {
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, el("h2", {}, "Timeline"),
        el("div", { class: "desc" }, `Episode assembly · ${Math.round(data.duration_seconds)}s · editing is non-destructive`)),
      el("div", { class: "actions" },
        el("button", { class: "btn primary", onclick: buildTimeline }, el("span", { html: ICONS.film }), "Build Episode Timeline"),
        el("button", { class: "btn", onclick: showQC }, el("span", { html: ICONS.check }), "QC / Render"))));
  const lanes = el("div", { style: "overflow-x:auto; border:1px solid var(--border); border-radius:10px" });
  for (const track of data.tracks) {
    const items = data.items.filter((i) => i.track_id === track.id);
    lanes.append(lane(track, items));
  }
  container.append(lanes, el("div", { class: "muted", style: "font-size:11.5px; margin-top:8px" },
    "Tap a clip to edit (move/trim/fades/gain/split/duplicate). Mixer per track: tap the track label."));
}

function lane(track, items) {
  const width = Math.max(600, (data.duration_seconds + 4) * pxPerSecond);
  const laneEl = el("div", { style: "display:flex; border-bottom:1px solid var(--border); min-width:100%" },
    el("div", {
      style: "width:110px; flex:0 0 110px; padding:9px 10px; border-right:1px solid var(--border); cursor:pointer; background:var(--panel-raised)",
      onclick: () => trackModal(track),
    }, el("div", { style: "font-weight:650; font-size:12px" }, track.name),
      track.muted ? el("span", { class: "pill s-red", style: "font-size:9px; padding:0 5px" }, "MUTE") : null,
      track.solo ? el("span", { class: "pill s-green", style: "font-size:9px; padding:0 5px" }, "SOLO") : null,
      el("div", { class: "muted", style: "font-size:10px" }, `vol ${Math.round(track.volume * 100)}%`)),
    el("div", { style: `position:relative; height:52px; width:${width}px` },
      ...items.map((item) => clip(item))));
  return laneEl;
}

function clip(item) {
  const left = item.start_seconds * pxPerSecond;
  const width = Math.max(8, (item.end_seconds - item.start_seconds) * pxPerSecond);
  const colors = { video: "#2d5e3d", dialogue: "#3b4f8c", narration: "#6a4a8f", sfx: "#8a6a2d", ambience: "#4a6a6a", music: "#8f4a5a" };
  return el("div", {
    style: `position:absolute; left:${left}px; width:${width}px; top:6px; bottom:6px; border-radius:6px;
      background:${colors[item.track_kind] || "#444"}; padding:3px 6px; font-size:10px; color:#eafbef;
      overflow:hidden; cursor:pointer; border:1px solid rgba(255,255,255,.15); ${item.source_type === "gap" ? "opacity:.45; background:var(--bg-deep); color:var(--red)" : ""}`,
    onclick: () => clipModal(item),
  }, (item.label || "").slice(0, 30));
}

function clipModal(item) {
  const length = item.end_seconds - item.start_seconds;
  const start = el("input", { type: "number", value: String(item.start_seconds), step: "0.1" });
  const len = el("input", { type: "number", value: String(Math.round(length * 10) / 10), step: "0.1" });
  const fadeI = el("input", { type: "number", value: String(item.fade_in || 0), step: "0.1" });
  const fadeO = el("input", { type: "number", value: String(item.fade_out || 0), step: "0.1" });
  const gain = el("input", { type: "number", value: String(item.volume_gain ?? 1), step: "0.1" });
  openModal({
    title: item.label || "Clip", sub: `${pretty(item.track_kind)} · ${item.source_type}`,
    body: el("div", {},
      el("div", { class: "form-row" },
        el("div", { class: "field" }, el("label", {}, "Start (s)"), start),
        el("div", { class: "field" }, el("label", {}, "Length (s)"), len)),
      el("div", { class: "form-row-3 grid cols-3" },
        el("div", { class: "field" }, el("label", {}, "Fade in"), fadeI),
        el("div", { class: "field" }, el("label", {}, "Fade out"), fadeO),
        el("div", { class: "field" }, el("label", {}, "Gain"), gain))),
    actions: [
      { label: "Delete from timeline", kind: "danger", onClick: async (e, close) => {
        await fetch(`/api/timeline/items/${item.id}`, { method: "DELETE" });
        close(); toast("Removed from timeline (source kept).", "ok"); refresh();
      } },
      { label: "Split", onClick: async () => {
        await postJSON(`/api/timeline/items/${item.id}/split?at_seconds=${(item.start_seconds + item.end_seconds) / 2}`);
        toast("Clip split.", "ok");
      } },
      { label: "Duplicate", onClick: async () => { await postJSON(`/api/timeline/items/${item.id}/duplicate`); toast("Duplicated.", "ok"); } },
      { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
        await patchJSON(`/api/timeline/items/${item.id}`, {
          start_seconds: parseFloat(start.value),
          end_seconds: parseFloat(start.value) + parseFloat(len.value),
          fade_in: parseFloat(fadeI.value) || 0, fade_out: parseFloat(fadeO.value) || 0,
          volume_gain: parseFloat(gain.value) || 1 });
        document.querySelector(".modal-backdrop")?.remove();
        toast("Clip saved.", "ok"); refresh();
      } },
    ],
  });
}

function trackModal(track) {
  const volume = el("input", { type: "number", value: String(track.volume), step: "0.1", min: "0", max: "2" });
  openModal({
    title: `${track.name} track`, sub: "Mixer — non-destructive",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Volume (0-2)"), volume),
      el("div", { style: "display:flex; gap:8px" },
        el("button", { class: `btn small ${track.muted ? "danger" : "ghost"}`, onclick: async () => {
          await patchJSON(`/api/timeline/tracks/${track.id}`, { muted: !track.muted }); draw();
        } }, track.muted ? "Unmute" : "Mute"),
        el("button", { class: `btn small ${track.solo ? "primary" : "ghost"}`, onclick: async () => {
          await patchJSON(`/api/timeline/tracks/${track.id}`, { solo: !track.solo }); draw();
        } }, track.solo ? "Solo ON" : "Solo"))),
    actions: [{ label: "Close" }, { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
      await patchJSON(`/api/timeline/tracks/${track.id}`, { volume: parseFloat(volume.value) || 1 });
      document.querySelector(".modal-backdrop")?.remove(); draw();
    } }],
  });
}

async function buildTimeline() {
  const result = await postJSON(`/api/episodes/${episodeId}/timeline/build`);
  toast(`Assembled: ${result.placed_results} video clips, ${result.placed_audio_clips} audio clips` +
    (result.missing.length ? ` — ${result.missing.length} missing items reported.` : "."), "ok", "Timeline built");
  refresh();
}

async function showQC() {
  const qc = await getJSON(`/api/episodes/${episodeId}/qc`);
  const renders = await getJSON(`/api/episodes/${episodeId}/renders`);
  const body = el("div", {},
    el("div", { style: "margin-bottom:10px" }, statusPill(qc.status === "pass" ? "approved" : qc.status === "warning" ? "needs_review" : "rejected",
      qc.status.toUpperCase() + ` — ${qc.blocked} blocked, ${qc.warnings} warnings`)),
    ...qc.findings.map((f) => el("div", { class: f.severity === "blocked" ? "callout" : "muted", style: "font-size:12px; margin-bottom:6px" },
      f.severity === "blocked" ? "⛔ " : "⚠ ", f.message)),
    el("div", { class: "muted", style: "font-size:11px; margin:10px 0" },
      renders.ffmpeg_available ? "ffmpeg detected — local rendering available (free, self-hosted)."
        : "No ffmpeg on this machine — the render queue will report renderer_not_available until ffmpeg is installed."),
    renders.renders.length ? el("div", {}, ...renders.renders.map((r) => el("div", { class: "card", style: "padding:9px 12px; margin-bottom:7px; display:flex; gap:8px; align-items:center" },
      el("b", {}, `v${r.version_number}`), statusPill(r.status, pretty(r.status)),
      el("span", { class: "muted", style: "font-size:11px" }, `${r.resolution} · ${r.fps}fps`),
      r.output_path ? el("a", { href: `/api/renders/${r.id}/file`, target: "_blank", style: "margin-left:auto" }, "Open") : null,
      r.status === "failed" && r.error_code === "renderer_not_available" ? el("span", { class: "muted", style: "font-size:10px" }, r.error?.slice(0, 60)) : null))) : null);
  openModal({ title: "QC & Render", sub: "Ready for Render gate + render queue", wide: true, body,
    actions: [
      { label: "Close" },
      { label: "Queue render (draft v" + (renders.renders.length + 1) + ")", kind: "primary", onClick: async (e, close) => {
        try {
          const render = await postJSON(`/api/episodes/${episodeId}/renders`, { resolution: "1280x720", fps: 24 });
          await postJSON(`/api/renders/${render.id}/queue`);
          close(); toast("Render queued — honest failure reported if ffmpeg is missing.", "ok");
        } catch (error) {
          const detail = error.detail || {};
          if (detail.blocking) toast(`QC blocked: ${detail.blocking.map((b) => b.key).join(", ")}. Override from the API or resolve findings.`, "warn", "Render gate");
          else toast(detail.message || error.message, "error");
        }
      } },
    ] });
}
