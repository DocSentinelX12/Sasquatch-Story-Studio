// Phase 8 UI test: Control Center tabs (automation, notifications, series, templates, backups).
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
const clickTab = (label) => [...document.querySelectorAll("#content button")].find((b) => b.textContent.trim() === label)?.click();
let failed = 0;
const ok = (name, cond, extra = "") => { console.log((cond ? "PASS" : "FAIL") + " - " + name + (cond ? "" : " " + extra)); if (!cond) failed++; };

await wait(800);
location.hash = "#/control"; await wait(1100);
ok("CONTROL renders", text().includes("Control Center"));
ok("AUTOMATION rules list + safety", text().includes("never approves creative content") && (text().includes("Scene complete") || text().includes("WHEN")));
ok("rule actions present", text().includes("Test (dry-run)") && text().includes("Run now") && text().includes("Enable") || text().includes("Disable"));
clickTab("Notifications"); await wait(800);
ok("NOTIFICATIONS tab renders", text().includes("No notifications") || text().includes("automation"));
clickTab("Series"); await wait(900);
ok("SERIES tab + isolation note", text().includes("fully isolated") || text().includes("Isolation check"));
ok("new series button", text().includes("New Series"));
clickTab("Templates"); await wait(800);
ok("TEMPLATES tab", text().includes("No templates") || text().includes("Instantiate"));
clickTab("Backups"); await wait(800);
ok("BACKUPS tab + media honesty", text().includes("referenced by path, not embedded") && text().includes("Download JSON backup"));
// regression: dashboard + assistant + settings
location.hash = "#/dashboard"; await wait(700);
ok("dashboard intact", text().includes("The Great Moonberry Bounce"));
location.hash = "#/assistant"; await wait(1000);
ok("assistant intact", text().includes("Production Assistant"));
location.hash = "#/settings"; await wait(900);
ok("settings intact", text().includes("Seedance"));
console.log("ERRORS: " + (errors.length === 0 ? "none" : errors.join(" | ")));
console.log(failed || errors.length ? `PHASE8-UI: ${failed} failed` : "PHASE8-UI-OK");
process.exit(failed || errors.length ? 1 : 0);
