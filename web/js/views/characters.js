// Characters — Character Bible library: cards, search, lifecycle, import.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, charAvatar,
} from "../ui.js";
import { getJSON, postJSON } from "../api.js";

let container;
let state = { q: "", life_status: "" };

export async function render(c, params = new URLSearchParams()) {
  container = c;
  if (params.get("import") === "1") setTimeout(() => importFromRepo(), 200);
  await drawList();
}

async function drawList() {
  container.replaceChildren();
  container.append(loadingState("Loading characters…"));
  try {
    const query = new URLSearchParams();
    const projectId = localStorage.getItem("studio.projectId");
    if (projectId) query.set("project_id", projectId);
    if (state.q) query.set("q", state.q);
    if (state.life_status) query.set("life_status", state.life_status);
    const data = await getJSON(`/api/characters?${query}`);
    renderCharacters(data.characters);
  } catch (error) {
    container.replaceChildren(errorState(error, drawList));
  }
}

function renderCharacters(characters) {
  const search = el("input", { type: "search", placeholder: "Search characters…", value: state.q,
    oninput: (e) => { state.q = e.target.value; clearTimeout(drawList._t); drawList._t = setTimeout(drawList, 250); } });
  const life = el("select", { onchange: (e) => { state.life_status = e.target.value; drawList(); } },
    el("option", { value: "" }, "All statuses"),
    ["draft", "active", "archived"].map((s) => el("option", { value: s, selected: state.life_status === s ? "" : null }, pretty(s))));

  const head = el("div", { class: "page-head" },
    el("div", {},
      el("h2", {}, "Characters"),
      el("div", { class: "desc" },
        "Character Bible for this project. Creator artwork is the visual source of truth — references are approved explicitly, never automatically.")),
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: importFromRepo }, el("span", { html: ICONS.refresh }), "Import from Source Folders"),
      el("button", { class: "btn primary", onclick: newCharacterModal }, el("span", { html: ICONS.plus }), "New Character")));

  const toolbar = el("div", { class: "filter-bar" }, search, life,
    el("span", { class: "pill s-outline" }, `${characters.length} shown`));

  const grid = characters.length
    ? el("div", { class: "grid cols-auto" }, ...characters.map((ch) => characterCard(ch)))
    : emptyState({
        big: characters.length === 0 && (state.q || state.life_status) ? "No characters match" : "No characters yet",
        small: state.q || state.life_status
          ? "Try clearing the search or status filter."
          : "Characters imported from the series bible appear here. You can also create a new character draft.",
        actions: [el("button", { class: "btn small", onclick: newCharacterModal }, "New Character")],
      });

  container.replaceChildren(head, toolbar, grid);
}

function characterCard(ch) {
  const avatarAsset = null; // primary reference resolved lazily below
  const card = el("div", { class: "asset-tile", style: "cursor:default", onclick: () => location.hash = `#/characters/${ch.id}` });
  const thumbWrap = el("div", { class: "asset-thumb", style: "height:150px" },
    el("div", { style: "display:grid; place-items:center; width:100%; height:100%; background:radial-gradient(420px 160px at 50% -30%, rgba(143,209,155,.12), transparent 70%)" }));
  thumbWrap.firstChild.append(charAvatar(avatarAsset, 64));
  card.append(thumbWrap);
  card.append(el("div", { class: "asset-meta" },
    el("div", { class: "t" }, `${ch.name} `, ch.char_ref ? el("span", { style: "color:var(--text-faint); font-weight:400" }, `· ${ch.char_ref}`) : null),
    el("div", { class: "s" }, [ch.species, ch.role].filter(Boolean).join(" · ") || "—"),
    el("div", { style: "display:flex; gap:6px; margin-top:7px; flex-wrap:wrap" },
      statusPill(ch.life_status),
      ch.approval_status === "approved" ? statusPill("approved", "Canon approved") : statusPill(ch.approval_status),
      el("span", { class: "pill s-outline" }, `${ch.reference_count} ref${ch.reference_count === 1 ? "" : "s"}`),
      ch.approved_reference_count ? el("span", { class: "pill s-green" }, `${ch.approved_reference_count} approved`) : null)));

  // resolve primary/approved reference image for the avatar
  getJSON(`/api/characters/${ch.id}`).then((detail) => {
    const best = (detail.references || []).find((r) => r.is_primary && r.asset) ||
                 (detail.references || []).find((r) => r.approval_status === "approved" && r.asset) ||
                 (detail.references || []).find((r) => r.asset);
    if (best) thumbWrap.firstChild.replaceChildren(charAvatar(best.asset, 96));
  }).catch(() => {});
  return card;
}

/* ---------- New character ---------- */
function newCharacterModal() {
  const name = el("input", { type: "text", placeholder: "e.g. Pebble" });
  const role = el("input", { type: "text", placeholder: "e.g. Yeti's forest-school classmate" });
  const species = el("input", { type: "text", placeholder: "e.g. Sasquatch" });
  const kind = el("select", {}, el("option", { value: "person" }, "Person"), el("option", { value: "animal" }, "Animal / pet"));
  const desc = el("textarea", { placeholder: "Short description…" });
  const projectId = Number(localStorage.getItem("studio.projectId")) || null;
  if (!projectId) return toast("Create a project first.", "error", "No project");

  openModal({
    title: "New Character",
    sub: "Starts as a Draft. Nothing becomes canon until you approve it.",
    body: el("div", {},
      field("Name *", name),
      el("div", { class: "form-row" }, field("Role", role), field("Species", species)),
      el("div", { class: "form-row" }, field("Kind", kind), field("Description", desc))),
    actions: [
      { label: "Cancel" },
      {
        label: "Create Draft", kind: "primary",
        onClick: async (e, close) => {
          if (!name.value.trim()) return toast("Name is required.", "error");
          await postJSON("/api/characters", {
            project_id: projectId, name: name.value.trim(), role: role.value.trim() || null,
            species: species.value.trim() || null, character_kind: kind.value,
            description: desc.value.trim() || null,
          });
          close(); toast("Character created as draft.", "ok"); drawList();
        },
      },
    ],
  });
}

/* ---------- Repository import (honest reporting) ---------- */
function importFromRepo() {
  const projectId = Number(localStorage.getItem("studio.projectId"));
  if (!projectId) return toast("Select a project first.", "error");
  const body = el("div", {}, el("p", { style: "color:var(--text-dim); font-size:13px" },
    "Scanning assets/characters/source/ and the repository for real media files. Files are registered in place — never moved, copied, or modified."));
  const modal = openModal({ title: "Import from Source Folders", sub: "assets/characters/source/", body,
    actions: [{ label: "Close" }] });
  postJSON(`/api/characters/import?project_id=${projectId}`).then((report) => {
    const scan = report.scan || {};
    const rows = el("div", {},
      el("div", { class: "kv", style: "margin-bottom:10px" },
        el("dt", {}, "Media files found"), el("dd", {}, String(scan.scanned_files)),
        el("dt", {}, "Newly registered"), el("dd", {}, String(scan.registered)),
        el("dt", {}, "Already registered"), el("dd", {}, String(scan.already_registered)),
        el("dt", {}, "Character links created"), el("dd", {}, String(report.links?.links_created ?? 0))),
      scan.registered === 0 && scan.already_registered === 0
        ? emptyState({
            big: "No character artwork found in this environment",
            small: "assets/characters/source/ contains no image files right now. Drop your Meta AI / creator sheets into that folder and re-run this scan — nothing will be modified.",
          })
        : el("div", { class: "callout info", style: "font-size:12.5px" }, report.note),
      (report.family_intake_folders || []).length
        ? el("div", { class: "callout", style: "margin-top:10px; font-size:12.5px" },
            "Family intake folders detected: ", el("b", {}, report.family_intake_folders.join(", ")),
            " — create characters for them, then re-run the import to link their artwork.")
        : null);
    body.append(rows);
  }).catch((error) => {
    body.append(errorState(error));
  });
  void modal;
}
