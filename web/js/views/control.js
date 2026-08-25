// Production Control Center: automation rules, notifications, series, templates, backups.
import { el, ICONS, statusPill, pretty, loadingState, errorState, toast, openModal, field, fmtWhen } from "../ui.js";
import { getJSON, postJSON, patchJSON } from "../api.js";

let container;
let tab = "automation";

export async function render(c, params = new URLSearchParams()) {
  container = c;
  tab = params.get("tab") || "automation";
  draw();
}

function draw() {
  const { tabBar } = window.__ui;
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {}, el("h2", {}, "Control Center"),
        el("div", { class: "desc" }, "Automation, notifications, series, templates and backups. Automation may prepare or queue work — it never approves creative content and never publishes."))),
    tabBar([
      { id: "automation", label: "Automation" },
      { id: "notifications", label: "Notifications" },
      { id: "series", label: "Series" },
      { id: "templates", label: "Templates" },
      { id: "backups", label: "Backups" },
    ], tab, (id) => { tab = id; location.hash = `#/control?tab=${id}`; draw(); }));
  const panel = el("div", {});
  container.append(panel);
  if (tab === "automation") automationPanel(panel);
  else if (tab === "notifications") notificationsPanel(panel);
  else if (tab === "series") seriesPanel(panel);
  else if (tab === "templates") templatesPanel(panel);
  else backupsPanel(panel);
}

/* ---------------- automation ---------------- */
async function automationPanel(panel) {
  panel.append(loadingState("Loading rules…"));
  const projectId = Number(localStorage.getItem("studio.projectId")) || null;
  try {
    const data = await getJSON(`/api/automation/rules${projectId ? `?project_id=${projectId}` : ""}`);
    panel.replaceChildren(
      el("div", { class: "callout", style: "font-size:12px; margin-bottom:12px" }, data.safety),
      el("div", { style: "display:flex; gap:8px; margin-bottom:12px" },
        el("button", { class: "btn small primary", onclick: () => ruleModal(null, data) }, el("span", { html: ICONS.plus }), "New Rule"),
        el("button", { class: "btn small ghost", onclick: showHistory }, "View history")));
    for (const rule of data.rules) {
      panel.append(el("div", { class: "card", style: "padding:12px 14px; margin-bottom:9px" },
        el("div", { style: "display:flex; gap:9px; align-items:center; flex-wrap:wrap" },
          el("b", {}, rule.name),
          statusPill(rule.enabled ? "approved" : "draft", rule.enabled ? "Enabled" : "Disabled"),
          rule.dry_run ? el("span", { class: "pill s-purple" }, "dry-run") : null,
          el("span", { class: "pill s-outline" }, `WHEN ${pretty(rule.trigger)}`),
          el("span", { class: "muted", style: "font-size:11px" }, `ran ${rule.run_count}×`)),
        el("div", { class: "muted", style: "font-size:12px; margin:6px 0" },
          rule.description || (rule.actions || []).map((a) => typeof a === "string" ? a : a.action).join(" → ")),
        el("div", { style: "display:flex; gap:6px; flex-wrap:wrap" },
          el("button", { class: "btn small", onclick: async () => {
            await patchJSON(`/api/automation/rules/${rule.id}`, { enabled: !rule.enabled });
            toast(rule.enabled ? "Rule disabled." : "Rule enabled.", "ok"); draw();
          } }, rule.enabled ? "Disable" : "Enable"),
          el("button", { class: "btn small ghost", onclick: async () => {
            const audit = await postJSON(`/api/automation/rules/${rule.id}/run`, { dry_run: true });
            toast(`Dry-run: ${JSON.stringify(audit.actions_taken?.[0]?.result || "").slice(1, 90)}`, "info", "Test rule");
          } }, "Test (dry-run)"),
          el("button", { class: "btn small ghost", onclick: async () => {
            const audit = await postJSON(`/api/automation/rules/${rule.id}/run`, {});
            toast("Run complete — see history.", "ok");
          } }, "Run now"),
          el("button", { class: "btn small ghost", onclick: () => ruleModal(rule, data) }, "Edit"))));
    }
  } catch (error) { panel.replaceChildren(errorState(error, () => automationPanel(panel))); }
}

function ruleModal(rule, vocab) {
  const name = el("input", { type: "text", value: rule?.name || "", placeholder: "Rule name" });
  const description = el("input", { type: "text", value: rule?.description || "", placeholder: "What it does" });
  const trigger = el("select", {}, vocab.triggers.map((t) => el("option", { value: t, selected: rule?.trigger === t ? "" : null }, pretty(t))));
  const action1 = el("select", {}, vocab.actions.map((a) => el("option", { value: a, selected: rule?.actions?.[0]?.action === a ? "" : null }, pretty(a))));
  const dryRun = el("input", { type: "checkbox" });
  const priority = el("input", { type: "number", value: String(rule?.priority ?? 5) });
  openModal({
    title: rule ? `Edit: ${rule.name}` : "New automation rule", wide: true,
    sub: "Automation may PREPARE or QUEUE work only — never approve or publish.",
    body: el("div", {},
      field("Name *", name), field("Description", description),
      el("div", { class: "form-row" }, field("WHEN (trigger)", trigger), field("THEN (action)", action1)),
      el("div", { class: "form-row" }, field("Priority (lower = first)", priority),
        el("div", { class: "field" }, el("label", {}, "Dry-run mode"), dryRun))),
    actions: [
      { label: "Cancel" },
      { label: rule ? "Save" : "Create (disabled)", kind: "primary", keepOpen: true, onClick: async () => {
        const payload = { name: name.value.trim(), description: description.value.trim() || null,
          trigger: trigger.value, actions: [{ action: action1.value }],
          priority: parseInt(priority.value) || 5, dry_run: dryRun.checked };
        if (!payload.name) return toast("Name required.", "warn");
        if (rule) await patchJSON(`/api/automation/rules/${rule.id}`, payload);
        else await postJSON("/api/automation/rules", { ...payload, enabled: false });
        document.querySelector(".modal-backdrop")?.remove();
        toast("Rule saved (enable it when ready).", "ok"); draw();
      } },
    ],
  });
}

async function showHistory() {
  const hist = await getJSON("/api/automation/history?limit=50");
  openModal({
    title: "Automation history (nothing hidden)", wide: true,
    body: el("pre", { class: "code", style: "max-height:420px" },
      JSON.stringify(hist.history.map((h) => ({
        when: h.created_at?.slice(0, 19).replace("T", " "), rule: h.rule_name,
        trigger: h.trigger_event, target: h.target, dry_run: h.dry_run,
        outcome: h.outcome, actions: h.actions_taken })), null, 2)),
    actions: [{ label: "Close" }],
  });
}

/* ---------------- notifications ---------------- */
async function notificationsPanel(panel) {
  panel.append(loadingState("Loading…"));
  try {
    const data = await getJSON("/api/notifications");
    panel.replaceChildren();
    if (!data.notifications.length) {
      panel.append(el("div", { class: "empty" }, el("div", { class: "big" }, "No notifications"),
        el("div", { class: "small" }, "Automation events and warnings appear here.")));
      return;
    }
    for (const note of data.notifications) {
      panel.append(el("div", { class: "card", style: `padding:11px 14px; margin-bottom:8px; ${note.read ? "opacity:.6" : ""}` },
        el("div", { style: "display:flex; gap:9px; align-items:center" },
          el("span", { class: `pill ${note.kind === "warning" ? "s-amber" : note.kind === "blocker" ? "s-red" : "s-blue"}` }, pretty(note.kind)),
          el("span", { style: "flex:1" }, note.message),
          note.link ? el("a", { href: note.link, class: "btn small ghost", style: "text-decoration:none" }, "Open") : null,
          !note.read ? el("button", { class: "btn small ghost", onclick: async () => {
            await postJSON(`/api/notifications/${note.id}/read`); draw();
          } }, "✓") : null)));
    }
  } catch (error) { panel.replaceChildren(errorState(error, () => notificationsPanel(panel))); }
}

/* ---------------- series ---------------- */
async function seriesPanel(panel) {
  panel.append(loadingState("Loading series…"));
  try {
    const [projects, iso] = await Promise.all([
      getJSON("/api/projects"), getJSON("/api/series/isolation-check")]);
    panel.replaceChildren(
      el("div", { class: "callout info", style: "font-size:12px; margin-bottom:12px" },
        "Each series is fully isolated: its own bible, canon, characters, episodes, assets and generation history never cross series.",
        iso.problems.length ? ` ⚠ ${iso.problems.length} isolation issue(s).` : " Isolation check: clean."),
      el("button", { class: "btn primary", style: "margin-bottom:12px", onclick: newSeriesModal }, el("span", { html: ICONS.plus }), "New Series"));
    for (const project of projects.projects) {
      panel.append(el("div", { class: "card", style: "padding:12px 14px; margin-bottom:9px; display:flex; gap:10px; align-items:center; flex-wrap:wrap" },
        el("b", {}, project.name), statusPill(project.status),
        el("span", { class: "pill s-outline" }, `${project.counts.episodes} episodes`),
        el("span", { class: "pill s-outline" }, `${project.counts.characters} characters`),
        String(project.id) === localStorage.getItem("studio.projectId")
          ? el("span", { class: "pill s-green", style: "margin-left:auto" }, "active") 
          : el("button", { class: "btn small", style: "margin-left:auto", onclick: () => {
            localStorage.setItem("studio.projectId", String(project.id));
            toast(`Switched to “${project.name}”.`, "ok", "Series"); location.hash = "#/dashboard";
          } }, "Switch")));
    }
  } catch (error) { panel.replaceChildren(errorState(error, () => seriesPanel(panel))); }
}

function newSeriesModal() {
  const name = el("input", { type: "text", placeholder: "e.g. Future Cartoon Series" });
  const premise = el("textarea", { placeholder: "Series premise" });
  openModal({
    title: "New series",
    sub: "An independent cartoon series with its own bible, characters and episodes.",
    body: el("div", {}, field("Name *", name), field("Premise", premise)),
    actions: [
      { label: "Cancel" },
      { label: "Create", kind: "primary", onClick: async (e, close) => {
        if (!name.value.trim()) return toast("Name required.", "warn");
        const result = await postJSON("/api/series", { name: name.value.trim(), series_premise: premise.value.trim() });
        close();
        localStorage.setItem("studio.projectId", String(result.series.id));
        toast(`Series “${result.series.name}” created and activated.`, "ok");
        location.hash = "#/dashboard";
      } },
    ],
  });
}

/* ---------------- templates ---------------- */
async function templatesPanel(panel) {
  panel.append(loadingState("Loading templates…"));
  try {
    const [templates, episodes] = await Promise.all([
      getJSON("/api/templates"), getJSON("/api/episodes")]);
    panel.replaceChildren(
      el("button", { class: "btn primary", style: "margin-bottom:12px", onclick: () => templateModal(episodes.episodes) },
        el("span", { html: ICONS.plus }), "New Template from Episode"));
    if (!templates.templates.length) {
      panel.append(el("div", { class: "empty" }, el("div", { class: "big" }, "No templates"),
        el("div", { class: "small" }, "Capture an episode's act/scene/shot/script structure, then instantiate it as drafts for new episodes.")));
    }
    for (const template of templates.templates) {
      const sceneCount = template.structure?.scenes?.length || 0;
      const shotCount = (template.structure?.scenes || []).reduce((n, s) => n + (s.shots || []).length, 0);
      panel.append(el("div", { class: "card", style: "padding:12px 14px; margin-bottom:9px; display:flex; gap:10px; align-items:center; flex-wrap:wrap" },
        el("b", {}, template.name),
        el("span", { class: "pill s-outline" }, `${sceneCount} scenes · ${shotCount} shots`),
        el("span", { class: "muted", style: "font-size:11.5px" }, template.description || ""),
        el("button", { class: "btn small primary", style: "margin-left:auto", onclick: async () => {
          const result = await postJSON(`/api/templates/${template.id}/instantiate`);
          toast(`Draft episode “${result.episode.title}” created — everything starts as draft.`, "ok");
          location.hash = `#/episodes/${result.episode.id}`;
        } }, "Instantiate")));
    }
  } catch (error) { panel.replaceChildren(errorState(error, () => templatesPanel(panel))); }
}

function templateModal(episodes) {
  const name = el("input", { type: "text", placeholder: "Template name" });
  const source = el("select", {}, el("option", { value: "" }, "— none (empty template) —"),
    episodes.map((e) => el("option", { value: e.id }, `EP ${String(e.number).padStart(3, "0")} — ${e.title}`)));
  openModal({
    title: "Capture episode template",
    body: el("div", {}, field("Name *", name), field("Source episode", source)),
    actions: [
      { label: "Cancel" },
      { label: "Capture", kind: "primary", onClick: async (e, close) => {
        if (!name.value.trim()) return toast("Name required.", "warn");
        await postJSON("/api/templates", { name: name.value.trim(),
          project_id: Number(localStorage.getItem("studio.projectId")) || null,
          source_episode_id: source.value ? Number(source.value) : null });
        close(); toast("Template captured.", "ok"); draw();
      } },
    ],
  });
}

/* ---------------- backups ---------------- */
async function backupsPanel(panel) {
  panel.append(loadingState("Loading series…"));
  try {
    const projects = await getJSON("/api/projects");
    panel.replaceChildren(
      el("div", { class: "callout", style: "font-size:12px; margin-bottom:12px" },
        "Backups export the complete series (bible, canon, characters, episodes, scenes, shots, script, timeline, generation history, exports) as JSON. ",
        el("b", {}, "Media files are referenced by path, not embedded"), " — back up assets/ and renders/ folders separately (e.g. with git or your file backup)."));
    for (const project of projects.projects) {
      panel.append(el("div", { class: "card", style: "padding:12px 14px; margin-bottom:9px; display:flex; gap:10px; align-items:center" },
        el("b", {}, project.name),
        el("button", { class: "btn small primary", style: "margin-left:auto", onclick: () => {
          const url = `/api/series/${project.id}/backup`;
          const link = el("a", { href: url, download: `${project.slug}-backup.json` });
          document.body.append(link); link.click(); link.remove();
          toast("Backup download started.", "ok");
        } }, "Download JSON backup")));
    }
  } catch (error) { panel.replaceChildren(errorState(error, () => backupsPanel(panel))); }
}
