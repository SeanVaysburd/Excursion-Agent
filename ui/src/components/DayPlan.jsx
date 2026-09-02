import React, { useEffect, useRef, useState } from "react";
import { getDay, getRuns, startDay, watchRun } from "../api.js";
import { relTime } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FeedbackModal from "./FeedbackModal.jsx";
import FlowView from "./FlowView.jsx";
import { WeatherIcon } from "./Icons.jsx";
import PlanView from "./PlanView.jsx";

export default function DayPlan({ active = true }) {
  const [state, setState] = useState({ loading: true });
  const [runs, setRuns] = useState([]);
  const [pinned, setPinned] = useState("");
  const [liveRecords, setLiveRecords] = useState(null);
  const [starting, setStarting] = useState(false);
  const [logging, setLogging] = useState(false);
  const [savedNote, setSavedNote] = useState(null);
  const abortRef = useRef(null);
  const watchingRef = useRef(null); // trace id currently being watched

  const load = (run) => {
    setState({ loading: true });
    getDay(run || undefined)
      .then((data) => setState({ data }))
      .catch((error) => setState({ error: String(error.message || error) }));
  };
  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, []);

  const watchLive = async (traceId) => {
    watchingRef.current = traceId;
    abortRef.current = new AbortController();
    try {
      setLiveRecords([]);
      const records = await watchRun(traceId, setLiveRecords,
        { signal: abortRef.current.signal });
      const dayPlan = records.filter((r) => r.type === "day_plan").pop();
      const summary = records.filter((r) => r.type === "run_summary").pop();
      setLiveRecords(null);
      if (dayPlan) {
        setState({ data: { source: "live", trace: traceId, plan: dayPlan.plan, summary } });
      } else load();
      getRuns().then(setRuns).catch(() => {});
    } catch (error) {
      if (!error.aborted) {
        setLiveRecords(null);
        setState((s) => ({ ...s, error: String(error.message || error) }));
      }
    }
    // Only the CURRENT watcher may clear the marker; an old one finishing
    // late must not erase a newer watcher's guard.
    if (watchingRef.current === traceId) watchingRef.current = null;
  };

  const runLive = async () => {
    if (starting || liveRecords) return;
    setStarting(true); // disabled from the CLICK, not from the first poll
    try {
      const started = await startDay();
      setStarting(false);
      await watchLive(started.trace_id);
    } catch (error) {
      setStarting(false);
      setState((s) => ({ ...s, error: String(error.message || error) }));
    }
  };

  // Whenever this tab is shown: refresh the run list, and if a live DAY
  // run is in flight (started from any tab, usually Ask), attach to it so
  // its progress shows here instead of stale completed data. If nothing is
  // live, an Ask run may have FINISHED for a different date while this tab
  // was hidden: silently refetch the latest plan, swapping state only when
  // the trace actually changed (no skeleton flash on plain tab switches).
  useEffect(() => {
    if (!active) return;
    getRuns().then((r) => {
      setRuns(r);
      const live = r.find((x) => x.live && x.scenario === "ui-day");
      if (live && watchingRef.current !== live.id) watchLive(live.id);
      else if (!live && !pinned && !watchingRef.current) {
        // Compare trace ids with the .jsonl suffix stripped: live runs
        // store the stem, GET /api/day returns the file name, and a raw
        // compare would swap identical data (losing the run summary).
        const stem = (t) => (t || "").replace(/\.jsonl$/, "");
        getDay().then((data) => setState((s) =>
          stem(s.data?.trace) === stem(data.trace) ? s : { data })).catch(() => {});
      }
    }).catch(() => {});
  }, [active]);

  if (state.loading) return <Skeleton h={110} n={3} />;

  const plan = state.data?.plan;
  const summary = state.data?.summary;
  // While attached to a live run, headline WHAT is being planned (from the
  // trace's run_start record) instead of leaving stale plan data on top.
  const liveStart = (liveRecords || []).find((r) => r.type === "run_start");
  // Demo surface: only clean, completed day plans belong in the picker.
  // Simulated forced-error and escalation fixtures stay in the Runs tab,
  // labeled, for the guardrail story.
  const dayRuns = runs.filter((r) => r.has_day_plan && !r.simulated && !r.escalated);

  return (
    <div>
      <div className="pagehead">
        <h2>
          {liveRecords ? `Planning ${liveStart?.date || "a new day"}…`
            : plan ? `${plan.date} (${plan.weekday})` : "Day plan"}
        </h2>
        {state.data && !liveRecords && <span className="sub">{state.data.trace}</span>}
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
        <button className="btn primary" onClick={runLive}
          disabled={starting || !!liveRecords}>
          {starting ? "starting…" : liveRecords ? "running…" : "Run live now"}
        </button>
      </div>
      {liveRecords && <FlowView records={liveRecords} live mode="day" />}
      {state.error && !liveRecords && (
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
      {plan && !liveRecords && <PlanView plan={plan} summary={summary} />}
      {logging && (
        <FeedbackModal initial={{ kind: "outing" }}
          onClose={() => setLogging(false)}
          onSaved={(result) => setSavedNote(result.id)} />
      )}
    </div>
  );
}
