// Settings — provider configuration, capabilities, connection validation.
import {
  el, ICONS, statusPill, pretty, emptyState, loadingState, errorState, toast, openModal,
} from "../ui.js";
import { getJSON, postJSON } from "../api.js";

let container;
let providers = [];

export async function render(c) {
  container = c;
  await draw();
}

async function draw() {
  container.replaceChildren(
    el("div", { class: "page-head" },
      el("div", {},
        el("h2", {}, "Settings"),
        el("div", { class: "desc" }, "Video-generation providers, connection status, and studio configuration."))));
  container.append(loadingState("Loading providers…"));
  try {
    const data = await getJSON("/api/providers");
    providers = data.providers;
    container.lastChild.remove();
    container.append(
      el("div", { class: "callout", style: "margin-bottom:16px; font-size:12.5px" },
        el("b", {}, "Credentials stay server-side. "),
        "API keys live in the .env file on the studio server (or process environment) and are never sent to the browser. ",
        "“Connected” appears only after a real validation call succeeds — presence of a key alone is never reported as connected."));
    container.append(el("div", { class: "grid cols-2" }, providerCards(), systemCard()));
  } catch (error) {
    container.lastChild.remove();
    container.append(errorState(error, draw));
  }
}

function providerCards() {
  const wrap = el("div", { class: "grid cols-2" });
  const video = providers.filter((p) => p.kind === "video");
  const text = providers.filter((p) => p.kind !== "video");
  if (!video.length) wrap.append(emptyState({ big: "No providers", small: "Provider registry empty." }));
  for (const provider of [...video, ...text]) {
    const caps = provider.caps;
    wrap.append(el("div", { class: `card ${provider.is_test ? "" : ""}`, style: provider.is_test ? "border-color:rgba(199,155,242,.4)" : "" },
      el("div", { style: "display:flex; align-items:center; gap:9px; margin-bottom:8px; flex-wrap:wrap" },
        el("b", {}, provider.display_name),
        provider.is_test ? el("span", { class: "pill s-purple" }, "TEST") : null,
        statusPill(displayStatus(provider.status), pretty(displayStatus(provider.status))),
        el("span", { class: "pill s-outline" }, provider.kind)),
      provider.status === "not_configured"
        ? el("div", { class: "callout", style: "font-size:11.5px; padding:8px 11px; margin-bottom:8px" },
            "Requires server-side environment variable", (provider.missing_env || provider.required_env).map((n) => el("code", { style: "font-family:var(--mono); color:var(--amber)" }, ` ${n}`)),
            ". Add it to .env and restart the studio.")
        : el("div", { class: "muted", style: "font-size:11.5px; margin-bottom:8px" },
            provider.last_validation
              ? `Validated ${provider.last_validation.checked_at?.slice(0, 19).replace("T", " ")} — ${provider.last_validation.detail || provider.last_validation.status}`
              : "Credentials present. Run “Validate Connection” to verify for real."),
      caps ? el("div", { style: "display:flex; gap:5px; flex-wrap:wrap; margin-bottom:9px" },
          ...capChips(caps)) : null,
      el("div", { style: "display:flex; gap:7px; flex-wrap:wrap" },
        el("button", {
          class: "btn small", onclick: async () => {
            toast("Validating — this performs a real (free) API check…", "info");
            try {
              const result = await postJSON(`/api/providers/${provider.key}/validate`);
              toast(result.connected ? `${provider.display_name}: credentials valid.` :
                `${provider.display_name}: ${pretty(result.status)}.`, result.connected ? "ok" : "error",
                "Connection check");
              draw();
            } catch (error) {
              const detail = error.detail || {};
              toast(detail.message || error.message, "error", "Connection check");
              draw();
            }
          },
        }, el("span", { html: ICONS.refresh }), "Validate Connection"),
        provider.docs_url ? el("a", { class: "btn small ghost", href: provider.docs_url, target: "_blank", style: "text-decoration:none" }, "Provider docs ↗") : null),
      (provider.caps?.notes || []).length
        ? el("div", { class: "muted", style: "font-size:11px; margin-top:8px" }, provider.caps.notes.join(" · ")) : null));
  }
  return wrap;
}

function displayStatus(status) {
  return status === "ready" ? "available" : status;
}

function capChips(caps) {
  const chips = [];
  const flag = (label, on) => { if (on !== undefined) chips.push(on
    ? el("span", { class: "pill s-green", style: "padding:1px 7px; font-size:10px" }, label)
    : null); };
  flag("T2V", caps.text_to_video); flag("I2V", caps.image_to_video);
  flag("last frame", caps.last_frame || caps.start_end_frames);
  flag("audio", caps.audio_generation); flag("seed", caps.seed_support);
  if (caps.durations?.length) chips.push(el("span", { class: "pill s-outline", style: "padding:1px 7px; font-size:10px" }, `${caps.durations.join("/")}s`));
  if (caps.resolutions?.length) chips.push(el("span", { class: "pill s-outline", style: "padding:1px 7px; font-size:10px" }, caps.resolutions.slice(0, 3).join(" ")));
  if (caps.aspect_ratios?.length) chips.push(el("span", { class: "pill s-outline", style: "padding:1px 7px; font-size:10px" }, caps.aspect_ratios.slice(0, 4).join(" ")));
  if (caps.max_reference_slots) chips.push(el("span", { class: "pill s-outline", style: "padding:1px 7px; font-size:10px" }, `${caps.max_reference_slots} ref slots`));
  if (caps.url_reference_only) chips.push(el("span", { class: "pill s-amber", style: "padding:1px 7px; font-size:10px" }, "URL refs only"));
  return chips.filter(Boolean);
}

function systemCard() {
  void openModal;
  return el("div", { class: "card" },
    el("h3", {}, "Studio system"),
    el("div", { style: "font-size:12.5px; line-height:1.9" },
      el("div", {}, el("b", {}, "Canon validation"), " — runs the repository content validator"),
      el("button", { class: "btn small ghost", style: "margin-top:6px", onclick: async () => {
        const result = await postJSON("/api/system/validate-content");
        toast(result.passed ? "Canon validation passed." : "Canon validation found errors.", result.passed ? "ok" : "error");
        openModal({ title: "Canon validation", body: el("pre", { class: "code", style: "max-height:300px" }, result.output), actions: [{ label: "Close" }] });
      } }, "Run validation"),
      el("div", { style: "margin-top:12px" }, el("b", {}, "Re-import canon"), " — idempotent seed from the repository"),
      el("button", { class: "btn small ghost", style: "margin-top:6px", onclick: async () => {
        const result = await postJSON("/api/system/seed");
        toast("Seed refreshed.", "ok");
        openModal({ title: "Seed result", body: el("pre", { class: "code" }, JSON.stringify(result, null, 2)), actions: [{ label: "Close" }] });
      } }, "Run seed")));
}
