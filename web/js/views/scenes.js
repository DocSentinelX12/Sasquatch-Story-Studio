// Scenes — cross-episode scene browser with production readiness.
import { el, ICONS, statusPill, pretty, emptyState, loadingState, errorState } from "../ui.js";
import { getJSON } from "../api.js";

let container;
let state = { q: "", status: "" };

const STATUSES = ["draft", "needs_review", "approved", "ready_for_storyboard", "in_production", "complete"];

export async function render(c) {
  container = c;
  container.replaceChildren(loadingState("Loading scenes…"));
  try {
    const query = new URLSearchParams();
    if (state.q) query.set("q", state.q);
    if (state.status) query.set("status", state.status);
    const data = await getJSON(`/api/scenes?${query}`);
    renderList(data.scenes);
  } catch (error) {
    container.replaceChildren(errorState(error, () => render(c)));
  }
}

function renderList(scenes) {
  const head = el("div", { class: "page-head" },
    el("div", {},
      el("h2", {}, "Scenes"),
      el("div", { class: "desc" }, "Every scene across every episode. Open one inside its episode workspace to edit, cast, script and send to storyboard.")));

  const bar = el("div", { class: "filter-bar" },
    el("input", { type: "search", placeholder: "Search scene titles, summaries…", value: state.q,
      oninput: (e) => { state.q = e.target.value; clearTimeout(render._t); render._t = setTimeout(render, 250); } }),
    el("select", { onchange: (e) => { state.status = e.target.value; render(); } },
      el("option", { value: "" }, "All statuses"),
      STATUSES.map((s) => el("option", { value: s, selected: state.status === s ? "" : null }, pretty(s)))),
    el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${scenes.length} scene${scenes.length === 1 ? "" : "s"}`));

  const body = scenes.length
    ? el("div", { class: "table-wrap" },
        el("table", { class: "data" },
          el("thead", {}, el("tr", {},
            el("th", {}, "Ref"), el("th", {}, "Title"), el("th", {}, "Location"),
            el("th", {}, "Time"), el("th", {}, "Cast"), el("th", {}, "Lines"), el("th", {}, "Status"))),
          el("tbody", {}, ...scenes.map((s) => el("tr", { class: "clickable", onclick: () => location.hash = `#/episodes/${s.episode_id}?scene=${s.id}` },
            el("td", {}, el("span", { class: "pill s-outline" }, s.scene_ref || `#${s.number}`)),
            el("td", { style: "font-weight:600" }, s.title || "Untitled"),
            el("td", {}, s.location_name || el("span", { style: "color:var(--red)" }, "not set")),
            el("td", {}, s.time_of_day || "—"),
            el("td", {}, String((s.cast || []).length)),
            el("td", {}, String((s.script || []).length)),
            el("td", {}, statusPill(s.status)))))))
    : emptyState({
        big: state.q || state.status ? "No scenes match" : "No scenes yet",
        small: state.q || state.status ? "Try clearing filters." : "Open an episode and add scenes in the Acts & Scenes tab.",
        actions: [el("a", { class: "btn small ghost", href: "#/episodes" }, "Open Episodes")],
      });

  container.replaceChildren(head, bar, body);
}
