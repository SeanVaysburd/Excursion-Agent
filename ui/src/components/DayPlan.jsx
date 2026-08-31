import React, { useEffect, useState } from "react";
import { approve, getDay } from "../api.js";

function Badge({ level }) {
  return <span className={`badge conf-${level}`}>{level}</span>;
}

function Card({ candidate, date, onApprove }) {
  const base = candidate.base;
  const adjustments = candidate.adjustments.filter((a) => a.delta !== 0);
  return (
    <div className="card">
      <div className="card-head">
        <strong>{base.name}</strong>
        <span className="score">
          {candidate.final_score.toFixed(1)}
          <small> (model {base.score})</small>
        </span>
      </div>
      <p className="reason">{base.reason}</p>
      {candidate.transit_note && (
        <p className="transit">⚠ {candidate.transit_note}</p>
      )}
      <div className="chips">
        <Badge level={candidate.confidence} />
        {adjustments.map((adjustment) => (
          <span key={adjustment.label} className="chip adj">
            {adjustment.label} {adjustment.delta > 0 ? "+" : ""}
            {adjustment.delta.toFixed(1)}
          </span>
        ))}
        {candidate.lifer_species.length > 0 && (
          <span
            className="chip lifer"
            title={`potential lifers (synthetic, intentionally incomplete life list): ${candidate.lifer_species.join(", ")}`}
          >
            ★ {candidate.lifer_species.length} lifer
            {candidate.lifer_species.length > 1 ? "s" : ""}
          </span>
        )}
        {candidate.trip && (
          <span className="chip">
            {candidate.trip.minutes} min · {candidate.trip.lines.join("/")}
            {candidate.trip.approximate ? " ≈" : ""}
          </span>
        )}
      </div>
      <div className="chips evidence">
        {base.evidence_ids.slice(0, 5).map((id) => (
          <span key={id} className="chip ev" title={id}>
            {id.split(":")[0]}:{id.split(":").slice(1).join(":").slice(0, 14)}
          </span>
        ))}
      </div>
      <button className="approve" onClick={() => onApprove(candidate)}>
        Approve → calendar
      </button>
    </div>
  );
}

export default function DayPlan() {
  const [state, setState] = useState({ loading: true });
  const [confirming, setConfirming] = useState(null);
  const [written, setWritten] = useState(null);

  const load = (refresh) => {
    setState({ loading: true, refresh });
    getDay(refresh)
      .then((data) => setState({ data }))
      .catch((error) => setState({ error: String(error.message || error) }));
  };
  useEffect(() => load(false), []);

  const doApprove = async () => {
    const { candidate, window } = confirming;
    const diff = await approve({
      name: candidate.base.name,
      date: state.data.plan.date,
      window,
      reason: candidate.base.reason,
    }).catch((error) => ({ error: String(error.message || error) }));
    setConfirming(null);
    setWritten(diff);
  };

  if (state.loading)
    return (
      <p className="status">
        {state.refresh
          ? "running a live plan (weather, birds, transit, three agents)…"
          : "loading latest run…"}
      </p>
    );
  if (state.error)
    return (
      <div>
        <p className="status error">{state.error}</p>
        <button onClick={() => load(true)}>Run live now</button>
      </div>
    );

  const plan = state.data.plan;
  return (
    <div>
      <div className="bar">
        <h2>
          {plan.date} ({plan.weekday})
        </h2>
        <span className="source">
          {state.data.source === "live" ? "live run" : `latest run · ${state.data.trace}`}
        </span>
        <button onClick={() => load(true)}>Refresh (live run)</button>
      </div>
      {plan.escalated ? (
        <p className="status error">{plan.escalation_message}</p>
      ) : (
        <>
          {plan.windows.map((window) => (
            <div key={window.label} className="window">
              <h3>
                free {window.label}{" "}
                <small>({window.minutes} min)</small>
                {window.soft.length > 0 && (
                  <span className="chip soft">soft: {window.soft.join(", ")}</span>
                )}
                {(plan.gated[window.label] || []).length > 0 && (
                  <span className="chip gated">
                    weather-gated: {plan.gated[window.label].join(", ")}
                  </span>
                )}
              </h3>
              {(plan.gate_reasons[window.label] || []).map((reason) => (
                <p key={reason} className="gate-reason">
                  {reason}
                </p>
              ))}
              <div className="cards">
                {(plan.slots[window.label] || []).map((candidate) => (
                  <Card
                    key={candidate.base.candidate_id}
                    candidate={candidate}
                    date={plan.date}
                    onApprove={(c) =>
                      setConfirming({ candidate: c, window: window.label })
                    }
                  />
                ))}
              </div>
            </div>
          ))}
          <details className="selfreports">
            <summary>agent self-reports</summary>
            {Object.entries(plan.self_reports).map(([domain, text]) => (
              <p key={domain}>
                <strong>{domain}</strong>
                {plan.cold_starts[domain] ? " (cold start)" : ""}: {text}
              </p>
            ))}
          </details>
        </>
      )}
      {confirming && (
        <div className="modal-back" onClick={() => setConfirming(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>Add to calendar?</h3>
            <p>
              <strong>{confirming.candidate.base.name}</strong>
              <br />
              {plan.date} · {confirming.window}
            </p>
            <p className="fine">
              Writes a VEVENT to the local working copy
              (data/calendar.local.ics). Never happens without this
              confirmation.
            </p>
            <button className="approve" onClick={doApprove}>
              Confirm
            </button>
            <button onClick={() => setConfirming(null)}>Cancel</button>
          </div>
        </div>
      )}
      {written && (
        <div className="modal-back" onClick={() => setWritten(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>{written.error ? "Write failed" : "Written"}</h3>
            {written.error ? (
              <p className="status error">{written.error}</p>
            ) : (
              <pre>{JSON.stringify(written, null, 2)}</pre>
            )}
            <button onClick={() => setWritten(null)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
