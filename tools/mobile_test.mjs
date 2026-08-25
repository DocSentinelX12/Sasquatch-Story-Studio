// Phase 5 mobile viewport test (run: node --input-type=module tools/mobile_test.mjs)
import { JSDOM } from "/tmp/uitest/node_modules/jsdom/lib/api.js";
import { readFileSync } from "fs";

const html = readFileSync("./web/index.html", "utf8");
const css = readFileSync("./web/css/studio.css", "utf8");
const dom = new JSDOM(html, { url: "http://localhost:8000/", pretendToBeVisual: true });
dom.window.innerWidth = 390; dom.window.innerHeight = 844; // phone viewport
global.window = dom.window; global.document = dom.window.document;
global.Node = dom.window.Node; global.localStorage = dom.window.localStorage;
global.location = dom.window.location; global.confirm = () => true; global.history = dom.window.history;
global.prompt = () => "mobile test rejection reason";
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
const ok = (name, cond, extra = "") => {
  console.log((cond ? "PASS" : "FAIL") + " - " + name + (cond ? "" : " " + extra));
  if (!cond) failed++;
};

// CSS static checks (media queries don't execute in jsdom)
ok("CSS mobile layer + touch targets", css.includes("@media (max-width: 820px)") && css.includes(".btn { padding: 11px 16px"));
ok("CSS bottom-sheet modals + sheet component", css.includes("align-items: flex-end") && css.includes(".sheet"));
ok("CSS sticky generate + provider cards + queue cards",
  css.includes(".btn-generate") && css.includes(".provider-card-tap") && css.includes(".queue-cards"));

// prepare a ready shot on scene 2
const sceneId = 2;
const shot = (await (await api(`/api/shots?scene_id=${sceneId}`)).json()).shots[0];
await api(`/api/scenes/${sceneId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved" }) });
await post(`/api/shots/${shot.id}/approve`);
const v = await (await api(`/api/shots/${shot.id}/validate`)).json();
for (const f of v.findings) {
  if (f.severity !== "info" && !f.overridden) {
    await post(`/api/shots/${shot.id}/overrides`, { check_key: f.key, explanation: "mobile viewport test" });
  }
}
await post(`/api/shots/${shot.id}/ready-for-generation`);

// 1-3: route loads with shot info + sticky Generate
location.hash = `#/generate/${shot.id}`;
await wait(1200);
ok("GENERATE route + shot info", text().includes("Generate Video") && text().includes(shot.shot_ref));
ok("sticky Generate button", !!document.querySelector(".sticky-actions .btn-generate"));

// 4: provider selector
const cardNames = [...document.querySelectorAll(".provider-card-tap .name")].map((n) => n.textContent);
for (const expected of ["Automatic Best Match", "Seedance", "Google Veo", "Wan", "Local / Self-Hosted", "Gemini Omni Flash", "Higgsfield"]) {
  ok(`provider card: ${expected}`, cardNames.some((c) => c.includes(expected)));
}
const localCard = [...document.querySelectorAll(".provider-card-tap")].find((c) => c.textContent.includes("Local / Self-Hosted"));
ok("local lane shows Not configured + self-hosted tag", localCard?.textContent.includes("Not configured") && localCard?.textContent.includes("self-hosted"));
ok("cost honesty", localCard?.textContent.includes("no per-video credits") && !localCard.textContent.includes("free"));

// 5-6: advanced settings capability gating (Veo: no last-frame, no seed)
const veoCard = [...document.querySelectorAll(".provider-card-tap")].find((c) => c.textContent.includes("Google Veo"));
veoCard?.click(); await wait(400);
const advToggle = [...document.querySelectorAll(".content .card div")].find((d) => d.style?.cursor === "pointer" && d.textContent.includes("Advanced settings"));
advToggle?.click(); await wait(300);
ok("advanced settings open (caps-gated)", text().includes("Duration") && text().includes("Aspect ratio"));
const seedInput = [...document.querySelectorAll(".content input[type=number]")].find((i) => i.placeholder?.includes("seed") || i.placeholder === "optional");
ok("seed disabled for Veo", !seedInput || seedInput.disabled);

// back to Automatic for the live test (test adapter enabled on this server)
[...document.querySelectorAll(".provider-card-tap")].find((c) => c.textContent.includes("Automatic Best Match"))?.click();
await wait(400);

// 8-9: Generate
document.querySelector(".sticky-actions .btn-generate")?.click();
await wait(2200);
const jobNow = (await (await api(`/api/generation/jobs?shot_id=${shot.id}&limit=1`)).json()).jobs[0];
ok("submission left draft state", jobNow && jobNow.status !== "draft", jobNow?.status);
await wait(5000);
const jobAfter = (await (await api(`/api/generation/jobs?shot_id=${shot.id}&limit=1`)).json()).jobs[0];
ok("job reached review state", ["needs_review", "approved", "rejected", "failed"].includes(jobAfter?.status), jobAfter?.status);

// 10-11: video + review actions
await wait(1600);
ok("video result rendered", !!document.querySelector(".content video"));
ok("review actions present", text().includes("Approve") && text().includes("Reject") && text().includes("Generate another version"));
ok("TEST output labelled", text().includes("TEST OUTPUT"));

const approveBtn = [...document.querySelectorAll(".content button")].find((b) => b.textContent.includes("Approve"));
approveBtn?.click(); await wait(1300);
ok("approve -> shot complete", (await (await api(`/api/shots/${shot.id}`)).json()).status === "complete");

// another version on a complete shot
const another = [...document.querySelectorAll(".content button")].find((b) => b.textContent.includes("Generate another version"));
another?.click(); await wait(2500); await wait(5000);
const results = (await (await api(`/api/generation/results?shot_id=${shot.id}`)).json()).results;
ok("versions preserved (v1 not overwritten)", results.length >= 2, String(results.length));

// mobile queue
location.hash = "#/queue"; await wait(1200);
ok("mobile queue cards render", document.querySelectorAll(".queue-card").length >= 2);
ok("queue card actions", text().includes("Open") || text().includes("Review"));

// phone navigation sanity
location.hash = "#/dashboard"; await wait(700);
ok("dashboard works from phone flow", text().includes("The Great Moonberry Bounce"));

console.log("ERRORS: " + (errors.length === 0 ? "none" : errors.join(" | ")));
console.log(failed || errors.length ? `MOBILE-SUITE: ${failed} failed` : "MOBILE-SUITE-OK");
process.exit(failed || errors.length ? 1 : 0);
