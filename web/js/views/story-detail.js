// Story development editor: idea → logline → premise → beats → episode.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast,
  openModal, field, textToList, listFromText, fmtWhen,
} from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let storyId;
let story = null;
let characters = [];

const BEAT_GROUPS = [
  ["major", "Major story beats"],
  ["comedy", "Comedy beats"],
  ["emotional", "Emotional beats"],
  ["suspense", "Suspense / adventure beats"],
];

const TEXT_FIELDS = [
  ["logline", "Logline", "One sentence: who wants what, and what stands in the way."],
  ["premise", "Premise", "2–4 sentences setting up the episode."],
  ["main_conflict", "Main conflict", ""],
  ["stakes", "Stakes", "What happens if the goal fails?"],
  ["setting", "Setting", "Where and when."],
  ["goal", "Goal (development)", "The concrete want."],
  ["climax", "Climax", "The peak moment of the conflict."],
];

const STRUCTURE_FIELDS = [
  ["beginning", "Beginning"], ["middle", "Middle"], ["ending", "Ending"], ["resolution", "Resolution"],
];

const LIST_FIELDS = [
  ["obstacles", "Obstacles", "One per line"],
  ["motivations", "Character motivations", "One per line"],
  ["turning_points", "Turning points", "One per line"],
];

export async function render(c, id) {
  container = c;
  storyId = id;
  container.replaceChildren(loadingState("Loading story…"));
  try {
    const projectId = localStorage.getItem("studio.projectId");
    const [storyData, charData] = await Promise.all([
      getJSON(`/api/stories/${storyId}`),
      getJSON(`/api/characters${projectId ? `?project_id=${projectId}` : ""}`),
    ]);
    story = storyData;
    characters = charData.characters || [];
    draw();
  } catch (error) {
    container.replaceChildren(errorState(error, () => render(c, id)),
      el("div", { style: "margin-top:10px" }, el("a", { class: "btn ghost small", href: "#/story" }, "← Back to Story")));
  }
}

function draw() {
  const inputs = {};
  for (const [key, label, hint] of TEXT_FIELDS) {
    inputs[key] = el("textarea", { value: story[key] || "", rows: 2, placeholder: hint || "" });
  }
  for (const [key, label] of STRUCTURE_FIELDS) {
    inputs[key] = el("textarea", { value: story[key] || "", rows: 3 });
  }
  for (const [key, , hint] of LIST_FIELDS) {
    inputs[key] = el("textarea", { value: textToList(story[key]), rows: 3, placeholder: hint });
  }
  const beatInputs = {};
  for (const [key, ] of BEAT_GROUPS) beatInputs[key] = el("textarea", { value: textToList((story.beats || {})[key]), rows: 4, placeholder: "One beat per line" });

  const castPicker = el("div", { style: "display:flex; gap:7px; flex-wrap:wrap" },
    characters.map((ch) => {
      const selected = (story.character_ids || []).includes(ch.id);
      const pill = el("button", {
        class: `btn small ${selected ? "primary" : "ghost"}`,
        onclick: () => {
          const ids = new Set(story.character_ids || []);
          selected ? ids.delete(ch.id) : ids.add(ch.id);
          story.character_ids = [...ids];
          patchJSON(`/api/stories/${storyId}`, { character_ids: story.character_ids })
            .then(() => { toast("Cast updated.", "ok"); draw(); });
        },
      }, ch.name);
      return pill;
    }));

  const aiBanner = el("div", { class: "callout", style: "font-size:12.5px; margin-bottom:14px; display:flex; align-items:center; gap:9px" },
    el("span", { html: ICONS.spark, style: "color:var(--berry); flex:0 0 auto; display:inline-flex" }),
    el("span", {}, el("b", {}, "AI story assistance: not connected. "),
      "No language-model provider is configured, so all writing here is manual and fully functional. ",
      "Future providers hook into /api/story-assist without changing this editor."));

  const header = el("div", { class: "hero-band" },
    el("div", { style: "flex:1; min-width:240px" },
      el("input", { type: "text", value: story.title, style: "font-size:18px; font-weight:650; background:transparent; border-color:transparent; padding:4px 0", onchange: (e) => patchAndToast({ title: e.target.value }) }),
      el("div", { style: "color:var(--text-dim); font-size:13px; margin-top:4px; font-style:italic" }, story.idea_text || ""),
      el("div", { style: "display:flex; gap:8px; margin-top:10px; flex-wrap:wrap" },
        statusPill(story.status),
        el("span", { class: "pill s-outline" }, `updated ${fmtWhen(story.updated_at)}`),
        story.episode_id ? el("a", { class: "btn small", href: `#/episodes/${story.episode_id}` }, "Open Episode →") : null)),
    el("div", { style: "display:flex; gap:7px; flex-wrap:wrap" },
      statusFlow(),
      story.status !== "approved"
        ? el("button", { class: "btn primary", onclick: async () => {
            await patchJSON(`/api/stories/${storyId}`, { status: "approved" });
            toast("Story approved — you can now create an episode from it.", "ok"); refresh();
          } }, el("span", { html: ICONS.check }), "Approve Story")
        : !story.episode_id ? el("button", { class: "btn primary", onclick: createEpisode }, "Create Episode →") : null,
      el("button", { class: "btn ghost", onclick: saveAll }, "Save All")));

  const form = el("div", {},
    aiBanner,
    el("div", { class: "grid cols-2" },
      el("div", { class: "card" }, el("h3", {}, "Core"), ...TEXT_FIELDS.slice(0, 5).map(([k, label]) => field(label, inputs[k]))),
      el("div", { class: "card" }, el("h3", {}, "Development"),
        field(TEXT_FIELDS[5][1], inputs.goal),
        ...LIST_FIELDS.map(([k, label]) => field(label, inputs[k])),
        field(TEXT_FIELDS[6][1], inputs.climax))),
    el("div", { class: "card", style: "margin-top:14px" }, el("h3", {}, "Structure"),
      el("div", { class: "grid cols-2" }, STRUCTURE_FIELDS.map(([k, label]) => field(label, inputs[k])))),
    el("div", { class: "card", style: "margin-top:14px" }, el("h3", {}, "Beats"),
      el("div", { class: "grid cols-2" }, BEAT_GROUPS.map(([key, label]) => field(label, beatInputs[key], "One beat per line")))),
    el("div", { class: "card", style: "margin-top:14px" }, el("h3", {}, "Characters in this story"), castPicker));

  function saveAll() {
    const payload = {};
    for (const key of [...TEXT_FIELDS.map((f) => f[0]), ...STRUCTURE_FIELDS.map((f) => f[0])]) {
      payload[key] = inputs[key].value.trim() || null;
    }
    for (const [key] of LIST_FIELDS) payload[key] = listFromText(inputs[key].value);
    payload.beats = {
      major: listFromText(beatInputs.major.value), comedy: listFromText(beatInputs.comedy.value),
      emotional: listFromText(beatInputs.emotional.value), suspense: listFromText(beatInputs.suspense.value),
    };
    patchJSON(`/api/stories/${storyId}`, payload)
      .then(() => { toast("Story saved.", "ok"); refresh(); })
      .catch((e) => toast(e.message, "error"));
  }

  container.replaceChildren(header, form);
}

function statusFlow() {
  const flow = ["draft", "in_development", "review", "approved"];
  const currentIdx = flow.indexOf(story.status);
  if (currentIdx === -1) return statusPill(story.status);
  return el("select", {
    style: "max-width:170px",
    onchange: async (e) => { await patchJSON(`/api/stories/${storyId}`, { status: e.target.value }); refresh(); },
  }, flow.map((s, i) => el("option", { value: s, selected: s === story.status ? "" : null },
    pretty(s) + (i > currentIdx ? " →" : ""))));
}

async function patchAndToast(payload) {
  await patchJSON(`/api/stories/${storyId}`, payload);
  toast("Saved.", "ok"); refresh();
}

function createEpisode() {
  openModal({
    title: "Create episode from this story?",
    sub: "Creates a new episode in Development with this story attached. The story stays as the source.",
    body: el("div", { class: "callout info", style: "font-size:12.5px" },
      "Story: ", el("b", {}, story.title), " — approved ", pretty(story.status)),
    actions: [
      { label: "Cancel" },
      { label: "Create Episode", kind: "primary", onClick: async (e, close) => {
        const episode = await postJSON(`/api/stories/${storyId}/create-episode`);
        close(); toast(`Episode ${episode.number} created in development.`, "ok");
        location.hash = `#/episodes/${episode.id}`;
      } },
    ],
  });
}

async function refresh() {
  story = await getJSON(`/api/stories/${storyId}`);
  draw();
}
