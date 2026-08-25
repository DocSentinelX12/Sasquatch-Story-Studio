// Episodes — production list with lifecycle pipeline.
import { el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast, openModal, field, fmtWhen } from "../ui.js";
import { getJSON, postJSON } from "../api.js";

const STATUSES = ["draft", "development", "script", "approved", "in_production", "complete", "archived"];
let container;
let state = { status: "" };

export async function render(c) {
  container = c;
  container.replaceChildren(loadingState("Loading episodes…"));
  try {
    const query = new URLSearchParams();
    const projectId = localStorage.getItem("studio.projectId");
    if (projectId) query.set("project_id", projectId);
    if (state.status) query.set("status", state.status);
    const data = await getJSON(`/api/episodes?${query}`);
    renderList(data.episodes);
  } catch (error) {
    container.replaceChildren(errorState(error, () => render(c)));
  }
}

function renderList(episodes) {
  const head = el("div", { class: "page-head" },
    el("div", {},
      el("h2", {}, "Episodes"),
      el("div", { class: "desc" }, "Draft → Development → Script → Approved → In Production → Complete. Each step needs your approval.")),
    el("div", { class: "actions" },
      el("a", { class: "btn ghost", href: "#/story" }, el("span", { html: ICONS.spark }), "From a Story Idea"),
      el("button", { class: "btn primary", onclick: newEpisodeModal }, el("span", { html: ICONS.plus }), "New Episode")));

  const pipeline = el("div", { class: "filter-bar" },
    el("select", { onchange: (e) => { state.status = e.target.value; render(episodes.containerRef || container); } },
      el("option", { value: "" }, "All statuses"),
      STATUSES.map((s) => el("option", { value: s, selected: state.status === s ? "" : null }, pretty(s)))),
    el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${episodes.length} episode${episodes.length === 1 ? "" : "s"}`));

  const body = episodes.length
    ? el("div", { class: "table-wrap" },
        el("table", { class: "data" },
          el("thead", {}, el("tr", {},
            el("th", {}, "Episode"), el("th", {}, "Title"), el("th", {}, "Status"),
            el("th", {}, "Script"), el("th", {}, "Scenes"), el("th", {}, "Lines"), el("th", {}, "Updated"))),
          el("tbody", {}, ...episodes.map((e) => el("tr", { class: "clickable", onclick: () => location.hash = `#/episodes/${e.id}` },
            el("td", {}, el("span", { class: "pill s-outline" }, `EP ${String(e.number).padStart(3, "0")}`)),
            el("td", { style: "font-weight:600" }, e.title),
            el("td", {}, statusPill(e.status)),
            el("td", {}, statusPill(e.script_status || "draft", pretty(e.script_status || "draft"))),
            el("td", {}, String(e.scene_count ?? 0)),
            el("td", {}, String(e.script_element_count ?? 0)),
            el("td", { style: "color:var(--text-faint)" }, fmtWhen(e.updated_at)))))))
    : emptyState({
        big: "No episodes yet",
        small: "Create one directly, or develop a story idea first (recommended: Story → approve → Create Episode).",
        actions: [
          el("button", { class: "btn small primary", onclick: newEpisodeModal }, "New Episode"),
          el("a", { class: "btn small ghost", href: "#/story" }, "Story Ideas"),
        ],
      });

  container.replaceChildren(head, pipeline, body);
}

function newEpisodeModal() {
  const title = el("input", { type: "text", placeholder: "e.g. The Great Moonberry Bounce" });
  const logline = el("input", { type: "text", placeholder: "One sentence…" });
  const target = el("input", { type: "number", value: "8", min: "1", max: "30" });
  openModal({
    title: "New Episode",
    sub: "Starts in Draft. Develop acts, scenes and script inside the episode workspace.",
    body: el("div", {},
      field("Title *", title),
      field("Logline", logline),
      field("Target length (minutes)", target)),
    actions: [
      { label: "Cancel" },
      { label: "Create Draft", kind: "primary", onClick: async (e, close) => {
        if (!title.value.trim()) return toast("Title required.", "warn");
        const episode = await postJSON("/api/episodes", {
          project_id: Number(localStorage.getItem("studio.projectId")),
          title: title.value.trim(), logline: logline.value.trim() || null,
          target_length_minutes: parseFloat(target.value) || 8,
        });
        close(); location.hash = `#/episodes/${episode.id}`;
      } },
    ],
  });
}
