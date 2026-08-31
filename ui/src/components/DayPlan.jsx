import React, { useEffect, useState } from "react";
import { getDay, getRuns, startDay, watchRun } from "../api.js";
import { relTime } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FlowView from "./FlowView.jsx";
import PlanView from "./PlanView.jsx";

export default function DayPlan() {
  const [state, setState] = useState({ loading: true });
  const [runs, setRuns] = useState([]);
  const [pinned, setPinned] = useState("");
  const [liveRecords, setLiveRecords] = useState(null);

  const load = (run) => {
    setState({ loading: true });
    getDay(run || undefined)
      .then((data) => setState({ data }))
      .catch((error) => setState({ error: String(error.message || error) }));
  };
  useEffect(() => {
    load();
    getRuns().then(setRuns).catch(() => {});
  }, []);

  const runLive = async () => {
    try {
      const started = await startDay();
      setLiveRecords([]);
      const records = await watchRun(started.trace_id, setLiveRecords);
      const dayPlan = records.filter((r) => r.type === "day_plan").pop();
      const summary = records.filter((r) => r.type === "run_summary").pop();
      setLiveRecords(null);
      if (dayPlan) {
        setState({ data: { source: "live", trace: started.trace_id, plan: dayPlan.plan, summary } });
      } else load();
      getRuns().then(setRuns).catch(() => {});
    } catch (error) {
      setLiveRecords(null);
      setState((s) => ({ ...s, error: String(error.message || error) }));
    }
  };

  if (state.loading) return <Skeleton h={110} n={3} />;

  const plan = state.data?.plan;
  const summary = state.data?.summary;
  const dayRuns = runs.filter((r) => /S1|S3|S4|day|ollama_S1|escalation|forced/.test(r.id));

  return (
    <div>
      <div className="pagehead">
        <h2>{plan ? `${plan.date} (${plan.weekday})` : "Day plan"}</h2>
        {state.data && <span className="sub">{state.data.trace}</span>}
        <span className="spacer" />
        {dayRuns.length > 0 && (
          <select className="runpick" value={pinned}
            onChange={(e) => { setPinned(e.target.value); load(e.target.value); }}>
            <option value="">latest clean run</option>
            {dayRuns.map((r) => (
              <option key={r.id} value={r.id}>
                {r.scenario} · {r.id.replace(/^sample_/, "")} · {relTime(r.mtime)}
              </option>
            ))}
          </select>
        )}
        <button className="btn primary" onClick={runLive} disabled={!!liveRecords}>
          {liveRecords ? "running…" : "Run live now"}
        </button>
      </div>
      {liveRecords && <FlowView records={liveRecords} live />}
      {state.error && !plan && (
        <div className="empty">
          <div className="big-ico">🌤️</div>
          <p className="fine">{state.error}</p>
          <button className="btn primary" onClick={runLive}>Run the first plan</button>
        </div>
      )}
      {plan && <PlanView plan={plan} summary={summary} />}
    </div>
  );
}
