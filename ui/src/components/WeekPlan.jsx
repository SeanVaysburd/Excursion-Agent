import React, { useEffect, useState } from "react";
import { getWeek } from "../api.js";

function PenaltyChips({ penalties }) {
  return (
    <span className="chips inline">
      {Object.entries(penalties)
        .filter(([, value]) => value > 0)
        .map(([name, value]) => (
          <span key={name} className="chip adj">
            {name} −{value.toFixed(1)}
          </span>
        ))}
    </span>
  );
}

export default function WeekPlan() {
  const [state, setState] = useState({ loading: true });
  const load = (refresh) => {
    setState({ loading: true, refresh });
    getWeek(refresh)
      .then((data) => setState({ data }))
      .catch((error) => setState({ error: String(error.message || error) }));
  };
  useEffect(() => load(false), []);

  if (state.loading)
    return (
      <p className="status">
        {state.refresh
          ? "running the weekly Tree-of-Thought (7 daily plans + beam search — several minutes)…"
          : "loading latest weekly run…"}
      </p>
    );
  if (state.error)
    return (
      <div>
        <p className="status error">{state.error}</p>
        <button onClick={() => load(true)}>Run weekly now (minutes)</button>
      </div>
    );

  const plan = state.data.plan;
  const winner = plan.sets[0];
  return (
    <div>
      <div className="bar">
        <h2>week of {plan.week_start}</h2>
        <span className="source">
          {state.data.source === "live" ? "live run" : `latest run · ${state.data.trace}`}
        </span>
        <button onClick={() => load(true)}>Refresh (live, minutes)</button>
      </div>
      {!winner ? (
        <p className="status">no plannable days this week</p>
      ) : (
        <>
          <div className="week-grid">
            {winner.picks.map((pick) => (
              <div key={pick.date} className="day-cell">
                <div className="day-date">{pick.date.slice(5)}</div>
                <strong>{pick.name}</strong>
                <div className="fine">
                  {pick.category} · {pick.final_score.toFixed(1)} ·{" "}
                  {pick.transit_min} min transit
                </div>
              </div>
            ))}
            {plan.days_skipped.map((day) => (
              <div key={day} className="day-cell skipped">
                <div className="day-date">{day.slice(5)}</div>
                <div className="fine">no free window</div>
              </div>
            ))}
          </div>
          <p>
            base {winner.base_sum.toFixed(1)} → adjusted{" "}
            <strong>{winner.adjusted.toFixed(1)}</strong>
            <PenaltyChips penalties={winner.penalties} />
          </p>
          <p className="fine">critic: {winner.rationale}</p>

          {plan.naive && plan.contrast && plan.contrast.differing_days && (
            <div className="contrast">
              <h3>naive rank-by-sum vs Tree-of-Thought</h3>
              {plan.contrast.differing_days.length === 0 ? (
                <p className="fine">
                  no contrast this week (naive == ToT — reported honestly;
                  try another week)
                </p>
              ) : (
                <>
                  {plan.contrast.differing_days.map((delta) => (
                    <p key={delta.date}>
                      {delta.date}: <s>{delta.naive}</s> → {delta.tot}
                    </p>
                  ))}
                  <p className="fine">
                    dominant penalty: {plan.contrast.dominant_penalty} — a
                    set&apos;s value is not the sum of its parts
                  </p>
                </>
              )}
            </div>
          )}

          {plan.sets.slice(1).map((alternate) => (
            <details key={alternate.rank} className="alt">
              <summary>
                alternate #{alternate.rank} · adjusted{" "}
                {alternate.adjusted.toFixed(1)}
              </summary>
              {alternate.picks.map((pick) => (
                <p key={pick.date} className="fine">
                  {pick.date}: {pick.name} [{pick.category}]{" "}
                  {pick.final_score.toFixed(1)}
                </p>
              ))}
              <PenaltyChips penalties={alternate.penalties} />
            </details>
          ))}
          <p className="fine">
            critic calls {plan.critic_calls} (bound {plan.critic_bound}) ·
            arithmetic mismatches {plan.critic_mismatches}
          </p>
        </>
      )}
    </div>
  );
}
