// Plain fetch against the FastAPI backend (Vite proxies /api in dev).
async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

const post = (path, body) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });

export const getDay = (run) =>
  request(`/api/day${run ? `?run=${encodeURIComponent(run)}` : ""}`);
export const getWeek = () => request("/api/week");
export const getRuns = () => request("/api/runs");
export const getRun = (id) => request(`/api/runs/${encodeURIComponent(id)}`);
export const startDay = (date) => post("/api/day/start", { date });
export const startWeek = (date) => post("/api/week/start", { date });
export const ask = (message) => post("/api/ask", { message });
export const approve = (body) => post("/api/approve", { ...body, confirmed: true });

// Poll a growing trace until its run_summary lands. onTick receives the
// records seen so far; returns the final record list.
export async function watchRun(traceId, onTick, intervalMs = 1500) {
  for (;;) {
    let records = [];
    try {
      records = await getRun(traceId);
    } catch {
      // file may not exist for the first beat; keep waiting
    }
    onTick(records);
    if (records.some((r) => r.type === "run_summary")) return records;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
