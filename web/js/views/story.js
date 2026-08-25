// Story workspace: Ideas · Story Bible · Canon.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, tabBar, textToList, listFromText, fmtWhen,
} from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let tab = "ideas";
let state = { q: "", status: "", canonCategory: "", canonStatus: "" };

export async function render(c, params = new URLSearchParams()) {
  container = c;
  tab = params.get("tab") || "ideas";
  draw();
}

function draw() {
  const tabs = [
    { id: "ideas", label: "Story Ideas" },
    { id: "bible", label: "Story Bible" },
    { id: "canon", label: "Canon" },
  ];
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("h2", {}, "Story"),
        el("div", { class: "desc" },
          "Idea → development → bible → canon. Nothing becomes canon or production-ready without your approval."))),
    tabBar(tabs, tab, (id) => { tab = id; location.hash = `#/story?tab=${id}`; draw(); }),
  );
  if (tab === "ideas") renderIdeas();
  else if (tab === "bible") renderBible();
  else renderCanon();
}

/* ================= Idea workspace ================= */
async function renderIdeas() {
  container.append(loadingState("Loading stories…"));
  try {
    const query = new URLSearchParams();
    const projectId = localStorage.getItem("studio.projectId");
    if (projectId) query.set("project_id", projectId);
    if (state.q) query.set("q", state.q);
    if (state.status) query.set("status", state.status);
    const data = await getJSON(`/api/stories?${query}`);
    container.lastChild.remove();
    container.append(
      el("div", { class: "filter-bar" },
        el("input", { type: "search", placeholder: "Search ideas…", value: state.q,
          oninput: (e) => { state.q = e.target.value; clearTimeout(draw._t); draw._t = setTimeout(renderIdeas, 250); } }),
        el("select", { onchange: (e) => { state.status = e.target.value; renderIdeas(); } },
          el("option", { value: "" }, "All statuses"),
          ["draft", "in_development", "review", "approved", "archived"].map((s) =>
            el("option", { value: s, selected: state.status === s ? "" : null }, pretty(s)))),
        el("span", { class: "pill s-outline", style: "margin-left:auto" }, `${data.stories.length} story ideas`),
        el("button", { class: "btn primary", onclick: newIdeaModal }, el("span", { html: ICONS.plus }), "New Story Idea")));
    if (!data.stories.length) {
      container.append(emptyState({
        big: state.q || state.status ? "No stories match" : "Start with a story idea",
        small: state.q || state.status ? "Try clearing filters." : "“Sasquatch finds a mysterious object in the forest.” Type one sentence — develop it into a full story from there.",
        actions: [el("button", { class: "btn small primary", onclick: newIdeaModal }, "New Story Idea")],
      }));
      return;
    }
    container.append(el("div", { class: "grid cols-auto" }, ...data.stories.map(storyCard)));
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, renderIdeas));
  }
}

function storyCard(story) {
  return el("div", { class: "asset-tile", onclick: () => location.hash = `#/stories/${story.id}` },
    el("div", { class: "asset-meta", style: "padding:14px 15px" },
      el("div", { class: "t", style: "font-size:15px" }, story.title),
      el("div", { class: "s", style: "white-space:normal; -webkit-line-clamp:3; display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden" },
        story.logline || story.idea_text || "No logline yet — open to develop."),
      el("div", { style: "display:flex; gap:6px; margin-top:10px; flex-wrap:wrap" },
        statusPill(story.status),
        (story.characters || []).length ? el("span", { class: "pill s-outline" }, `${story.characters.length} char`) : null,
        story.episode_id ? el("span", { class: "pill s-green" }, "→ episode") : null,
        el("span", { style: "color:var(--text-faint); font-size:11px; margin-left:auto" }, fmtWhen(story.updated_at)))));
}

function newIdeaModal() {
  const title = el("input", { type: "text", placeholder: "Working title" });
  const idea = el("textarea", { placeholder: "One simple sentence…\ne.g. Sasquatch finds a mysterious object in the forest." });
  openModal({
    title: "New Story Idea",
    sub: "Ideas stay drafts. AI assistance is not connected — manual writing always works.",
    body: el("div", {}, field("Working title", title), field("The idea *", idea)),
    actions: [
      { label: "Cancel" },
      { label: "Create Draft", kind: "primary", onClick: async (e, close) => {
        if (!idea.value.trim()) return toast("Write the idea first.", "warn");
        const projectId = Number(localStorage.getItem("studio.projectId"));
        const story = await postJSON("/api/stories", {
          project_id: projectId, title: title.value.trim() || "Untitled Idea",
          idea_text: idea.value.trim(),
        });
        close();
        location.hash = `#/stories/${story.id}`;
      } },
    ],
  });
}

/* ================= Story Bible ================= */
const BIBLE_FIELDS = [
  ["series_title", "Series title", "text"],
  ["premise", "Premise", "area"],
  ["world_description", "World description", "area"],
  ["setting", "Setting", "text"],
  ["genre", "Genre", "text"],
  ["audience", "Audience", "text"],
  ["tone", "Tone", "list"],
  ["visual_storytelling_rules", "Visual storytelling rules", "list"],
  ["humor_rules", "Humor rules", "list"],
  ["storytelling_rules", "Storytelling rules", "list"],
  ["world_rules", "World rules", "list"],
  ["never_happen", "Things that must never happen", "list"],
  ["recurring_themes", "Recurring themes", "list"],
];

async function renderBible() {
  container.append(loadingState("Loading Story Bible…"));
  const projectId = Number(localStorage.getItem("studio.projectId"));
  try {
    const { story_bible: bible } = await getJSON(`/api/story-bible?project_id=${projectId}`);
    container.lastChild.remove();
    if (!bible) {
      container.append(emptyState({ big: "No Story Bible yet", small: "The bible is created when a project is seeded." }));
      return;
    }
    const content = bible.content || {};
    const inputs = {};
    const form = el("div", { class: "grid cols-2" });
    for (const [key, label, kind] of BIBLE_FIELDS) {
      const value = content[key];
      const input = kind === "list"
        ? el("textarea", { value: textToList(value), placeholder: "One per line" })
        : kind === "area" ? el("textarea", { value: value || "" })
        : el("input", { type: "text", value: value || "" });
      inputs[key] = input;
      form.append(field(label, input, kind === "list" ? "One entry per line" : null));
    }
    const summary = el("div", { class: "card", style: "margin-bottom:14px; display:flex; align-items:center; gap:12px; flex-wrap:wrap" },
      el("h3", { style: "margin:0" }, bible.title),
      statusPill(bible.status),
      el("span", { class: "pill s-outline" }, `v${bible.version}`),
      el("span", { class: "muted", style: "font-size:12px" }, `updated ${fmtWhen(bible.updated_at)} · ${bible.source_path || ""}`));
    container.append(
      summary,
      el("div", { class: "callout", style: "margin-bottom:14px; font-size:12.5px" },
        "This bible is ", el("b", {}, bible.status === "approved" ? "APPROVED CANON" : bible.status),
        bible.status === "approved" ? ". Saving requires confirming the approved-canon edit (recorded in the ledger and versioned)." : "."),
      form,
      el("div", { style: "display:flex; gap:9px; margin-top:14px" },
        el("button", {
          class: "btn primary", onclick: async () => {
            const newContent = { ...content, structured: true };
            for (const [key, , kind] of BIBLE_FIELDS) {
              newContent[key] = kind === "list" ? listFromText(inputs[key].value) : inputs[key].value.trim();
            }
            try {
              await patchJSON(`/api/story-bible/${bible.id}`, { content: newContent });
              toast("Bible saved.", "ok"); renderBible();
            } catch (error) {
              if (error.status === 409) {
                confirmApprovedEdit(bible.id, newContent);
              } else toast(error.message, "error");
            }
          },
        }, el("span", { html: ICONS.check }), "Save Bible"),
        bible.status !== "approved"
          ? el("button", { class: "btn", onclick: async () => {
              await patchJSON(`/api/story-bible/${bible.id}`, { status: "approved" });
              toast("Story Bible approved as canon.", "ok"); renderBible();
            } }, "Approve as Canon")
          : null,
      ));
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, renderBible));
  }
}

function confirmApprovedEdit(bibleId, newContent) {
  openModal({
    title: "Edit approved canon?",
    sub: "The Story Bible is approved canon. Confirming records this edit in the approval ledger and bumps the version.",
    body: el("div", { class: "callout", style: "font-size:12.5px" },
      "Canon is never silently overwritten — this confirmation is the audit trail."),
    actions: [
      { label: "Cancel" },
      { label: "Confirm Edit", kind: "danger", onClick: async (e, close) => {
        await patchJSON(`/api/story-bible/${bibleId}`, { content: newContent, edit_approved: true });
        close(); toast("Approved canon edited — version bumped.", "ok", "Ledger entry added"); renderBible();
      } },
    ],
  });
}

/* ================= Canon ================= */
const CANON_CATEGORIES = ["character", "world", "location", "relationship", "event", "object", "episode"];

async function renderCanon() {
  container.append(loadingState("Loading canon…"));
  const projectId = Number(localStorage.getItem("studio.projectId"));
  try {
    const query = new URLSearchParams({ project_id: projectId });
    if (state.canonCategory) query.set("category", state.canonCategory);
    if (state.canonStatus) query.set("status", state.canonStatus);
    if (state.q) query.set("q", state.q);
    const data = await getJSON(`/api/canon?${query}`);
    container.lastChild.remove();
    const counts = data.counts_by_status || {};
    const catSelect = el("select", { onchange: (e) => { state.canonCategory = e.target.value; renderCanon(); } },
      el("option", { value: "" }, "All categories"),
      CANON_CATEGORIES.map((cat) => el("option", { value: cat, selected: state.canonCategory === cat ? "" : null }, pretty(cat))));
    const statusSelect = el("select", { onchange: (e) => { state.canonStatus = e.target.value; renderCanon(); } },
      el("option", { value: "" }, "All statuses"),
      ["draft", "proposed", "canon", "deprecated"].map((s) =>
        el("option", { value: s, selected: state.canonStatus === s ? "" : null }, pretty(s))));
    const search = el("input", { type: "search", placeholder: "Search canon…", value: state.q,
      oninput: (e) => { state.q = e.target.value; clearTimeout(renderCanon._t); renderCanon._t = setTimeout(renderCanon, 250); } });
    const addButton = el("button", { class: "btn primary", style: "margin-left:auto", onclick: addCanonModal },
      el("span", { html: ICONS.plus }), "Add Canon Entry");
    container.append(
      el("div", { class: "filter-bar" },
        search, catSelect, statusSelect,
        ...Object.entries(counts).map(([k, v]) => statusPill(k, `${pretty(k)} · ${v}`)),
        addButton));
    if (!data.canon.length) {
      container.append(emptyState({ big: "No canon entries match", small: "Canon facts are proposed, then approved by you. Nothing auto-canonizes." }));
      return;
    }
    const list = el("div", {});
    for (const entry of data.canon) {
      list.append(el("div", { class: "card", style: "margin-bottom:9px; padding:12px 15px" },
        el("div", { style: "display:flex; gap:10px; align-items:flex-start" },
          el("div", { style: "flex:1; min-width:0" },
            el("b", {}, entry.title),
            el("div", { style: "font-size:12.5px; margin-top:3px" }, entry.statement || el("span", { class: "muted" }, "No statement")),
            el("div", { style: "display:flex; gap:6px; margin-top:7px; flex-wrap:wrap" },
              el("span", { class: "pill s-outline" }, pretty(entry.category)),
              statusPill(entry.status),
              entry.origin === "seeded" ? el("span", { class: "pill s-outline" }, "seeded from canon files") : null)),
          canonActions(entry))));
    }
    container.append(list);
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, renderCanon));
  }
}

function canonActions(entry) {
  const row = el("div", { style: "display:flex; gap:5px; flex-wrap:wrap" });
  if (entry.status === "draft") row.append(el("button", { class: "btn small", onclick: async () => { await postJSON(`/api/canon/${entry.id}/propose`); toast("Proposed — awaiting your approval.", "ok"); renderCanon(); } }, "Propose"));
  if (entry.status === "proposed" || entry.status === "draft") row.append(el("button", { class: "btn small primary", onclick: async () => { await postJSON(`/api/canon/${entry.id}/approve`); toast("Canon approved.", "ok"); renderCanon(); } }, el("span", { html: ICONS.check }), "Approve"));
  if (entry.status === "canon") row.append(el("button", { class: "btn small ghost", onclick: async () => { await postJSON(`/api/canon/${entry.id}/deprecate`); toast("Deprecated (kept for history).", "info"); renderCanon(); } }, "Deprecate"));
  if (entry.status === "deprecated") row.append(el("button", { class: "btn small ghost", onclick: async () => { await postJSON(`/api/canon/${entry.id}/propose`); renderCanon(); } }, "Re-propose"));
  if (entry.status !== "canon") row.append(el("button", { class: "btn small danger", onclick: async () => {
    await fetch(`/api/canon/${entry.id}`, { method: "DELETE" }); toast("Entry deleted.", "ok"); renderCanon();
  } }, el("span", { html: ICONS.x })));
  return row;
}

function addCanonModal() {
  const title = el("input", { type: "text", placeholder: "e.g. Mossy Hollow market day" });
  const category = el("select", {}, CANON_CATEGORIES.map((c) => el("option", { value: c }, pretty(c))));
  const statement = el("textarea", { placeholder: "The factual statement. e.g. Market day happens every third sunrise." });
  openModal({
    title: "Add Canon Entry",
    sub: "Entries start as drafts — you approve them into canon explicitly.",
    body: el("div", {}, field("Title *", title),
      el("div", { class: "form-row" }, field("Category", category), el("div")),
      field("Statement", statement)),
    actions: [
      { label: "Cancel" },
      { label: "Add as Draft", kind: "primary", onClick: async (e, close) => {
        if (!title.value.trim()) return toast("Title required.", "warn");
        await postJSON("/api/canon", {
          project_id: Number(localStorage.getItem("studio.projectId")),
          category: category.value, title: title.value.trim(),
          statement: statement.value.trim(), status: "draft",
        });
        close(); toast("Canon draft added — propose it when ready.", "ok"); renderCanon();
      } },
    ],
  });
}
