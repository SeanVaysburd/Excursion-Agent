// Small presentation helpers. Display-only: trace data is never mutated.

export const CATEGORY_ICONS = {
  nature: "🦆",
  birding: "🦆",
  hike: "🥾",
  kayaking: "🛶",
  outdoor_event: "🎪",
  indoor: "🏛️",
  museum: "🏛️",
};

export function iconFor(candidate) {
  const key = candidate?.domain || "";
  const id = candidate?.base?.candidate_id || "";
  if (id.startsWith("venue@")) return CATEGORY_ICONS.museum;
  if (id.startsWith("event@")) return CATEGORY_ICONS.outdoor_event;
  return CATEGORY_ICONS[key] || "📍";
}

export function titleCase(text) {
  if (!text) return text;
  // Only fix shouting ALL-CAPS source names; leave mixed case alone.
  if (text !== text.toUpperCase()) return text;
  return text
    .toLowerCase()
    .replace(/\b([a-z])/g, (m, c) => c.toUpperCase());
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
  const [h, m] = hm.split(":").map(Number);
  const t = h + m / 60;
  return Math.min(1, Math.max(0, (t - dayStart) / (dayEnd - dayStart)));
}

export const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function themeInit() {
  let saved = null;
  try { saved = localStorage.getItem("ea-theme"); } catch { /* private mode */ }
  const theme = saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  return theme;
}

export function themeSet(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("ea-theme", theme); } catch { /* fine */ }
}
