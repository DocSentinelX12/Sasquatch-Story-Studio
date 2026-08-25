// Assets — production asset library: upload (Meta AI workflow), browse,
// search, filter, sort, tags, favorites, versions, approval, archive.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, assetThumb, fmtBytes, fmtWhen,
} from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

const CATEGORIES = [
  ["characters", "Characters"], ["character_references", "Character references"],
  ["expressions", "Expressions"], ["poses", "Poses"],
  ["environments", "Environments"], ["backgrounds", "Backgrounds"],
  ["props", "Props"], ["vehicles", "Vehicles"], ["animals", "Animals"],
  ["images", "Images"], ["video", "Video"], ["voice", "Voice"],
  ["music", "Music"], ["sound_effects", "Sound effects"], ["other", "Other"],
];
const STATUS_OPTIONS = [
  ["", "All statuses"], ["draft", "Draft"], ["review", "In Review"],
  ["approved", "Approved"], ["rejected", "Rejected"], ["archived", "Archived"],
];
const SORT_OPTIONS = [["newest", "Newest"], ["oldest", "Oldest"], ["title", "Title A→Z"], ["size", "Largest"]];

// Display mapping for stored statuses
const STATUS_LABEL = {
  registered: "Draft", pending_approval: "In Review", approved: "Approved",
  rejected: "Rejected", obsolete: "Archived",
};

let container;
let state = { q: "", category: "", status: "", tag: "", sort: "newest", favorite: false, view: "grid", offset: 0, limit: 48 };
let lastData = null;
let loadedAssets = [];
let tagOptions = [];
let characterOptions = [];

export async function render(c, params = new URLSearchParams()) {
  container = c;
  state.category = params.get("category") || "";
  if (params.get("import") === "1") setTimeout(() => importArtworkModal(), 150);
  await Promise.all([loadTags(), loadCharacters()]);
  await draw(false);
}

async function loadTags() {
  try { tagOptions = (await getJSON("/api/assets/tags")).tags; } catch { tagOptions = []; }
}

async function loadCharacters() {
  try {
    const projectId = localStorage.getItem("studio.projectId");
    const query = projectId ? `?project_id=${projectId}` : "";
    characterOptions = (await getJSON(`/api/characters${query}`)).characters;
  } catch { characterOptions = []; }
}

async function draw(appendMode) {
  if (!appendMode) container.replaceChildren(loadingState("Loading assets…"));
  const query = new URLSearchParams();
  const projectId = localStorage.getItem("studio.projectId");
  if (projectId) query.set("project_id", projectId);
  for (const key of ["q", "category", "tag", "sort"]) if (state[key]) query.set(key, state[key]);
  if (state.status) query.set("status", state.status);
  if (state.favorite) query.set("favorite", "true");
  query.set("limit", String(state.limit));
  query.set("offset", String(appendMode ? state.offset : 0));

  try {
    lastData = await getJSON(`/api/assets?${query}`);
    if (!appendMode) {
      state.offset = 0;
      loadedAssets = [];
    }
    state.offset += lastData.assets.length;
    loadedAssets.push(...lastData.assets);
    renderLibrary();
  } catch (error) {
    container.replaceChildren(errorState(error, () => draw(false)));
  }
}

function renderLibrary() {
  const assets = loadedAssets;
  const total = lastData.total;
  const counts = lastData.counts_by_category || {};

  const search = el("input", { type: "search", placeholder: "Search title, filename, notes…", value: state.q,
    oninput: (e) => { state.q = e.target.value; clearTimeout(draw._t); draw._t = setTimeout(() => draw(false), 250); } });
  const categorySel = el("select", { onchange: (e) => { state.category = e.target.value; draw(false); } },
    el("option", { value: "" }, "All categories"),
    CATEGORIES.map(([value, label]) => el("option", { value, selected: state.category === value ? "" : null },
      `${label}${counts[value] ? ` (${counts[value]})` : ""}`)));
  const statusSel = el("select", { onchange: (e) => { state.status = e.target.value; draw(false); } },
    STATUS_OPTIONS.map(([value, label]) => el("option", { value, selected: state.status === value ? "" : null }, label)));
  const tagSel = el("select", { onchange: (e) => { state.tag = e.target.value; draw(false); } },
    el("option", { value: "" }, "All tags"),
    tagOptions.map((t) => el("option", { value: t.name, selected: state.tag === t.name ? "" : null }, `${t.name} (${t.count})`)));
  const sortSel = el("select", { onchange: (e) => { state.sort = e.target.value; draw(false); } },
    SORT_OPTIONS.map(([value, label]) => el("option", { value, selected: state.sort === value ? "" : null }, label)));
  const favToggle = el("button", {
    class: `btn small ${state.favorite ? "primary" : "ghost"}`,
    onclick: () => { state.favorite = !state.favorite; draw(false); },
  }, "★ Favorites");
  const viewToggle = el("button", {
    class: "btn small ghost",
    onclick: () => { state.view = state.view === "grid" ? "list" : "grid"; renderLibrary(); },
  }, state.view === "grid" ? "☰ List view" : "▦ Grid view");

  const head = el("div", { class: "page-head" },
    el("div", {},
      el("h2", {}, "Asset Library"),
      el("div", { class: "desc" },
        "Meta AI artwork → import → categorize & tag → associate with a character → approve → use as production reference.")),
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: scanRepo }, el("span", { html: ICONS.refresh }), "Scan Repository Files"),
      el("button", { class: "btn primary", onclick: importArtworkModal }, el("span", { html: ICONS.upload }), "Import Artwork")));

  const meta = el("div", { class: "workflow-hint", style: "display:flex; gap:0; margin-bottom:16px; border:1px solid var(--border); border-radius:10px; overflow:hidden; flex-wrap:wrap" },
    ...["1 · Generate in Meta AI", "2 · Download the image", "3 · Import Artwork here", "4 · Categorize + Tag", "5 · Approve for production"].map((step, i) =>
      el("div", {
        style: `flex:1; min-width:130px; padding:10px 13px; font-size:12px; text-align:center; ${i < 4 ? "border-right:1px solid var(--border);" : ""}
        ${i === 2 ? "background:rgba(143,209,155,.09); color:var(--moss);" : "color:var(--text-dim);"} background:${i === 2 ? "rgba(143,209,155,.09)" : "transparent"}`,
      }, step)));

  const toolbar = el("div", { class: "filter-bar" }, search, categorySel, statusSel, tagSel, sortSel, favToggle, viewToggle,
    el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${total} asset${total === 1 ? "" : "s"}`));

  const body = assets.length
    ? (state.view === "grid"
        ? el("div", { class: "grid cols-auto" }, ...assets.map(assetTile))
        : listView(assets))
    : emptyState({
        big: hasActiveFilters() ? "No assets match your filters" : "The library is empty",
        small: hasActiveFilters()
          ? "Try clearing the search, category, tag or status filters."
          : "Import artwork generated with Meta AI, or scan the repository for existing files. Nothing is fabricated or auto-approved.",
        actions: [
          el("button", { class: "btn small primary", onclick: importArtworkModal }, el("span", { html: ICONS.upload }), "Import Artwork"),
          el("button", { class: "btn small ghost", onclick: scanRepo }, "Scan Repository Files"),
        ],
      });

  const remaining = total != null && state.offset < total ? total - state.offset : null;
  const more = (remaining != null && remaining > 0) || lastData.next_cursor
    ? el("div", { style: "text-align:center; margin-top:16px" },
        el("button", { class: "btn", onclick: () => draw(true) },
          remaining != null ? `Load more (${remaining} remaining)` : "Load more"))
    : null;

  container.replaceChildren(head, meta, toolbar, body, more);
}

function assetTile(asset) {
  const tile = el("div", { class: "asset-tile", onclick: () => assetModal(asset) },
    assetThumb(asset),
    el("div", { class: "asset-meta" },
      el("div", { class: "t" }, asset.title),
      el("div", { class: "s" }, `${pretty(asset.category)} · ${fmtBytes(asset.byte_size)} · v${countVersions(asset)}`),
      el("div", { style: "display:flex; gap:6px; margin-top:6px; align-items:center" },
        statusPill(asset.status, STATUS_LABEL[asset.status] || pretty(asset.status)),
        asset.provenance === "meta_ai" ? el("span", { class: "pill s-purple", style: "padding:1px 6px" }, "Meta AI") : null,
        starButton(asset))));
  return tile;
}

function listView(assets) {
  return el("div", { class: "table-wrap" },
    el("table", { class: "data" },
      el("thead", {}, el("tr", {},
        el("th", {}, "Preview"), el("th", {}, "Title"), el("th", {}, "Category"),
        el("th", {}, "Status"), el("th", {}, "Origin"), el("th", {}, "Size"), el("th", {}, "Updated"))),
      el("tbody", {},
        ...assets.map((a) => el("tr", { class: "clickable", onclick: () => assetModal(a) },
          el("td", {}, el("div", { style: "width:52px; height:34px; border-radius:6px; overflow:hidden; background:#0b0e0c; display:grid; place-items:center" },
            (a.mime_type || "").startsWith("image/")
              ? el("img", { src: `/api/assets/${a.id}/file`, style: "width:100%; height:100%; object-fit:cover", loading: "lazy" })
              : el("span", { style: "font-size:14px" }, "🎞"))),
          el("td", { style: "font-weight:600" }, a.title, " ", starButton(a, true)),
          el("td", {}, pretty(a.category)),
          el("td", {}, statusPill(a.status, STATUS_LABEL[a.status] || pretty(a.status))),
          el("td", {}, a.provenance === "meta_ai" ? "Meta AI" : pretty(a.provenance || "—")),
          el("td", {}, fmtBytes(a.byte_size)),
          el("td", { style: "color:var(--text-faint)" }, fmtWhen(a.updated_at)))))));
}

const versionCounts = new Map();
function countVersions(asset) { return versionCounts.get(asset.id) || 1; }

function hasActiveFilters() {
  return Boolean(state.q || state.category || state.status || state.tag || state.favorite);
}

function starButton(asset, small = false) {
  return el("button", {
    class: `btn small ghost`, style: `color:${asset.is_favorite ? "var(--amber)" : "var(--text-faint)"}`,
    onclick: async (e) => {
      e.stopPropagation();
      await postJSON(`/api/assets/${asset.id}/favorite`);
      asset.is_favorite = !asset.is_favorite;
      draw(false);
    },
  }, asset.is_favorite ? "★" : "☆");
}

/* ---------------- Import Artwork (Meta AI workflow) ---------------- */
function importArtworkModal() {
  const fileInput = el("input", { type: "file", accept: "image/*,video/*,audio/*" });
  const title = el("input", { type: "text", placeholder: "e.g. Yeti — happy expression sheet" });
  const category = el("select", {}, CATEGORIES.map(([value, label]) =>
    el("option", { value, selected: value === "character_references" ? "" : null }, label)));
  const provenance = el("select", {},
    el("option", { value: "meta_ai" }, "Meta AI (external generation)"),
    el("option", { value: "creator" }, "Creator artwork"),
    el("option", { value: "other" }, "Other"));
  const tags = el("input", { type: "text", placeholder: "yeti, expression, meta-ai" });
  const characterSel = el("select", {},
    el("option", { value: "" }, "— None —"),
    characterOptions.map((c) => el("option", { value: c.id }, c.name)));
  const notes = el("input", { type: "text", placeholder: "Optional note" });

  openModal({
    title: "Import Artwork",
    sub: "Meta AI workflow — generate externally, import here, approve before production use",
    wide: true,
    body: el("div", {},
      el("div", { class: "callout info", style: "font-size:12px; margin-bottom:13px" },
        "Files are stored in the studio's local asset storage (assets/studio-uploads/). Uploads are durable on this machine but are not automatically committed to git. Every import starts as ",
        el("b", {}, "Draft"), " — nothing is approved automatically."),
      field("Artwork file *", fileInput),
      field("Title", title),
      el("div", { class: "form-row" }, field("Category", category), field("Origin", provenance)),
      el("div", { class: "form-row" }, field("Tags (comma separated)", tags), field("Associate with character", characterSel)),
      field("Notes", notes)),
    actions: [
      { label: "Cancel" },
      { label: "Import as Draft", kind: "primary", onClick: async (e, close) => {
        const file = fileInput.files[0];
        if (!file) { toast("Choose a file first.", "warn"); return; }
        const form = new FormData();
        form.append("file", file);
        form.append("category", category.value);
        form.append("title", title.value.trim() || file.name);
        form.append("provenance", provenance.value);
        form.append("tags", tags.value);
        form.append("notes", notes.value.trim());
        const projectId = localStorage.getItem("studio.projectId");
        if (projectId) form.append("project_id", projectId);
        if (characterSel.value) form.append("character_id", characterSel.value);
        const response = await fetch("/api/assets/upload", { method: "POST", body: form });
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          toast(typeof error.detail === "string" ? error.detail : "Upload failed.", "error");
          return;
        }
        const asset = await response.json();
        close();
        toast(`Imported “${asset.title}” as Draft. Review it, then approve for production use.`, "ok", "Artwork imported");
        await Promise.all([loadTags(), draw(false)]);
      } },
    ],
  });
}

/* ---------------- repository scan ---------------- */
function scanRepo() {
  const body = el("div", { class: "muted", style: "font-size:13px" },
    "Scanning assets/ and episodes/ for real media files. Files are registered in place — never moved or modified.");
  openModal({ title: "Scan Repository Files", sub: "Register existing files without copying", body, actions: [{ label: "Close" }] });
  const projectId = localStorage.getItem("studio.projectId");
  postJSON(`/api/assets/scan-repo${projectId ? `?project_id=${projectId}` : ""}`).then((report) => {
    body.append(el("div", { class: "kv", style: "margin-top:12px" },
      el("dt", {}, "Found"), el("dd", {}, String(report.scanned_files)),
      el("dt", {}, "Registered"), el("dd", {}, String(report.registered)),
      el("dt", {}, "Already tracked"), el("dd", {}, String(report.already_registered))));
    if (!report.scanned_files) {
      body.append(emptyState({
        big: "No media files found",
        small: "The repository contains no artwork files in this environment yet. Add files under assets/ (e.g. assets/characters/source/) and scan again.",
      }));
    } else {
      toast(`Registered ${report.registered} file(s).`, "ok");
    }
    draw(false);
  }).catch((error) => body.append(errorState(error)));
}

/* ---------------- asset detail modal ---------------- */
async function assetModal(asset) {
  let detail;
  try {
    detail = await getJSON(`/api/assets/${asset.id}`);
  } catch (error) {
    toast(error.message, "error"); return;
  }
  versionCounts.set(asset.id, detail.versions.length);
  const isImage = (detail.mime_type || "").startsWith("image/");
  const preview = el("div", {
    style: "border:1px solid var(--border); border-radius:10px; overflow:hidden; background:#0b0e0c; display:grid; place-items:center; min-height:200px; max-height:340px",
  },
    isImage ? el("img", { src: `/api/assets/${detail.id}/file`, style: "width:100%; object-fit:contain; max-height:340px" })
      : el("div", { style: "padding:40px; color:var(--text-faint)" }, el("span", { html: ICONS.film })));

  const meta = el("dl", { class: "kv" },
    el("dt", {}, "Status"), el("dd", {}, STATUS_LABEL[detail.status] || detail.status),
    el("dt", {}, "Category"), el("dd", {}, pretty(detail.category)),
    el("dt", {}, "Origin"), el("dd", {}, detail.provenance === "meta_ai" ? "Meta AI" : pretty(detail.provenance || "—")),
    el("dt", {}, "Class"), el("dd", {}, pretty(detail.asset_class)),
    el("dt", {}, "Size"), el("dd", {}, fmtBytes(detail.byte_size)),
    el("dt", {}, "Storage"), el("dd", {}, detail.storage_mode === "repo_reference" ? "Repository file (in place)" : "Studio storage"),
    detail.repo_path ? el("dt", {}, "Path") : null, detail.repo_path ? el("dd", {}, detail.repo_path) : null,
    el("dt", {}, "Updated"), el("dd", {}, fmtWhen(detail.updated_at)),
    detail.sha256 ? el("dt", {}, "SHA-256") : null, detail.sha256 ? el("dd", {}, detail.sha256.slice(0, 16) + "…") : null);

  // versions block
  const versionsEl = el("div", {},
    el("h3", { style: "margin:14px 0 8px; font-size:13px" }, "Versions — old versions are never deleted"),
    el("div", { style: "display:flex; flex-direction:column; gap:7px" },
      ...detail.versions.slice().reverse().map((v) => el("div", {
        style: `display:flex; align-items:center; gap:9px; padding:8px 11px; border:1px solid ${v.is_current ? "rgba(143,209,155,.4)" : "var(--border)"}; border-radius:8px; background:${v.is_current ? "rgba(143,209,155,.06)" : "transparent"}`,
      },
        el("b", { style: "width:34px" }, `v${v.version_number}`),
        statusPill(v.status || "registered", STATUS_LABEL[v.status || "registered"] || pretty(v.status)),
        v.is_current ? el("span", { class: "pill s-green" }, "Current") : null,
        el("span", { style: "color:var(--text-faint); font-size:11.5px; margin-left:auto" }, fmtBytes(v.byte_size) + " · " + fmtWhen(v.created_at)),
        !v.is_current ? el("button", { class: "btn small ghost", onclick: async () => {
          await postJSON(`/api/assets/${detail.id}/versions/${v.id}/current`);
          toast(`v${v.version_number} is now current.`, "ok"); assetModal(detail);
        } }, "Set current") : null,
        el("button", { class: "btn small ghost", onclick: async () => {
          await postJSON(`/api/assets/${detail.id}/versions/${v.id}/status`, { status: "approved" });
          toast(`v${v.version_number} approved.`, "ok"); assetModal(detail);
        } }, "Approve")))));

  const newVersionInput = el("input", { type: "file", accept: "image/*,video/*,audio/*" });
  const actionsRow = el("div", { style: "display:flex; gap:8px; flex-wrap:wrap; margin-top:14px" },
    detail.status !== "approved" ? el("button", { class: "btn primary small", onclick: () => setStatus(detail, "approved") }, el("span", { html: ICONS.check }), "Approve") : null,
    detail.status === "approved" ? el("button", { class: "btn small", onclick: () => setStatus(detail, "registered") }, "Back to Draft") : null,
    detail.status !== "rejected" ? el("button", { class: "btn danger small", onclick: () => setStatus(detail, "rejected") }, "Reject") : null,
    detail.status !== "obsolete" ? el("button", { class: "btn ghost small", onclick: () => setStatus(detail, "obsolete") }, "Archive") : null,
    detail.status === "obsolete" ? el("button", { class: "btn ghost small", onclick: () => setStatus(detail, "registered") }, "Unarchive") : null);

  const tagsInput = el("input", { type: "text", value: (detail.tags || []).join(", "), placeholder: "comma,separated,tags" });
  const saveMeta = el("button", { class: "btn small", onclick: async () => {
    await patchJSON(`/api/assets/${detail.id}`, {
      tags: tagsInput.value.split(",").map((t) => t.trim()).filter(Boolean),
    });
    await loadTags(); toast("Tags saved.", "ok");
  } }, "Save tags");

  const linkCharacter = el("select", {},
    el("option", { value: "" }, "— None —"),
    characterOptions.map((c) => el("option", { value: c.id, selected: detail.character_id === c.id ? "" : null }, c.name)));
  const saveLink = el("button", { class: "btn small", onclick: async () => {
    if (!linkCharacter.value) return toast("Choose a character to link.", "warn");
    await patchJSON(`/api/assets/${detail.id}`, { character_id: Number(linkCharacter.value) });
    toast("Character link updated.", "ok");
  } }, "Save link");

  document.querySelector(".modal-backdrop")?.remove();
  openModal({
    title: detail.title,
    sub: `${pretty(detail.category)} · ${STATUS_LABEL[detail.status] || pretty(detail.status)}`,
    wide: true,
    body: el("div", { class: "grid cols-2", style: "align-items:start" },
      el("div", {}, preview, actionsRow,
        el("h3", { style: "margin:16px 0 8px; font-size:13px" }, "Add new version"),
        newVersionInput,
        el("button", { class: "btn small", style: "margin-top:8px", onclick: async () => {
          const file = newVersionInput.files[0];
          if (!file) return toast("Choose a file for the new version.", "warn");
          const form = new FormData();
          form.append("file", file);
          form.append("notes", `uploaded ${new Date().toLocaleDateString()}`);
          const response = await fetch(`/api/assets/${detail.id}/versions`, { method: "POST", body: form });
          if (!response.ok) return toast("Version upload failed.", "error");
          toast("New version added as draft. Previous versions are kept.", "ok");
          assetModal(detail); draw(false);
        } }, el("span", { html: ICONS.upload }), "Upload version")),
      el("div", {}, meta,
        el("h3", { style: "margin:14px 0 8px; font-size:13px" }, "Tags"), tagsInput, saveMeta,
        el("h3", { style: "margin:14px 0 8px; font-size:13px" }, "Linked character"), linkCharacter, saveLink),
      el("div", { style: "grid-column:1/-1" }, versionsEl)),
    actions: [{ label: "Close" }],
  });
}

async function setStatus(asset, status) {
  await postJSON(`/api/assets/${asset.id}/status`, { status });
  toast(`Asset status: ${STATUS_LABEL[status] || status}.`, "ok");
  assetModal(asset);
  draw(false);
}

