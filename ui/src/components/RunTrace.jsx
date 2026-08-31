import React, { useEffect, useState } from "react";
import { getRun, getRuns } from "../api.js";
import { relTime } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FlowView from "./FlowView.jsx";
import {
  AgentIcon, AlertIcon, CalendarIcon, CheckIcon, DocIcon, DotIcon,
  GridIcon, PruneIcon, ScaleIcon, SigmaIcon, StampIcon, StarIcon,
} from "./Icons.jsx";

const TYPE_ICONS = {
  step: DotIcon, llm_call: AgentIcon, agent_report: AgentIcon,
  validation: CheckIcon, prune: PruneIcon, critic: ScaleIcon,
  escalation: AlertIcon, approval: StampIcon, run_summary: SigmaIcon,
  day_plan: DocIcon, weekly_plan: GridIcon, feedback: StarIcon,
  run_start: CalendarIcon,
};

// Which timeline records each flow node maps to (FlowView click filter).
const NODE_FILTERS = {
  calendar: "calendar", gate: "weather_gate", prefetch: "prefetch",
  nature: "nature", outdoor_event: "outdoor_event", indoor: "indoor",
  pipeline: "validation", result: "day_plan", escalate: "escalation",
  days: "calendar", beam: "critic", winner: "weekly_plan",
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
    case "agent_report": {
      const n = (record.report?.candidates || []).length;
      return `${record.domain} agent full output · ${n} candidate(s)`
        + (record.retried ? " · retried" : "")
        + (record.fallback ? " · FALLBACK" : "");
    }
    case "day_plan":
      return `day plan ready · ${record.plan?.date || ""}`
        + (record.plan?.escalated ? " · escalated" : "");
    case "weekly_plan":
      return `weekly plan ready · week of ${record.plan?.week_start || ""}`;
    case "approval":
      return `calendar write ${record.decision} · ${record.detail || record.event_uid || ""}`;
    case "run_summary":
      return `run finished · ${record.provider || "?"} · `
        + `${Object.values(record.llm_calls || {}).length ? `llm ${record.llm_calls?.total ?? "?"}` : "no llm calls"}`
        + (record.error ? ` · ERROR: ${record.error}` : "");
    case "feedback":
      return `feedback saved · ${record.kind} · ${record.entry_id}`;
    default:
      return record.type;
  }
}

function Row({ record }) {
  const [open, setOpen] = useState(false);
  const Icon = TYPE_ICONS[record.type] || DotIcon;
  return (
    <div className={`trace-row t-${record.type}`}>
      <button className="trace-head" onClick={() => setOpen(!open)}>
        <span className="t-ico"><Icon size={13} /></span>
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

// Fixtures and bookkeeping traces stay listed (labeled) but should not be
// what the tab opens on.
const isFixture = (run) =>
  run.simulated || run.approval || run.escalated
  || /^ui-(approval|feedback)/.test(run.scenario || "");

export default function RunTrace() {
  const [runs, setRuns] = useState(null);
  const [selected, setSelected] = useState(null);
  const [records, setRecords] = useState(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    getRuns().then((r) => {
      setRuns(r);
      const first = r.find((run) => !isFixture(run)) || r[0];
      if (first) setSelected(first.id);
    }).catch((e) => setError(String(e.message || e)));
  }, []);
  useEffect(() => {
    if (!selected) return;
    setRecords(null);
    setFilter("");
    setError(null);
    getRun(selected).then(setRecords).catch((e) => setError(String(e.message || e)));
  }, [selected]);

  if (!runs) {
    return error ? <p className="fine">{error}</p> : <Skeleton h={70} n={5} />;
  }
  if (runs.length === 0) {
    return (
      <div className="empty">
        <div className="big-ico"><DocIcon size={34} /></div>
        <p className="fine">no trajectory logs yet. Ask for a plan first.</p>
      </div>
    );
  }

  const shown = (records || [])
    .map((record, index) => ({ record, index }))
    .filter(({ record }) =>
      !filter || JSON.stringify(record).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <div className="pagehead">
        <h2>Run trace</h2>
        <span className="sub">every step, agent output and check, as logged</span>
        <span className="spacer" />
        <input className="runpick" placeholder="filter records…" value={filter}
          onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }} />
      </div>
      {error && (
        <div className="callout warn" onClick={() => setError(null)}>
          {error} (click to dismiss)
        </div>
      )}
      <div className="trace">
        <div className="run-list">
          {runs.map((run) => (
            <button key={run.id}
              className={run.id === selected ? "run active" : "run"}
              onClick={() => setSelected(run.id)}>
              <span className="scen">{run.scenario}</span>
              {run.live && <span className="live-dot">● live</span>}
              {run.simulated && <span className="chip sim">simulated</span>}
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
              <FlowView records={records}
                onSelect={(nodeId) => setFilter(NODE_FILTERS[nodeId] || "")} />
              {filter && (
                <p className="fine" style={{ margin: "6px 0" }}>
                  filtering on "{filter}"{" "}
                  <button className="btn quiet" style={{ padding: "2px 8px" }}
                    onClick={() => setFilter("")}>clear</button>
                </p>
              )}
              <div className="records">
                {shown.map(({ record, index }) => (
                  <Row key={`${index}-${record.type}`} record={record} />
                ))}
                {!shown.length && <p className="fine" style={{ padding: 14 }}>no records match the filter</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
