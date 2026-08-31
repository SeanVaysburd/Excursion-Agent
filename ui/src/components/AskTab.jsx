import React, { useEffect, useRef, useState } from "react";
import { ask, watchRun } from "../api.js";
import FlowView from "./FlowView.jsx";
import PlanView from "./PlanView.jsx";
import { WeekView } from "./WeekPlan.jsx";

const SUGGESTIONS = [
  "What should I do Saturday morning?",
  "Plan tomorrow for me",
  "Plan my week",
  "Anything good on Sunday?",
];

export default function AskTab({ active = true }) {
  const [message, setMessage] = useState("");
  const [thread, setThread] = useState([]);
  const [busy, setBusy] = useState(false);
  const [liveRecords, setLiveRecords] = useState(null);
  const [liveKind, setLiveKind] = useState("day");
  const inputRef = useRef(null);
  const endRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  // New thread entries (or a live run starting/ending) scroll into view;
  // the input gets focus back once the agent is done. Both are no-ops
  // while the tab is hidden, so they also re-run when it becomes visible.
  // Keyed on WHETHER a live view exists, not its contents: every poll
  // tick delivers a fresh records array, and force-scrolling on each one
  // would yank the page away from wherever the user scrolled.
  const liveShowing = liveRecords !== null;
  useEffect(() => {
    if (!active) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread, liveShowing, active]);
  useEffect(() => {
    if (!busy && active) inputRef.current?.focus();
  }, [busy, active]);

  const submit = async (text) => {
    const q = (text || message).trim();
    if (!q || busy) return;
    setMessage("");
    setBusy(true);
    setThread((t) => [...t, { role: "you", text: q }]);
    try {
      const res = await ask(q);
      const intent = res.intent;
      if (intent.kind === "clarify" || intent.kind === "unsupported") {
        setThread((t) => [...t, { role: "agent", text: intent.reply }]);
        setBusy(false);
        return;
      }
      setThread((t) => [...t, {
        role: "agent",
        text: intent.kind === "week"
          ? `On it. Planning the week of ${intent.date} (7 daily plans plus the beam search, a few minutes).`
          : `On it. Planning ${intent.date} live.`,
      }]);
      setLiveKind(intent.kind === "week" ? "week" : "day");
      setLiveRecords([]);
      abortRef.current = new AbortController();
      const records = await watchRun(res.trace_id, setLiveRecords,
        { signal: abortRef.current.signal });
      const dayPlan = records.filter((r) => r.type === "day_plan").pop();
      const weekPlan = records.filter((r) => r.type === "weekly_plan").pop();
      const summary = records.filter((r) => r.type === "run_summary").pop();
      setLiveRecords(null);
      if (weekPlan) {
        setThread((t) => [...t, { role: "result-week", plan: weekPlan.plan }]);
      } else if (dayPlan) {
        setThread((t) => [...t, { role: "result-day", plan: dayPlan.plan, summary }]);
      } else {
        setThread((t) => [...t, {
          role: "agent",
          text: summary?.error
            ? `That run failed: ${summary.error}`
            : "The run finished but produced no plan. Check its trace in the Runs tab.",
        }]);
      }
    } catch (error) {
      if (error.aborted) return;
      setThread((t) => [...t, { role: "agent", text: String(error.message || error) }]);
      setLiveRecords(null);
    }
    setBusy(false);
  };

  return (
    <div>
      {thread.length === 0 && (
        <div className="hero">
          <div className="glow" />
          <div className="kicker">Excursion Agent</div>
          <h2>
            Where should your <span className="grad">free time</span> go?
          </h2>
          <p>
            Ask about any day in the next 16 days (the reach of a real
            forecast). It reads your calendar, checks live weather, birds,
            events and subway alerts, and remembers how your past trips
            actually went.
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {thread.map((entry, i) => {
          if (entry.role === "you") {
            return (
              <div key={i} className="bubble you">
                {entry.text}
              </div>
            );
          }
          if (entry.role === "agent") {
            return (
              <div key={i} className="bubble agent">
                {entry.text}
              </div>
            );
          }
          if (entry.role === "result-day") {
            return <PlanView key={i} plan={entry.plan} summary={entry.summary} />;
          }
          return <WeekView key={i} plan={entry.plan} />;
        })}
        {liveRecords && <FlowView records={liveRecords} live mode={liveKind} />}
        <div ref={endRef} />
      </div>

      <div className="askbar">
        <div style={{ display: "flex", gap: 8 }}>
          <input
            ref={inputRef}
            className="askinput"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder={busy ? "planning..." : "Ask about a day or your week"}
            disabled={busy}
          />
          <button className="btn primary" disabled={busy} onClick={() => submit()}>
            {busy ? "…" : "Plan it"}
          </button>
        </div>
        {thread.length === 0 && (
          <div className="chips" style={{ marginTop: 10 }}>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip ev" style={{ border: "none", fontFamily: "inherit" }}
                onClick={() => submit(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
