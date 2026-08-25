// Shots — cross-episode shot browser with generation readiness.
import { el, ICONS, statusPill, pretty, emptyState, loadingState, errorState } from "../ui.js";
import { getJSON } from "../api.js";

let container;
let state = { q: "", status: "" };

const STATUSES = ["draft", "needs_review", "approved", "ready_for_generation", "generating", "generated", "needs_revision", "rejected", "complete"];

export async function render(c) {
  container = c;
  container.replaceChildren(loadingState("Loading shots…"));
  try {
    const query = new URLSearchParams();
    if (state.q) query.set("q", state.q);
    if (state.status) query.set("status", state.status);
    const data = await getJSON(`/api/shots?${query}`);
    renderList(data);
  } catch (error) {
    container.replaceChildren(errorState(error, () => render(c)));
  }
}

function renderList(data) {
  const counts = data.counts_by_status || {};
  const ready = counts.ready_for_generation || 0;
  const head = el("div", { class: "page-head" },
    el("div", {},
      el("h2", {}, "Shots"),
      el("div", { class: "desc" },
        "Every shot across every scene. Phase 5 will submit shots marked “Ready for Generation” to video providers.")),
    el("div", { class: "actions" },
      ready ? el("span", { class: "pill s-green" }, `${ready} ready for generation`) : null));

  const bar = el("div", { class: "filter-bar" },
    el("input", { type: "search", placeholder: "Search shots…", value: state.q,
      oninput: (e) => { state.q = e.target.value; clearTimeout(render._t); render._t = setTimeout(render, 250); } }),
    el("select", { onchange: (e) => { state.status = e.target.value; render(); } },
      el("option", { value: "" }, "All statuses"),
      STATUSES.map((s) => el("option", { value: s, selected: state.status === s ? "" : null },
        `${pretty(s)}${counts[s] ? ` (${counts[s]})` : ""}`))),
    el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${data.shots.length} shot${data.shots.length === 1 ? "" : "s"}`));

  const body = data.shots.length
    ? el("div", { class: "table-wrap" },
        el("table", { class: "data" },
          el("thead", {}, el("tr", {},
            el("th", {}, "Shot"), el("th", {}, "Scene"), el("th", {}, "Title"),
            el("th", {}, "Type"), el("th", {}, "Camera"), el("th", {}, "Duration"),
            el("th", {}, "Cast"), el("th", {}, "Status"), el("th", {}, ""))),
          el("tbody", {}, ...data.shots.map((s) => el("tr", { class: "clickable", onclick: () => location.hash = `#/scenes/${s.scene_id}/director` },
            el("td", {}, el("span", { class: "pill s-outline" }, s.shot_ref || `#${s.number}`)),
            el("td", {}, s.scene_ref || `Scene ${s.scene_id}`),
            el("td", { style: "font-weight:600" }, s.title || "Untitled"),
            el("td", {}, pretty(s.shot_type || "—")),
            el("td", {}, [s.camera_angle && pretty(s.camera_angle), s.camera_movement && pretty(s.camera_movement)].filter(Boolean).join(" / ") || "—"),
            el("td", {}, `${s.duration_seconds || 0}s`),
            el("td", {}, (s.cast || []).map((l) => l.character?.name).filter(Boolean).join(", ") || "—"),
            el("td", {}, statusPill(s.status)),
            el("td", {},
              el("a", { class: "btn small primary", href: `#/generate/${s.id}`, style: "text-decoration:none",
                onclick: (e) => e.stopPropagation() }, "⚡ Generate")))))))
    : emptyState({
        big: state.q || state.status ? "No shots match" : "No shots yet",
        small: state.q || state.status ? "Try clearing filters." : "Open a scene's Director view and build its storyboard.",
        actions: [el("a", { class: "btn small ghost", href: "#/scenes" }, "Open Scenes")],
      });

  container.replaceChildren(head, bar, body);
}
