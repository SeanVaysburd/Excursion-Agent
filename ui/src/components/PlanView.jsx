import React, { useState } from "react";
import { approve } from "../api.js";
import { guessType, hmToFrac, num, titleCase } from "../helpers.js";
import { Confidence, ScoreRing, ScoreWaterfall } from "./bits.jsx";
import FeedbackModal from "./FeedbackModal.jsx";
import { AlertIcon, CategoryIcon, StarIcon, TrainIcon } from "./Icons.jsx";

function DayTimeline({ plan }) {
  const windows = plan.windows || [];
  const topPick = Object.entries(plan.slots || {})[0]?.[1]?.[0];
  const segs = [];
  let cursor = 0;
  for (const w of windows) {
    const [a, b] = (w.label || "").split("-");
    const left = hmToFrac(a), right = hmToFrac(b);
    if (left > cursor) segs.push({ kind: "busy", l: cursor, r: left });
    segs.push({ kind: (w.soft || []).length ? "soft" : "free", l: left, r: right, label: w.label, soft: w.soft });
    cursor = right;
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
              (s.soft || []).length ? `free, but soft: ${s.soft.join(", ")}` : `free ${s.label}`} />
        ))}
        {topPick && (() => {
          const [a, b] = (topPick.base?.window || "").split("-");
          const left = hmToFrac(a), right = hmToFrac(b);
          return (
            <div className="tl-seg pick"
              style={{ left: `${left * 100}%`, width: `${(right - left) * 100}%` }}
              title={`top pick: ${topPick.base?.name}`}>
              <CategoryIcon candidate={topPick} size={13} /> {titleCase(topPick.base?.name)}
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

function Card({ candidate, rank, onApprove, onPass, onLog }) {
  const base = candidate.base || {};
  const evidence = base.evidence_ids || [];
  const lifers = candidate.lifer_species || [];
  return (
    <div className="card">
      <span className="rank">{rank}</span>
      <div className="card-top">
        <div className="cat-tile"><CategoryIcon candidate={candidate} size={17} /></div>
        <div className="card-title">
          <strong title={base.name}>{titleCase(base.name)}</strong>
          <div className="fine">{base.window} · {(candidate.domain || "").replace("_", " ")}</div>
        </div>
        <ScoreRing score={candidate.final_score} model={base.score} />
      </div>
      <p className="reason">{base.reason}</p>
      {candidate.transit_note && (
        <div className="transit-note"><AlertIcon size={14} /> <span>{candidate.transit_note}</span></div>
      )}
      <div className="chips">
        <Confidence level={candidate.confidence} />
        {lifers.length > 0 && (
          <span className="chip lifer"
            title={`potential lifers (from the sample life list): ${lifers.join(", ")}`}>
            <StarIcon size={12} /> {lifers.length} lifers
          </span>
        )}
        {candidate.trip && (
          <span className="chip">
            <TrainIcon size={12} /> {candidate.trip.minutes} min · {(candidate.trip.lines || []).join("/")}
            {candidate.trip.approximate ? " (approx)" : ""}
          </span>
        )}
        {evidence.slice(0, 3).map((id) => (
          <span key={id} className="chip ev" title={id}>{id.split(":")[0]}</span>
        ))}
        {evidence.length > 3 && (
          <span className="chip">+{evidence.length - 3} more</span>
        )}
      </div>
      <details className="why">
        <summary>why this score</summary>
        <ScoreWaterfall base={base.score} adjustments={candidate.adjustments || []}
          final={candidate.final_score} />
      </details>
      <div className="card-actions">
        {onApprove && (
          <button className="btn primary" onClick={() => onApprove(candidate)}>
            Add to calendar
          </button>
        )}
        <button className="btn quiet" onClick={() => onPass(candidate)}
          title="pass on this suggestion; your reason becomes memory">
          Pass
        </button>
        <button className="btn quiet" onClick={() => onLog(candidate)}
          title="already did this? rate it so the agent learns">
          Log this trip
        </button>
      </div>
    </div>
  );
}

export default function PlanView({ plan, summary, allowApprove = true }) {
  const [confirming, setConfirming] = useState(null);
  const [written, setWritten] = useState(null);
  const [feedback, setFeedback] = useState(null); // FeedbackModal initial
  const [savedNote, setSavedNote] = useState(null);

  if (plan.escalated) {
    return (
      <div className="callout warn">
        <b>The agent stopped and asked instead of guessing:</b>
        <br />{plan.escalation_message}
      </div>
    );
  }

  const feedbackInit = (candidate, extra) => ({
    date: plan.date,
    type: guessType(candidate),
    site: candidate.base?.site || candidate.base?.name || "",
    agent_score: candidate.final_score,
    ...extra,
  });

  const doApprove = async () => {
    const { candidate } = confirming;
    const result = await approve({
      name: titleCase(candidate.base.name), date: plan.date,
      window: candidate.base.window, reason: candidate.base.reason,
    }).catch((error) => ({ error: String(error.message || error) }));
    setConfirming(null);
    setWritten({ ...result, candidate });
  };

  return (
    <div>
      {(plan.degraded_sources || []).length > 0 && (
        <div className="callout warn">
          <b>Some data sources were down for this run:</b>{" "}
          {plan.degraded_sources.join(", ")}. Affected picks carry low
          confidence and say so; re-run later for full data.
        </div>
      )}
      <HeroStats plan={plan} summary={summary} />
      <DayTimeline plan={plan} />
      {(plan.windows || []).map((w) => (
        <div key={w.label}>
          <div className="window-head">
            <h3>free {w.label}</h3>
            <span className="fine">{w.minutes} min</span>
            {(w.soft || []).map((s) => (
              <span key={s} className="chip neg" title="tentative or optional calendar block overlaps; a score penalty applies">
                soft: {s}
              </span>
            ))}
            {((plan.gated || {})[w.label] || []).length > 0 && (
              <span className="chip bad">
                weather gated: {plan.gated[w.label].join(", ")}
              </span>
            )}
          </div>
          {((plan.gate_reasons || {})[w.label] || []).slice(0, 2).map((reason) => (
            <p key={reason} className="gate-reason">{reason}</p>
          ))}
          <div className="cards">
            {((plan.slots || {})[w.label] || []).map((candidate, i) => (
              <Card key={candidate.base?.candidate_id || i} candidate={candidate}
                rank={i + 1}
                onApprove={allowApprove ? (c) => setConfirming({ candidate: c }) : null}
                onPass={(c) => setFeedback(feedbackInit(c, { kind: "decision", accepted: false }))}
                onLog={(c) => setFeedback(feedbackInit(c, { kind: "outing" }))} />
            ))}
            {!((plan.slots || {})[w.label] || []).length && (
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
      {savedNote && (
        <div className="callout ok" onClick={() => setSavedNote(null)} role="status">
          Saved as <b>{savedNote}</b>. The agent retrieves it from the next
          run on. (click to dismiss)
        </div>
      )}

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
                <span className="k">event</span><span>{written.written?.[0]?.added?.summary || written.added?.summary}</span>
                <span className="k">starts</span><span>{written.written?.[0]?.added?.start || written.added?.start}</span>
                <span className="k">file</span><span style={{ wordBreak: "break-all" }}>{written.written_to}</span>
              </div>
            )}
            <div className="row">
              {!written.error && written.candidate && (
                <button className="btn quiet" onClick={() => {
                  const c = written.candidate;
                  setWritten(null);
                  setFeedback(feedbackInit(c, { kind: "decision", accepted: true }));
                }}>
                  Add a quick note (optional)
                </button>
              )}
              <button className="btn" onClick={() => setWritten(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {feedback && (
        <FeedbackModal initial={feedback}
          onClose={() => setFeedback(null)}
          onSaved={(result) => setSavedNote(result.id)} />
      )}
    </div>
  );
}
