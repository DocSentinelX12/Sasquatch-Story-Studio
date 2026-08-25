// Exports + shorts — approval-first publishing workspace.
import { el, ICONS, statusPill, pretty, loadingState, errorState, toast, openModal, field } from "../ui.js";
import { getJSON, postJSON } from "../api.js";

let container;
let episodeId = 1;

export async function render(c) {
  container = c;
  await refresh();
}

async function refresh() {
  container.replaceChildren(loadingState("Loading exports…"));
  try {
    const [exportsData, shorts] = await Promise.all([
      getJSON(`/api/exports?episode_id=${episodeId}`),
      getJSON(`/api/episodes/${episodeId}/shorts/proposals`),
    ]);
    draw(exportsData.exports, shorts.proposals);
  } catch (error) { container.replaceChildren(errorState(error, refresh)); }
}

function draw(exportsList, proposals) {
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, el("h2", {}, "Exports & Shorts"),
        el("div", { class: "desc" }, "Nothing publishes automatically — every export is a draft until you approve it.")),
      el("div", { class: "actions" },
        el("button", { class: "btn primary", onclick: newFullExport }, el("span", { html: ICONS.plus }), "New Export"))),
    el("h3", { style: "font-size:14px; margin:6px 0 10px" }, "Exports"),
    exportsList.length ? el("div", {}, ...exportsList.map(exportCard))
      : el("div", { class: "empty" }, el("div", { class: "big" }, "No exports yet"),
          el("div", { class: "small" }, "Queue an episode render in the Timeline QC panel first, then create the export.")),
    el("h3", { style: "font-size:14px; margin:18px 0 10px" }, "Short-form proposals"),
    proposals.length
      ? el("div", {}, ...proposals.map((p) => el("div", { class: "card", style: "padding:11px 14px; margin-bottom:8px; display:flex; gap:10px; align-items:center; flex-wrap:wrap" },
          el("b", {}, p.shot_ref), el("span", {}, p.title),
          el("span", { class: "pill s-outline" }, `${Math.round(p.duration_seconds)}s`),
          el("span", { class: "muted", style: "font-size:11.5px" }, p.why),
          el("button", { class: "btn small primary", style: "margin-left:auto", onclick: () => createShort(p) }, "Draft Short"))))
      : el("div", { class: "empty" }, el("div", { class: "big" }, "No proposals"),
          el("div", { class: "small" }, "Approve shot results to see short-form proposals here.")));
}

function exportCard(ex) {
  return el("div", { class: "card", style: "padding:11px 14px; margin-bottom:8px" },
    el("div", { style: "display:flex; gap:9px; align-items:center; flex-wrap:wrap" },
      el("b", {}, ex.title || pretty(ex.kind)),
      el("span", { class: "pill s-outline" }, pretty(ex.kind)),
      statusPill(ex.status === "exported" ? "approved" : ex.status, pretty(ex.status)),
      ex.duration_seconds ? el("span", { class: "muted", style: "font-size:11px" }, `${Math.round(ex.duration_seconds)}s`) : null,
      ex.output_path ? el("a", { href: "#", style: "margin-left:auto" }, "file") : null),
    ex.tags_text ? el("div", { class: "muted", style: "font-size:11.5px; margin-top:5px" }, `tags: ${ex.tags_text}`) : null,
    el("div", { style: "display:flex; gap:6px; margin-top:8px; flex-wrap:wrap" },
      ex.status !== "approved" ? el("button", { class: "btn small primary", onclick: async () => {
        await postJSON(`/api/exports/${ex.id}/status?status=approved`); toast("Export approved.", "ok"); refresh();
      } }, el("span", { html: ICONS.check }), "Approve") : null,
      ex.status === "approved" ? el("button", { class: "btn small", onclick: async () => {
        await postJSON(`/api/exports/${ex.id}/status?status=exported`); toast("Marked exported (record only — no publishing integration).", "ok"); refresh();
      } }, "Mark exported") : null));
}

async function newFullExport() {
  const renders = await getJSON(`/api/episodes/${episodeId}/renders`);
  const completed = renders.renders.filter((r) => r.status === "completed");
  if (!completed.length) return toast("Queue a completed render first (Timeline → QC / Render).", "warn", "No render");
  const title = el("input", { type: "text", placeholder: "YouTube title" });
  const desc = el("textarea", { placeholder: "YouTube description" });
  const tags = el("input", { type: "text", placeholder: "comma,separated,tags" });
  openModal({ title: "New full-episode export", wide: true,
    body: el("div", {}, field("Title *", title), field("Description", desc), field("Tags", tags)),
    actions: [{ label: "Cancel" }, { label: "Create draft", kind: "primary", onClick: async (e, close) => {
      await postJSON(`/api/exports?episode_id=${episodeId}`, { kind: "full_episode",
        render_id: completed[completed.length - 1].id, title: title.value.trim() || "Episode export",
        title_text: title.value.trim() || null, description_text: desc.value.trim() || null, tags_text: tags.value.trim() || null });
      close(); toast("Export draft created — approve when ready.", "ok"); refresh();
    } }] });
}

async function createShort(p) {
  await postJSON(`/api/exports?episode_id=${episodeId}`, {
    kind: "short_vertical", source_result_id: p.result_id,
    start_seconds: 0, end_seconds: p.duration_seconds, title: `Short — ${p.title}` });
  toast("Short drafted (0–%ds) — approve before use.".replace("%d", Math.round(p.duration_seconds)), "ok");
  refresh();
}
