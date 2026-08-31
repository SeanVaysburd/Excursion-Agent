import React, { useRef, useState } from "react";
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

export default function AskTab() {
  const [message, setMessage] = useState("");
  const [thread, setThread] = useState([]);
  const [busy, setBusy] = useState(false);
  const [liveRecords, setLiveRecords] = useState(null);
  const inputRef = useRef(null);

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
      setLiveRecords([]);
      const records = await watchRun(res.trace_id, setLiveRecords);
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
            Ask about any day in the next two weeks. It reads your calendar,
            checks real weather, birds, events and subway alerts, and
            remembers how your past trips actually went.
          </p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {thread.map((entry, i) => {
          if (entry.role === "you") {
            return (
              <div key={i} style={{ alignSelf: "flex-end" }}>
                <span className="chip accent" style={{ fontSize: 13, padding: "8px 14px" }}>
                  {entry.text}
                </span>
              </div>
            );
          }
          if (entry.role === "agent") {
            return (
              <div key={i} style={{ alignSelf: "flex-start", maxWidth: 560 }}>
                <span className="chip" style={{ fontSize: 13, padding: "8px 14px", whiteSpace: "normal" }}>
                  {entry.text}
                </span>
              </div>
            );
          }
          if (entry.role === "result-day") {
            return <PlanView key={i} plan={entry.plan} summary={entry.summary} />;
          }
          return <WeekView key={i} plan={entry.plan} />;
        })}
        {liveRecords && <FlowView records={liveRecords} live />}
      </div>

      <div style={{ position: "sticky", bottom: 16, marginTop: 22 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            ref={inputRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder={busy ? "planning..." : "Ask about a day or your week"}
            disabled={busy}
            style={{
              flex: 1, padding: "13px 16px", borderRadius: 14, fontSize: 14,
              border: "1px solid var(--line-2)", background: "var(--bg-raised)",
              color: "var(--text)", boxShadow: "var(--shadow-1)", outline: "none",
            }}
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
