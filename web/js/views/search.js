// Global search results.
import { el, ICONS, emptyState, loadingState, errorState } from "../ui.js";
import { getJSON } from "../api.js";

let container;

const GROUPS = [
  ["stories", "Stories"], ["episodes", "Episodes"], ["scenes", "Scenes"],
  ["characters", "Characters"], ["locations", "Locations"], ["props", "Props"], ["canon", "Canon"],
];

export async function render(c, params = new URLSearchParams()) {
  container = c;
  const q = params.get("q") || "";
  if (!q) {
    container.replaceChildren(emptyState({ big: "Type a search", small: "Use the search box in the top bar (Enter to run)." }));
    return;
  }
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("h2", {}, `Search: “${q}”`),
        el("div", { class: "desc" }, "Across stories, episodes, scenes, characters, locations, props and canon."))),
    loadingState("Searching…"));
  try {
    const data = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
    container.lastChild.remove();
    const results = data.results || {};
    const total = Object.values(results).reduce((sum, rows) => sum + rows.length, 0);
    if (!total) {
      container.append(emptyState({ big: "No results", small: `Nothing matched “${q}”.` }));
      return;
    }
    container.append(el("div", { class: "pill s-outline", style: "margin-bottom:14px; align-self:flex-start" }, `${total} result${total === 1 ? "" : "s"}`));
    for (const [key, label] of GROUPS) {
      const rows = results[key] || [];
      if (!rows.length) continue;
      container.append(el("div", { class: "card", style: "margin-bottom:12px" },
        el("h3", {}, label, el("span", { class: "pill s-outline" }, String(rows.length))),
        ...rows.map((row) => el("a", {
          href: row.href || "#/dashboard",
          style: "display:flex; gap:10px; align-items:center; padding:9px 4px; border-bottom:1px solid rgba(38,49,42,.5); text-decoration:none; color:var(--text)",
          onclick: (e) => { /* let hash nav work */ },
        },
          el("span", { html: ICONS.arrow, style: "color:var(--text-faint); flex:0 0 auto; display:inline-flex" }),
          el("b", {}, row.title),
          el("span", { style: "color:var(--text-dim); font-size:12.5px" }, row.subtitle || "")))));
    }
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, () => render(c, params)));
  }
}
