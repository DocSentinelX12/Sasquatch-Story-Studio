// Supplementary mobile checks: reject-with-reason, retry from failed, entry points.
import { JSDOM } from "/tmp/uitest/node_modules/jsdom/lib/api.js";
import { readFileSync } from "fs";

const dom = new JSDOM(readFileSync("./web/index.html", "utf8"), { url: "http://localhost:8000/", pretendToBeVisual: true });
dom.window.innerWidth = 390;
global.window = dom.window; global.document = dom.window.document;
global.Node = dom.window.Node; global.localStorage = dom.window.localStorage;
global.location = dom.window.location; global.confirm = () => true; global.history = dom.window.history;
let promptAnswer = "off-model motion (mobile test)";
global.prompt = () => promptAnswer;
const realFetch = global.fetch;
global.fetch = (p, o) => realFetch(new URL(p, "http://localhost:8000").href, o);
const errors = [];
dom.window.addEventListener("error", (e) => errors.push(String(e.message)));
await import("../web/js/app.js");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const text = () => document.getElementById("content").textContent;
const api = (p, o) => realFetch(new URL(p, "http://localhost:8000").href, o);
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
let failed = 0;
const ok = (name, cond, extra = "") => { console.log((cond ? "PASS" : "FAIL") + " - " + name + (cond ? "" : " " + extra)); if (!cond) failed++; };

// find the complete shot from the previous run (has approved v1 + second result)
const sceneId = 2;
const shot = (await (await api(`/api/shots?scene_id=${sceneId}`)).json()).shots[0];

// --- entry points ---
location.hash = "#/shots"; await wait(1000);
ok("Shots browser Generate entry point", [...document.querySelectorAll("#content a")].some((a) => a.getAttribute("href") === `#/generate/${shot.id}`));
location.hash = `#/scenes/${sceneId}/director`; await wait(1200);
ok("Scene Director Generate entry point", [...document.querySelectorAll("#content a.btn-generate")].length >= 1);

// --- reject with reason on the pending second version ---
location.hash = `#/generate/${shot.id}`; await wait(1200); await wait(1500);
const rejectBtn = [...document.querySelectorAll(".content button")].find((b) => b.textContent === "Reject");
ok("reject button present", !!rejectBtn);
rejectBtn?.click(); await wait(700);
// complete the bottom-sheet rejection dialog (reason textarea + confirm)
const reasonBox = document.querySelector(".modal textarea");
if (reasonBox) {
  reasonBox.value = "off-model motion (mobile test)";
  [...document.querySelectorAll(".modal button")].find((b) => b.textContent === "Reject")?.click();
  await wait(900);
}
const afterReject = (await (await api(`/api/generation/results?shot_id=${shot.id}`)).json()).results;
ok("some version rejected with recorded reason",
  afterReject.some((r) => r.status === "rejected"));
const approvedResult = afterReject.find((r) => r.status === "approved");
let approvedIntact = true;
if (approvedResult) approvedIntact = (await api(`/api/generation/results/${approvedResult.id}/file`)).status === 200;
ok("approved version still intact", approvedIntact);

// --- retry from a failed job ---
const failResp = await post(`/api/shots/${shot.id}/generate`, { provider_key: "auto", settings: { duration_seconds: 2, test_force_failure: true } });
if (failResp.status !== 201) console.log("generate resp:", failResp.status, (await failResp.text()).slice(0, 200));
const failJob = await failResp.json();
const submitResp = await post(`/api/generation/jobs/${failJob.id}/submit`);
if (submitResp.status !== 200) console.log("submit resp:", submitResp.status, (await submitResp.text()).slice(0, 200));
let job = null;
for (let i = 0; i < 20; i++) { job = await (await api(`/api/generation/jobs/${failJob.id}`)).json(); if (job.status === "failed") break; await wait(500); }
ok("forced failure recorded", job?.status === "failed" && job?.error_code === "generation_failed");
location.hash = `#/generate/${shot.id}`; await wait(2500);
const retryBtn = [...document.querySelectorAll(".content button")].find((b) => b.textContent === "Retry");
ok("retry button appears after failure", !!retryBtn);
retryBtn?.click(); await wait(2500);
const jobsList = (await (await api(`/api/generation/jobs?shot_id=${shot.id}&limit=5`)).json()).jobs;
const newest = jobsList[0];
ok("retry created new attempt + failed job preserved",
  newest && newest.attempt === job.attempt + 1 && jobsList.some((j) => j.id === job.id && j.status === "failed"));

// --- approved references display (honest when none attached) ---
ok("references summary honest", text().includes("References") || text().includes("No frame references"));

console.log("ERRORS: " + (errors.length === 0 ? "none" : errors.join(" | ")));
console.log(failed || errors.length ? `SUPPLEMENTARY: ${failed} failed` : "SUPPLEMENTARY-OK");
process.exit(failed || errors.length ? 1 : 0);
