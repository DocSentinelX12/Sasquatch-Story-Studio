// Phase 1-4 + Phase 5 UI regression (fresh seeded DB, server must be running).
import { JSDOM } from "/tmp/uitest/node_modules/jsdom/lib/api.js";
import { readFileSync } from "fs";

const dom = new JSDOM(readFileSync("./web/index.html", "utf8"), { url: "http://localhost:8000/", pretendToBeVisual: true });
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
let failed = 0;
const ok = (name, cond) => { console.log((cond ? "PASS" : "FAIL") + " - " + name); if (!cond) failed++; };

await wait(900);
location.hash = "#/dashboard"; await wait(900);
ok("P1 dashboard", text().includes("The Great Moonberry Bounce"));
location.hash = "#/characters"; await wait(1000);
ok("P2 characters (5 canon)", document.querySelectorAll("#content .asset-tile").length === 5);
location.hash = "#/assets"; await wait(900);
ok("P2 assets library", text().includes("Asset Library"));
location.hash = "#/story?tab=bible"; await wait(900);
ok("P3 story bible", text().includes("Series title"));
location.hash = "#/episodes/1"; await wait(1300);
ok("P3 episode workspace", text().includes("Acts & Scenes"));
location.hash = "#/world"; await wait(900);
ok("P3 locations/props", text().includes("Locations"));
location.hash = "#/scenes"; await wait(900);
ok("P4 scenes browser + Director links", text().includes("Director"));
location.hash = "#/scenes/1/director"; await wait(1300);
ok("P4 scene director + storyboard", text().includes("Storyboard") && document.querySelectorAll("#content .asset-tile").length >= 2);
ok("P4 generate entry point on shot cards", !!document.querySelector("#content a.btn-generate"));
location.hash = "#/shots"; await wait(900);
ok("P4 shots browser + generate", text().includes("Generate"));
location.hash = "#/settings"; await wait(1000);
ok("P5 settings: all providers", ["Seedance", "Google Veo", "Wan", "Local / Self-Hosted", "Gemini Omni Flash", "Higgsfield"].every((n) => text().includes(n)));
location.hash = "#/queue"; await wait(900);
ok("P5 queue view", text().includes("Jobs") && text().includes("Video Review"));

console.log("ERRORS: " + (errors.length === 0 ? "none" : errors.join(" | ")));
console.log(failed || errors.length ? `REGRESSION: ${failed} failed` : "REGRESSION-OK");
process.exit(failed || errors.length ? 1 : 0);
