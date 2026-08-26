// Milestone H UI test (390px). Requires server on :8000 with STUDIO_TEST_PROVIDER=1.
import { JSDOM } from "/tmp/uitest/node_modules/jsdom/lib/api.js";
import { readFileSync } from "fs";

const dom = new JSDOM(readFileSync("./web/index.html", "utf8"), { url: "http://localhost:8000/", pretendToBeVisual: true });
dom.window.innerWidth = 390;
global.window = dom.window; global.document = dom.window.document;
global.Node = dom.window.Node; global.localStorage = dom.window.localStorage;
global.location = dom.window.location; global.confirm = () => true; global.history = dom.window.history;
const realFetch = global.fetch;
global.fetch = (p, o) => realFetch(new URL(p, "http://localhost:8000").href, o);
const api = (p, o) => realFetch(new URL(p, "http://localhost:8000").href, o);
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const errors = [];
dom.window.addEventListener("error", (e) => errors.push(String(e.message)));
await import("../web/js/app.js");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const text = () => document.getElementById("content").textContent;
let failed = 0;
const ok = (name, cond, extra = "") => { console.log((cond ? "PASS" : "FAIL") + " - " + name + (cond ? "" : " " + extra)); if (!cond) failed++; };
await wait(700);

// prepare: 2 versions (reject v1, approve v2) + 1 failed attempt
await api("/api/scenes/1", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved" }) });
const shot = (await (await api("/api/shots?scene_id=1")).json()).shots[0];
const chars = (await (await api("/api/characters?project_id=1")).json()).characters;
try { await post(`/api/shots/${shot.id}/cast`, { character_id: chars[0].id }); } catch (e) { void e; }
await post(`/api/shots/${shot.id}/approve`);
const v = await (await api(`/api/shots/${shot.id}/validate`)).json();
for (const f of v.findings) if (f.severity !== "info" && !f.overridden)
  await post(`/api/shots/${shot.id}/overrides`, { check_key: f.key, explanation: "H UI test" });
await post(`/api/shots/${shot.id}/ready-for-generation`);
const gen1 = await (await post(`/api/shots/${shot.id}/generate`, { provider_key: "auto", settings: { duration_seconds: 2 } })).json();
await post(`/api/generation/jobs/${gen1.id}/submit`, {});
let j = null;
for (let i = 0; i < 28; i++) { j = await (await api(`/api/generation/jobs/${gen1.id}`)).json(); if (j.status === "needs_review" || j.status === "failed") break; await wait(700); }
let results = (await (await api(`/api/generation/results?shot_id=${shot.id}`)).json()).results;
if (results.length) await post(`/api/generation/results/${results[0].id}/review`, { decision: "rejected", reason: "character wrong" });
const gen2 = await (await post(`/api/shots/${shot.id}/generate`, { provider_key: "auto", settings: { duration_seconds: 2 } })).json();
await post(`/api/generation/jobs/${gen2.id}/submit`, {});
await wait(6000);
results = (await (await api(`/api/generation/results?shot_id=${shot.id}`)).json()).results;
if (results.length) await post(`/api/generation/results/${results[0].id}/review`, { decision: "approved" });
const gen3 = await (await post(`/api/shots/${shot.id}/generate`, { provider_key: "auto", settings: { duration_seconds: 2, test_force_failure: true } })).json();
await post(`/api/generation/jobs/${gen3.id}/submit`, {});
await wait(4000);

location.hash = "#/generate/" + shot.id;
await wait(1600); await wait(1500);
ok("H1. version history renders", text().includes("Version History"));
ok("H2. both versions visible", text().includes("v2") && text().includes("v1"));
ok("H3. rejected label + reason", text().includes("Rejected") && text().includes("character wrong"));
ok("H4. failed attempt kept", text().includes("failed") || text().includes("kept for inspection"));
ok("H5. production marker", text().includes("PRODUCTION") || text().includes("production version"));
ok("H6. compare button exists", [...document.querySelectorAll("button")].some((b) => b.textContent === "Compare"));
const compareBtn = [...document.querySelectorAll("button")].find((b) => b.textContent === "Compare");
compareBtn?.click(); await wait(900);
ok("H7. compare modal", (document.querySelector(".modal")?.textContent || "").includes("stored metadata"));
document.querySelector(".modal-backdrop")?.remove();
const css = readFileSync("./web/css/studio.css", "utf8");
ok("H8. 390px safe (touch targets)", css.includes("min-height:44px") || css.includes(".btn { padding: 11px 16px"));
console.log("ERRORS: " + (errors.length === 0 ? "none" : errors.join(" | ")));
console.log(failed || errors.length ? "H-UI: FAILED" : "H-UI-OK");
process.exit(failed || errors.length ? 1 : 0);
