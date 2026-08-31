import React, { useState } from "react";
import { approve } from "../api.js";
import { hmToFrac, iconFor, titleCase } from "../helpers.js";
import { Confidence, ScoreRing, ScoreWaterfall } from "./bits.jsx";

function DayTimeline({ plan }) {
  const windows = plan.windows || [];
  const topPick = Object.entries(plan.slots || {})[0]?.[1]?.[0];
  const segs = [];
  let cursor = 0;
  for (const w of windows) {
    const [a, b] = w.label.split("-");
    const l = hmToFrac(a), r = hmToFrac(b);
    if (l > cursor) segs.push({ kind: "busy", l: cursor, r: l });
    segs.push({ kind: w.soft?.length ? "soft" : "free", l, r, label: w.label, soft: w.soft });
    cursor = r;
  }
  if (cursor < 1) segs.push({ kind: "busy", l: cursor, r: 1 });
  return (
    <div className="timeline-card">
      <h3>your day at a glance</h3>
      <div className="timeline">
        <div className="rail" />
        {segs.map((s, i) => (
          <div key={i}
            className={`tl-seg ${s.kind}`}
            style={{ left: `${s.l * 100}%`, width: `${(s.r - s.l) * 100}%` }}
            title={s.kind === "busy" ? "calendar block" :
              s.soft?.length ? `free, but soft: ${s.soft.join(", ")}` : `free ${s.label}`} />
        ))}
        {topPick && (() => {
          const [a, b] = topPick.base.window.split("-");
          const l = hmToFrac(a), r = hmToFrac(b);
          return (
            <div className="tl-seg pick"
              style={{ left: `${l * 100}%`, width: `${(r - l) * 100}%` }}
              title={`top pick: ${topPick.base.name}`}>
              {iconFor(topPick)} {titleCase(topPick.base.name)}
            </div>
          );
        })()}
        {[6, 9, 12, 15, 18, 21].map((h) => (
          <span key={h} className="tl-hour" style={{ left: `${hmToFrac(`${h}:00`) * 100}%` }}>
            {h}:00
          </span>
        ))}
      </div>
    </div>
  );
}

function HeroStats({ plan, summary }) {
  const candidates = plan.scored_summary || [];
  const pruned = candidates.filter((c) => c.pruned).length;
  const gated = Object.keys(plan.gated || {}).length;
  const calls = summary ? Object.values(summary.calls_by_source || {}).reduce((a, b) => a + b, 0) : null;
  return (
    <div className="stats">
      <div className="stat"><div className="k">considered</div>
        <div className="v">{candidates.length} <small>candidates</small></div></div>
      <div className="stat"><div className="k">pruned</div>
        <div className="v">{pruned} <small>by transit or alerts</small></div></div>
      <div className="stat"><div className="k">weather gate</div>
        <div className="v">{gated ? `${gated} window(s)` : "clear"} </div></div>
      <div className="stat"><div className="k">lifers nearby</div>
        <div className="v">{(plan.lifers || []).length} <small>species</small></div></div>
      {calls != null && (
        <div className="stat"><div className="k">api calls</div>
          <div className="v">{calls} <small>{summary.provider}</small></div></div>
      )}
    </div>
  );
}

function Card({ candidate, rank, onApprove }) {
  const base = candidate.base;
  return (
    <div className="card">
      <span className="rank">{rank}</span>
      <div className="card-top">
        <div className="cat-tile">{iconFor(candidate)}</div>
        <div className="card-title">
          <strong title={base.name}>{titleCase(base.name)}</strong>
          <div className="fine">{base.window} · {candidate.domain.replace("_", " ")}</div>
        </div>
        <ScoreRing score={candidate.final_score} model={base.score} />
      </div>
      <p className="reason">{base.reason}</p>
      {candidate.transit_note && (
        <div className="transit-note">⚠️ <span>{candidate.transit_note}</span></div>
      )}
      <div className="chips">
        <Confidence level={candidate.confidence} />
        {candidate.lifer_species.length > 0 && (
          <span className="chip lifer"
            title={`potential lifers (synthetic, intentionally incomplete life list): ${candidate.lifer_species.join(", ")}`}>
            ★ {candidate.lifer_species.length} lifers
          </span>
        )}
        {candidate.trip && (
          <span className="chip">
            🚇 {candidate.trip.minutes} min · {candidate.trip.lines.join("/")}
            {candidate.trip.approximate ? " ≈" : ""}
          </span>
        )}
        {base.evidence_ids.slice(0, 3).map((id) => (
          <span key={id} className="chip ev" title={id}>{id.split(":")[0]}</span>
        ))}
        {base.evidence_ids.length > 3 && (
          <span className="chip">+{base.evidence_ids.length - 3} more</span>
        )}
      </div>
      <details className="why">
        <summary>why this score</summary>
        <ScoreWaterfall base={base.score} adjustments={candidate.adjustments}
          final={candidate.final_score} />
      </details>
      {onApprove && (
        <button className="btn primary" onClick={() => onApprove(candidate)}>
          Add to calendar
        </button>
      )}
    </div>
  );
}

export default function PlanView({ plan, summary, allowApprove = true }) {
  const [confirming, setConfirming] = useState(null);
  const [written, setWritten] = useState(null);

  if (plan.escalated) {
    return (
      <div className="callout warn">
        <b>The agent stopped and asked instead of guessing:</b>
        <br />{plan.escalation_message}
      </div>
    );
  }

  const doApprove = async () => {
    const { candidate } = confirming;
    const result = await approve({
      name: titleCase(candidate.base.name), date: plan.date,
      window: candidate.base.window, reason: candidate.base.reason,
    }).catch((error) => ({ error: String(error.message || error) }));
    setConfirming(null);
    setWritten(result);
  };

  return (
    <div>
      <HeroStats plan={plan} summary={summary} />
      <DayTimeline plan={plan} />
      {(plan.windows || []).map((w) => (
        <div key={w.label}>
          <div className="window-head">
            <h3>free {w.label}</h3>
            <span className="fine">{w.minutes} min</span>
            {w.soft.map((s) => (
              <span key={s} className="chip neg" title="tentative or optional calendar block overlaps; a score penalty applies">
                soft: {s}
              </span>
            ))}
            {(plan.gated[w.label] || []).length > 0 && (
              <span className="chip bad">
                weather gated: {plan.gated[w.label].join(", ")}
              </span>
            )}
          </div>
          {(plan.gate_reasons[w.label] || []).slice(0, 2).map((reason) => (
            <p key={reason} className="gate-reason">{reason}</p>
          ))}
          <div className="cards">
            {(plan.slots[w.label] || []).map((candidate, i) => (
              <Card key={candidate.base.candidate_id} candidate={candidate}
                rank={i + 1}
                onApprove={allowApprove ? (c) => setConfirming({ candidate: c }) : null} />
            ))}
            {!(plan.slots[w.label] || []).length && (
              <p className="fine">no candidates cleared the gates for this window</p>
            )}
          </div>
        </div>
      ))}
      <details className="selfreports">
        <summary>agent self-reports</summary>
        {Object.entries(plan.self_reports || {}).map(([domain, text]) => (
          <p key={domain}>
            <b>{domain}</b>{plan.cold_starts?.[domain] ? " (cold start)" : ""}: {text}
          </p>
        ))}
      </details>

      {confirming && (
        <div className="modal-back" onClick={() => setConfirming(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Add to calendar?</h3>
            <div className="kv">
              <span className="k">excursion</span><span>{titleCase(confirming.candidate.base.name)}</span>
              <span className="k">when</span><span>{plan.date} · {confirming.candidate.base.window}</span>
            </div>
            <p className="fine">
              Writes one event to the local working copy
              (data/calendar.local.ics). Never happens without this confirm.
            </p>
            <div className="row">
              <button className="btn quiet" onClick={() => setConfirming(null)}>Cancel</button>
              <button className="btn primary" onClick={doApprove}>Confirm</button>
            </div>
          </div>
        </div>
      )}
      {written && (
        <div className="modal-back" onClick={() => setWritten(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{written.error ? "Write failed" : "Added to calendar"}</h3>
            {written.error ? (
              <p className="fine">{written.error}</p>
            ) : (
              <div className="kv">
                <span className="k">event</span><span>{written.added?.summary}</span>
                <span className="k">starts</span><span>{written.added?.start}</span>
                <span className="k">ends</span><span>{written.added?.end}</span>
                <span className="k">file</span><span style={{ wordBreak: "break-all" }}>{written.written_to}</span>
              </div>
            )}
            <div className="row">
              <button className="btn" onClick={() => setWritten(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
