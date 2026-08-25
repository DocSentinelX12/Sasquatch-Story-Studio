// Phase 6 UI test: audio, timeline, QC/render, exports views.
import { JSDOM } from "/tmp/uitest/node_modules/jsdom/lib/api.js";
import { readFileSync } from "fs";

const dom = new JSDOM(readFileSync("./web/index.html", "utf8"), { url: "http://localhost:8000/", pretendToBeVisual: true });
dom.window.innerWidth = 390;
global.window = dom.window; global.document = dom.window.document;
global.Node = dom.window.Node; global.localStorage = dom.window.localStorage;
global.location = dom.window.location; global.confirm = () => true; global.history = dom.window.history;
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

// seed an approved recording so timeline has audio
const ep = await (await api("/api/episodes/1")).json();
const element = ep.scenes[0].script.find((e) => e.element_type === "dialogue");
const rec = (await post(`/api/audio/recordings/from-script/${element.id}`)).json();
await api(`/api/audio/recordings/${rec.id}/generate?provider_key=auto`, { method: "POST" });
await wait(4000);
await api(`/api/audio/recordings/${rec.id}/review?decision=approved`, { method: "POST" });
await post("/api/episodes/1/timeline/build");

// AUDIO view
location.hash = "#/audio"; await wait(1200);
ok("AUDIO view renders lines", text().includes("Dialogue & Narration") && text().includes("Approve") || text().includes("approved"));
ok("AUDIO voice tab", [...document.querySelectorAll("#content button")].some((b) => b.textContent.includes("Voice Profiles")));
[...document.querySelectorAll("#content button")].find((b) => b.textContent.includes("Voice Profiles"))?.click(); await wait(700);
ok("AUDIO voices honest lane note", text().includes("LOCAL_AUDIO_API_URL"));

// TIMELINE view
location.hash = "#/timeline"; await wait(1200);
ok("TIMELINE renders tracks", text().includes("Timeline") && document.querySelectorAll("#content .card").length + document.querySelectorAll("#content div[style*=position]").length > 0);
ok("TIMELINE build button", text().includes("Build Episode Timeline"));
ok("TIMELINE QC button", text().includes("QC / Render"));
// open QC modal
[...document.querySelectorAll("#content button")].find((b) => b.textContent.includes("QC / Render"))?.click(); await wait(800);
const qcText = document.querySelector(".modal")?.textContent || "";
ok("QC modal shows findings + ffmpeg honesty", qcText.includes("renderer_not_available") || qcText.includes("ffmpeg"), qcText.slice(0, 80));
document.querySelector(".modal-backdrop")?.remove();

// EXPORTS view
location.hash = "#/exports"; await wait(1100);
ok("EXPORTS view renders", text().includes("Exports & Shorts") && text().includes("Short-form proposals"));
ok("EXPORTS approval-first copy", text().includes("nothing publishes automatically" || "Nothing publishes automatically") || text().includes("draft until you approve"));

// regression spot
location.hash = "#/dashboard"; await wait(700);
ok("phases intact (dashboard)", text().includes("The Great Moonberry Bounce"));

console.log("ERRORS: " + (errors.length === 0 ? "none" : errors.join(" | ")));
console.log(failed || errors.length ? `PHASE6-UI: ${failed} failed` : "PHASE6-UI-OK");
process.exit(failed || errors.length ? 1 : 0);
