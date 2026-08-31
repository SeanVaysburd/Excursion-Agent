// Plain fetch against the FastAPI backend (Vite proxies /api in dev).
async function request(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const getDay = (refresh = false) =>
  request(`/api/day${refresh ? "?refresh=true" : ""}`);
export const getWeek = (refresh = false) =>
  request(`/api/week${refresh ? "?refresh=true" : ""}`);
export const getRuns = () => request("/api/runs");
export const getRun = (id) => request(`/api/runs/${encodeURIComponent(id)}`);
export const approve = (body) =>
  request("/api/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, confirmed: true }),
  });
