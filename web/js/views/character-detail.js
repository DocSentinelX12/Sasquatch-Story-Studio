// Character detail — Character Bible workspace with tabs.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, charAvatar, tabBar, textToList, listFromText, fmtWhen,
} from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

const PURPOSES = ["primary", "full_body", "face", "expression", "pose", "side_view", "back_view", "action_pose", "outfit", "prop_reference", "other"];
const REL_KINDS = ["friend", "family", "enemy", "companion", "neighbor", "recurring", "mentor", "other"];

let container;
let characterId;
let data = null;
let activeTab = "overview";

export async function render(c, id, params = new URLSearchParams()) {
  container = c;
  characterId = id;
  activeTab = params.get("tab") || "overview";
  await refresh();
}

async function refresh() {
  container.replaceChildren(loadingState("Loading character…"));
  try {
    data = await getJSON(`/api/characters/${characterId}`);
    renderAll();
  } catch (error) {
    container.replaceChildren(
      errorState(error, refresh),
      el("div", { style: "margin-top:10px" }, el("a", { class: "btn ghost small", href: "#/characters" }, "← Back to Characters")));
  }
}

const references = () => data.references || [];
const countFor = (purposes) => references().filter((r) => purposes.includes(r.purpose)).length;

function renderAll() {
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "references", label: "References", count: references().length },
    { id: "expressions", label: "Expressions & Poses", count: countFor(["expression", "pose", "action_pose"]) },
    { id: "outfits", label: "Outfits & Props", count: countFor(["outfit", "prop_reference"]) },
    { id: "relationships", label: "Relationships", count: (data.relationships.outgoing.length + data.relationships.incoming.length) },
    { id: "continuity", label: "Continuity" },
    { id: "notes", label: "Notes" },
  ];

  container.replaceChildren(
    header(),
    tabBar(tabs, activeTab, (id) => { activeTab = id; renderAll(); }),
    tabPanel(),
  );
}

/* ---------------- header ---------------- */
function header() {
  const best = references().find((r) => r.is_primary && r.asset) || references().find((r) => r.asset);
  const actions = el("div", { class: "actions" },
    el("button", { class: "btn", onclick: editProfileModal }, el("span", { html: ICONS.story }), "Edit Profile"),
    data.approval_status !== "approved"
      ? el("button", { class: "btn", onclick: () => decide("approved") }, el("span", { html: ICONS.check }), "Approve Canon")
      : null,
    data.life_status === "archived"
      ? el("button", { class: "btn", onclick: () => setLife("active") }, "Reactivate")
      : el("button", { class: "btn danger", onclick: () => setLife("archived") }, "Archive"),
    el("button", { class: "btn primary", onclick: addReferenceModal }, el("span", { html: ICONS.upload }), "Add Reference"));

  return el("div", { class: "hero-band" },
    charAvatar(best?.asset, 84),
    el("div", { style: "flex:1; min-width:240px" },
      el("h2", {}, data.name,
        data.char_ref ? el("span", { style: "color:var(--text-faint); font-size:13px; font-weight:400; margin-left:10px" }, data.char_ref) : null),
      el("p", {}, data.description || data.role || "No description yet."),
      el("div", { style: "display:flex; gap:8px; margin-top:10px; flex-wrap:wrap" },
        statusPill(data.life_status),
        statusPill(data.approval_status, data.approval_status === "approved" ? "Canon approved" : pretty(data.approval_status)),
        data.species ? el("span", { class: "pill s-outline" }, data.species) : null,
        data.family_ref ? el("span", { class: "pill s-outline" }, data.family_ref.replace("FAMILY-", "").replace(/-/g, " ")) : null,
        el("span", { class: "pill s-outline" }, `updated ${fmtWhen(data.updated_at)}`))),
    actions);
}

/* ---------------- tab panels ---------------- */
function tabPanel() {
  switch (activeTab) {
    case "references": return referencesPanel(PURPOSES, "References");
    case "expressions": return referencesPanel(["expression", "pose", "action_pose"], "Expressions & Poses");
    case "outfits": return outfitsPanel();
    case "relationships": return relationshipsPanel();
    case "continuity": return continuityPanel();
    case "notes": return notesPanel();
    default: return overviewPanel();
  }
}

function overviewPanel() {
  const row = (label, value) => el("div", { class: "card" },
    el("h3", {}, label),
    value ? el("div", { style: "font-size:13px; color:var(--text); white-space:pre-wrap" }, value)
          : el("div", { class: "muted" }, "Not set"));

  return el("div", { class: "grid cols-2" },
    row("Role", data.role),
    row("Species", data.species),
    row("Age", [pretty(data.age_group || ""), data.approximate_age].filter(Boolean).join(" · ") || null),
    row("Family", data.family_ref || null),
    row("Personality", data.personality_summary),
    row("Appearance", data.appearance_summary),
    row("Body / Proportions", data.height_proportions),
    row("Clothing", data.clothing),
    row("Colors", (data.colors || []).join(", ") || null),
    row("Voice Profile", data.voice_notes));
}

function referencesPanel(purposes, title) {
  const refs = references().filter((r) => purposes.includes(r.purpose));
  const grid = refs.length
    ? el("div", { class: "grid cols-auto" }, ...refs.map(referenceTile))
    : emptyState({
        big: `No ${title.toLowerCase()} yet`,
        small: "Add a reference by uploading artwork (e.g. generated in Meta AI) or by linking an existing asset from the library.",
        actions: [el("button", { class: "btn small primary", onclick: addReferenceModal }, "Add Reference")],
      });
  return el("div", {},
    el("div", { style: "display:flex; align-items:center; gap:10px; margin-bottom:12px" },
      el("span", { class: "muted", style: "font-size:12.5px" },
        "References are never auto-approved — approve each one before it becomes a production reference."),
      el("span", { class: "pill s-green", style: "margin-left:auto" }, `${refs.filter((r) => r.approval_status === "approved").length} approved`)),
    grid);
}

function referenceTile(ref) {
  const asset = ref.asset;
  const isImage = asset && (asset.mime_type || "").startsWith("image/");
  return el("div", { class: "asset-tile", style: "cursor:default" },
    el("div", { class: "asset-thumb" },
      isImage ? el("img", { src: `/api/assets/${asset.id}/file`, loading: "lazy", alt: ref.label || "" })
              : el("span", { class: "file-icon" }, "🎞"),
      el("div", { class: "flags" },
        ref.is_primary ? el("span", { class: "pill s-amber", style: "padding:1px 6px" }, "★ Primary") : null,
        statusPill(ref.approval_status, ref.approval_status === "approved" ? "Approved" : pretty(ref.approval_status)))),
    el("div", { class: "asset-meta" },
      el("div", { class: "t" }, ref.label || asset?.title || "Reference"),
      el("div", { class: "s" },
        pretty(ref.purpose) +
        ((ref.tags || []).length ? ` · ${ref.tags.join(", ")}` : "")),
      ref.description ? el("div", { class: "s", style: "white-space:normal" }, ref.description) : null,
      el("div", { style: "display:flex; gap:5px; margin-top:8px; flex-wrap:wrap" },
        ref.approval_status !== "approved"
          ? el("button", { class: "btn small", onclick: () => approveReference(ref) }, "Approve") : null,
        !ref.is_primary ? el("button", { class: "btn small ghost", onclick: () => makePrimary(ref) }, "Set Primary") : null,
        el("button", { class: "btn small ghost", onclick: () => editReferenceModal(ref) }, "Edit"),
        el("button", { class: "btn small danger", onclick: () => unlinkReference(ref) }, "Unlink"))));
}

/* ---------- outfits & props ---------- */
function outfitsPanel() {
  const outfits = references().filter((r) => r.purpose === "outfit");
  const props = references().filter((r) => r.purpose === "prop_reference");
  return el("div", {},
    el("div", { class: "grid cols-2", style: "margin-bottom:14px" },
      el("div", { class: "card" },
        el("h3", {}, "Current Outfit", el("button", { class: "btn small ghost", style: "margin-left:auto", onclick: () => editContinuityModal() }, "Edit")),
        el("div", { style: "font-size:13px; white-space:pre-wrap" }, data.current_outfit || el("span", { class: "muted" }, "Not set — clothing details must come from creator artwork."))),
      el("div", { class: "card" },
        el("h3", {}, "Standard Props", el("button", { class: "btn small ghost", style: "margin-left:auto", onclick: () => editContinuityModal() }, "Edit")),
        (data.standard_props || []).length
          ? el("ul", { style: "margin:0; padding-left:18px; font-size:13px" }, ...data.standard_props.map((p) => el("li", {}, p)))
          : el("div", { class: "muted" }, "No standard props recorded."))),
    referencesPanel(["outfit", "prop_reference"], "Outfit & Prop References"));
}

/* ---------- relationships ---------- */
function relationshipsPanel() {
  const { outgoing, incoming } = data.relationships;
  const relRow = (rel, direction) => el("div", { class: "card", style: "display:flex; gap:12px; align-items:flex-start; padding:12px 15px; margin-bottom:9px" },
    el("span", { class: `pill ${rel.kind === "enemy" ? "s-red" : rel.kind === "family" ? "s-purple" : "s-blue"}` }, pretty(rel.kind)),
    el("div", { style: "flex:1; min-width:0" },
      el("b", {}, direction === "out" ? (rel.related_name || "—") : (rel.from_name || "—")),
      el("div", { class: "muted", style: "font-size:12.5px" }, rel.notes || "")),
    direction === "out"
      ? el("button", { class: "btn small danger", onclick: () => deleteRelationship(rel) }, el("span", { html: ICONS.x }))
      : el("span", { class: "muted", style: "font-size:11px" }, "incoming"));

  return el("div", { class: "grid cols-2" },
    el("div", {},
      el("h3", { style: "margin:4px 0 10px; display:flex; align-items:center; gap:8px" }, "From this character",
        el("button", { class: "btn small", style: "margin-left:auto", onclick: addRelationshipModal }, el("span", { html: ICONS.plus }), "Add")),
      outgoing.length ? el("div", {}, ...outgoing.map((r) => relRow(r, "out")))
        : emptyState({ big: "No outgoing relationships", small: "Add family, friend, mentor or rival links." })),
    el("div", {},
      el("h3", { style: "margin:4px 0 10px" }, "Towards this character"),
      incoming.length ? el("div", {}, ...incoming.map((r) => relRow(r, "in")))
        : emptyState({ big: "No incoming relationships", small: "Other characters list this one on their pages." })));
}

/* ---------- continuity ---------- */
function continuityPanel() {
  const listCard = (title, items, alwaysShow = true) => el("div", { class: "card" },
    el("h3", {}, title),
    items && items.length
      ? el("ul", { style: "margin:0; padding-left:18px; font-size:13px" }, ...items.map((i) => el("li", { style: "margin-bottom:5px" }, i)))
      : el("div", { class: "muted" }, "Not set"));

  return el("div", {},
    el("div", { style: "display:flex; align-items:center; gap:10px; margin-bottom:12px" },
      el("span", { class: "muted", style: "font-size:12.5px; flex:1" },
        "Continuity foundation — the Scene and Shot systems (Phase 3+) will read these fields automatically when building reference packages."),
      el("button", { class: "btn small", onclick: editContinuityModal }, el("span", { html: ICONS.story }), "Edit Continuity")),
    el("div", { class: "grid cols-2" },
      el("div", { class: "card" },
        el("h3", {}, "Standard Appearance"),
        el("div", { style: "font-size:13px; white-space:pre-wrap" }, data.standard_appearance || el("span", { class: "muted" }, "Not set"))),
      el("div", { class: "card" },
        el("h3", {}, "Current Outfit"),
        el("div", { style: "font-size:13px; white-space:pre-wrap" }, data.current_outfit || el("span", { class: "muted" }, "Not set"))),
      listCard("Standard Props", data.standard_props),
      listCard("Personality Rules", data.personality_rules),
      listCard("Visual Rules", data.visual_rules),
      listCard("Must Never Change", data.never_changes)));
}

/* ---------- notes ---------- */
function notesPanel() {
  return el("div", { class: "grid cols-2" },
    el("div", { class: "card" },
      el("h3", {}, "Master Visual Prompt"),
      el("pre", { class: "code", style: "max-height:280px" }, data.master_visual_prompt || "Not set"),
      el("div", { class: "muted", style: "margin-top:8px; font-size:12px" }, "Used as the base positive prompt for generation. Creator artwork always overrides written descriptions.")),
    el("div", { class: "card" },
      el("h3", {}, "Negative Prompt"),
      el("pre", { class: "code", style: "max-height:280px" }, data.negative_prompt || "Not set"),
      el("div", { class: "muted", style: "margin-top:8px; font-size:12px" }, "Always includes: no character redesign, no footwear (characters are always barefoot).")),
    el("div", { class: "card", style: "grid-column:1/-1" },
      el("h3", {}, "Canon Record"),
      el("div", { class: "muted", style: "font-size:12px; margin-bottom:8px" },
        data.source_path ? `Seeded from ${data.source_path} — the JSON record remains canon.` : "No canon record linked."),
      el("pre", { class: "code", style: "max-height:340px" },
        JSON.stringify(data.bible?.content ?? { note: "No bible content" }, null, 2))));
}

/* ---------------- actions ---------------- */
async function decide(decision) {
  await postJSON(`/api/characters/${characterId}/approval`, { decision });
  toast(decision === "approved" ? "Character approved as canon." : "Review recorded.", "ok");
  refresh();
}

async function setLife(status) {
  await postJSON(`/api/characters/${characterId}/life`, { status });
  toast(status === "archived" ? "Character archived — source assets untouched." : "Character reactivated.", "ok");
  refresh();
}

function editProfileModal() {
  const inputs = {
    name: el("input", { type: "text", value: data.name || "" }),
    role: el("input", { type: "text", value: data.role || "" }),
    description: el("textarea", { value: data.description || "" }),
    species: el("input", { type: "text", value: data.species || "" }),
    age_group: el("select", {}, ["", "infant", "toddler", "child", "preteen", "teen", "young_adult", "adult", "senior", "unconfirmed"].map((v) => el("option", { value: v, selected: data.age_group === v ? "" : null }, v || "—"))),
    approximate_age: el("input", { type: "text", value: data.approximate_age || "" }),
    personality_summary: el("textarea", { value: data.personality_summary || "" }),
    appearance_summary: el("textarea", { value: data.appearance_summary || "" }),
    height_proportions: el("textarea", { value: data.height_proportions || "" }),
    clothing: el("textarea", { value: data.clothing || "" }),
    voice_notes: el("textarea", { value: data.voice_notes || "" }),
  };
  openModal({
    title: "Edit Character Profile", sub: data.name, wide: true,
    body: el("div", {},
      el("div", { class: "form-row" }, field("Name", inputs.name), field("Role", inputs.role)),
      field("Description", inputs.description),
      el("div", { class: "form-row" }, field("Species", inputs.species), field("Age group", inputs.age_group)),
      el("div", { class: "form-row" }, field("Approximate age", inputs.approximate_age), field("Voice notes", inputs.voice_notes)),
      field("Personality", inputs.personality_summary),
      field("Appearance", inputs.appearance_summary),
      el("div", { class: "form-row" }, field("Body / proportions", inputs.height_proportions), field("Clothing", inputs.clothing))),
    actions: [
      { label: "Cancel" },
      { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
        const payload = {};
        for (const [key, node] of Object.entries(inputs)) {
          const value = node.value.trim();
          if (value && value !== "—") payload[key] = value;
        }
        await patchJSON(`/api/characters/${characterId}`, payload);
        toast("Profile saved.", "ok"); refresh();
        document.querySelector(".modal-backdrop")?.remove();
      } },
    ],
  });
}

function editContinuityModal() {
  const mk = (label, value, hint) => {
    const area = el("textarea", { value: textToList(value), placeholder: "One entry per line" });
    return { area, label, hint };
  };
  const text = {
    standard_appearance: mk("Standard Appearance", data.standard_appearance),
    current_outfit: mk("Current Outfit", data.current_outfit),
  };
  const lists = {
    standard_props: mk("Standard Props", data.standard_props),
    personality_rules: mk("Personality Rules", data.personality_rules),
    visual_rules: mk("Visual Rules", data.visual_rules),
    never_changes: mk("Must Never Change", data.never_changes),
  };
  const body = el("div", {},
    field(text.standard_appearance.label, text.standard_appearance.area, "e.g. Exact fur/silhouette notes from creator artwork"),
    field(text.current_outfit.label, text.current_outfit.area),
    ...Object.values(lists).map((f) => field(f.label, f.area, "One entry per line")));
  openModal({
    title: "Edit Continuity", sub: `${data.name} — consumed by future Scene/Shot reference packages`, wide: true, body,
    actions: [
      { label: "Cancel" },
      { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
        await patchJSON(`/api/characters/${characterId}`, {
          standard_appearance: text.standard_appearance.area.value.trim() || null,
          current_outfit: text.current_outfit.area.value.trim() || null,
          standard_props: listFromText(lists.standard_props.area.value),
          personality_rules: listFromText(lists.personality_rules.area.value),
          visual_rules: listFromText(lists.visual_rules.area.value),
          never_changes: listFromText(lists.never_changes.area.value),
        });
        toast("Continuity saved.", "ok"); refresh();
        document.querySelector(".modal-backdrop")?.remove();
      } },
    ],
  });
}

function addRelationshipModal() {
  const siblingSel = el("select", {}, (data.siblings || []).map((s) => el("option", { value: s.id }, s.name)));
  const kindSel = el("select", {}, REL_KINDS.map((k) => el("option", { value: k }, pretty(k))));
  const notes = el("input", { type: "text", placeholder: "e.g. Older sister; gives advice Yeti resists but needs" });
  openModal({
    title: "Add Relationship", sub: `${data.name} → other character`,
    body: el("div", {},
      field("Character", siblingSel),
      field("Kind", kindSel),
      field("Notes", notes)),
    actions: [
      { label: "Cancel" },
      { label: "Add", kind: "primary", onClick: async (e, close) => {
        await postJSON(`/api/characters/${characterId}/relationships`, {
          related_character_id: Number(siblingSel.value), kind: kindSel.value, notes: notes.value.trim() || null,
        });
        close(); toast("Relationship added.", "ok"); refresh();
      } },
    ],
  });
}

async function deleteRelationship(rel) {
  await fetch(`/api/characters/${characterId}/relationships/${rel.id}`, { method: "DELETE" });
  toast("Relationship removed.", "ok"); refresh();
}

function addReferenceModal() {
  const purposeSel = el("select", {}, PURPOSES.map((p) => el("option", { value: p }, pretty(p))));
  const label = el("input", { type: "text", placeholder: "e.g. Happy expression sheet" });
  const desc = el("input", { type: "text", placeholder: "Optional description" });
  const fileInput = el("input", { type: "file", accept: "image/*,video/*,audio/*" });
  const note = el("div", { class: "callout info", style: "font-size:12px" },
    "Meta AI workflow: generate the artwork in Meta AI, download it, then select the file here. It uploads to studio storage, links to this character, and starts as Draft — approve it after review.");

  openModal({
    title: "Add Reference", sub: `${data.name} — upload new artwork or link an existing library asset`, wide: true,
    body: el("div", {},
      note,
      el("div", { style: "height:10px" }),
      field("Artwork file", fileInput, "Image files generated with Meta AI or provided by the creator"),
      el("div", { class: "form-row" }, field("Category", purposeSel), field("Label", label)),
      field("Description", desc),
      el("div", { class: "muted", style: "font-size:12px" },
        "Need to link an existing asset instead? ", el("a", { href: "#/assets", style: "color:var(--moss)" }, "Open the Asset Library"), " to attach it there.")),
    actions: [
      { label: "Cancel" },
      { label: "Upload & Link", kind: "primary", onClick: async (e, close) => {
        const file = fileInput.files[0];
        if (!file) return toast("Choose an artwork file first (or use the Asset Library to link an existing one).", "warn");
        const form = new FormData();
        form.append("file", file);
        form.append("category", "character_references");
        form.append("title", label.value.trim() || file.name);
        form.append("provenance", "meta_ai");
        form.append("project_id", String(data.project_id));
        form.append("character_id", String(characterId));
        const asset = await (await fetch("/api/assets/upload", { method: "POST", body: form })).json();
        await postJSON(`/api/characters/${characterId}/references`, {
          asset_id: asset.id, purpose: purposeSel.value,
          label: label.value.trim() || file.name, description: desc.value.trim() || null,
        });
        close(); toast("Reference uploaded and linked as draft.", "ok"); refresh();
      } },
    ],
  });
}

async function approveReference(ref) {
  await postJSON(`/api/characters/${characterId}/references/${ref.id}/approval`, { decision: "approved" });
  toast("Reference approved — asset promoted to approved as well.", "ok"); refresh();
}

async function makePrimary(ref) {
  await patchJSON(`/api/characters/${characterId}/references/${ref.id}`, { is_primary: true });
  toast("Primary reference set.", "ok"); refresh();
}

function editReferenceModal(ref) {
  const purposeSel = el("select", {}, PURPOSES.map((p) => el("option", { value: p, selected: ref.purpose === p ? "" : null }, pretty(p))));
  const label = el("input", { type: "text", value: ref.label || "" });
  const desc = el("input", { type: "text", value: ref.description || "" });
  const tags = el("input", { type: "text", value: (ref.tags || []).join(", "), placeholder: "comma,separated,tags" });
  const notes = el("input", { type: "text", value: ref.notes || "" });
  openModal({
    title: "Edit Reference", sub: ref.label || "", wide: true,
    body: el("div", {},
      el("div", { class: "form-row" }, field("Category", purposeSel), field("Label", label)),
      field("Description", desc),
      el("div", { class: "form-row" }, field("Tags", tags), field("Notes", notes))),
    actions: [
      { label: "Cancel" },
      { label: "Save", kind: "primary", keepOpen: true, onClick: async () => {
        await patchJSON(`/api/characters/${characterId}/references/${ref.id}`, {
          purpose: purposeSel.value, label: label.value.trim() || null,
          description: desc.value.trim() || null,
          tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
          notes: notes.value.trim() || null,
        });
        toast("Reference updated.", "ok"); refresh();
        document.querySelector(".modal-backdrop")?.remove();
      } },
    ],
  });
}

async function unlinkReference(ref) {
  await fetch(`/api/characters/${characterId}/references/${ref.id}`, { method: "DELETE" });
  toast("Reference unlinked — the asset itself was not deleted.", "ok"); refresh();
}
