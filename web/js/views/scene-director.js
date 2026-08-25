// Scene Director: storyboard workspace — shots, references, validation, readiness.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, fmtBytes, tabBar,
} from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let sceneId;
let data = null;
let characters = [];
let assets = [];
let propsList = [];

const SHOT_TYPES = [["extreme_wide", "Extreme wide"], ["wide", "Wide"], ["full", "Full"], ["medium", "Medium"],
  ["medium_close_up", "Medium close-up"], ["close_up", "Close-up"], ["extreme_close_up", "Extreme close-up"],
  ["over_the_shoulder", "Over-the-shoulder"], ["two_shot", "Two-shot"], ["insert", "Insert"],
  ["establishing", "Establishing"], ["pov", "POV"], ["custom", "Custom"]];
const ANGLES = ["eye_level", "low_angle", "high_angle", "birds_eye", "worms_eye", "dutch_angle", "overhead", "custom"];
const MOVES = ["static", "pan", "tilt", "push_in", "pull_out", "dolly", "tracking", "orbit", "crane", "handheld", "custom"];
const REF_PURPOSES = [["storyboard_image", "Storyboard image"], ["first_frame", "First frame"], ["last_frame", "Last frame"],
  ["keyframe", "Keyframe"], ["prev_shot_frame", "Previous-shot frame"], ["next_shot_frame", "Next-shot frame"],
  ["character_reference", "Character reference"], ["location_reference", "Location reference"], ["prop_reference", "Prop reference"], ["other", "Other"]];

export async function render(c, id) {
  container = c;
  sceneId = Number(id);
  await refresh();
}

async function refresh() {
  container.replaceChildren(loadingState("Loading Scene Director…"));
  try {
    const projectId = localStorage.getItem("studio.projectId");
    [data] = await Promise.all([
      getJSON(`/api/scenes/${sceneId}/director`),
      getJSON(`/api/characters${projectId ? `?project_id=${projectId}` : ""}`).then((d) => { characters = d.characters; }),
      getJSON(`/api/assets?limit=200&project_id=${projectId || ""}`).then((d) => { assets = d.assets; }),
      getJSON(`/api/world/props${projectId ? `?project_id=${projectId}` : ""}`).then((d) => { propsList = d.props; }),
    ]);
    draw();
  } catch (error) {
    container.replaceChildren(errorState(error, refresh),
      el("div", { style: "margin-top:10px" }, el("a", { class: "btn ghost small", href: "#/scenes" }, "← All Scenes")));
  }
}

function draw() {
  const s = data.scene;
  const sum = data.summary;
  const readiness = { blocked: ["s-red", "Blocked"], needs_work: ["s-amber", "Needs Work"],
    in_progress: ["s-blue", "In Progress"], generation_ready: ["s-green", "Generation Ready"] }[sum.readiness] || ["s-gray", "—"];

  container.replaceChildren(
    el("div", { class: "hero-band" },
      el("div", { style: "flex:1; min-width:280px" },
        el("h2", {}, el("span", { class: "pill s-outline", style: "margin-right:10px" }, s.scene_ref || "Scene"), s.title || "Untitled"),
        el("p", {}, s.summary || s.story_purpose || "No summary."),
        el("div", { style: "display:flex; gap:8px; margin-top:10px; flex-wrap:wrap" },
          statusPill(s.status),
          data.location ? el("span", { class: "pill s-outline" }, `📍 ${data.location.name}`) : el("span", { class: "pill s-red" }, "no location"),
          s.time_of_day ? el("span", { class: "pill s-outline" }, s.time_of_day) : null,
          s.weather ? el("span", { class: "pill s-outline" }, s.weather) : null,
          el("span", { class: `pill ${readiness[0]}` }, readiness[1]),
          el("span", { class: "pill s-outline" }, `${sum.shot_count} shots · ~${Math.round(sum.estimated_duration)}s`),
          sum.blocking_errors ? el("span", { class: "pill s-red" }, `${sum.blocking_errors} errors`) : null,
          sum.ready_for_generation ? el("span", { class: "pill s-green" }, `${sum.ready_for_generation} ready`) : null)),
      el("div", { style: "display:flex; gap:7px; flex-wrap:wrap; align-items:flex-start" },
        el("button", { class: "btn", onclick: buildBoard }, el("span", { html: ICONS.film }), "Build Storyboard"),
        el("button", { class: "btn", onclick: () => addShotModal() }, el("span", { html: ICONS.plus }), "Add Shot"),
        el("button", { class: "btn", onclick: validateScene }, el("span", { html: ICONS.check }), "Validate Scene"),
        s.status !== "approved" && s.status !== "ready_for_storyboard"
          ? el("button", { class: "btn", onclick: approveScene }, "Approve Scene") : null,
        el("a", { class: "btn ghost", href: `#/episodes/${s.episode_id}?scene=${s.id}`, style: "text-decoration:none" }, "Episode ↗"))),
    infoCards(),
    el("div", { style: "display:flex; align-items:center; gap:10px; margin:18px 0 12px" },
      el("h3", { style: "margin:0" }, "Storyboard"),
      el("span", { class: "muted", style: "font-size:12px" }, "drag cards to reorder"),
      el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${data.shots.length} shots`),
      el("button", { class: "btn small ghost", onclick: prepareForGenerationInfo }, "Prepare for Generation")),
    boardGrid());
}

function infoCards() {
  const castCard = el("div", { class: "card" }, el("h3", {}, "Cast"));
  if (!data.cast.length) castCard.append(el("div", { class: "muted", style: "font-size:12.5px" }, "No characters cast in the scene."));
  for (const link of data.cast) {
    const ch = link.character;
    if (!ch) continue;
    castCard.append(el("div", { style: "padding:6px 0; border-bottom:1px solid rgba(38,49,42,.5)" },
      el("b", {}, ch.name), " ",
      ch.approval_status === "approved" ? statusPill("approved", "canon") : statusPill(ch.approval_status),
      el("div", { class: "muted", style: "font-size:11.5px; margin-top:2px" },
        ((ch.never_changes || []).length ? `never changes: ${ch.never_changes.length} rules` : "no never-change rules recorded"))));
  }
  const propsCard = el("div", { class: "card" }, el("h3", {}, "Scene Props"));
  if (!data.scene_props.length) propsCard.append(el("div", { class: "muted", style: "font-size:12.5px" }, "No props linked."));
  for (const link of data.scene_props) {
    if (!link.prop) continue;
    propsCard.append(el("div", { style: "padding:6px 0" }, el("b", {}, link.prop.name), " ",
      link.prop.approval_status === "approved" ? statusPill("approved") : statusPill(link.prop.approval_status, pretty(link.prop.approval_status))));
  }
  const scriptCard = el("div", { class: "card" }, el("h3", {}, "Script", el("span", { class: "pill s-outline" }, String(data.script.length))));
  if (!data.script.length) scriptCard.append(el("div", { class: "muted", style: "font-size:12.5px" }, "No lines."));
  for (const element of data.script.slice(0, 8)) {
    const speaker = element.element_type === "dialogue" ? (element.character_id || element.character_name || "?") : element.narrator_name || null;
    scriptCard.append(el("div", { style: `font-size:12px; margin-bottom:4px; ${element.element_type === "dialogue" || element.element_type === "narration" ? "padding-left:14px" : ""}` },
      speaker ? el("b", {}, String(speaker).slice(0, 24) + ": ") : null, element.text.slice(0, 90)));
  }
  const continuityCard = el("div", { class: "card" }, el("h3", {}, "Continuity"),
    el("div", { style: "font-size:12.5px; white-space:pre-wrap" },
      data.scene.continuity_notes || el("span", { class: "muted" }, "No scene continuity notes."),
      el("div", { class: "callout", style: "margin-top:10px; font-size:11.5px; padding:8px 10px" },
        "ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, SANDALS, SLIPPERS, OR ANY OTHER FOOTWEAR.")));
  return el("div", { class: "grid cols-4", style: "margin-top:2px" }, castCard, propsCard, scriptCard, continuityCard);
}

/* ---------------- storyboard grid with drag & drop ---------------- */
function boardGrid() {
  if (!data.shots.length) {
    return emptyState({
      big: "No shots yet",
      small: "“Build Storyboard” drafts shots from the scene script (deterministic, fully editable), or add shots manually.",
      actions: [
        el("button", { class: "btn small primary", onclick: buildBoard }, "Build Storyboard"),
        el("button", { class: "btn small", onclick: () => addShotModal() }, "Add Shot"),
      ],
    });
  }
  const grid = el("div", { class: "grid cols-auto" });
  data.shots.forEach((shot) => grid.append(shotCard(shot)));
  return grid;
}

function shotCard(shot) {
  const img = shot.storyboard_image_url;
  const card = el("div", {
    class: "asset-tile", draggable: "true",
    style: "cursor:grab",
    onclick: (e) => { if (!card.dataset.dragged) shotModal(shot); },
    ondragstart: (e) => { e.dataTransfer.setData("text/plain", String(shot.id)); card.style.opacity = ".4"; card.dataset.dragging = "1"; },
    ondragend: () => { card.style.opacity = "1"; delete card.dataset.dragging; },
    ondragover: (e) => e.preventDefault(),
    ondrop: async (e) => {
      e.preventDefault(); e.stopPropagation();
      const draggedId = Number(e.dataTransfer.getData("text/plain"));
      if (!draggedId || draggedId === shot.id) return;
      const ids = data.shots.map((s) => s.id);
      const from = ids.indexOf(draggedId);
      const to = ids.indexOf(shot.id);
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      try {
        await postJSON(`/api/scenes/${sceneId}/shots/reorder`, { shot_ids: ids });
        toast("Shots reordered.", "ok"); refresh();
      } catch (error) { toast(error.message, "error"); }
    },
  },
    el("div", { class: "asset-thumb" },
      img ? el("img", { src: img, alt: shot.title || "", loading: "lazy" })
        : el("span", { class: "file-icon" }, "🎬"),
      el("div", { class: "flags" },
        shot.validation?.blocking_errors ? el("span", { class: "pill s-red", style: "padding:1px 6px" }, "errors") : null,
        shot.status === "ready_for_generation" ? el("span", { class: "pill s-green", style: "padding:1px 6px" }, "READY") : null)),
    el("div", { class: "asset-meta" },
      el("div", { class: "t" }, `${shot.shot_ref || `#${shot.number}`} · ${shot.title || "Untitled"}`),
      el("div", { class: "s" }, [pretty(shot.shot_type || "type?"), pretty(shot.camera_movement || "—"), `${shot.duration_seconds || 0}s`].join(" · ")),
      el("div", { class: "s" }, (shot.cast || []).map((l) => l.character?.name).filter(Boolean).join(", ") || "no cast"),
      shot.description ? el("div", { class: "s", style: "white-space:normal; -webkit-line-clamp:2; display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden" }, shot.description) : null,
      el("div", { style: "display:flex; gap:5px; margin-top:7px; flex-wrap:wrap; align-items:center" },
        statusPill(shot.status),
        shot.version_count > 1 ? el("span", { class: "pill s-outline" }, `v${shot.version_count}`) : null,
        (shot.dialogue || []).length ? el("span", { class: "pill s-outline" }, `${(shot.dialogue || []).length} lines`) : null)));
  return card;
}

/* ---------------- actions ---------------- */
async function buildBoard() {
  const result = await postJSON(`/api/scenes/${sceneId}/storyboard/build`);
  if (result.created > 0) toast(`Drafted ${result.created} shots from the script — every shot is editable.`, "ok", "Storyboard built");
  else toast(result.note || "No shots created.", "info");
  refresh();
}

async function approveScene() {
  try {
    await patchJSON(`/api/scenes/${sceneId}`, { status: "approved" });
    toast("Scene approved.", "ok"); refresh();
  } catch (error) { toast(error.message, "error"); }
}

async function validateScene() {
  let allPass = true;
  const lines = [];
  for (const shot of data.shots) {
    const v = await getJSON(`/api/shots/${shot.id}/validate`);
    if (!v.passed) allPass = false;
    lines.push(`${shot.shot_ref}: ${v.blocking_errors} errors, ${v.open_warnings} warnings${v.passed ? "" : " — needs work"}`);
  }
  openModal({
    title: "Scene validation",
    sub: allPass ? "All shots pass blocking checks." : "Some shots have blocking errors.",
    body: el("div", {},
      el("pre", { class: "code" }, lines.join("\n") || "No shots to validate."),
      el("div", { class: "callout info", style: "font-size:12px; margin-top:10px" },
        "Warnings can be overridden per shot with a written explanation. Errors must be fixed or overridden before approval.")),
    actions: [{ label: "Close" }, { label: "Re-validate", onClick: () => { document.querySelector(".modal-backdrop")?.remove(); validateScene(); } }],
  });
}

function prepareForGenerationInfo() {
  openModal({
    title: "Prepare for Generation",
    sub: "How shots become Phase-5 ready",
    body: el("div", { style: "font-size:13px; line-height:1.8" },
      "1 · Approve the scene", el("br", {}),
      "2 · Build/edit shots with camera direction + cast", el("br", {}),
      "3 · Approve each shot (fix or override warnings)", el("br", {}),
      "4 · Mark ", el("b", {}, "Ready for Generation"), " — this assembles the provider-neutral package", el("br", {}),
      "5 · Phase 5 submits the package to a configured video provider", el("br", {}), el("br", {}),
      el("span", { class: "muted" }, `Currently: ${data.summary.ready_for_generation} of ${data.summary.shot_count} shots ready.`)),
    actions: [{ label: "Close" }],
  });
}

/* ---------------- shot create ---------------- */
function addShotModal() {
  const title = el("input", { type: "text", placeholder: "e.g. Berry ricochet close-up" });
  const description = el("textarea", { placeholder: "What happens in this shot" });
  const typeSel = el("select", {}, SHOT_TYPES.map(([v, l]) => el("option", { value: v }, l)));
  const angleSel = el("select", {}, el("option", { value: "" }, "—"), ANGLES.map((a) => el("option", { value: a }, pretty(a))));
  const moveSel = el("select", {}, el("option", { value: "" }, "—"), MOVES.map((m) => el("option", { value: m }, pretty(m))));
  const notes = el("input", { type: "text", placeholder: "Natural-language camera direction…" });
  const duration = el("input", { type: "number", value: "6", min: "1", max: "60", step: "0.5" });
  openModal({
    title: "Add Shot", wide: true,
    sub: `Scene ${data.scene.scene_ref || sceneId} — casting is inherited from the scene.`,
    body: el("div", {},
      el("div", { class: "form-row" }, field("Title", title), field("Duration (s)", duration)),
      field("Description", description),
      el("div", { class: "form-row-3" }, field("Shot type", typeSel), field("Camera angle", angleSel), field("Camera movement", moveSel)),
      field("Camera notes", notes)),
    actions: [
      { label: "Cancel" },
      { label: "Create Draft", kind: "primary", onClick: async (e, close) => {
        await postJSON("/api/shots", {
          scene_id: sceneId, title: title.value.trim() || null,
          description: description.value.trim() || null,
          shot_type: typeSel.value, camera_angle: angleSel.value || null,
          camera_movement: moveSel.value || null, camera_notes: notes.value.trim() || null,
          duration_seconds: parseFloat(duration.value) || 6,
        });
        close(); toast("Shot created as draft.", "ok"); refresh();
      } },
    ],
  });
}

/* ---------------- shot detail modal ---------------- */
function shotModal(shot) {
  let current = shot;
  let active = "shot";
  const body = el("div", {});
  const tabBarEl = tabBar([
    { id: "shot", label: "Shot" },
    { id: "cast", label: "Cast & Props", count: (current.cast || []).length + (current.props || []).length },
    { id: "refs", label: "References & Frames", count: (current.references || []).length },
    { id: "approve", label: "Validation & Approval" },
    { id: "versions", label: "Versions", count: current.version_count },
    { id: "generate", label: "Generate" },
  ], active, (id) => { active = id; renderTab(); });

  async function redraw() {
    current = await getJSON(`/api/shots/${current.id}`);
    document.querySelector(".modal-backdrop")?.remove();
    shotModal(current);
  }

  function renderTab() {
    body.replaceChildren();
    if (active === "shot") shotTab();
    else if (active === "cast") castTab();
    else if (active === "refs") refsTab();
    else if (active === "approve") approveTab();
    else if (active === "generate") generateTab();
    else versionsTab();
  }

  const saveFields = (inputs, map) => el("button", {
    class: "btn small primary", style: "margin-top:8px",
    onclick: async () => {
      const payload = {};
      for (const [key, node] of Object.entries(inputs)) payload[key] = node.value !== null && node.value !== undefined ? (node.value.trim ? (node.value.trim() || null) : node.value) : null;
      for (const k of Object.keys(payload)) if (map && map[k] === "number") payload[k] = parseFloat(payload[k]) || null;
      await patchJSON(`/api/shots/${current.id}`, payload);
      toast("Shot saved.", "ok"); redraw();
    },
  }, "Save Shot");

  function shotTab() {
    const mk = (v, ph) => el("textarea", { value: v || "", rows: 2, placeholder: ph || "" });
    const mki = (v) => el("input", { type: "text", value: v || "" });
    const sel = (opts, v) => el("select", {}, el("option", { value: "" }, "—"), opts.map((o) => el("option", { value: o, selected: v === o ? "" : null }, pretty(o))));
    const dur = el("input", { type: "number", value: String(current.duration_seconds ?? 6), min: "1", step: "0.5" });
    const inputs = {
      title: mki(current.title), description: mk(current.description),
      shot_type: sel(SHOT_TYPES.map(([v]) => v), current.shot_type),
      camera_angle: sel(ANGLES, current.camera_angle), camera_movement: sel(MOVES, current.camera_movement),
      camera_notes: mk(current.camera_notes, "Natural-language direction"), lens_framing: mk(current.lens_framing),
      composition: mk(current.composition), subject_position: mk(current.subject_position),
      character_action: mk(current.character_action), facial_expression: mk(current.facial_expression),
      environment_action: mk(current.environment_action), lighting: mk(current.lighting),
      weather: mki(current.weather), transition: mki(current.transition), visual_style: mk(current.visual_style),
      narration: mk(current.narration), music: mki(current.music),
      continuity_notes: mk(current.continuity_notes),
      character_state_notes: mk(current.character_state_notes, "State carried from previous shots"),
      prop_state_notes: mk(current.prop_state_notes), location_state_notes: mk(current.location_state_notes),
    };
    body.append(
      el("div", { class: "form-row" }, field("Title", inputs.title), field("Status", el("div", { style: "padding-top:8px" }, statusPill(current.status)))),
      field("Description", inputs.description),
      el("div", { class: "form-row-3" }, field("Shot type", inputs.shot_type), field("Camera angle", inputs.camera_angle), field("Camera movement", inputs.camera_movement)),
      el("div", { class: "form-row" }, field("Camera notes (natural language)", inputs.camera_notes), field("Duration (s)", dur)),
      el("div", { class: "form-row" }, field("Lens / framing", inputs.lens_framing), field("Subject position", inputs.subject_position)),
      field("Composition", inputs.composition),
      el("div", { class: "form-row-3" }, field("Character action", inputs.character_action), field("Facial expression", inputs.facial_expression), field("Environment action", inputs.environment_action)),
      el("div", { class: "form-row-3" }, field("Lighting", inputs.lighting), field("Weather", inputs.weather), field("Transition", inputs.transition)),
      field("Visual style", inputs.visual_style),
      el("div", { class: "form-row" }, field("Narration", inputs.narration), field("Music", inputs.music)),
      el("h3", { style: "margin:14px 0 6px; font-size:13px" }, "Continuity & dependencies"),
      field("Continuity notes", inputs.continuity_notes),
      el("div", { class: "form-row-3" }, field("Character state", inputs.character_state_notes), field("Prop state", inputs.prop_state_notes), field("Location state", inputs.location_state_notes)),
      saveFields({ ...inputs, duration_seconds: dur }, { duration_seconds: "number" }));
  }

  function castTab() {
    const wrap = el("div", {});
    for (const link of current.cast || []) {
      const ch = link.character;
      if (!ch) continue;
      wrap.append(el("div", { class: "card", style: "margin-bottom:9px; padding:11px 13px" },
        el("div", { style: "display:flex; align-items:center; gap:8px" },
          el("b", {}, ch.name),
          ch.approval_status === "approved" ? statusPill("approved", "canon") : statusPill(ch.approval_status, pretty(ch.approval_status)),
          el("span", { class: "muted", style: "font-size:11.5px" }, link.role_in_shot || ""),
          el("button", { class: "btn small danger", style: "margin-left:auto", onclick: async () => {
            await fetch(`/api/shots/${current.id}/cast/${ch.id}`, { method: "DELETE" });
            toast("Removed from shot.", "ok"); redraw();
          } }, "Remove"),
          el("button", { class: "btn small ghost", onclick: () => viewCharacterInfo(ch.id) }, "References →")),
        link.expression_note || link.action_note ? el("div", { class: "muted", style: "font-size:11.5px; margin-top:5px" },
          [link.action_note && `action: ${link.action_note}`, link.expression_note && `expression: ${link.expression_note}`].filter(Boolean).join(" · ")) : null));
    }
    const inShot = new Set((current.cast || []).map((l) => l.character?.id));
    wrap.append(el("div", { style: "display:flex; gap:6px; flex-wrap:wrap; margin:10px 0" },
      characters.filter((ch) => !inShot.has(ch.id)).map((ch) =>
        el("button", { class: "btn small ghost", onclick: async () => {
          await postJSON(`/api/shots/${current.id}/cast`, { character_id: ch.id });
          toast(`${ch.name} added — their approved references will be used.`, "ok"); redraw();
        } }, el("span", { html: ICONS.plus }), ch.name))));
    const propsCard = el("div", { class: "card", style: "margin-top:10px" }, el("h3", {}, "Props in shot"));
    for (const link of current.props || []) {
      if (!link.prop) continue;
      propsCard.append(el("div", { style: "display:flex; gap:8px; align-items:center; padding:6px 0" },
        el("b", {}, link.prop.name),
        link.prop.approval_status === "approved" ? statusPill("approved") : statusPill(link.prop.approval_status, pretty(link.prop.approval_status)),
        el("button", { class: "btn small danger", style: "margin-left:auto", onclick: async () => {
          await fetch(`/api/shots/${current.id}/props/${link.prop.id}`, { method: "DELETE" });
          toast("Prop removed.", "ok"); redraw();
        } }, "Remove")));
    }
    const inProps = new Set((current.props || []).map((l) => l.prop?.id));
    propsCard.append(el("div", { style: "display:flex; gap:6px; flex-wrap:wrap; margin-top:8px" },
      propsList.filter((p) => !inProps.has(p.id)).map((p) =>
        el("button", { class: "btn small ghost", onclick: async () => {
          await postJSON(`/api/shots/${current.id}/props`, { prop_id: p.id });
          toast(`${p.name} linked.`, "ok"); redraw();
        } }, el("span", { html: ICONS.plus }), p.name))));
    body.append(el("div", {}, el("h3", { style: "margin:2px 0 6px; font-size:13px" }, "Cast"), wrap, propsCard));
  }

  async function viewCharacterInfo(characterId) {
    const profile = await getJSON(`/api/scenes/${sceneId}/cast/${characterId}/profile`);
    openModal({
      title: `${profile.character.name} — approved production references`, wide: true,
      sub: "Exactly what the shot's generation package will include for this character.",
      body: el("div", {},
        el("div", { class: "callout", style: "font-size:11.5px; margin-bottom:10px" },
          (profile.character.never_changes || []).slice(0, 3).join(" · ")),
        profile.approved_references.length
          ? el("ul", { style: "margin:0; padding-left:16px; font-size:12.5px" },
              ...profile.approved_references.map((r) => el("li", {}, `${pretty(r.purpose)} — ${r.label}`)))
          : el("div", { class: "callout", style: "font-size:12px" }, "⚠ No approved reference images yet — approve references in Characters first.")),
      actions: [{ label: "Close" }],
    });
  }

  function refsTab() {
    const list = el("div", {});
    for (const ref of current.references || []) {
      const isImage = (ref.asset?.mime_type || "").startsWith("image/");
      list.append(el("div", { class: "card", style: "display:flex; gap:11px; align-items:center; margin-bottom:8px; padding:9px 12px" },
        el("div", { style: "width:64px; height:42px; border-radius:6px; overflow:hidden; background:#0b0e0c; display:grid; place-items:center; flex:0 0 auto" },
          isImage ? el("img", { src: `/api/assets/${ref.asset.id}/file`, style: "width:100%; height:100%; object-fit:cover" }) : el("span", {}, "🎞")),
        el("div", { style: "flex:1; min-width:0" },
          el("b", {}, ref.label || ref.asset?.title || "Reference"),
          el("div", { class: "muted", style: "font-size:11.5px" },
            `${pretty(ref.purpose)} · ${ref.asset?.repo_path?.split("/").pop() || ""} · ${fmtBytes(ref.asset?.byte_size)}`)),
        el("button", { class: "btn small danger", onclick: async () => {
          await fetch(`/api/shots/${current.id}/references/${ref.id}`, { method: "DELETE" });
          toast("Reference removed.", "ok"); redraw();
        } }, el("span", { html: ICONS.x }))));
    }
    const purposeSel = el("select", {}, REF_PURPOSES.map(([v, l]) => el("option", { value: v }, l)));
    const assetSel = el("select", {}, el("option", { value: "" }, "— Choose library asset —"),
      assets.map((a) => el("option", { value: a.id }, `${a.title} (${a.status})`)));
    const fileInput = el("input", { type: "file", accept: "image/*" });
    const attachButton = el("button", {
      class: "btn small", style: "margin-bottom:12px",
      onclick: async () => {
        if (!assetSel.value) return toast("Choose a library asset.", "warn");
        try {
          await postJSON(`/api/shots/${current.id}/references`, { asset_id: Number(assetSel.value), purpose: purposeSel.value });
          toast("Reference attached.", "ok"); redraw();
        } catch (error) {
          toast(error.message, "error", "Attach refused");
        }
      },
    }, "Attach from Library");
    const uploadButton = el("button", {
      class: "btn small ghost",
      onclick: async () => {
        const file = fileInput.files[0];
        if (!file) return toast("Choose a file.", "warn");
        const form = new FormData();
        form.append("file", file);
        form.append("category", "images");
        form.append("title", `${current.shot_ref || "Shot"} board image`);
        form.append("provenance", "meta_ai");
        const pid = localStorage.getItem("studio.projectId");
        if (pid) form.append("project_id", pid);
        const response = await fetch("/api/assets/upload", { method: "POST", body: form });
        const asset = await response.json();
        await postJSON(`/api/shots/${current.id}/references`, { asset_id: asset.id, purpose: "storyboard_image", label: file.name });
        toast("Storyboard image uploaded and attached (draft).", "ok"); redraw();
      },
    }, el("span", { html: ICONS.upload }), "Upload & Attach as Storyboard Image");
    const uploadSection = el("div", { style: "border-top:1px solid var(--border); margin:10px 0; padding-top:10px" },
      field("…or upload a Meta AI storyboard image", fileInput, "Uploads start as draft; approve in Assets before using as a frame reference"),
      uploadButton);
    body.append(el("div", {},
      el("div", { class: "callout info", style: "font-size:11.5px; margin-bottom:10px" },
        "Meta AI workflow: generate artwork externally → import below (or via the Asset Library) → approve → attach. Frame references (first/last/key) must use approved assets."),
      list,
      el("div", { class: "card" },
        el("h3", {}, "Attach reference"),
        el("div", { class: "form-row" }, field("Purpose", purposeSel), field("From library", assetSel)),
        attachButton,
        uploadSection)));
  }

  function approveTab() {
    const holder = el("div", {});
    const run = async () => {
      holder.replaceChildren(loadingState("Validating…"));
      const v = await getJSON(`/api/shots/${current.id}/validate`);
      holder.replaceChildren();
      if (!v.findings.length) holder.append(el("div", { class: "callout green", style: "font-size:12.5px" }, el("b", {}, "All checks pass. "), "No warnings or errors."));
      for (const f of v.findings) {
        const severityClass = f.severity === "error" ? "callout" : f.severity === "warning" ? "callout" : "muted";
        const card = el("div", {
          class: severityClass,
          style: `margin-bottom:8px; font-size:12.5px; display:flex; gap:9px; align-items:flex-start; ${f.severity === "info" ? "border:1px dashed var(--border); border-radius:8px; padding:8px 10px" : ""}`,
        },
          el("div", { style: "flex:1" },
            el("b", {}, f.severity === "error" ? "⛔ " : f.severity === "warning" ? "⚠ " : "ℹ ", pretty(f.severity), " · ", f.key),
            el("div", {}, f.message),
            f.overridden ? el("div", { style: "color:var(--moss); margin-top:4px; font-size:11.5px" },
              "✓ Overridden: ", f.override_explanation || "") : null),
          !f.overridden && f.severity !== "info"
            ? el("button", { class: "btn small ghost", onclick: () => overrideModal(f) }, "Override…") : null);
        holder.append(card);
      }
    };
    const overrideModal = (f) => {
      const explanation = el("textarea", { placeholder: "Why this warning is acceptable (recorded in the audit trail)" });
      openModal({
        title: "Override warning",
        sub: f.message,
        body: field("Explanation *", explanation),
        actions: [
          { label: "Cancel" },
          { label: "Record Override", kind: "danger", onClick: async (e, close) => {
            if (explanation.value.trim().length < 3) return toast("Write an explanation.", "warn");
            await postJSON(`/api/shots/${current.id}/overrides`, { check_key: f.key, explanation: explanation.value.trim() });
            close(); toast("Override recorded.", "ok"); run();
          } },
        ],
      });
    };
    run();
    body.append(el("div", {},
      el("div", { style: "display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap" },
        el("button", { class: "btn small", onclick: run }, el("span", { html: ICONS.refresh }), "Re-validate"),
        el("button", { class: "btn small primary", onclick: async () => {
          try {
            await postJSON(`/api/shots/${current.id}/approve`);
            toast("Shot approved — version snapshotted.", "ok"); redraw();
          } catch (error) {
            const detail = error.detail || {};
            toast(detail.message || error.message, "error", "Approval blocked");
          }
        } }, el("span", { html: ICONS.check }), "Approve Shot"),
        el("button", { class: "btn small", style: "border-color:#4a8a5e", onclick: async () => {
          try {
            const result = await postJSON(`/api/shots/${current.id}/ready-for-generation`);
            toast("Shot is READY FOR GENERATION — package assembled for Phase 5.", "ok");
            packageModal(result.generation_package);
            redraw();
          } catch (error) {
            const detail = error.detail || {};
            toast(detail.message || error.message, "warn", "Not ready");
          }
        } }, "Mark Ready for Generation"),
        el("button", { class: "btn small ghost", onclick: async () => {
          packageModal(await getJSON(`/api/shots/${current.id}/generation-package`));
        } }, "View Generation Package")),
      holder));
  }

  async function versionsTab() {
    body.replaceChildren(loadingState("Loading versions…"));
    const data2 = await getJSON(`/api/shots/${current.id}/versions`);
    body.replaceChildren();
    if (!data2.versions.length) {
      body.append(el("div", { class: "muted", style: "font-size:12.5px" },
        "No versions yet — approving a shot snapshots it automatically."));
    }
    for (const v of data2.versions) {
      body.append(el("div", { class: "card", style: "margin-bottom:8px; padding:10px 13px; display:flex; gap:10px; align-items:center" },
        el("b", { style: "width:36px" }, `v${v.version_number}`),
        v.label ? el("span", { class: "pill s-purple" }, v.label) : null,
        statusPill(v.status, pretty(v.status)),
        v.is_current ? el("span", { class: "pill s-green" }, "current") : null,
        el("span", { class: "muted", style: "font-size:11.5px; margin-left:auto" }, (v.snapshot || {}).captured_at?.slice(0, 16).replace("T", " ") || ""),
        el("button", { class: "btn small ghost", onclick: async () => {
          await postJSON(`/api/shots/${current.id}/versions/${v.id}/restore`);
          toast(`Restored v${v.version_number} — review re-opened, snapshot kept.`, "ok"); redraw();
        } }, "Restore")));
    }
    body.append(el("button", { class: "btn small", style: "margin-top:6px", onclick: async () => {
      await postJSON(`/api/shots/${current.id}/versions`, {});
      toast("Current state snapshotted as a new version.", "ok"); redraw();
    } }, el("span", { html: ICONS.plus }), "Snapshot Current State"));
  }

  function autoCaps(providerList) {
    const available = providerList.filter((p) => p.status !== "not_configured" && p.caps);
    if (!available.length) return null;
    const intersect = (lists) => {
      if (!lists.length) return [];
      return lists.reduce((acc, list) => acc.filter((v) => list.includes(v)));
    };
    return {
      durations: intersect(available.map((p) => p.caps.durations || [])),
      resolutions: intersect(available.map((p) => p.caps.resolutions || [])),
      aspect_ratios: intersect(available.map((p) => p.caps.aspect_ratios || [])),
      seed_support: available.every((p) => p.caps.seed_support),
      audio_generation: available.every((p) => p.caps.audio_generation),
    };
  }

  async function generateTab() {
    body.replaceChildren(loadingState("Loading providers…"));
    let providers = [];
    try {
      providers = (await getJSON("/api/providers")).providers.filter((p) => p.kind === "video");
    } catch (error) {
      body.replaceChildren(errorState(error));
      return;
    }
    const selectable = [{ key: "auto", label: "Automatic (capability match)" },
      ...providers.map((p) => ({ key: p.key, label: (p.is_test ? "[TEST] " : "") + p.display_name + (p.status === "not_configured" ? " — not configured" : ""), provider: p }))];
    const providerSel = el("select", { onchange: () => updateSettingsUI() },
      selectable.map((option) => el("option", { value: option.key }, option.label)));
    const providerInfo = el("div", { class: "muted", style: "font-size:11.5px; margin-top:5px" });
    const settingsHolder = el("div", {});
    const previewHolder = el("div", {});

    function currentProvider() {
      return selectable.find((s) => s.key === providerSel.value) || null;
    }

    function updateSettingsUI() {
      const choice = currentProvider();
      settingsHolder.replaceChildren();
      providerInfo.replaceChildren();
      if (!choice) return;
      if (choice.key === "auto") {
        providerInfo.append("Chooses a configured provider whose capabilities match this shot. No cost/performance claims — selection is documented per job.");
      } else {
        const p = choice.provider;
        providerInfo.append(p.status === "not_configured"
          ? `Not configured — set ${p.missing_env.join(", ")} server-side. Jobs can still be drafted but submission will refuse honestly.`
          : `Status: ${pretty(p.status)}.`);
      }
      const caps = choice.key === "auto" ? autoCaps(providers) : choice.provider?.caps;
      const useCaps = caps || { durations: [], resolutions: [], aspect_ratios: ["16:9", "9:16"], seed_support: false, audio_generation: false };
      const durSel = el("select", {},
        (useCaps.durations?.length ? useCaps.durations : [4, 5, 6, 8, 10]).map((d) =>
          el("option", { value: String(d), selected: Number(d) === (current.duration_seconds || 6) ? "" : null }, `${d}s`)));
      const resSel = el("select", {},
        (useCaps.resolutions?.length ? useCaps.resolutions : ["720p"]).map((r) => el("option", { value: r }, r)));
      const arSel = el("select", {},
        (useCaps.aspect_ratios?.length ? useCaps.aspect_ratios : ["16:9", "9:16"]).map((a) =>
          el("option", { value: a, selected: a === "16:9" ? "" : null }, a)));
      const seedInput = el("input", { type: "number", placeholder: "—" });
      if (!useCaps.seed_support) seedInput.disabled = true;
      const audioSel = el("select", {}, el("option", { value: "" }, "provider default"),
        el("option", { value: "true" }, "generate audio"), el("option", { value: "false" }, "no audio"));
      if (!useCaps.audio_generation) audioSel.disabled = true;
      settingsHolder.append(
        el("div", { class: "form-row-3" },
          field("Duration", durSel), field("Resolution", resSel), field("Aspect ratio", arSel)),
        el("div", { class: "form-row" },
          field("Seed" + (useCaps.seed_support ? "" : " (unsupported)"), seedInput),
          field("Audio" + (useCaps.audio_generation ? "" : " (unsupported)"), audioSel)));
      settingsHolder._collect = () => {
        const payload = { duration_seconds: parseFloat(durSel.value), resolution: resSel.value, aspect_ratio: arSel.value };
        if (seedInput.value && !seedInput.disabled) payload.seed = parseInt(seedInput.value, 10);
        if (audioSel.value && !audioSel.disabled) payload.generate_audio = audioSel.value === "true";
        return payload;
      };
    }

    const refreshPreview = async () => {
      previewHolder.replaceChildren(loadingState("Translating request…"));
      const settings = settingsHolder._collect ? settingsHolder._collect() : {};
      try {
        const preview = await getJSON(`/api/shots/${current.id}/preview-request?provider_key=${providerSel.value}&settings=${encodeURIComponent(JSON.stringify(settings))}`);
        previewHolder.replaceChildren();
        if (!preview.provider) {
          previewHolder.append(el("div", { class: "callout", style: "font-size:12px" },
            el("b", {}, "No provider available. "), (preview.errors || []).join(" ")));
          return;
        }
        if (preview.errors?.length) {
          previewHolder.append(el("div", { class: "callout", style: "font-size:12px; margin-bottom:8px" },
            el("b", {}, "Capability errors: "), preview.errors.join("; ")));
        }
        const refs = preview.references || {};
        if ((refs.submitted || []).length || (refs.skipped || []).length) {
          previewHolder.append(el("div", { class: "card", style: "margin-bottom:8px; padding:10px 13px" },
            el("b", { style: "fontSize:12px" }, `References — ${(refs.submitted || []).length} submitted, ${(refs.skipped || []).length} skipped`),
            el("ul", { style: "margin:6px 0 0 16px; font-size:11.5px" },
              ...(refs.submitted || []).map((r) => el("li", {}, `✓ ${r.purpose} — ${r.label || r.asset_id}`)),
              ...(refs.skipped || []).map((r) => el("li", { style: "color:var(--amber)" }, `⚠ ${r.purpose} — ${r.reason}`)))));
        }
        previewHolder.append(el("details", {},
          el("summary", { style: "cursor:pointer; font-size:12px; margin-bottom:6px" }, "Exact provider-translated request (nothing submitted yet)"),
          el("pre", { class: "code", style: "max-height:260px" }, JSON.stringify(preview.translated, null, 2))));
      } catch (error) {
        previewHolder.replaceChildren(errorState(error));
      }
    };

    const generateNow = async () => {
      const settings = settingsHolder._collect ? settingsHolder._collect() : {};
      try {
        const job = await postJSON(`/api/shots/${current.id}/generate`, { provider_key: providerSel.value, settings });
        const submit = await postJSON(`/api/generation/jobs/${job.id}/submit`);
        toast(submit.status.startsWith("fail") ? `Submission failed: ${submit.error_code}` :
          `Generation submitted (${pretty(submit.status)}) — watch the Generation Queue.`, "ok", "Generating");
        document.querySelector(".modal-backdrop")?.remove();
        location.hash = "#/queue";
      } catch (error) {
        const detail = error.detail || {};
        toast(detail.message || error.message, "error", "Generation refused");
      }
    };

    updateSettingsUI();
    body.replaceChildren(
      el("div", {},
        el("div", { class: "callout info", style: "font-size:11.5px; margin-bottom:12px" },
          "The universal generation package stays provider-neutral; the adapter translates it. Review the exact request before submitting. Approved references only."),
        field("Provider", providerSel), providerInfo,
        el("div", { style: "height:10px" }), settingsHolder,
        el("div", { style: "display:flex; gap:8px; margin:12px 0" },
          el("button", { class: "btn small ghost", onclick: refreshPreview }, el("span", { html: ICONS.refresh }), "Preview exact request"),
          el("button", { class: "btn small primary", onclick: generateNow }, el("span", { html: ICONS.spark }), "Generate now")),
        previewHolder));
  }

  openModal({
    title: `${current.shot_ref || `Shot ${current.number}`} — ${current.title || "Untitled"}`,
    sub: `${data.scene.scene_ref || "Scene"} · ${pretty(current.shot_type || "no type")} · ${current.duration_seconds}s`,
    wide: true,
    body: el("div", {}, tabBarEl, body),
    actions: [{ label: "Close" }],
  });
  renderTab();
}

function packageModal(pkg) {
  openModal({
    title: "Generation package (Phase 5 payload)", wide: true,
    sub: `${pkg.shot.shot_ref || "Shot"} — ${pkg.ready_for_generation ? "READY" : "not ready yet"} · provider-neutral assembly`,
    body: el("div", {},
      el("div", { class: "callout green", style: "font-size:12px; margin-bottom:10px" }, pkg.prompt_package.continuity_requirements.barefoot_rule),
      el("div", { class: "muted", style: "font-size:11.5px; margin-bottom:8px" }, pkg.provider_notes),
      el("pre", { class: "code", style: "max-height:420px" }, JSON.stringify(pkg, null, 2))),
    actions: [{ label: "Close" }],
  });
}
