// Production Assistant + batch generation console (mobile-first).
import { el, ICONS, statusPill, pretty, loadingState, errorState, toast, openModal } from "../ui.js";
import { getJSON, postJSON } from "../api.js";

let container;
let episodeId = 1;

export async function render(c) {
  container = c;
  await refresh();
}

async function refresh() {
  container.replaceChildren(loadingState("Inspecting episode…"));
  try {
    const [assistant, audio] = await Promise.all([
      getJSON(`/api/batch/assistant/${episodeId}`),
      getJSON(`/api/batch/audio/report/${episodeId}`),
    ]);
    draw(assistant, audio);
  } catch (error) { container.replaceChildren(errorState(error, refresh)); }
}

function draw(a, audio) {
  const s = a.summary;
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, el("h2", {}, "Production Assistant"),
        el("div", { class: "desc" }, "What's ready, what's missing, what's blocked — and what the studio can queue for you. Approvals always stay human.")),
      el("div", { class: "actions" },
        el("button", { class: "btn", onclick: batchVideoModal }, el("span", { html: ICONS.spark }), "Batch Generate Video"),
        el("button", { class: "btn", onclick: batchAudio }, "Generate Missing Audio"))),
    el("div", { class: "grid cols-4", style: "margin-bottom:14px" },
      stat(`${s.shots_approved}/${s.shots_total}`, "Shots approved"),
      stat(`${audio.approved}/${audio.total_spoken_lines}`, "Audio approved"),
      stat(s.qc_blocking, "QC blocking", s.qc_blocking ? "var(--red)" : "var(--moss)"),
      stat(s.qc_status.toUpperCase(), "QC status")),
    el("div", { class: "grid cols-2" },
      section("✅ READY", [
        `${a.ready.shots.length} approved shot${a.ready.shots.length === 1 ? "" : "s"}`,
        `${a.ready.audio_approved_count} approved audio item${a.ready.audio_approved_count === 1 ? "" : "s"}`,
      ], "var(--moss)"),
      section("🧩 MISSING", [
        a.missing.shots.length ? `Video: ${a.missing.shots.slice(0, 6).join(", ")}${a.missing.shots.length > 6 ? ` +${a.missing.shots.length - 6}` : ""}` : "Video: none",
        `Audio: ${a.missing.audio_missing_count} missing, ${a.missing.audio_unapproved_count} unapproved`,
      ], "var(--amber)"),
      section("⛔ BLOCKED", [
        ...a.blocked.shots_needing_fixes.slice(0, 4).map((x) => `Shot ${x} needs fixes`),
        ...a.blocked.qc_findings.slice(0, 3),
        a.blocked.characters_without_voices.length ? `No voice profile: ${a.blocked.characters_without_voices.join(", ")}` : null,
      ].filter(Boolean).length ? [
        ...a.blocked.shots_needing_fixes.slice(0, 4).map((x) => `Shot ${x} needs fixes`),
        ...a.blocked.qc_findings.slice(0, 3),
        a.blocked.characters_without_voices.length ? `No voice profile: ${a.blocked.characters_without_voices.join(", ")}` : null,
      ].filter(Boolean) : ["Nothing blocking"], "var(--red)"),
      section("🤖 CAN QUEUE AUTOMATICALLY", [
        a.can_generate_automatically.length
          ? `${a.can_generate_automatically.filter((x) => x.action.includes("video")).length} shots + ${a.can_generate_automatically.filter((x) => x.action.includes("audio")).length} audio lines can be queued now`
          : "Nothing left to queue",
        "Human approval still required for: results, exports, QC overrides",
      ], "var(--sky)")),
    el("div", { class: "muted", style: "font-size:11.5px; margin-top:12px" }, a.note));
}

const stat = (value, label, color) => el("div", { class: "card stat-card" },
  el("div", { class: "value", style: color ? `color:${color}` : "" }, value),
  el("div", { class: "label" }, label));

function section(title, lines, color) {
  return el("div", { class: "card" },
    el("h3", { style: `color:${color}` }, title),
    ...lines.map((line) => el("div", { style: "font-size:12.5px; margin-bottom:5px" }, line)));
}

async function batchVideoModal() {
  const mode = el("select", {},
    el("option", { value: "missing" }, "Shots missing approved video"),
    el("option", { value: "failed" }, "Failed generations"),
    el("option", { value: "rejected" }, "Rejected results"),
    el("option", { value: "new_versions" }, "New versions of approved shots"));
  const autoPrepare = el("input", { type: "checkbox" });
  const overrideWarnings = el("input", { type: "checkbox" });
  const holder = el("div", {});
  const preview = async () => {
    const dry = await postJSON("/api/batch/video", { episode_id: episodeId, mode: mode.value, dry_run: true });
    holder.replaceChildren(el("div", { class: "callout info", style: "font-size:12px" },
      `${dry.target_count} shot(s) would be targeted.`));
  };
  preview();
  mode.addEventListener("change", preview);
  openModal({
    title: "Batch Generate Video", wide: true,
    sub: "Asynchronous — the browser never blocks. Approved versions are never overwritten.",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "What"), mode),
      el("div", { style: "display:flex; flex-direction:column; gap:8px; margin:10px 0" },
        el("label", { style: "display:flex; gap:8px; align-items:center; min-height:32px" }, autoPrepare,
          "Auto-prepare validation-passing draft shots (audited)"),
        el("label", { style: "display:flex; gap:8px; align-items:center; min-height:32px" }, overrideWarnings,
          "Override open warnings (recorded with explanation)")),
      holder),
    actions: [
      { label: "Cancel" },
      { label: "Queue Generation", kind: "primary", onClick: async (e, close) => {
        const result = await postJSON("/api/batch/video", {
          episode_id: episodeId, mode: mode.value,
          auto_prepare: autoPrepare.checked, override_warnings: overrideWarnings.checked });
        close();
        toast(`Queued ${result.queued.length} job(s)` +
          (result.skipped.length ? ` — ${result.skipped.length} skipped (see queue/assistant for reasons)` : "."),
          "ok", "Batch generation");
        refresh();
      } },
    ],
  });
}

async function batchAudio() {
  try {
    const result = await postJSON("/api/batch/audio", { episode_id: episodeId });
    toast(`Queued ${result.queued.length} audio job(s). Approved audio untouched.`, "ok", "Batch audio");
    refresh();
  } catch (error) {
    toast(error.message, "error", "Batch audio refused");
  }
}
