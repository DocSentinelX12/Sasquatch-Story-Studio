// Application shell: hash router, sidebar navigation, topbar, project context.
import { el, ICONS, toast } from "./ui.js";
import { getJSON } from "./api.js";

const nav = [
  {
    label: "Production",
    items: [
      { path: "#/dashboard", title: "Dashboard", icon: "dashboard" },
      { path: "#/assistant", title: "Assistant", icon: "spark" },
      { path: "#/story", title: "Story", icon: "story" },
      { path: "#/projects", title: "Projects", icon: "projects" },
      { path: "#/episodes", title: "Episodes", icon: "episodes" },
      { path: "#/scenes", title: "Scenes", icon: "scenes" },
      { path: "#/characters", title: "Characters", icon: "characters" },
      { path: "#/assets", title: "Assets", icon: "assets" },
      { path: "#/world", title: "Locations & Props", icon: "folder" },
    ],
  },
  {
    label: "Scene Work",
    items: [
      { path: "#/shots", title: "Shots", icon: "shots", soon: "P4" },
      { path: "#/queue", title: "Generation Queue", icon: "queue" },
    ],
  },
  {
    label: "Post & Delivery",
    items: [
      { path: "#/audio", title: "Audio", icon: "audio" },
      { path: "#/timeline", title: "Timeline", icon: "timeline" },
      { path: "#/exports", title: "Exports", icon: "exports" },
    ],
  },
  {
    label: "Studio",
    items: [
      { path: "#/settings", title: "Settings", icon: "settings" },
    ],
  },
];

const views = new Map(); // path → async render(container, params)
const paramRoutes = []; // {prefix, load} → load(container, id, params)

function registerViews() {
  views.set("/dashboard", async (c, p) => {
    const mod = await import("./views/dashboard.js");
    await mod.render(c, p);
  });
  views.set("/story", async (c, p) => {
    const mod = await import("./views/story.js");
    await mod.render(c, p);
  });
  views.set("/episodes", async (c, p) => {
    const mod = await import("./views/episodes.js");
    await mod.render(c, p);
  });
  views.set("/scenes", async (c, p) => {
    const mod = await import("./views/scenes.js");
    await mod.render(c, p);
  });
  views.set("/world", async (c, p) => {
    const mod = await import("./views/world.js");
    await mod.render(c, p);
  });
  views.set("/search", async (c, p) => {
    const mod = await import("./views/search.js");
    await mod.render(c, p);
  });
  views.set("/characters", async (c, p) => {
    const mod = await import("./views/characters.js");
    await mod.render(c, p);
  });
  views.set("/assets", async (c, p) => {
    const mod = await import("./views/assets.js");
    await mod.render(c, p);
  });
  views.set("/projects", placeholderRoute("projects"));
  views.set("/queue", async (c, p) => {
    const mod = await import("./views/queue.js");
    await mod.render(c, p);
  });
  views.set("/assistant", async (c, p) => {
    const mod = await import("./views/assistant.js");
    await mod.render(c, p);
  });
  views.set("/settings", async (c, p) => {
    const mod = await import("./views/settings.js");
    await mod.render(c, p);
  });
  views.set("/audio", async (c, p) => {
    const mod = await import("./views/audio.js");
    await mod.render(c, p);
  });
  views.set("/timeline", async (c, p) => {
    const mod = await import("./views/timeline.js");
    await mod.render(c, p);
  });
  views.set("/exports", async (c, p) => {
    const mod = await import("./views/exports.js");
    await mod.render(c, p);
  });
  views.set("/shots", async (c, p) => {
    const mod = await import("./views/shots.js");
    await mod.render(c, p);
  });
  for (const key of []) {
    views.set(`/${key}`, phasePlaceholderRoute(key));
  }
  paramRoutes.push({
    prefix: "/characters/",
    load: async (container, id, params) => {
      const mod = await import("./views/character-detail.js");
      await mod.render(container, Number(id), params);
    },
  });
  paramRoutes.push({
    prefix: "/stories/",
    load: async (container, id, params) => {
      const mod = await import("./views/story-detail.js");
      await mod.render(container, Number(id), params);
    },
  });
  paramRoutes.push({
    prefix: "/episodes/",
    load: async (container, id, params) => {
      const mod = await import("./views/episode-detail.js");
      await mod.render(container, Number(id), params);
    },
  });
  paramRoutes.push({
    prefix: "/scenes/",
    match: "/director",
    load: async (container, id, params) => {
      const mod = await import("./views/scene-director.js");
      await mod.render(container, Number(id), params);
    },
  });
  paramRoutes.push({
    prefix: "/generate/",
    load: async (container, id, params) => {
      const mod = await import("./views/generate.js");
      await mod.render(container, Number(id), params);
    },
  });
}

const PLACEHOLDER_COPY = {
  projects: {
    title: "Projects",
    summary: "The project workspace (series, seasons, episode rosters) is wired to the API and arrives in the next Phase 1 step.",
    points: ["Multiple series without mixing assets", "Season and episode tracking", "Per-project asset scoping"],
  },
  episodes: {
    title: "Episodes",
    summary: "The episode production workspace arrives in the next Phase 1 step. The database already stores episodes, acts, scenes and shots — EP-001 is seeded.",
    points: ["Episode → Acts → Scenes → Shots", "Read-only canon view of EP-001", "Scene and shot builders land in Phase 2"],
  },
  characters: {
    title: "Characters",
    summary: "The Character Bible browser arrives in the next Phase 1 step. Five canon characters are already imported from the series bible.",
    points: ["Character bibles with canon records", "Reference image import from assets/characters/source/", "Approval-first reference workflow"],
  },
  assets: {
    title: "Asset Library",
    summary: "The full asset browser (upload, search, filters, versioning, approvals) arrives in the next Phase 1 step.",
    points: ["Upload Meta AI artwork as production assets", "Register existing repo files in place", "Versioning — old versions are never deleted"],
  },
  queue: {
    title: "Generation Queue",
    summary: "The generation queue view arrives in the next Phase 1 step. The job ledger and provider status API are already live.",
    points: ["Draft → Queued → Generating → Completed → Review", "Honest provider states — no fake generations", "Structured errors with missing-credential detail"],
  },
  settings: {
    title: "Settings",
    summary: "The settings screen arrives in the next Phase 1 step. Provider credentials already live server-side only.",
    points: ["Provider configuration and status", "Storage locations", "Canon content validation"],
  },
};

const PHASE2_COPY = {
  shots: { title: "Shots", summary: "Shot builder with camera direction, reference packages and generation settings.", phase: "Phase 4" },
  audio: { title: "Audio", summary: "Voice, music, sound effects and ambience workspaces.", phase: "a later phase" },
  timeline: { title: "Timeline", summary: "Lightweight episode timeline editor with tracks, trimming and transitions.", phase: "a later phase" },
  exports: { title: "Exports", summary: "Export workflows for full episodes, trailers and vertical shorts.", phase: "a later phase" },
};

function placeholderRoute(key) {
  return async (container) => renderPlaceholder(container, { ...PLACEHOLDER_COPY[key], badge: "Next in Phase 1" });
}
function phasePlaceholderRoute(key) {
  return async (container) => renderPlaceholder(container, { ...PHASE2_COPY[key], badge: "Coming in a later production phase" });
}

function renderPlaceholder(container, { title, summary, points, phase, badge }) {
  const { emptyState } = window.__ui;
  container.append(
    el("div", { class: "page-head" }, el("div", {},
      el("h2", {}, title),
      el("div", { class: "desc" }, summary))),
    emptyState({
      big: `${badge}`,
      small: phase ? `Planned for ${phase}. The navigation, database and API foundations are ready for it now.` :
        "This screen is intentionally not simulated. The database tables and API routes for it already exist.",
      actions: [
        el("a", { class: "btn ghost small", href: "#/dashboard" }, "← Back to Dashboard"),
        el("a", { class: "btn ghost small", href: "https://github.com/DocSentinelX12/Sasquatch-Story-Studio/blob/main/docs/IMPLEMENTATION_PLAN.md", target: "_blank" }, "Implementation plan"),
      ],
    }),
    points ? el("div", { class: "card", style: "margin-top:14px" },
      el("h3", {}, "What this area will include"),
      el("ul", { style: "margin:0; padding-left:18px; color:var(--text-dim); font-size:13px" },
        ...points.map((p) => el("li", { style: "margin-bottom:5px" }, p)))) : null,
  );
}

/* ---------- Router ---------- */
function currentPath() {
  const hash = location.hash || "#/dashboard";
  return hash.replace(/^#/, "") || "/dashboard";
}

let currentTitle = "Dashboard";

async function route() {
  const path = currentPath();
  const clean = path.split("?")[0].split("/").filter(Boolean).join("/");
  const key = `/${clean || "dashboard"}`;
  const params = new URLSearchParams(path.split("?")[1] || "");
  const content = document.getElementById("content");
  content.scrollTop = 0;
  content.replaceChildren();

  // exact route or param route (/characters/<id> …)
  let view = views.get(key);
  let paramLoad = null, paramId = null;
  if (!view) {
    for (const candidate of paramRoutes) {
      if (key.startsWith(candidate.prefix)) {
        const remainder = key.slice(candidate.prefix.length);
        if (candidate.match) {
          // pattern: prefix<id>/suffix
          const [idPart, ...rest] = remainder.split("/");
          if (idPart && /^\d+$/.test(idPart) && rest.join("/") === candidate.match.slice(1)) {
            paramLoad = candidate.load;
            paramId = idPart;
            break;
          }
        } else if (/^\d+$/.test(remainder)) {
          paramLoad = candidate.load;
          paramId = remainder;
          break;
        }
      }
    }
  }

  // nav active state (param routes highlight their section)
  const sectionKey = paramLoad ? `/${key.split("/").filter(Boolean)[0]}` : key;
  void sectionKey;
  document.querySelectorAll("#nav a").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("href") === `#${sectionKey}`);
  });
  // breadcrumb
  const item = nav.flatMap((g) => g.items).find((i) => i.path === `#${sectionKey}`);
  currentTitle = item?.title || "Studio";
  document.getElementById("crumb").replaceChildren(el("b", {}, currentTitle));
  document.getElementById("sidebar").classList.remove("open");

  if (!view && !paramLoad) {
    location.hash = "#/dashboard";
    return;
  }
  try {
    if (view) await view(content, params);
    else await paramLoad(content, paramId, params);
  } catch (error) {
    const { errorState } = window.__ui;
    content.replaceChildren(errorState(error, () => route()));
  }
}

/* ---------- Sidebar / topbar ---------- */
function renderNav() {
  const navEl = document.getElementById("nav");
  navEl.replaceChildren();
  for (const group of nav) {
    navEl.append(el("div", { class: "nav-label" }, group.label));
    for (const item of group.items) {
      navEl.append(el("a", { href: item.path },
        el("span", { html: ICONS[item.icon] }),
        item.title,
        item.soon ? el("span", { class: "pill-soon" }, item.soon) : null));
    }
  }
}

async function renderProjectPicker() {
  const search = el("input", {
    type: "search", placeholder: "Search studio…", id: "global-search",
    style: "max-width:210px",
    onkeydown: (e) => {
      if (e.key === "Enter" && e.target.value.trim().length >= 2) {
        location.hash = `#/search?q=${encodeURIComponent(e.target.value.trim())}`;
      }
    },
  });
  const holder = document.getElementById("project-pick");
  try {
    const data = await getJSON("/api/projects");
    const projects = data.projects || [];
    if (projects.length === 0) {
      holder.replaceChildren(search, el("span", { class: "pill s-outline" }, "No project yet"));
      return;
    }
    const saved = localStorage.getItem("studio.projectId");
    let current = projects.find((p) => String(p.id) === saved) || projects[0];
    const select = el("select", {
      style: "max-width:230px",
      onchange: (e) => {
        localStorage.setItem("studio.projectId", e.target.value);
        toast(`Switched to “${projects.find((p) => String(p.id) === e.target.value)?.name}”`, "info", "Project context");
        route();
      },
    },
      projects.map((p) => el("option", { value: p.id, selected: String(p.id) === String(current.id) ? "" : null }, p.name)));
    localStorage.setItem("studio.projectId", String(current.id));
    holder.replaceChildren(search, select);
  } catch {
    holder.replaceChildren(search, el("span", { class: "pill s-red" }, "Server unreachable"));
  }
}

function bindMobileToggle() {
  const toggle = document.getElementById("nav-toggle");
  const show = () => { toggle.style.display = window.innerWidth <= 820 ? "inline-flex" : "none"; };
  window.addEventListener("resize", show);
  show();
  toggle.addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
}

/* ---------- Boot ---------- */
async function boot() {
  // expose ui helpers for view modules loaded dynamically
  const ui = await import("./ui.js");
  window.__ui = ui;
  registerViews();
  renderNav();
  bindMobileToggle();
  await renderProjectPicker();
  window.addEventListener("hashchange", route);
  await route();
}

boot();
