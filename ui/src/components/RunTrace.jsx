import React, { useEffect, useState } from "react";
import { getRun, getRuns } from "../api.js";
import { relTime } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FlowView from "./FlowView.jsx";

const TYPE_ICONS = {
  step: "·", llm_call: "🤖", validation: "✓", prune: "✂", critic: "⚖",
  escalation: "⛔", approval: "📅", run_summary: "Σ", day_plan: "📋",
  weekly_plan: "🗓",
};

function headline(record) {
  switch (record.type) {
    case "step":
      return `${record.stage} · ${record.tool} · ${record.status}`
        + (record.latency_ms != null ? ` · ${record.latency_ms}ms` : "")
        + (record.fallback_taken ? " · FALLBACK" : "");
    case "validation":
      return `${record.validator}: checked ${record.checked}, violations ${record.violations}`;
    case "critic":
      return `depth ${record.depth} · ${record.candidate} · adjusted ${Number(record.code_adjusted).toFixed(1)}`;
    case "prune":
      return `pruned ${JSON.stringify(record.picks || record.candidate)}: ${record.reason}`;
    case "escalation":
      return record.message;
    case "llm_call":
      return `${record.purpose} call · ${record.provider}` + (record.retried ? " · retried" : "");
    default:
      return record.type;
  }
}

function Row({ record }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`trace-row t-${record.type}`}>
      <button className="trace-head" onClick={() => setOpen(!open)}>
        <span>{TYPE_ICONS[record.type] || "·"}</span>
        <span className="ts">{(record.ts || "").slice(11, 19)}</span>
        <span style={{ flex: 1 }}>{headline(record)}</span>
        {record.injected_failure && (
          <span className="chip sim">SIMULATED: {record.injected_failure}</span>
        )}
      </button>
      {open && <pre>{JSON.stringify(record, null, 2)}</pre>}
    </div>
  );
}

export default function RunTrace() {
  const [runs, setRuns] = useState(null);
  const [selected, setSelected] = useState(null);
  const [records, setRecords] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    getRuns().then((r) => {
      setRuns(r);
      if (r.length) setSelected(r[0].id);
    }).catch((e) => setError(String(e.message || e)));
  }, []);
  useEffect(() => {
    if (!selected) return;
    setRecords(null);
    setFilter("");
    getRun(selected).then(setRecords).catch((e) => setError(String(e.message || e)));
  }, [selected]);

  if (error) return <p className="fine">{error}</p>;
  if (!runs) return <Skeleton h={70} n={5} />;
  if (runs.length === 0) {
    return (
      <div className="empty">
        <div className="big-ico">🧾</div>
        <p className="fine">no trajectory logs yet. Ask for a plan first.</p>
      </div>
    );
  }

  const shown = (records || []).filter((r) =>
    !filter || JSON.stringify(r).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <div className="pagehead">
        <h2>Run trace</h2>
        <span className="sub">every run's full audit log; nothing is invented</span>
        <span className="spacer" />
        <input className="runpick" placeholder="filter records…" value={filter}
          onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }} />
      </div>
      <div className="trace">
        <div className="run-list">
          {runs.map((run) => (
            <button key={run.id}
              className={run.id === selected ? "run active" : "run"}
              onClick={() => setSelected(run.id)}>
              <span className="scen">{run.scenario}</span>
              {run.live && <span className="live-dot">● live</span>}
              <span className="fine"> {relTime(run.mtime)} · {run.records} records</span>
              <div className="id">{run.id}</div>
            </button>
          ))}
        </div>
        <div>
          {records === null ? (
            <Skeleton h={60} n={6} />
          ) : (
            <>
              <FlowView records={records} />
              <div className="records">
                {shown.map((record, i) => <Row key={i} record={record} />)}
                {!shown.length && <p className="fine" style={{ padding: 14 }}>no records match the filter</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
