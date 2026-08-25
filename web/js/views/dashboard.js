// Dashboard — real production overview. Every number comes from the API;
// zero/empty states are shown honestly when no data exists.
import { el, ICONS, statusPill, pretty, fmtWhen, fmtBytes, statCard, emptyState, assetThumb, toast, loadingState, errorState } from "../ui.js";
import { getJSON } from "../api.js";

let container;

export async function render(c) {
  container = c;
  draw(loadingUI());
  try {
    const data = await getJSON("/api/dashboard");
    draw(dashboardUI(data));
  } catch (error) {
    draw(el("div", {},
      el("div", { class: "page-head" }, el("div", {},
        el("h2", {}, "Dashboard"),
        el("div", { class: "desc" }, "Production overview for your Sasquatch series."))),
      errorState(error, () => render(c))));
  }
}

function draw(node) {
  container.replaceChildren(node);
}

function loadingUI() {
  return el("div", {},
    el("div", { class: "page-head" }, el("div", {},
      el("h2", {}, "Dashboard"),
      el("div", { class: "desc" }, "Loading production data…"))),
    loadingState());
}

/* ------------------ main layout ------------------ */
function dashboardUI(data) {
  const stats = data.production_stats;
  const queue = data.queue;
  const project = currentProject(data);
  const providers = data.providers || [];

  return el("div", {},
    heroBand(project, stats),
    el("div", { class: "grid cols-4", style: "margin-bottom:18px" },
      statCard(stats.projects, "Projects", `${stats.episodes} episode${s(stats.episodes)} tracked`),
      statCard(stats.episodes, "Episodes", summarizeStatuses(stats.episode_status_counts)),
      statCard(stats.scenes, "Scenes", `${stats.shots} shots in the database`),
      statCard(stats.assets, "Assets", `${stats.approved_assets} approved for production`),
    ),
    el("div", { class: "grid cols-2", style: "margin-bottom:18px" },
      quickActionsPanel(),
      queuePanel(queue, providers),
    ),
    el("div", { class: "grid cols-2", style: "margin-bottom:18px" },
      episodesPanel(data.episodes_in_progress || []),
      assetsPanel(data.recent_assets || []),
    ),
    charactersFooter(stats),
  );
}

const s = (n) => (n === 1 ? "" : "s");

function summarizeStatuses(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) return "none in progress";
  return entries.slice(0, 3).map(([k, v]) => `${v} ${k}`).join(" · ");
}

function currentProject(data) {
  const projects = data.projects || [];
  return projects.find((p) => p.id === Number(localStorage.getItem("studio.projectId"))) || projects[0] || null;
}

/* ------------------ hero ------------------ */
function heroBand(project, stats) {
  const inner = el("div", { style: "flex:1; min-width:260px" },
    el("h2", {}, project ? project.name : "No project yet"),
    project
      ? el("p", {}, project.series_premise || "No series premise recorded yet.")
      : el("p", {}, "Create your first project to start tracking episodes, characters and assets."),
    el("div", { style: "display:flex; gap:8px; margin-top:10px; flex-wrap:wrap" },
      project ? statusPill(project.status) : null,
      project ? el("span", { class: "pill s-outline" }, `Season ${project.current_season_number}`) : null,
      project ? el("span", { class: "pill s-outline" }, `${project.episode_count} episode${s(project.episode_count)}`) : null,
      el("span", { class: "pill s-outline" }, `${stats.characters} characters`),
    ),
  );
  const art = el("div", {
    html: ICONS.sasquatch,
    style: "width:74px; height:74px; border-radius:16px; display:grid; place-items:center; flex:0 0 auto; color:var(--moss); background:rgba(143,209,155,.08); border:1px solid var(--border-strong)",
  });
  art.querySelector("svg").setAttribute("width", "40");
  art.querySelector("svg").setAttribute("height", "40");
  return el("div", { class: "hero-band" }, art, inner,
    el("button", { class: "btn primary", onclick: () => location.hash = "#/projects" }, "Open Project"));
}

/* ------------------ quick actions ------------------ */
function quickActionsPanel() {
  const action = (icon, label, { phase = null, run } = {}) =>
    el("button", {
      class: `quick-btn ${run ? "" : "soon"}`,
      onclick: () => {
        if (run) return run();
        toast(phase === "P2"
          ? "“" + label + "” comes in a later production phase."
          : "“" + label + "” arrives in the next Phase 1 build step.", "info", phase === "P2" ? "Coming in a later phase" : "Next in Phase 1");
      },
    },
      el("span", { html: ICONS[icon] }),
      label,
      phase ? el("span", { class: "tag" }, phase === "P2" ? "LATER" : "SOON") : null);

  return el("div", { class: "card" },
    el("h3", {}, "Quick Actions"),
    el("div", { class: "quick-grid" },
      action("spark", "New Story", { phase: "P2" }),
      action("spark", "Production Assistant", { run: () => location.hash = "#/assistant" }),
      action("episodes", "New Episode", { phase: "P1" }),
      action("characters", "Import Character", { run: () => location.hash = "#/characters?import=1" }),
      action("assets", "Import Environment", { run: () => location.hash = "#/assets?category=environments&import=1" }),
      action("scenes", "Create Scene", { phase: "P2" }),
      action("shots", "Create Shot", { phase: "P2" }),
      action("queue", "Generate Video", { run: () => location.hash = "#/assistant" }),
      action("timeline", "Open Timeline", { phase: "P2" }),
      action("exports", "Export Episode", { phase: "P2" }),
    ));
}

/* ------------------ queue + providers ------------------ */
const JOB_ORDER = ["draft", "queued", "generating", "completed", "needs_review", "approved", "failed", "rejected", "cancelled"];

function queuePanel(queue, providers) {
  const counts = queue?.counts_by_status || {};
  const chips = el("div", { style: "display:flex; gap:6px; flex-wrap:wrap" },
    JOB_ORDER.filter((k) => counts[k]).length
      ? JOB_ORDER.filter((k) => counts[k]).map((k) => statusPill(k, `${pretty(k)} · ${counts[k]}`))
      : el("span", { class: "muted", style: "font-size:12.5px" }, "No generation jobs yet — nothing is running or queued."));

  const providerRows = providers.map((p) =>
    el("div", { style: "display:flex; align-items:center; gap:9px" },
      statusPill(p.status, p.status === "ready" ? "Configured" : "Not configured"),
      el("b", { style: "font-size:12.5px" }, p.display_name),
      p.status !== "ready"
        ? el("span", { class: "muted", style: "font-size:11.5px" }, `needs ${p.missing_env.join(", ")}`)
        : el("span", { class: "muted", style: "font-size:11.5px" }, "no live adapter yet — see Settings")));

  return el("div", { class: "card" },
    el("h3", {}, "Generation Queue",
      el("span", { class: "pill s-outline" }, `${queue?.total || 0} total`)),
    el("div", { style: "margin-bottom:12px" }, chips),
    queue?.failed ? el("div", {
      class: "callout",
      style: "margin-bottom:12px; padding:8px 12px; font-size:12.5px; display:flex; align-items:center; gap:8px",
    }, el("span", { html: ICONS.alert }), `${queue.failed} failed generation${s(queue.failed)} — review before export.`) : null,
    el("div", { style: "display:flex; flex-direction:column; gap:7px; padding-top:4px; border-top:1px solid var(--border)" },
      el("div", { class: "muted", style: "font-size:11px; text-transform:uppercase; letter-spacing:.08em; margin-top:4px" }, "Video Providers"),
      ...providerRows));
}

/* ------------------ episodes ------------------ */
function episodesPanel(episodes) {
  const body = episodes.length
    ? el("div", {},
        ...episodes.slice(0, 5).map((e) =>
          el("div", {
            class: "card",
            style: "display:flex; align-items:center; gap:12px; padding:11px 14px; margin-bottom:8px; cursor:pointer",
            onclick: () => location.hash = "#/episodes",
          },
            el("span", { class: "pill s-outline" }, `EP ${String(e.number).padStart(3, "0")}`),
            el("div", { style: "flex:1; min-width:0" },
              el("div", { style: "font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap" }, e.title),
              el("div", { class: "muted", style: "font-size:11.5px" }, fmtWhen(e.updated_at))),
            statusPill(e.status))))
    : emptyState({
        big: "No episodes in progress",
        small: "EP-001 “The Great Moonberry Bounce” is seeded in the database — the Episodes workspace arrives in the next Phase 1 step.",
      });

  return el("div", { class: "card" },
    el("h3", {}, "Episodes in Progress",
      el("span", { class: "pill s-outline" }, String(episodes.length))),
    body);
}

/* ------------------ assets ------------------ */
function assetsPanel(assets) {
  const body = assets.length
    ? el("div", { class: "grid cols-auto" },
        ...assets.slice(0, 6).map((a) =>
          el("div", { class: "asset-tile", onclick: () => location.hash = "#/assets" },
            assetThumb(a),
            el("div", { class: "asset-meta" },
              el("div", { class: "t" }, a.title),
              el("div", { class: "s" }, `${pretty(a.category)} · ${fmtBytes(a.byte_size)}`)))))
    : emptyState({
        big: "No assets yet",
        small: "Upload Meta AI artwork or scan the repository for existing files once the Assets library ships in the next Phase 1 step.",
      });

  return el("div", { class: "card" },
    el("h3", {}, "Recent Assets",
      el("span", { class: "pill s-outline" }, String(assets.length))),
    body);
}

/* ------------------ characters strip ------------------ */
function charactersFooter(stats) {
  return el("div", { class: "card", style: "margin-top:4px" },
    el("div", { style: "display:flex; align-items:center; gap:12px; flex-wrap:wrap" },
      el("span", { html: ICONS.characters, style: "color:var(--moss); display:inline-flex" }),
      el("div", { style: "flex:1; min-width:220px" },
        el("b", {}, `${stats.characters} canon character${s(stats.characters)} imported`),
        el("div", { class: "muted", style: "font-size:12.5px" },
          "Character bibles are seeded from the series bible records. Creator artwork folders stay protected and read-only.")),
      el("a", { class: "btn small", href: "#/characters" }, "View Characters")));
}
