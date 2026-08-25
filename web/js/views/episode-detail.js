// Episode workspace: overview, acts & scenes (with scene editor), script, continuity.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, textToList, listFromText, fmtWhen,
} from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let episodeId;
let data = null;
let tab = "scenes";
let locations = [];
let characters = [];
let propsList = [];

const EP_STATUSES = ["draft", "development", "script", "approved", "in_production", "complete", "archived"];
const SCENE_STATUSES = ["draft", "needs_review", "approved", "ready_for_storyboard", "in_production", "complete"];
const ELEMENT_TYPES = [["scene_heading", "Scene heading"], ["action", "Action"], ["dialogue", "Dialogue"],
  ["narration", "Narration"], ["parenthetical", "Parenthetical"], ["sound_cue", "Sound cue"],
  ["camera_note", "Camera note"], ["transition", "Transition"]];

export async function render(c, id, params = new URLSearchParams()) {
  container = c;
  episodeId = id;
  tab = params.get("tab") || "scenes";
  container.replaceChildren(loadingState("Loading episode…"));
  try {
    const projectId = localStorage.getItem("studio.projectId");
    [data] = await Promise.all([
      getJSON(`/api/episodes/${episodeId}`),
      getJSON(`/api/world/locations${projectId ? `?project_id=${projectId}` : ""}`).then((d) => { locations = d.locations; }),
      getJSON(`/api/characters${projectId ? `?project_id=${projectId}` : ""}`).then((d) => { characters = d.characters; }),
      getJSON(`/api/world/props${projectId ? `?project_id=${projectId}` : ""}`).then((d) => { propsList = d.props; }),
    ]);
    draw(params);
  } catch (error) {
    container.replaceChildren(errorState(error, () => render(c, id, params)),
      el("div", { style: "margin-top:10px" }, el("a", { class: "btn ghost small", href: "#/episodes" }, "← Back to Episodes")));
  }
}

function draw(params = new URLSearchParams()) {
  const tabs = [
    { id: "scenes", label: "Acts & Scenes", count: data.scenes.length },
    { id: "overview", label: "Overview" },
    { id: "script", label: "Script", count: data.scenes.reduce((n, s) => n + s.script.length, 0) },
    { id: "continuity", label: "Continuity" },
  ];
  const { tabBar } = window.__ui;
  container.replaceChildren(header(), tabBar(tabs, tab, (id) => {
    tab = id;
    history.replaceState(null, "", `#/episodes/${episodeId}?tab=${id}`);
    drawPanel(params);
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#/episodes"));
  }));
  drawPanel(params);
}

function drawPanel(params) {
  const old = container.querySelector(".panel"); if (old) old.remove();
  const panel = el("div", { class: "panel" });
  container.append(panel);
  if (tab === "overview") overviewPanel(panel);
  else if (tab === "script") scriptPanel(panel);
  else if (tab === "continuity") continuityPanel(panel);
  else scenesPanel(panel, params);
}

/* ================= header ================= */
function header() {
  const ready = data.scenes.filter((s) => s.status === "ready_for_storyboard").length;
  return el("div", { class: "hero-band" },
    el("div", { style: "flex:1; min-width:260px" },
      el("h2", {}, el("span", { class: "pill s-outline", style: "margin-right:10px" }, `EP ${String(data.number).padStart(3, "0")}`), data.title),
      el("p", {}, data.logline || data.premise || "No logline yet."),
      el("div", { style: "display:flex; gap:8px; margin-top:10px; flex-wrap:wrap" },
        el("select", { style: "max-width:170px", onchange: async (e) => {
          await patchJSON(`/api/episodes/${episodeId}`, { status: e.target.value });
          toast(`Episode status: ${pretty(e.target.value)}.`, "ok"); data.status = e.target.value;
        } }, EP_STATUSES.map((s) => el("option", { value: s, selected: s === data.status ? "" : null }, pretty(s)))),
        statusPill(data.script_status || "draft", `Script: ${pretty(data.script_status || "draft")}`),
        el("span", { class: "pill s-outline" }, `${data.scenes.length} scenes`),
        ready ? el("span", { class: "pill s-green" }, `${ready} storyboard-ready`) : null,
        data.story_id ? el("a", { class: "btn small ghost", href: `#/stories/${data.story_id}` }, "Source story →") : null)),
    el("div", { style: "display:flex; gap:7px; flex-wrap:wrap" },
      el("button", { class: "btn", onclick: editEpisodeModal }, el("span", { html: ICONS.story }), "Edit Episode"),
      el("button", { class: "btn primary", onclick: async () => {
        try {
          await patchJSON(`/api/episodes/${episodeId}`, { script_status: "approved" });
          toast("Script approved.", "ok"); refresh();
        } catch (e) { toast(e.message, "error"); }
      } }, el("span", { html: ICONS.check }), "Approve Script")));
}

/* ================= overview ================= */
function overviewPanel(panel) {
  panel.append(
    el("div", { class: "grid cols-2" },
      el("div", { class: "card" }, el("h3", {}, "Summary"),
        el("div", { style: "white-space:pre-wrap; font-size:13px" }, data.summary || el("span", { class: "muted" }, "Not set — use Edit Episode."))),
      el("div", { class: "card" }, el("h3", {}, "Production"),
        el("dl", { class: "kv" },
          el("dt", {}, "Target length"), el("dd", {}, `${data.target_length_minutes} min`),
          el("dt", {}, "Status"), el("dd", {}, pretty(data.status)),
          el("dt", {}, "Script status"), el("dd", {}, pretty(data.script_status || "draft")),
          el("dt", {}, "Scenes"), el("dd", {}, String(data.scenes.length)),
          el("dt", {}, "Updated"), el("dd", {}, fmtWhen(data.updated_at)))),
      el("div", { class: "card" }, el("h3", {}, "Premise"),
        el("div", { style: "white-space:pre-wrap; font-size:13px" }, data.premise || el("span", { class: "muted" }, "Not set"))),
      el("div", { class: "card" }, el("h3", {}, "Workflow"),
        el("div", { style: "font-size:12.5px; color:var(--text-dim); line-height:1.9" },
          "Draft → Development → Script → ", el("b", { style: "color:var(--moss)" }, "Approved"), " → In Production → Complete",
          el("br", {}), "Scenes: Draft → Needs Review → Approved → ", el("b", { style: "color:var(--moss)" }, "Ready for Storyboard"),
          el("br", {}), "Every step requires explicit approval — nothing finalizes silently."))));
}

function editEpisodeModal() {
  const title = el("input", { type: "text", value: data.title });
  const logline = el("textarea", { value: data.logline || "", rows: 2 });
  const premise = el("textarea", { value: data.premise || "", rows: 3 });
  const summary = el("textarea", { value: data.summary || "", rows: 3 });
  const target = el("input", { type: "number", value: String(data.target_length_minutes) });
  openModal({
    title: "Edit Episode", wide: true,
    body: el("div", {},
      el("div", { class: "form-row" }, field("Title", title), field("Target minutes", target)),
      field("Logline", logline), field("Premise", premise), field("Summary", summary)),
    actions: [
      { label: "Cancel" },
      { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
        await patchJSON(`/api/episodes/${episodeId}`, {
          title: title.value.trim(), logline: logline.value.trim() || null,
          premise: premise.value.trim() || null, summary: summary.value.trim() || null,
          target_length_minutes: parseFloat(target.value) || 8,
        });
        document.querySelector(".modal-backdrop")?.remove();
        toast("Episode saved.", "ok"); refresh();
      } },
    ],
  });
}

/* ================= acts & scenes ================= */
function scenesPanel(panel, params) {
  const openSceneId = params.get("scene");
  const actsById = new Map(data.acts.map((a) => [a.id, a]));
  const grouped = new Map();
  for (const scene of data.scenes) {
    const key = scene.act_id ?? null;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(scene);
  }
  panel.append(el("div", { style: "display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap" },
    el("button", { class: "btn", onclick: addActModal }, el("span", { html: ICONS.plus }), "Add Act"),
    el("button", { class: "btn primary", onclick: () => addSceneModal() }, el("span", { html: ICONS.plus }), "Add Scene")));

  if (!data.scenes.length && !data.acts.length) {
    panel.append(emptyState({
      big: "No acts or scenes yet",
      small: "Structure the episode: acts hold scenes, scenes hold the script. Start with Act 1.",
      actions: [el("button", { class: "btn small primary", onclick: addSceneModal }, "Add First Scene")],
    }));
    return;
  }

  const renderGroup = (label, scenes, act) => {
    const block = el("div", { class: "card", style: "margin-bottom:12px" },
      el("div", { style: "display:flex; align-items:center; gap:9px; margin-bottom:10px" },
        el("h3", { style: "margin:0" }, label),
        act ? el("span", { class: "muted", style: "font-size:12px" }, act.purpose || "") : null,
        act ? el("button", { class: "btn small ghost", style: "margin-left:auto", onclick: () => actModal(act) }, "Edit Act") : null,
        act ? el("button", { class: "btn small danger", onclick: async () => {
          if (!confirm(`Delete ${label}? Scenes fall back to episode level.`)) return;
          await fetch(`/api/acts/${act.id}`, { method: "DELETE" }); toast("Act removed.", "ok"); refresh();
        } }, el("span", { html: ICONS.x })) : null),
      act && (act.summary || act.beginning) ? el("div", { class: "muted", style: "font-size:12px; margin-bottom:10px" },
        [act.summary, act.beginning && `B: ${act.beginning}`, act.middle && `M: ${act.middle}`, act.ending && `E: ${act.ending}`].filter(Boolean).join(" · ")) : null);
    if (!scenes.length) {
      block.append(el("div", { class: "muted", style: "font-size:12.5px; padding:8px 0" }, "No scenes in this act yet."));
    }
    scenes.forEach((scene, index) => block.append(sceneRow(scene, scenes, index, openSceneId)));
    return block;
  };

  // acts first (in order), then unassigned
  for (const act of data.acts) panel.append(renderGroup(act.title || `Act ${act.number}`, grouped.get(act.id) || [], act));
  if (grouped.has(null)) panel.append(renderGroup("Ungrouped scenes", grouped.get(null), null));
}

function sceneRow(scene, siblings, index, openSceneId) {
  const row = el("div", {
    class: "card", style: `display:flex; gap:11px; align-items:center; padding:11px 13px; margin-bottom:8px; cursor:pointer; ${scene.id === Number(openSceneId) ? "border-color:var(--moss-deep);" : ""}`,
    onclick: () => sceneModal(scene),
  },
    el("span", { class: "pill s-outline" }, scene.scene_ref || `#${scene.number}`),
    el("div", { style: "flex:1; min-width:0" },
      el("div", { style: "font-weight:600" }, scene.title || "Untitled scene"),
      el("div", { style: "display:flex; gap:6px; margin-top:5px; flex-wrap:wrap; font-size:11.5px" },
        statusPill(scene.status),
        el("span", { class: "pill s-outline" }, scene.location_name || "no location"),
        scene.time_of_day ? el("span", { class: "pill s-outline" }, scene.time_of_day) : null,
        (scene.cast || []).length ? el("span", { class: "pill s-outline" }, scene.cast.map((l) => l.character?.name).filter(Boolean).join(", ")) : el("span", { class: "pill s-red" }, "no cast"),
        scene.script.length ? el("span", { class: "pill s-outline" }, `${scene.script.length} lines`) : null)),
    el("div", { style: "display:flex; gap:4px", onclick: (e) => e.stopPropagation() },
      el("button", { class: "btn small ghost", title: "Move up", onclick: async () => { await moveScene(scene, siblings, -1); } }, "↑"),
      el("button", { class: "btn small ghost", title: "Move down", onclick: async () => { await moveScene(scene, siblings, +1); } }, "↓"),
      el("button", { class: "btn small ghost", title: "Delete", onclick: async () => {
        if (!confirm(`Delete ${scene.scene_ref}?`)) return;
        const response = await fetch(`/api/scenes/${scene.id}`, { method: "DELETE" });
        response.ok ? (toast("Scene deleted.", "ok"), refresh()) : toast("Could not delete (already in production?).", "warn");
      } }, el("span", { html: ICONS.x }))));
  return row;
}

async function moveScene(scene, siblings, delta) {
  const ids = siblings.map((s) => s.id);
  const index = ids.indexOf(scene.id);
  const target = index + delta;
  if (target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target], ids[index]];
  // full episode ordering: rebuild from all scenes in current DOM order approximation
  const allIds = data.scenes.map((s) => s.id);
  const fullOrder = [];
  for (const id of allIds) {
    fullOrder.push(ids.includes(id) ? id : id);
  }
  // splice swapped pair into the full list positions of those two scenes
  const posA = allIds.indexOf(ids[index]);
  const posB = allIds.indexOf(ids[target]);
  [fullOrder[posA], fullOrder[posB]] = [ids[target], ids[index]];
  await postJSON(`/api/episodes/${episodeId}/scenes/reorder`, { scene_ids: fullOrder.filter((x, i, arr) => arr.indexOf(x) === i) });
  refresh();
}

function addActModal() {
  const title = el("input", { type: "text", placeholder: "Act 1 — The Find" });
  const purpose = el("input", { type: "text", placeholder: "Setup: want and obstacle" });
  const summary = el("textarea", { placeholder: "What happens across this act" });
  openModal({
    title: "Add Act",
    body: el("div", {}, field("Title", title), field("Purpose", purpose), field("Summary", summary)),
    actions: [
      { label: "Cancel" },
      { label: "Create", kind: "primary", onClick: async (e, close) => {
        await postJSON("/api/acts", { episode_id: episodeId, title: title.value.trim(), purpose: purpose.value.trim() || null, summary: summary.value.trim() || null });
        close(); toast("Act added.", "ok"); refresh();
      } },
    ],
  });
}

function actModal(act) {
  const title = el("input", { type: "text", value: act.title });
  const purpose = el("input", { type: "text", value: act.purpose || "" });
  const summary = el("textarea", { value: act.summary || "" });
  const beginning = el("textarea", { value: act.beginning || "", rows: 2 });
  const middle = el("textarea", { value: act.middle || "", rows: 2 });
  const ending = el("textarea", { value: act.ending || "", rows: 2 });
  openModal({
    title: `Edit ${act.title}`, wide: true,
    body: el("div", {},
      el("div", { class: "form-row" }, field("Title", title), field("Purpose", purpose)),
      field("Summary", summary),
      el("div", { class: "form-cols-3 grid cols-3" },
        field("Beginning", beginning), field("Middle", middle), field("Ending", ending))),
    actions: [
      { label: "Cancel" },
      { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
        await patchJSON(`/api/acts/${act.id}`, {
          title: title.value.trim(), purpose: purpose.value.trim() || null,
          summary: summary.value.trim() || null, beginning: beginning.value.trim() || null,
          middle: middle.value.trim() || null, ending: ending.value.trim() || null,
        });
        document.querySelector(".modal-backdrop")?.remove(); toast("Act saved.", "ok"); refresh();
      } },
    ],
  });
}

function addSceneModal(act = null) {
  const title = el("input", { type: "text", placeholder: "e.g. The hollow echo" });
  const location = el("select", {}, el("option", { value: "" }, "— Choose location —"),
    locations.map((l) => el("option", { value: l.id }, l.name)));
  const tod = el("select", {}, ["", "morning", "midday", "afternoon", "evening", "night"].map((t) => el("option", { value: t }, t || "—")));
  const weather = el("input", { type: "text", placeholder: "e.g. misty" });
  const purpose = el("input", { type: "text", placeholder: "Story purpose of this scene" });
  const duration = el("input", { type: "number", value: "45", min: "5" });
  openModal({
    title: "Add Scene", wide: true,
    sub: "Cast characters, link props and write the script after creating.",
    body: el("div", {},
      el("div", { class: "form-row" }, field("Title", title), field("Location", location)),
      el("div", { class: "form-row" }, field("Time of day", tod), field("Weather", weather)),
      el("div", { class: "form-row" }, field("Story purpose", purpose), field("Est. seconds", duration))),
    actions: [
      { label: "Cancel" },
      { label: "Create Scene", kind: "primary", onClick: async (e, close) => {
        const scene = await postJSON("/api/scenes", {
          episode_id: episodeId, act_id: act?.id ?? null,
          title: title.value.trim() || "Untitled scene",
          location_id: location.value ? Number(location.value) : null,
          time_of_day: tod.value || null, weather: weather.value.trim() || null,
          story_purpose: purpose.value.trim() || null,
          estimated_duration_seconds: parseFloat(duration.value) || null,
        });
        close(); toast("Scene created as draft.", "ok");
        refresh().then(() => sceneModalById(scene.id));
      } },
    ],
  });
}

/* ---------- scene editor modal ---------- */
async function refresh() {
  data = await getJSON(`/api/episodes/${episodeId}`);
  draw();
}

async function sceneModalById(id) {
  const fresh = await getJSON(`/api/scenes/${id}`);
  sceneModal(fresh);
}

function sceneModal(scene) {
  const modalTabs = ["details", "cast", "script", "checks"];
  let active = "details";
  let current = scene;

  const body = el("div", {});
  const { tabBar } = window.__ui;
  const tabBarEl = tabBar([
    { id: "details", label: "Details" },
    { id: "cast", label: "Cast & Props", count: (current.cast || []).length + (current.props || []).length },
    { id: "script", label: "Script", count: (current.script || []).length },
    { id: "checks", label: "Continuity & Approval" },
  ], active, (id) => { active = id; renderTab(); });

  const redraw = () => {
    document.querySelector(".modal-backdrop")?.remove();
    sceneModalById(current.id);
  };

  function renderTab() {
    body.replaceChildren();
    if (active === "details") detailsTab();
    else if (active === "cast") castTab();
    else if (active === "script") scriptTab();
    else checksTab();
  }

  function detailsTab() {
    const inputs = {
      title: el("input", { type: "text", value: current.title || "" }),
      location: el("select", { onchange: async (e) => {
        await patchJSON(`/api/scenes/${current.id}`, { location_id: e.target.value ? Number(e.target.value) : null });
        toast("Location set.", "ok");
      } }, el("option", { value: "" }, "— none —"),
        locations.map((l) => el("option", { value: l.id, selected: current.location_id === l.id ? "" : null }, l.name))),
      act: el("select", { onchange: async (e) => {
        await patchJSON(`/api/scenes/${current.id}`, { act_id: e.target.value ? Number(e.target.value) : null });
        toast("Act set.", "ok");
      } }, el("option", { value: "" }, "— ungrouped —"),
        data.acts.map((a) => el("option", { value: a.id, selected: current.act_id === a.id ? "" : null }, a.title))),
      time_of_day: el("select", { onchange: async (e) => { await patchJSON(`/api/scenes/${current.id}`, { time_of_day: e.target.value || null }); } },
        ["", "morning", "midday", "afternoon", "evening", "night"].map((t) => el("option", { value: t, selected: current.time_of_day === t ? "" : null }, t || "—"))),
      weather: el("input", { type: "text", value: current.weather || "" }),
      emotional_tone: el("input", { type: "text", value: current.emotional_tone || "", placeholder: "e.g. wonder → worry" }),
      story_purpose: el("input", { type: "text", value: current.story_purpose || "" }),
      summary: el("textarea", { value: current.summary || "", rows: 3 }),
      visual_action: el("textarea", { value: current.visual_action || "", rows: 3 }),
      visual_direction: el("textarea", { value: current.visual_direction || "", rows: 2 }),
      continuity_notes: el("textarea", { value: current.continuity_notes || "", rows: 2 }),
      dependency_notes: el("input", { type: "text", value: current.dependency_notes || "", placeholder: "Depends on previous/next scene…" }),
    };
    body.append(el("div", {},
      el("div", { class: "form-row" },
        field("Title", inputs.title),
        field("Status", el("select", { onchange: async (e) => {
          await patchJSON(`/api/scenes/${current.id}`, { status: e.target.value });
          current.status = e.target.value; toast(`Scene: ${pretty(e.target.value)}.`, "ok");
        } }, SCENE_STATUSES.map((s) => el("option", { value: s, selected: current.status === s ? "" : null }, pretty(s))))),
      el("div", { class: "form-row-3" }, field("Location", inputs.location), field("Act", inputs.act), field("Time of day", inputs.time_of_day)),
      el("div", { class: "form-row" }, field("Weather", inputs.weather), field("Emotional tone", inputs.emotional_tone)),
      field("Story purpose", inputs.story_purpose),
      field("Summary", inputs.summary), field("Action", inputs.visual_action),
      field("Visual direction", inputs.visual_direction),
      el("div", { class: "form-row" }, field("Continuity notes", inputs.continuity_notes), field("Dependencies", inputs.dependency_notes)),
      el("div", { style: "display:flex; justify-content:flex-end; margin-top:6px" },
        el("button", { class: "btn small primary", onclick: async () => {
          await patchJSON(`/api/scenes/${current.id}`, {
            title: inputs.title.value.trim() || null, weather: inputs.weather.value.trim() || null,
            emotional_tone: inputs.emotional_tone.value.trim() || null,
            story_purpose: inputs.story_purpose.value.trim() || null,
            summary: inputs.summary.value.trim() || null,
            visual_action: inputs.visual_action.value.trim() || null,
            visual_direction: inputs.visual_direction.value.trim() || null,
            continuity_notes: inputs.continuity_notes.value.trim() || null,
            dependency_notes: inputs.dependency_notes.value.trim() || null,
          });
          toast("Scene saved.", "ok"); redraw();
        } }, "Save Details")))));
  }

  function castTab() {
    const wrap = el("div", {});
    // current cast with approved-info
    for (const link of current.cast || []) {
      const character = link.character;
      if (!character) continue;
      const castCard = el("div", { class: "card", style: "margin-bottom:10px" },
        el("div", { style: "display:flex; align-items:center; gap:9px" },
          el("b", {}, character.name),
          character.species ? el("span", { class: "pill s-outline" }, character.species) : null,
          el("button", { class: "btn small danger", style: "margin-left:auto", onclick: async () => {
            await fetch(`/api/scenes/${current.id}/cast/${character.id}`, { method: "DELETE" });
            toast("Removed from scene.", "ok"); redraw();
          } }, "Remove")),
        el("button", { class: "btn small ghost", style: "margin-top:8px", onclick: async () => {
          const profile = await getJSON(`/api/scenes/${current.id}/cast/${character.id}/profile`);
          profileModal(profile);
        } }, "Approved info (Phase 4 package) →"));
      wrap.append(castCard);
    }
    // picker
    const inScene = new Set((current.cast || []).map((l) => l.character?.id));
    const picker = el("div", { style: "display:flex; gap:6px; flex-wrap:wrap; margin:10px 0" },
      characters.filter((c) => !inScene.has(c.id)).map((c) =>
        el("button", { class: "btn small ghost", onclick: async () => {
          await postJSON(`/api/scenes/${current.id}/cast`, { character_id: c.id });
          toast(`${c.name} cast.`, "ok"); redraw();
        } }, el("span", { html: ICONS.plus }), c.name)));
    // props
    const propSection = el("div", { class: "card", style: "margin-top:12px" },
      el("h3", {}, "Props in this scene"),
      ...(current.props || []).map((p) => el("div", { style: "display:flex; gap:8px; align-items:center; padding:6px 0" },
        el("b", {}, p.prop?.name || "?"),
        el("span", { class: "muted", style: "font-size:12px" }, p.usage_notes || ""),
        el("button", { class: "btn small danger", style: "margin-left:auto", onclick: async () => {
          await fetch(`/api/scenes/${current.id}/props/${p.prop_id}`, { method: "DELETE" });
          toast("Prop removed.", "ok"); redraw();
        } }, "Remove"))),
      el("div", { style: "display:flex; gap:6px; flex-wrap:wrap; margin-top:8px" },
        propsList.filter((p) => !(current.props || []).some((x) => x.prop_id === p.id)).map((p) =>
          el("button", { class: "btn small ghost", onclick: async () => {
            await postJSON(`/api/scenes/${current.id}/props`, { prop_id: p.id });
            toast(`${p.name} linked.`, "ok"); redraw();
          } }, el("span", { html: ICONS.plus }), p.name))));
    body.append(el("div", {},
      el("h3", { style: "margin:2px 0 4px; font-size:13px" }, "Cast from the Character Library"),
      picker, wrap, propSection));
  }

  function scriptTab() {
    const list = el("div", {});
    const renderElements = () => {
      list.replaceChildren();
      if (!current.script.length) list.append(el("div", { class: "muted", style: "padding:10px 0; font-size:12.5px" }, "No lines yet — add the first script element below."));
      current.script.forEach((element, index) => {
        const typeStyle = {
          scene_heading: "font-weight:700; letter-spacing:.03em; text-transform:uppercase; color:var(--moss)",
          action: "color:var(--text)",
          dialogue: "padding-left:26px",
          narration: "padding-left:26px; color:var(--berry); font-style:italic",
          parenthetical: "padding-left:52px; color:var(--text-dim); font-style:italic",
          sound_cue: "color:var(--amber); font-family:var(--mono); font-size:12px",
          camera_note: "color:var(--sky); font-family:var(--mono); font-size:12px",
          transition: "text-align:right; font-weight:600",
        }[element.element_type] || "";
        const speaker = element.element_type === "dialogue"
          ? (element.character?.name || element.character_name || "?")
          : element.element_type === "narration" ? (element.narrator_name || "NARRATOR") : null;
        list.append(el("div", { class: "card", style: "padding:9px 13px; margin-bottom:7px; display:flex; gap:10px; align-items:flex-start" },
          el("div", { style: "flex:1; min-width:0" },
            speaker ? el("div", { style: "font-weight:650; margin-bottom:2px" }, speaker) : null,
            el("div", { style: `font-size:13px; ${typeStyle}` }, element.text || el("span", { class: "muted" }, "…")),
            element.timing_notes ? el("div", { class: "muted", style: "font-size:11px; margin-top:3px" }, `⏱ ${element.timing_notes}`) : null),
          el("span", { class: "pill s-outline" }, pretty(element.element_type)),
          el("div", { style: "display:flex; gap:3px" },
            el("button", { class: "btn small ghost", onclick: async () => { await postJSON(`/api/script-elements/${element.id}/move`, { direction: "up" }); redrawSceneScript(renderElements); } }, "↑"),
            el("button", { class: "btn small ghost", onclick: async () => { await postJSON(`/api/script-elements/${element.id}/move`, { direction: "down" }); redrawSceneScript(renderElements); } }, "↓"),
            el("button", { class: "btn small ghost", onclick: () => elementModal(element, renderElements) }, "Edit"),
            el("button", { class: "btn small ghost", title: "Duplicate", onclick: async () => { await postJSON(`/api/script-elements/${element.id}/duplicate`); redrawSceneScript(renderElements); } }, "⧉"),
            el("button", { class: "btn small ghost", title: "Move to another scene", onclick: () => transferModal(element, renderElements) }, "→"),
            el("button", { class: "btn small danger", onclick: async () => {
              await fetch(`/api/script-elements/${element.id}`, { method: "DELETE" });
              redrawSceneScript(renderElements);
            } }, el("span", { html: ICONS.x })))));
      });
    };
    renderElements();
    body.append(el("div", {},
      list,
      el("button", { class: "btn small", style: "margin-top:8px", onclick: () => elementModal(null, renderElements) },
        el("span", { html: ICONS.plus }), "Add Line"),
      el("div", { class: "muted", style: "fontSize:11.5px, fontSize:11.5px; margin-top:8px; font-size:11.5px" },
        "Dialogue stays bound to its character. Narration is a separate structured element (narrator, timing) for the future voice system.")));
  }

  async function redrawSceneScript(renderElements) {
    current = await getJSON(`/api/scenes/${current.id}`);
    renderElements();
  }

  function checksTab() {
    const holder = el("div", {});
    const run = async () => {
      holder.replaceChildren(loadingState("Checking canon…"));
      try {
        const check = await getJSON(`/api/scenes/${current.id}/continuity-check`);
        holder.replaceChildren();
        if (!check.warnings.length && !check.info.length) {
          holder.append(el("div", { class: "callout green", style: "font-size:12.5px" }, el("b", {}, "No warnings. "),
            "Checked: ", check.checked_fields.join(", "), "."));
        }
        for (const w of check.warnings) holder.append(el("div", { class: "callout", style: "margin-bottom:8px; font-size:12.5px" },
          el("b", {}, w.severity === "violation" ? "⚠ Violation" : "⚠ Warning"), " — ", w.message));
        for (const i of check.info) holder.append(el("div", { class: "muted", style: "font-size:12px; margin-bottom:6px" }, "ℹ ", i.message));
      } catch (e) {
        holder.replaceChildren(errorState(e));
      }
    };
    run();
    body.append(el("div", {},
      el("div", { class: "card", style: "margin-bottom:12px" },
        el("h3", {}, "Continuity check (draft vs canon)"),
        el("div", { class: "muted", style: "font-size:12px; margin-bottom:8px" }, "Warnings only — canon is never changed automatically."),
        holder,
        el("button", { class: "btn small ghost", style: "margin-top:8px", onclick: run }, el("span", { html: ICONS.refresh }), "Re-check")),
      el("div", { class: "card" },
        el("h3", {}, "Storyboard readiness"),
        el("div", { class: "muted", style: "font-size:12px; margin-bottom:10px" },
          "Approve the scene, then mark Ready for Storyboard. This assembles the Phase 4 reference package (cast + approved references + location + props + script + continuity)."),
        el("div", { style: "display:flex; gap:8px; flex-wrap:wrap" },
          current.status !== "approved" && current.status !== "ready_for_storyboard"
            ? el("button", { class: "btn", onclick: async () => {
                await patchJSON(`/api/scenes/${current.id}`, { status: "approved" });
                toast("Scene approved.", "ok"); redraw();
              } }, el("span", { html: ICONS.check }), "Approve Scene") : null,
          el("button", { class: "btn primary", onclick: async () => {
            try {
              const result = await postJSON(`/api/scenes/${current.id}/ready-for-storyboard`);
              toast("Scene is storyboard-ready — package assembled for Phase 4.", "ok");
              viewPackageModal(result.package);
              redraw();
            } catch (error) {
              const detail = error.detail || {};
              if (detail.missing) toast(`Incomplete: missing ${detail.missing.join(", ")}.`, "warn", "Not ready");
              else toast(error.message, "error");
            }
          } }, "Mark Ready for Storyboard"),
          el("button", { class: "btn ghost", onclick: async () => {
            const pkg = await getJSON(`/api/scenes/${current.id}/package`);
            viewPackageModal(pkg);
          } }, "View Package")))));
  }

  function profileModal(profile) {
    const ch = profile.character;
    openModal({
      title: `${ch.name} — approved production info`, wide: true,
      sub: "This is what the Phase 4 shot-reference package will receive for this character.",
      body: el("div", {},
        el("div", { class: "grid cols-2" },
          el("div", { class: "card" }, el("h3", {}, "Continuity"),
            el("div", { style: "font-size:12.5px" },
              el("div", {}, el("b", {}, "Appearance: "), ch.standard_appearance || "—"),
              el("div", {}, el("b", {}, "Outfit: "), ch.current_outfit || ch.clothing || "—"),
              el("div", {}, el("b", {}, "Standard props: "), (ch.standard_props || []).join(", ") || "—"),
              el("div", { style: "margin-top:8px" }, el("b", {}, "Never changes:")),
              el("ul", { style: "margin:4px 0 0 16px" }, ...(ch.never_changes || []).map((n) => el("li", {}, n))),
              el("div", { style: "margin-top:8px" }, el("b", {}, "Visual rules:")),
              el("ul", { style: "margin:4px 0 0 16px" }, ...(ch.visual_rules || []).map((n) => el("li", {}, n))))),
          el("div", { class: "card" }, el("h3", {}, "Approved references"),
            profile.approved_references.length
              ? el("ul", { style: "margin:0; padding-left:16px; font-size:12.5px" },
                  ...profile.approved_references.map((r) => el("li", {}, `${pretty(r.purpose)} — ${r.label || ""}`)))
              : el("div", { class: "callout", style: "font-size:12px" }, "No approved references yet — approve reference images in the Characters section."),
            el("h3", { style: "margin-top:12px" }, "Relationships in this scene"),
            profile.relationships.length
              ? el("ul", { style: "margin:0; padding-left:16px; font-size:12.5px" },
                  ...profile.relationships.map((r) => el("li", {},
                    el("b", {}, pretty(r.kind)), ` with ${r.with_character || "?"}`, r.in_scene ? el("span", { style: "color:var(--moss)" }, " · in scene") : "")))
              : el("div", { class: "muted", style: "font-size:12px" }, "None recorded.")))),
      actions: [{ label: "Close" }],
    });
  }

  function elementModal(element, rerender) {
    const type = el("select", {}, ELEMENT_TYPES.map(([v, l]) => el("option", { value: v, selected: element?.element_type === v ? "" : null }, l)));
    const text = el("textarea", { value: element?.text || "", rows: 3, placeholder: element?.element_type === "dialogue" ? "What they say…" : "" });
    const characterSel = el("select", { onchange: () => { /* character chosen */ } },
      el("option", { value: "" }, "— none —"),
      characters.map((c) => el("option", { value: c.id, selected: element?.character_id === c.id ? "" : null }, c.name)));
    const narrator = el("input", { type: "text", value: element?.narrator_name || "Narrator", placeholder: "Narrator" });
    const timing = el("input", { type: "text", value: element?.timing_notes || "", placeholder: "e.g. hushed, over the wide shot" });
    const notes = el("input", { type: "text", value: element?.notes || "", placeholder: "performance/intent notes" });
    openModal({
      title: element ? "Edit line" : "Add script line", wide: true,
      body: el("div", {},
        el("div", { class: "form-row" }, field("Type", type),
          field("Speaker (dialogue)", characterSel, "From the Character Library — no duplicates created.")),
        field("Text", text),
        el("div", { class: "form-row" }, field("Narrator name (narration)", narrator), field("Timing notes", timing)),
        field("Notes", notes)),
      actions: [
        { label: "Cancel" },
        { label: element ? "Save" : "Add", kind: "primary", keepOpen: true, onClick: async () => {
          const payload = {
            element_type: type.value, text: text.value.trim(),
            character_id: characterSel.value ? Number(characterSel.value) : null,
            narrator_name: narrator.value.trim() || null,
            timing_notes: timing.value.trim() || null, notes: notes.value.trim() || null,
          };
          if (element) await patchJSON(`/api/script-elements/${element.id}`, payload);
          else await postJSON("/api/script-elements", { scene_id: current.id, ...payload });
          document.querySelector(".modal-backdrop")?.remove();
          toast(element ? "Line saved." : "Line added.", "ok");
          redrawSceneScript(rerender).then(rerender);
        } },
      ],
    });
  }

  function transferModal(element, rerender) {
    const sceneButtons = data.scenes
      .filter((s) => s.id !== current.id)
      .map((s) => el("button", {
        class: "btn small ghost",
        onclick: async () => {
          await postJSON(`/api/script-elements/${element.id}/transfer`, { target_scene_id: s.id });
          document.querySelector(".modal-backdrop")?.remove();
          toast(`Moved to ${s.scene_ref}.`, "ok");
          redrawSceneScript(rerender).then(rerender);
        },
      }, `${s.scene_ref} — ${s.title || "Untitled"}`));
    openModal({
      title: "Move line to another scene",
      sub: "Lines can move between scenes of the same episode.",
      body: el("div", { class: "card" },
        el("div", { class: "muted", style: "font-size:12px; margin-bottom:8px" }, `“${element.text.slice(0, 80)}”`),
        el("div", { style: "display:flex; flex-direction:column; gap:6px" }, sceneButtons)),
      actions: [{ label: "Cancel" }],
    });
  }

  openModal({
    title: `${current.scene_ref || "Scene"} — ${current.title || "Untitled"}`,
    sub: `Episode ${data.number} · ${current.location_name || "no location"} · ${current.time_of_day || "?"}`,
    wide: true,
    body: el("div", {}, tabBarEl, body),
    actions: [{ label: "Close" }],
  });
  renderTab();
}

/* ================= script overview ================= */
function scriptPanel(panel) {
  panel.append(
    el("div", { class: "filter-bar" },
      el("span", { class: "pill s-outline" }, "Full episode script"),
      el("button", { class: "btn small", style: "margin-left:auto", onclick: async () => {
        await patchJSON(`/api/episodes/${episodeId}`, { script_status: "review" });
        toast("Script submitted for review.", "ok"); refresh();
      } }, "Submit Script for Review"),
      el("button", { class: "btn small primary", onclick: async () => {
        await patchJSON(`/api/episodes/${episodeId}`, { script_status: "approved" });
        toast("Script approved.", "ok"); refresh();
      } }, el("span", { html: ICONS.check }), "Approve Script")));
  if (!data.scenes.length) {
    panel.append(emptyState({ big: "No scenes yet", small: "Add scenes first — the script lives inside each scene." }));
    return;
  }
  for (const scene of data.scenes) {
    const block = el("div", { class: "scene-block" },
      el("h4", {}, el("span", { class: "pill s-outline" }, scene.scene_ref), " ",
        scene.title || "Untitled", " ",
        statusPill(scene.status), " ",
        el("button", { class: "btn small ghost", onclick: () => sceneModal(scene) }, "Edit script")),
      el("div", { class: "sub" }, `${scene.location_name || "no location"} · ${scene.time_of_day || "?"}${scene.weather ? ` · ${scene.weather}` : ""}`));
    if (!scene.script.length) block.append(el("div", { class: "muted", style: "font-size:12px" }, "No lines yet."));
    for (const element of scene.script) {
      const speaker = element.element_type === "dialogue" ? (element.character?.name || element.character_name || "?")
        : element.element_type === "narration" ? (element.narrator_name || "NARRATOR") : null;
      block.append(el("div", { style: `margin-bottom:5px; font-size:13px; ${element.element_type === "dialogue" || element.element_type === "narration" ? "padding-left:24px" : ""}` },
        speaker ? el("div", { style: "font-weight:650" }, speaker) : null,
        el("span", { style: element.element_type === "scene_heading" ? "font-weight:700; text-transform:uppercase" : element.element_type === "action" ? "" : "font-style:italic" }, element.text)));
    }
    panel.append(block);
  }
}

/* ================= continuity events ================= */
function continuityPanel(panel) {
  const holder = el("div", {});
  panel.append(holder,
    el("button", { class: "btn primary", onclick: addEventModal }, el("span", { html: ICONS.plus }), "Record Event / Thread"));
  renderEvents();

  async function renderEvents() {
    holder.replaceChildren(loadingState("Loading continuity…"));
    try {
      const data2 = await getJSON(`/api/episodes/${episodeId}/continuity`);
      holder.replaceChildren();
      if (!data2.events.length) {
        holder.append(emptyState({ big: "No continuity events yet", small: "Record discoveries, objects, location changes, relationship changes, revelations and threads." }));
        return;
      }
      for (const ev of data2.events) {
        holder.append(el("div", { class: "card", style: "display:flex; gap:10px; align-items:flex-start; margin-bottom:8px; padding:11px 14px" },
          el("span", { class: `pill ${ev.kind === "unresolved_thread" ? "s-amber" : ev.kind === "resolved_thread" ? "s-green" : ev.status === "canon" ? "s-purple" : "s-blue"}` }, pretty(ev.kind)),
          el("div", { style: "flex:1" },
            el("div", {}, ev.summary),
            el("div", { style: "display:flex; gap:6px; margin-top:5px" },
              statusPill(ev.status, pretty(ev.status)),
              ev.status !== "canon" ? el("button", { class: "btn small ghost", onclick: async () => {
                await patchJSON(`/api/continuity/${ev.id}`, { status: "canon" });
                toast("Event recorded as canon.", "ok"); renderEvents();
              } }, "Make Canon") : null)),
          ev.kind === "unresolved_thread" ? el("button", { class: "btn small", onclick: async () => {
            await postJSON(`/api/continuity/${ev.id}/resolve`);
            toast("Thread resolved.", "ok"); renderEvents();
          } }, "Resolve") : null));
      }
    } catch (e) {
      holder.replaceChildren(errorState(e, renderEvents));
    }
  }

  function addEventModal() {
    const kinds = ["discovery", "object", "location_change", "relationship", "revelation", "story_event", "unresolved_thread", "injury", "clothing", "weather"];
    const kind = el("select", {}, kinds.map((k) => el("option", { value: k }, pretty(k))));
    const summary = el("input", { type: "text", placeholder: "e.g. Yeti finds a carved whistle in the hollow" });
    openModal({
      title: "Record continuity event",
      body: el("div", {}, field("Kind", kind), field("Summary *", summary)),
      actions: [
        { label: "Cancel" },
        { label: "Record (draft)", kind: "primary", onClick: async (e, close) => {
          if (!summary.value.trim()) return toast("Summary required.", "warn");
          await postJSON(`/api/episodes/${episodeId}/continuity`, { kind: kind.value, summary: summary.value.trim() });
          close(); toast("Event recorded as draft.", "ok"); renderEvents();
        } },
      ],
    });
  }
}

function viewPackageModal(pkg) {
  openModal({
    title: "Phase 4 reference package", wide: true,
    sub: `${pkg.scene.scene_ref} — everything the storyboard/shot phase needs.`,
    body: el("div", {},
      el("div", { class: "callout green", style: "font-size:12px; margin-bottom:10px" }, pkg.barefoot_rule),
      el("pre", { class: "code", style: "max-height:420px" }, JSON.stringify(pkg, null, 2))),
    actions: [{ label: "Close" }],
  });
}
