// Generation Queue — jobs with live status, results with video review.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast, openModal, fmtWhen,
} from "../ui.js";
import { getJSON, postJSON } from "../api.js";

let container;
let tab = "queue";
let timer = null;

export async function render(c) {
  container = c;
  if (!render._bound) {
    render._bound = true;
    window.addEventListener("hashchange", () => {
      if (timer) { clearInterval(timer); timer = null; }
    });
  }
  draw();
}

function draw() {
  const { tabBar } = window.__ui;
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("h2", {}, "Generation Queue"),
        el("div", { class: "desc" },
          "Draft → Queued → Submitting → Submitted → Generating → Needs Review → Approved. Nothing is submitted to a provider without your action."))),
    tabBar([{ id: "queue", label: "Jobs" }, { id: "review", label: "Video Review" }], tab, (id) => { tab = id; draw(); }));
  if (tab === "queue") renderJobs();
  else renderReview();
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    if (tab === "queue" && document.contains(container)) refreshJobsQuietly();
  }, 5000);
}

/* ---------------- jobs ---------------- */
let jobsData = null;

async function renderJobs() {
  const panel = el("div", {}, loadingState("Loading jobs…"));
  container.append(panel);
  await fetchJobs(panel);
}

async function refreshJobsQuietly() {
  const panel = container.querySelector(".queue-panel");
  if (!panel) return;
  try {
    const data = await getJSON("/api/generation/jobs?limit=100");
    jobsData = data;
    const counts = data.counts_by_status || {};
    const strip = panel.querySelector(".counts");
    if (strip) strip.replaceChildren(...Object.entries(counts).map(([k, v]) => statusPill(k, `${pretty(k)} · ${v}`)));
    const tbody = panel.querySelector("tbody");
    if (tbody) fillJobRows(tbody, data.jobs);
    const cardList = panel.querySelector(".queue-cards");
    if (cardList) fillJobCards(cardList, data.jobs);
  } catch { /* server unreachable — keep last state */ }
}

async function fetchJobs(panel) {
  try {
    jobsData = await getJSON("/api/generation/jobs?limit=100");
    panel.replaceChildren();
    renderJobTable(panel);
  } catch (error) {
    panel.replaceChildren(errorState(error, () => fetchJobs(panel)));
  }
}

function renderJobTable(panel) {
  const counts = jobsData.counts_by_status || {};
  const strip = el("div", { class: "counts filter-bar" },
    ...Object.entries(counts).map(([k, v]) => statusPill(k, `${pretty(k)} · ${v}`)));
  const table = el("div", { class: "table-wrap" },
    el("table", { class: "data" },
      el("thead", {}, el("tr", {},
        el("th", {}, "Job"), el("th", {}, "Shot"), el("th", {}, "Provider"), el("th", {}, "Status"),
        el("th", {}, "Provider job"), el("th", {}, "Error"), el("th", {}, "Updated"), el("th", {}, "Actions"))),
      el("tbody", {})));
  const cards = el("div", { class: "queue-cards" });
  panel.className = "queue-panel";
  panel.append(strip, cards, table);
  fillJobRows(table.querySelector("tbody"), jobsData.jobs);
  fillJobCards(cards, jobsData.jobs);
  if (!jobsData.jobs.length) {
    panel.append(emptyState({ big: "No generation jobs yet",
      small: "Open a Scene Director, approve a shot, and use Generate." }));
  }
}

function fillJobRows(tbody, jobs) {
  tbody.replaceChildren();
  for (const job of jobs) {
    const row = el("tr", { class: "clickable", onclick: () => jobModal(job) },
      el("td", {}, `#${job.id} · a${job.attempt}`),
      el("td", {}, job.shot_ref || `shot ${job.shot_id}`),
      el("td", {}, job.provider_key === "test-echo" ? "TEST adapter" : pretty(job.provider_key || "")),
      el("td", {}, statusPill(job.status)),
      el("td", { style: "font-family:var(--mono); font-size:11px" }, job.provider_job_id || "—"),
      el("td", { style: `color:${job.error ? "var(--red)" : "inherit"}; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap` },
        job.error ? `${job.error_code || "error"}: ${job.error.slice(0, 60)}` : "—"),
      el("td", { style: "color:var(--text-faint)" }, fmtWhen(job.updated_at)),
      el("td", { onclick: (e) => e.stopPropagation() }, jobActions(job)));
    tbody.append(row);
  }
}

function fillJobCards(holder, jobs) {
  holder.replaceChildren();
  for (const job of jobs) {
    const active = ["submitting", "submitted", "generating"].includes(job.status);
    holder.append(el("div", { class: "queue-card" },
      el("div", { class: "row1" },
        el("div", { class: "thumb" }, job.result_id
          ? el("img", { src: `/api/generation/results/${job.result_id}/file#t=0.5`, loading: "lazy", alt: "" })
          : el("span", {}, "🎬")),
        el("div", { style: "flex:1; min-width:0" },
          el("div", { style: "font-weight:650" }, job.shot_ref || `Shot ${job.shot_id}`, " · attempt ", String(job.attempt)),
          el("div", { class: "muted", style: "font-size:11.5px" },
            (job.provider_key === "test-echo" ? "TEST adapter" : pretty(job.provider_key || ""))
            + (job.settings?.duration_seconds ? ` · ${job.settings.duration_seconds}s` : ""))),
        statusPill(job.status)),
      active ? el("div", { class: "progress-track", style: "margin-bottom:8px" },
        el("div", { class: "progress-fill", style: `width:${job.status === "generating" ? 55 : 25}%` })) : null,
      job.error ? el("div", { style: "color:var(--red); font-size:11.5px; margin-bottom:6px" },
        `${job.error_code || "error"}: ${job.error.slice(0, 80)}`) : null,
      el("div", { class: "actions" }, cardActions(job))));
  }
  if (!jobs.length) {
    holder.append(emptyState({ big: "No generation jobs yet", small: "Open a shot and tap Generate." }));
  }
}

function cardActions(job) {
  const wrap = el("div", { style: "display:flex; gap:7px; flex-wrap:wrap" });
  const goToGenerate = () => { location.hash = job.shot_id ? `#/generate/${job.shot_id}` : "#/queue"; };
  if (job.status === "draft") {
    wrap.append(el("button", { class: "btn small primary", onclick: async () => {
      try { await postJSON(`/api/generation/jobs/${job.id}/submit`); toast("Submitted.", "ok"); }
      catch (error) { toast(error.message, "error", "Submit refused"); }
      refreshNow();
    } }, "Submit"));
  }
  if (active(job) ) {
    wrap.append(el("button", { class: "btn small ghost", onclick: async () => {
      await postJSON(`/api/generation/jobs/${job.id}/cancel`); toast("Cancelled.", "ok"); refreshNow();
    } }, "Cancel"));
  }
  if (["failed", "cancelled", "rejected"].includes(job.status)) {
    wrap.append(el("button", { class: "btn small", onclick: async () => {
      try {
        const retry = await postJSON(`/api/generation/jobs/${job.id}/retry`, {});
        toast(`New attempt #${retry.attempt}.`, "ok"); refreshNow();
      } catch (error) { toast(error.message, "error"); }
    } }, "Retry"));
  }
  wrap.append(el("button", { class: "btn small", onclick: goToGenerate }, job.result_id ? "Review" : "Open"));
  return wrap;
}

const active = (job) => ["draft", "queued", "submitting", "submitted", "generating"].includes(job.status);

function jobActions(job) {
  const wrap = el("div", { style: "display:flex; gap:4px" });
  if (job.status === "draft") {
    wrap.append(el("button", { class: "btn small primary", onclick: async () => {
      try {
        await postJSON(`/api/generation/jobs/${job.id}/submit`);
        toast("Submitted — polling asynchronously.", "ok");
      } catch (error) { toast(error.message, "error", "Submit refused"); }
      refreshNow();
    } }, "Submit"));
  }
  if (["failed", "cancelled", "rejected"].includes(job.status)) {
    wrap.append(el("button", { class: "btn small", onclick: async () => {
      try {
        const retry = await postJSON(`/api/generation/jobs/${job.id}/retry`, {});
        toast(`New attempt #${retry.attempt} created (failed attempt kept).`, "ok");
        jobModal(retry);
      } catch (error) { toast(error.message, "error"); }
      refreshNow();
    } }, "Retry"));
  }
  if (["draft", "queued", "submitting", "submitted", "generating"].includes(job.status)) {
    wrap.append(el("button", { class: "btn small ghost", onclick: async () => {
      await postJSON(`/api/generation/jobs/${job.id}/cancel`);
      toast("Job cancelled.", "ok"); refreshNow();
    } }, "Cancel"));
  }
  return wrap;
}

async function refreshNow() {
  const panel = container.querySelector(".queue-panel");
  if (panel) await fetchJobs(panel);
}

function jobModal(job) {
  openModal({
    title: `Generation job #${job.id} — attempt ${job.attempt}`,
    sub: `${job.shot_ref || "shot"} · ${pretty(job.provider_key)} · ${pretty(job.status)}`,
    wide: true,
    body: el("div", {},
      el("dl", { class: "kv", style: "margin-bottom:12px" },
        el("dt", {}, "Provider job id"), el("dd", {}, job.provider_job_id || "—"),
        el("dt", {}, "Status"), el("dd", {}, pretty(job.status)),
        el("dt", {}, "Error"), el("dd", { style: "color:var(--red)" }, job.error || "—"),
        el("dt", {}, "Usage"), el("dd", {}, JSON.stringify(job.usage || {})),
        el("dt", {}, "Submitted"), el("dd", {}, job.submitted_at || "—"),
        el("dt", {}, "Completed"), el("dd", {}, job.completed_at || "—")),
      el("h3", { style: "font-size:13px; margin-bottom:6px" }, "Exact provider-translated request"),
      el("pre", { class: "code", style: "max-height:300px" }, JSON.stringify(job.translated_request, null, 2) || "—")),
    actions: [{ label: "Close" }],
  });
}

/* ---------------- video review ---------------- */
async function renderReview() {
  const panel = el("div", {}, loadingState("Loading results…"));
  container.append(panel);
  try {
    const data = await getJSON("/api/generation/results?limit=100");
    panel.replaceChildren();
    if (!data.results.length) {
      panel.append(emptyState({ big: "No generated results yet",
        small: "Results appear here after a generation completes — for review, never auto-approved." }));
      return;
    }
    const byShot = new Map();
    for (const result of data.results) {
      if (!byShot.has(result.shot_id)) byShot.set(result.shot_id, []);
      byShot.get(result.shot_id).push(result);
    }
    for (const [shotId, results] of byShot) {
      const block = el("div", { class: "scene-block" },
        el("h4", {}, el("span", { class: "pill s-outline" }, results[0].shot_ref || `shot ${shotId}`),
          " Versions", el("span", { class: "pill s-outline" }, String(results.length))));
      for (const result of results) {
        block.append(resultCard(result));
      }
      panel.append(block);
    }
  } catch (error) {
    panel.replaceChildren(errorState(error, () => renderReview()));
  }
}

function resultCard(result) {
  const isTest = result.test_adapter;
  return el("div", { class: "card", style: "margin-bottom:10px" },
    el("div", { style: "display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap" },
      el("video", {
        src: `/api/generation/results/${result.id}/file`, controls: "", preload: "metadata",
        style: "width:min(380px, 100%); border-radius:8px; background:#000; flex:0 1 380px; aspect-ratio:16/9",
      }),
      el("div", { style: "flex:1; min-width:220px" },
        el("div", { style: "display:flex; gap:7px; align-items:center; flex-wrap:wrap; margin-bottom:6px" },
          el("b", {}, `v${result.version_number}`),
          statusPill(result.status, pretty(result.status)),
          el("span", { class: "pill s-outline" }, pretty(result.provider_key || "")),
          isTest ? el("span", { class: "pill s-purple" }, "TEST OUTPUT — NOT A REAL VIDEO") : null,
          el("span", { class: "muted", style: "font-size:11px" }, fmtWhen(result.created_at))),
        el("div", { class: "muted", style: "font-size:11.5px; margin-bottom:8px" },
          [result.resolution, result.duration_seconds ? `${result.duration_seconds}s` : null,
           result.file_size ? `${Math.round(result.file_size / 1024)}KB` : null].filter(Boolean).join(" · ")),
        el("div", { style: "display:flex; gap:6px; flex-wrap:wrap" },
          result.status !== "approved"
            ? el("button", { class: "btn small primary", onclick: () => review(result, "approved") }, el("span", { html: ICONS.check }), "Approve") : null,
          result.status !== "rejected"
            ? el("button", { class: "btn small danger", onclick: () => review(result, "rejected") }, "Reject") : null,
          el("button", { class: "btn small ghost", onclick: () => retryFromResult(result) }, "Retry / new version")))));
}

async function review(result, decision) {
  let reason = null;
  if (decision === "rejected") {
    const input = el("input", { type: "text", placeholder: "Why is this rejected? (required)" });
    const submitted = await new Promise((resolve) => {
      openModal({
        title: `Reject v${result.version_number}`,
        sub: "A rejection reason is required — it becomes part of the audit trail.",
        body: el("div", { class: "field" }, el("label", {}, "Reason"), input),
        actions: [{ label: "Cancel", onClick: () => resolve(null) },
                  { label: "Reject", kind: "danger", onClick: (e, close) => { close(); resolve(input.value.trim()); } }],
      });
    });
    if (submitted === null) return;
    if (!submitted) return toast("Rejection requires a reason.", "warn");
    reason = submitted;
  }
  try {
    await postJSON(`/api/generation/results/${result.id}/review`, { decision, reason });
    toast(decision === "approved" ? "Version approved — shot marked complete." : "Version rejected — shot needs revision.", "ok");
    draw();
  } catch (error) { toast(error.message, "error"); }
}

async function retryFromResult(result) {
  try {
    const jobs = await getJSON(`/api/generation/jobs?shot_id=${result.shot_id}&limit=50`);
    const job = jobs.jobs[0];
    const retry = await postJSON(`/api/generation/jobs/${job.id}/retry`, {});
    toast(`New attempt #${retry.attempt} drafted — choose provider/settings, then Submit.`, "ok");
    tab = "queue"; draw();
  } catch (error) { toast(error.message, "error"); }
}
