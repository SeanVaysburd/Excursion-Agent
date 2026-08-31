import React, { useEffect, useState } from "react";
import { getWeek, startWeek, watchRun } from "../api.js";
import { DOW, iconFor, titleCase } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FlowView from "./FlowView.jsx";

const EDGE = {
  nature: "var(--ok)",
  outdoor_event: "var(--warn)",
  indoor: "var(--accent)",
};

export function WeekView({ plan }) {
  const [mode, setMode] = useState("tot");
  const winner = plan.sets?.[0];
  if (!winner) return <p className="fine">no plannable days this week</p>;

  const shown = mode === "naive" && plan.naive ? plan.naive : winner;
  const differ = new Set((plan.contrast?.differing_days || []).map((d) => d.date));
  const byDate = Object.fromEntries(shown.picks.map((p) => [p.date, p]));
  const allDates = [...plan.days_planned, ...plan.days_skipped].sort();

  return (
    <div>
      <div className="statrow">
        <div className="mode-toggle">
          <button className={mode === "naive" ? "on" : ""} onClick={() => setMode("naive")}
            title="pick each day's highest score independently">naive</button>
          <button className={mode === "tot" ? "on" : ""} onClick={() => setMode("tot")}
            title="Tree-of-Thought beam search with the week critic">Tree-of-Thought</button>
        </div>
        <span className="big">{(shown.adjusted ?? shown.base_sum).toFixed(1)}</span>
        <span className="fine">
          {mode === "naive" ? `raw sum ${shown.base_sum.toFixed(1)} (no critic)` :
            `base ${shown.base_sum.toFixed(1)} adjusted by the critic`}
        </span>
        {mode === "tot" && Object.entries(winner.penalties)
          .filter(([, v]) => v > 0)
          .map(([k, v]) => (
            <span key={k} className="chip neg">{k.replace(/_/g, " ")} −{v.toFixed(1)}</span>
          ))}
        <span className="chip">🚇 {shown.transit_min} min</span>
        <span className="chip">🥾 {Number(shown.walk_miles).toFixed(1)} mi</span>
      </div>

      <div className="week-strip">
        {allDates.map((d) => {
          const pick = byDate[d];
          const skipped = plan.days_skipped.includes(d);
          const changed = mode === "tot" && differ.has(d);
          const dt = new Date(d + "T12:00:00");
          return (
            <div key={d} className={`day-cell ${skipped ? "skipped" : ""} ${changed ? "changed" : ""}`}>
              <span className="edge" style={{ background: pick ? (EDGE[pick.category] || "var(--line-2)") : "var(--line-2)" }} />
              <div className="dow">{DOW[(dt.getDay() + 6) % 7]}</div>
              <div className="dom">{d.slice(8)}</div>
              {skipped ? (
                <span className="fine">no free window</span>
              ) : pick ? (
                <>
                  <strong>{iconFor({ domain: pick.category, base: { candidate_id: pick.candidate_id } })} {titleCase(pick.name)}</strong>
                  <div className="fine">{pick.final_score.toFixed(1)} · {pick.transit_min} min transit</div>
                  {changed && <div className="swap">critic changed this day</div>}
                </>
              ) : null}
            </div>
          );
        })}
      </div>

      {mode === "tot" && <p className="fine">critic: {winner.rationale}</p>}

      {plan.contrast?.differing_days?.length > 0 ? (
        <div className="contrast-box">
          <h3>what the critic changed, and why</h3>
          {plan.contrast.differing_days.map((delta) => (
            <div key={delta.date} className="contrast-row">
              <b>{delta.date}</b>
              <s>{titleCase(delta.naive)}</s>
              <span className="arrow">→</span>
              <span>{titleCase(delta.tot)}</span>
            </div>
          ))}
          <p className="fine" style={{ marginBottom: 0 }}>
            dominant penalty: <b>{plan.contrast.dominant_penalty?.replace(/_/g, " ")}</b>.
            A set's value is not the sum of its parts.
          </p>
        </div>
      ) : (
        plan.naive && <p className="fine">no contrast this week (naive matches ToT, reported honestly). Try another week.</p>
      )}

      {plan.sets.slice(1).map((alternate) => (
        <details key={alternate.rank} className="alt">
          <summary>alternate #{alternate.rank} · adjusted {alternate.adjusted.toFixed(1)}</summary>
          {alternate.picks.map((pick) => (
            <p key={pick.date} className="fine">
              {pick.date}: {titleCase(pick.name)} [{pick.category}] {pick.final_score.toFixed(1)}
            </p>
          ))}
        </details>
      ))}
      <p className="fine">
        critic calls {plan.critic_calls} (bound {plan.critic_bound}) ·
        arithmetic mismatches {plan.critic_mismatches}
      </p>
    </div>
  );
}

export default function WeekPlan() {
  const [state, setState] = useState({ loading: true });
  const [liveRecords, setLiveRecords] = useState(null);

  const load = () => {
    setState({ loading: true });
    getWeek()
      .then((data) => setState({ data }))
      .catch((error) => setState({ error: String(error.message || error) }));
  };
  useEffect(load, []);

  const runLive = async () => {
    try {
      const started = await startWeek();
      setLiveRecords([]);
      const records = await watchRun(started.trace_id, setLiveRecords);
      const weekPlan = records.filter((r) => r.type === "weekly_plan").pop();
      setLiveRecords(null);
      if (weekPlan) setState({ data: { source: "live", trace: started.trace_id, plan: weekPlan.plan } });
      else load();
    } catch (error) {
      setLiveRecords(null);
      setState((s) => ({ ...s, error: String(error.message || error) }));
    }
  };

  if (state.loading) return <Skeleton h={120} n={3} />;

  return (
    <div>
      <div className="pagehead">
        <h2>Week plan</h2>
        {state.data && (
          <span className="sub">week of {state.data.plan.week_start} · {state.data.trace}</span>
        )}
        <span className="spacer" />
        <button className="btn" onClick={runLive} disabled={!!liveRecords}
          title="runs 7 daily plans plus the beam search; several minutes">
          {liveRecords ? "running…" : "Run live (minutes)"}
        </button>
      </div>
      {liveRecords && <FlowView records={liveRecords} live />}
      {state.error && !state.data && (
        <div className="empty">
          <div className="big-ico">🗓️</div>
          <p className="fine">{state.error}</p>
          <button className="btn primary" onClick={runLive}>Run the first weekly plan</button>
        </div>
      )}
      {state.data && <WeekView plan={state.data.plan} />}
    </div>
  );
}
