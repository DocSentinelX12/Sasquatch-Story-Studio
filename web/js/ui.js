// UI toolkit: DOM builder, icons, status pills, modal, toast, and state views.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value; // trusted internal strings only
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

const I = (paths, extra = "") =>
  `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" ${extra}>${paths}</svg>`;

export const ICONS = {
  dashboard: I('<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>'),
  projects: I('<path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  episodes: I('<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3z"/>'),
  story: I('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>'),
  characters: I('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.3-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><circle cx="17.5" cy="9.5" r="2.5"/><path d="M16 14.6c2.6.3 4.6 1.9 5.5 4.4"/>'),
  assets: I('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.8"/><path d="M21 15l-5-5-9 9"/>'),
  scenes: I('<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M7 21h10M12 18v3M7 9h4M7 13h7"/>'),
  shots: I('<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>'),
  queue: I('<path d="M4 7h16M4 12h16M4 17h10"/><circle cx="19" cy="17" r="2"/>'),
  audio: I('<path d="M3 12v-1M7 15V8M11 19V5M15 16V8M19 13v-2"/>'),
  timeline: I('<path d="M4 6v12M9 4v16M14 9v6M19 7v10"/>'),
  exports: I('<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 19h16"/>'),
  settings: I('<circle cx="12" cy="12" r="3.2"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.2 3H9.8L9.4 5.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.7h4.4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.06-.4.1-.8.1-1.2z"/>'),
  plus: I('<path d="M12 5v14M5 12h14"/>'),
  upload: I('<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/>'),
  search: I('<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>'),
  check: I('<path d="M4 12l5 5L20 6"/>'),
  x: I('<path d="M6 6l12 12M18 6L6 18"/>'),
  refresh: I('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
  star: I('<path d="M12 3l2.7 5.6 6.3.8-4.6 4.3 1.2 6.1L12 17l-5.6 2.8 1.2-6.1L3 9.4l6.3-.8z"/>'),
  film: I('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 12h4M3 16h4M17 8h4M17 12h4M17 16h4"/>'),
  spark: I('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>'),
  folder: I('<path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  clock: I('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>'),
  alert: I('<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5v.5"/>'),
  arrow: I('<path d="M5 12h14M13 6l6 6-6 6"/>'),
  key: I('<rect x="3" y="10" width="18" height="10" rx="2"/><path d="M7 10V7a5 5 0 0 1 10 0v3"/>'),
  db: I('<ellipse cx="12" cy="5.5" rx="8" ry="2.8"/><path d="M4 5.5v13c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8v-13"/><path d="M4 12c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8"/>'),
  sasquatch: I('<path d="M3 21c2-8 5-12 9-12s7 4 9 12"/><circle cx="12" cy="6" r="2.5"/>'),
};

const STATUS_MAP = {
  // generic
  active: "green", planning: "blue", planned: "blue", paused: "amber", archived: "gray",
  outline: "blue", script: "blue", storyboard: "purple", shot_building: "purple",
  generating: "amber", editing: "amber", qc: "purple", exported: "green", released: "green",
  written: "blue", boarded: "purple", shot_ready: "purple", ready: "blue", queued: "blue",
  completed: "green", failed: "red", needs_review: "purple", approved: "green",
  rejected: "red", cancelled: "gray", draft: "gray",
  registered: "blue", pending_approval: "amber", obsolete: "gray",
  not_configured: "gray", error: "red",
};

export function statusPill(status, label) {
  const tone = STATUS_MAP[status] || "gray";
  return el("span", { class: `pill s-${tone}` }, label ?? pretty(status));
}

export const pretty = (s) => (s ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function fmtWhen(iso) {
  if (!iso) return "—";
  const then = new Date(iso);
  const diff = (Date.now() - then.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return then.toLocaleDateString();
}

/* ---------- Modal ---------- */
export function openModal({ title, sub, body, actions = [], wide = false }) {
  const backdrop = el("div", { class: "modal-backdrop" });
  const modal = el("div", { class: "modal", style: wide ? "width:min(860px, calc(100vw - 40px))" : "" });
  const close = () => backdrop.remove();
  modal.append(el("h3", {}, title));
  if (sub) modal.append(el("div", { class: "modal-sub" }, sub));
  if (body) modal.append(body);
  const actionsRow = el("div", { class: "modal-actions" });
  for (const action of actions) {
    actionsRow.append(
      el("button", {
        class: `btn ${action.kind || ""}`.trim(),
        onclick: async (e) => {
          if (action.keepOpen) { await action.onClick?.(e, close); return; }
          const btn = e.currentTarget;
          btn.disabled = true;
          try { await action.onClick?.(e, close); } finally { if (document.body.contains(backdrop)) { btn.disabled = false; } }
        },
      }, action.label)
    );
  }
  modal.append(actionsRow);
  backdrop.append(modal);
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
  });
  document.body.append(backdrop);
  return { close, modal };
}

/* ---------- Toast ---------- */
export function toast(message, type = "ok", title) {
  const box = document.getElementById("toasts");
  const node = el("div", { class: `toast ${type === "ok" ? "" : type}` },
    title ? el("b", {}, title) : null, message);
  box.append(node);
  setTimeout(() => { node.style.opacity = "0"; node.style.transition = "opacity .3s"; }, 4600);
  setTimeout(() => node.remove(), 5000);
}

/* ---------- State views ---------- */
export function emptyState({ big, small, actions = [] }) {
  const wrap = el("div", { class: "empty" },
    el("div", { class: "big" }, big),
    el("div", { class: "small" }, small));
  if (actions.length) {
    const row = el("div", { style: "margin-top:14px; display:flex; gap:8px; justify-content:center; flex-wrap:wrap" });
    for (const a of actions) row.append(a);
    wrap.append(row);
  }
  return wrap;
}

export function loadingState(label = "Loading…") {
  return el("div", { class: "empty", style: "display:flex; align-items:center; justify-content:center; gap:10px; padding:40px" },
    el("span", {
      html: `<svg class="spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9"/></svg>`,
    }),
    el("span", { style: "color:var(--text-dim)" }, label));
}

export function errorState(error, onRetry) {
  return el("div", {
    class: "callout",
    style: "display:flex; align-items:center; gap:12px; flex-wrap:wrap",
  },
    el("span", { html: ICONS.alert, style: "flex:0 0 auto; display:inline-flex" }),
    el("div", { style: "flex:1; min-width:200px" },
      el("b", {}, "Something went wrong"),
      el("div", { style: "font-size:12.5px; opacity:.9" }, error?.message || String(error))),
    onRetry ? el("button", { class: "btn small", onclick: onRetry }, "Retry") : null);
}

/* ---------- Small building blocks ---------- */
export function statCard(value, label, hint) {
  return el("div", { class: "card stat-card" },
    el("div", { class: "value" }, String(value)),
    el("div", { class: "label" }, label),
    hint ? el("div", { class: "hint" }, hint) : null);
}

export const textToList = (v) => (Array.isArray(v) ? v.join("\n") : v || "");
export const listFromText = (v) =>
  String(v || "").split("\n").map((x) => x.trim()).filter(Boolean);

export function field(labelTxt, inputEl, hint) {
  return el("div", { class: "field" },
    el("label", {}, labelTxt),
    inputEl,
    hint ? el("div", { class: "hint" }, hint) : null);
}

export function tabBar(tabs, activeId, onPick) {
  return el("div", {
    style: "display:flex; gap:6px; flex-wrap:wrap; border-bottom:1px solid var(--border); margin-bottom:16px; padding-bottom:0",
  },
    ...tabs.map((t) => {
      const active = t.id === activeId;
      return el("button", {
        class: "btn",
        style: active
          ? "background:rgba(143,209,155,.13); border-color:rgba(143,209,155,.35); color:var(--moss); border-radius:8px 8px 0 0; border-bottom-color:transparent"
          : "background:transparent; border-color:transparent; color:var(--text-dim); border-radius:8px 8px 0 0; border-bottom-color:transparent",
        onclick: () => onPick(t.id),
      },
        t.label,
        t.count !== undefined ? el("span", { style: "opacity:.65; margin-left:6px; font-size:11px" }, String(t.count)) : null);
    }));
}

export function charAvatar(referenceAsset, size = 44) {
  const img = referenceAsset && (referenceAsset.mime_type || "").startsWith("image/");
  return el("div", {
    style: `width:${size}px; height:${size}px; border-radius:12px; flex:0 0 auto; display:grid; place-items:center; overflow:hidden;
      background:rgba(143,209,155,.08); border:1px solid var(--border-strong); color:var(--moss)`,
  },
    img
      ? el("img", { src: `/api/assets/${referenceAsset.id}/file`, alt: "", style: "width:100%; height:100%; object-fit:cover" })
      : (() => { const s = el("span", { html: ICONS.sasquatch }); s.querySelector("svg").setAttribute("width", String(Math.round(size * 0.5))); return s; })());
}

export function assetThumb(asset, { height } = {}) {
  const isImage = (asset.mime_type || "").startsWith("image/");
  const flags = el("div", { class: "flags" });
  if (asset.is_favorite) flags.append(el("span", { class: "pill s-amber", style: "padding:1px 6px" }, "★"));
  if (asset.status === "approved") flags.append(el("span", { class: "pill s-green", style: "padding:1px 6px" }, "Approved"));
  const thumb = el("div", { class: "asset-thumb", style: height ? `height:${height}` : "" },
    isImage ? el("img", { src: `/api/assets/${asset.id}/file`, alt: asset.title, loading: "lazy" })
      : el("span", { class: "file-icon" }, "🎞"),
    flags);
  return thumb;
}
