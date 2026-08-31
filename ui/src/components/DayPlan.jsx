import React, { useEffect, useRef, useState } from "react";
import { getDay, getRuns, startDay, watchRun } from "../api.js";
import { relTime } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FeedbackModal from "./FeedbackModal.jsx";
import FlowView from "./FlowView.jsx";
import { WeatherIcon } from "./Icons.jsx";
import PlanView from "./PlanView.jsx";

export default function DayPlan() {
  const [state, setState] = useState({ loading: true });
  const [runs, setRuns] = useState([]);
  const [pinned, setPinned] = useState("");
  const [liveRecords, setLiveRecords] = useState(null);
  const [logging, setLogging] = useState(false);
  const [savedNote, setSavedNote] = useState(null);
  const abortRef = useRef(null);

  const load = (run) => {
    setState({ loading: true });
    getDay(run || undefined)
      .then((data) => setState({ data }))
      .catch((error) => setState({ error: String(error.message || error) }));
  };
  useEffect(() => {
    load();
    getRuns().then(setRuns).catch(() => {});
    return () => abortRef.current?.abort();
  }, []);

  const runLive = async () => {
    abortRef.current = new AbortController();
    try {
      const started = await startDay();
      setLiveRecords([]);
      const records = await watchRun(started.trace_id, setLiveRecords,
        { signal: abortRef.current.signal });
      const dayPlan = records.filter((r) => r.type === "day_plan").pop();
      const summary = records.filter((r) => r.type === "run_summary").pop();
      setLiveRecords(null);
      if (dayPlan) {
        setState({ data: { source: "live", trace: started.trace_id, plan: dayPlan.plan, summary } });
      } else load();
      getRuns().then(setRuns).catch(() => {});
    } catch (error) {
      if (error.aborted) return;
      setLiveRecords(null);
      setState((s) => ({ ...s, error: String(error.message || error) }));
    }
  };

  if (state.loading) return <Skeleton h={110} n={3} />;

  const plan = state.data?.plan;
  const summary = state.data?.summary;
  // Demo surface: only clean, completed day plans belong in the picker.
  // Simulated forced-error and escalation fixtures stay in the Runs tab,
  // labeled, for the guardrail story.
  const dayRuns = runs.filter((r) => r.has_day_plan && !r.simulated && !r.escalated);

  return (
    <div>
      <div className="pagehead">
        <h2>{plan ? `${plan.date} (${plan.weekday})` : "Day plan"}</h2>
        {state.data && <span className="sub">{state.data.trace}</span>}
        <span className="spacer" />
        <button className="btn quiet" onClick={() => setLogging(true)}
          title="log an outing the agent never suggested; it becomes memory too">
          Log an outing
        </button>
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
      {state.error && (
        <div className={plan ? "callout warn" : "empty"}>
          {!plan && <div className="big-ico"><WeatherIcon size={34} /></div>}
          <p className="fine">{state.error}</p>
          {!plan && <button className="btn primary" onClick={runLive}>Run the first plan</button>}
        </div>
      )}
      {savedNote && (
        <div className="callout ok" onClick={() => setSavedNote(null)} role="status">
          Saved as <b>{savedNote}</b>. The agent retrieves it from the next
          run on. (click to dismiss)
        </div>
      )}
      {plan && <PlanView plan={plan} summary={summary} />}
      {logging && (
        <FeedbackModal initial={{ kind: "outing" }}
          onClose={() => setLogging(false)}
          onSaved={(result) => setSavedNote(result.id)} />
      )}
    </div>
  );
}
