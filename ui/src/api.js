import { getProvider } from "./provider.js";

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
export const startDay = (date) =>
  post("/api/day/start", { date, provider: getProvider() || undefined });
export const startWeek = (date) =>
  post("/api/week/start", { date, provider: getProvider() || undefined });
export const ask = (message) =>
  post("/api/ask", { message, provider: getProvider() || undefined });
export const approve = (body) => post("/api/approve", { ...body, confirmed: true });
export const sendFeedback = (body) => post("/api/feedback", { ...body, confirmed: true });

// Poll a growing trace until its run_summary lands. onTick receives the
// records seen so far; resolves with the final record list. An abort
// signal (pass one from the mounting component) stops the poll cleanly,
// and the deadline keeps a stalled run from polling forever.
export async function watchRun(traceId, onTick, options = {}) {
  const { intervalMs = 1500, staleMs = 60 * 1000, signal } = options;
  // No wall-clock deadline: a weekly plan on the local model can run for an
  // hour, and a finished run must land in the UI however long it took. The
  // only way out without a result is proof the run DIED: no new records for
  // a while AND the server no longer lists it as live (a restart killed the
  // task before it could write its summary).
  let lastCount = -1;
  let quietSince = Date.now();
  for (;;) {
    if (signal?.aborted) {
      const err = new Error("stopped watching");
      err.aborted = true;
      throw err;
    }
    try {
      const records = await getRun(traceId);
      // Only a SUCCESSFUL poll updates the view: pushing [] on a hiccup
      // would blank the flow diagram until the next beat (visible blink).
      if (!signal?.aborted) onTick(records);
      if (records.some((r) => r.type === "run_summary")) return records;
      if (records.length !== lastCount) {
        lastCount = records.length;
        quietSince = Date.now();
      } else if (Date.now() - quietSince > staleMs) {
        const listed = (await getRuns()).find((r) => r.id === traceId);
        if (listed && !listed.live) {
          const err = new Error(
            "that run stopped before finishing (the server may have restarted); "
            + "its partial trace is in the Runs tab");
          err.dead = true;
          throw err;
        }
        quietSince = Date.now(); // still alive, just thinking; keep waiting
      }
    } catch (error) {
      if (error.dead) throw error;
      // file may not exist for the first beat, or the proxy hiccuped;
      // keep the last good view and try again
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
