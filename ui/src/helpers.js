// Small presentation helpers. Display-only: trace data is never mutated.

export function titleCase(text) {
  if (!text) return text;
  // Only fix shouting ALL-CAPS source names; leave mixed case alone.
  if (text !== text.toUpperCase()) return text;
  return text
    .toLowerCase()
    .replace(/\b([a-z])/g, (m, c) => c.toUpperCase());
}

// Render numbers defensively: a missing or malformed field shows "-",
// never "NaN".
export function num(value, digits = 1, fallback = "-") {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : fallback;
}

export function relTime(iso) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function hmToFrac(hm, dayStart = 6, dayEnd = 22) {
  const [h, m] = String(hm || "").split(":").map(Number);
  if (!Number.isFinite(h)) return 0;
  const t = h + (m || 0) / 60;
  return Math.min(1, Math.max(0, (t - dayStart) / (dayEnd - dayStart)));
}

export const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export const FEEDBACK_TYPES = [
  "birding", "hike", "kayaking", "outdoor_event", "museum", "other",
];

// Best-guess activity type for a scored candidate (the feedback modal
// prefills this; the user can change it).
export function guessType(candidate) {
  const id = candidate?.base?.candidate_id || candidate?.candidate_id || "";
  if (id.startsWith("venue@")) return "museum";
  if (id.startsWith("event@")) return "outdoor_event";
  const name = `${candidate?.base?.name || ""} ${candidate?.base?.site || ""}`.toLowerCase();
  if (/kayak|canoe|paddle/.test(name)) return "kayaking";
  if (/trail|park|hike|palisades|harriman/.test(name) && candidate?.domain === "nature") return "hike";
  if (candidate?.domain === "nature") return "birding";
  if (candidate?.domain === "outdoor_event") return "outdoor_event";
  return "other";
}

export function themeInit() {
  // Same precedence as the pre-paint script in index.html: an explicit
  // ?theme= link wins, then the saved choice, then the system setting.
  let fromUrl = null;
  let saved = null;
  try {
    const q = new URLSearchParams(location.search).get("theme");
    if (q === "dark" || q === "light") fromUrl = q;
  } catch { /* fine */ }
  try { saved = localStorage.getItem("ea-theme"); } catch { /* private mode */ }
  const theme = fromUrl
    || saved
    || document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  return theme;
}

export function themeSet(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("ea-theme", theme); } catch { /* fine */ }
}
