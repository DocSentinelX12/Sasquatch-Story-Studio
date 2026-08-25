// World — reusable locations and props libraries.
import { el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast, openModal, field, textToList, listFromText } from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let tab = "locations";
let state = { q: "" };

export async function render(c, params = new URLSearchParams()) {
  container = c;
  tab = params.get("tab") || "locations";
  draw();
}

function draw() {
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("h2", {}, "Locations & Props"),
        el("div", { class: "desc" }, "Reusable across episodes. Approved locations and props feed the Phase 4 reference packages."))),
  );
  const tabs = [{ id: "locations", label: "Locations" }, { id: "props", label: "Props" }];
  const { tabBar } = window.__ui;
  container.append(tabBar(tabs, tab, (id) => { tab = id; draw(); }));
  if (tab === "locations") renderLocations();
  else renderProps();
}

async function renderLocations() {
  container.append(loadingState("Loading locations…"));
  const projectId = localStorage.getItem("studio.projectId");
  try {
    const query = new URLSearchParams();
    if (projectId) query.set("project_id", projectId);
    if (state.q) query.set("q", state.q);
    const data = await getJSON(`/api/world/locations?${query}`);
    container.lastChild.remove();
    container.append(
      el("div", { class: "filter-bar" },
        el("input", { type: "search", placeholder: "Search locations…", value: state.q,
          oninput: (e) => { state.q = e.target.value; clearTimeout(renderLocations._t); renderLocations._t = setTimeout(renderLocations, 250); } }),
        el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${data.locations.length} location${data.locations.length === 1 ? "" : "s"}`),
        el("button", { class: "btn primary", onclick: () => locationModal() }, el("span", { html: ICONS.plus }), "New Location")),
      data.locations.length
        ? el("div", { class: "grid cols-2" }, ...data.locations.map((loc) => el("div", { class: "card" },
            el("div", { style: "display:flex; align-items:center; gap:9px; margin-bottom:8px" },
              el("b", { style: "font-size:14px" }, loc.name),
              loc.loc_ref ? el("span", { class: "pill s-outline" }, loc.loc_ref) : null,
              statusPill(loc.approval_status, pretty(loc.approval_status)),
              el("span", { class: "pill s-outline", style: "margin-left:auto" }, `used ${loc.scene_usage}×`),
              el("button", { class: "btn small ghost", onclick: () => locationModal(loc) }, "Edit")),
            loc.description ? el("div", { style: "font-size:12.5px; margin-bottom:6px" }, loc.description) : null,
            loc.environment ? el("div", { class: "muted", style: "font-size:12px" }, `Environment: ${loc.environment}`) : null,
            (loc.visual_rules || []).length ? el("div", { class: "muted", style: "font-size:12px" }, `Visual rules: ${loc.visual_rules.join("; ")}`) : null)))
        : emptyState({ big: "No locations yet", small: "Locations ground scenes visually and carry their own continuity rules." }));
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, renderLocations));
  }
}

function locationModal(existing = null) {
  const name = el("input", { type: "text", value: existing?.name || "" });
  const kind = el("input", { type: "text", value: existing?.kind || "", placeholder: "home / market / forest…" });
  const description = el("textarea", { value: existing?.description || "" });
  const environment = el("input", { type: "text", value: existing?.environment || "", placeholder: "old-growth forest interior…" });
  const tod = el("input", { type: "text", value: existing?.time_of_day_notes || "", placeholder: "soft morning light through east window…" });
  const weather = el("input", { type: "text", value: existing?.weather_notes || "" });
  const rules = el("textarea", { value: textToList(existing?.visual_rules), placeholder: "One per line" });
  const continuity = el("textarea", { value: existing?.continuity_notes || "" });
  openModal({
    title: existing ? `Edit ${existing.name}` : "New Location", wide: true,
    sub: "Locations are reusable across episodes; approval is explicit.",
    body: el("div", {},
      el("div", { class: "form-row" }, field("Name *", name), field("Kind", kind)),
      field("Description", description),
      el("div", { class: "form-row" }, field("Environment", environment), field("Time-of-day notes", tod)),
      el("div", { class: "form-row" }, field("Weather notes", weather), field("Visual rules", rules, "One per line")),
      field("Continuity notes", continuity)),
    actions: [
      { label: "Cancel" },
      ...(existing ? [{ label: "Approve", onClick: async () => {
        await patchJSON(`/api/world/locations/${existing.id}`, { approval_status: "approved" });
        toast("Location approved.", "ok"); draw();
      } }] : []),
      { label: existing ? "Save" : "Create", kind: "primary", keepOpen: true, onClick: async () => {
        if (!name.value.trim()) return toast("Name required.", "warn");
        const payload = {
          name: name.value.trim(), kind: kind.value.trim() || null,
          description: description.value.trim() || null, environment: environment.value.trim() || null,
          time_of_day_notes: tod.value.trim() || null, weather_notes: weather.value.trim() || null,
          visual_rules: listFromText(rules.value), continuity_notes: continuity.value.trim() || null,
        };
        if (existing) await patchJSON(`/api/world/locations/${existing.id}`, payload);
        else await postJSON("/api/world/locations", { project_id: Number(localStorage.getItem("studio.projectId")), ...payload });
        document.querySelector(".modal-backdrop")?.remove();
        toast(existing ? "Location saved." : "Location created.", "ok"); draw();
      } },
    ],
  });
}

async function renderProps() {
  container.append(loadingState("Loading props…"));
  const projectId = localStorage.getItem("studio.projectId");
  try {
    const query = new URLSearchParams();
    if (projectId) query.set("project_id", projectId);
    if (state.q) query.set("q", state.q);
    const data = await getJSON(`/api/world/props?${query}`);
    container.lastChild.remove();
    container.append(
      el("div", { class: "filter-bar" },
        el("input", { type: "search", placeholder: "Search props…", value: state.q,
          oninput: (e) => { state.q = e.target.value; clearTimeout(renderProps._t); renderProps._t = setTimeout(renderProps, 250); } }),
        el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${data.props.length} prop${data.props.length === 1 ? "" : "s"}`),
        el("button", { class: "btn primary", onclick: () => propModal() }, el("span", { html: ICONS.plus }), "New Prop")),
      data.props.length
        ? el("div", { class: "grid cols-2" }, ...data.props.map((prop) => el("div", { class: "card" },
            el("div", { style: "display:flex; align-items:center; gap:9px; margin-bottom:8px" },
              el("b", { style: "font-size:14px" }, prop.name),
              statusPill(prop.approval_status, pretty(prop.approval_status)),
              prop.owner_name ? el("span", { class: "pill s-outline" }, `owner: ${prop.owner_name}`) : null,
              el("span", { class: "pill s-outline", style: "margin-left:auto" }, `used ${prop.scene_usage}×`),
              el("button", { class: "btn small ghost", onclick: () => propModal(prop) }, "Edit")),
            prop.description ? el("div", { style: "font-size:12.5px" }, prop.description) : null)))
        : emptyState({ big: "No props yet", small: "Reusable props keep objects consistent across scenes and episodes." }));
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, renderProps));
  }
}

async function propModal(existing = null) {
  const characters = await getJSON(`/api/characters?project_id=${localStorage.getItem("studio.projectId")}`).catch(() => ({ characters: [] }));
  const name = el("input", { type: "text", value: existing?.name || "" });
  const description = el("textarea", { value: existing?.description || "" });
  const owner = el("select", {},
    el("option", { value: "" }, "— No owner —"),
    characters.characters.map((c) => el("option", { value: c.id, selected: existing?.owner_character_id === c.id ? "" : null }, c.name)));
  const continuity = el("textarea", { value: existing?.continuity_notes || "" });
  openModal({
    title: existing ? `Edit ${existing.name}` : "New Prop",
    body: el("div", {},
      field("Name *", name),
      field("Description", description),
      el("div", { class: "form-row" }, field("Owner / associated character", owner), el("div")),
      field("Continuity notes", continuity)),
    actions: [
      { label: "Cancel" },
      ...(existing ? [{ label: "Approve", onClick: async () => {
        await patchJSON(`/api/world/props/${existing.id}`, { approval_status: "approved" });
        toast("Prop approved.", "ok"); draw();
      } }] : []),
      { label: existing ? "Save" : "Create", kind: "primary", keepOpen: true, onClick: async () => {
        if (!name.value.trim()) return toast("Name required.", "warn");
        const payload = {
          name: name.value.trim(), description: description.value.trim() || null,
          owner_character_id: owner.value ? Number(owner.value) : null,
          continuity_notes: continuity.value.trim() || null,
        };
        if (existing) await patchJSON(`/api/world/props/${existing.id}`, payload);
        else await postJSON("/api/world/props", { project_id: Number(localStorage.getItem("studio.projectId")), ...payload });
        document.querySelector(".modal-backdrop")?.remove();
        toast(existing ? "Prop saved." : "Prop created.", "ok"); draw();
      } },
    ],
  });
}
