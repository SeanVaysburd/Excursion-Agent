// Per-run model choice, persisted per browser. Empty string means the
// server's .env default; the API receives a provider only when one is
// explicitly chosen, and every trace's run summary records what actually
// ran, so provenance stays honest whichever way the switch points.
export function getProvider() {
  try { return localStorage.getItem("ea-provider") || ""; } catch { return ""; }
}

export function setProvider(value) {
  try {
    if (value) localStorage.setItem("ea-provider", value);
    else localStorage.removeItem("ea-provider");
  } catch { /* private mode */ }
}
