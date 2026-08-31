import React, { useEffect, useState } from "react";
import { getRun, getRuns } from "../api.js";

const TYPE_ICONS = {
  step: "·",
  llm_call: "🤖",
  validation: "✓",
  prune: "✂",
  critic: "⚖",
  escalation: "⛔",
  approval: "📅",
  run_summary: "Σ",
  day_plan: "📋",
  weekly_plan: "🗓",
};

function Record({ record }) {
  const [open, setOpen] = useState(false);
  const icon = TYPE_ICONS[record.type] || "·";
  const headline =
    record.type === "step"
      ? `${record.stage} · ${record.tool} · ${record.status}` +
        (record.latency_ms != null ? ` · ${record.latency_ms}ms` : "") +
        (record.fallback_taken ? " · FALLBACK" : "")
      : record.type === "validation"
        ? `${record.validator}: checked ${record.checked}, violations ${record.violations}`
        : record.type === "critic"
          ? `depth ${record.depth} · ${record.candidate} · adj ${Number(record.code_adjusted).toFixed(1)}`
          : record.type === "prune"
            ? `pruned ${JSON.stringify(record.picks || record.candidate)} — ${record.reason}`
            : record.type === "escalation"
              ? record.message
              : record.type;
  return (
    <div className={`trace-row t-${record.type}`}>
      <button className="trace-head" onClick={() => setOpen(!open)}>
        <span className="icon">{icon}</span>
        <span className="ts">{(record.ts || "").slice(11, 19)}</span>
        <span>{headline}</span>
        {record.injected_failure && (
          <span className="chip gated">SIMULATED: {record.injected_failure}</span>
        )}
      </button>
      {open && <pre>{JSON.stringify(record, null, 2)}</pre>}
    </div>
  );
}

export default function RunTrace() {
  const [runs, setRuns] = useState(null);
  const [selected, setSelected] = useState(null);
  const [recordsData, setRecordsData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getRuns().then(setRuns).catch((e) => setError(String(e.message || e)));
  }, []);
  useEffect(() => {
    if (!selected) return;
    setRecordsData(null);
    getRun(selected).then(setRecordsData).catch((e) => setError(String(e.message || e)));
  }, [selected]);

  if (error) return <p className="status error">{error}</p>;
  if (!runs) return <p className="status">loading runs…</p>;
  if (runs.length === 0)
    return <p className="status">no trajectory logs yet — run demo.py or press Refresh on Day Plan</p>;

  return (
    <div className="trace">
      <div className="run-list">
        {runs.map((run) => (
          <button
            key={run.id}
            className={run.id === selected ? "run active" : "run"}
            onClick={() => setSelected(run.id)}
          >
            <strong>{run.scenario}</strong> {run.id}
            <div className="fine">
              {run.mtime} · {run.records} records
            </div>
          </button>
        ))}
      </div>
      <div className="records">
        {selected == null ? (
          <p className="status">pick a run</p>
        ) : recordsData == null ? (
          <p className="status">loading…</p>
        ) : (
          recordsData.map((record, index) => <Record key={index} record={record} />)
        )}
      </div>
    </div>
  );
}
