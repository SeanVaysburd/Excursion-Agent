import React, { useEffect, useRef, useState } from "react";
import { approve, getRuns, getWeek, startWeek, watchRun } from "../api.js";
import { DOW, num, titleCase } from "../helpers.js";
import { Skeleton } from "./bits.jsx";
import FeedbackModal from "./FeedbackModal.jsx";
import FlowView from "./FlowView.jsx";
import { CalendarIcon, CategoryIcon, TrainIcon, WalkIcon } from "./Icons.jsx";

const EDGE = {
  nature: "var(--ok)",
  outdoor_event: "var(--warn)",
  indoor: "var(--accent)",
};

export function WeekView({ plan }) {
  const [mode, setMode] = useState("tot");
  const [confirmingWeek, setConfirmingWeek] = useState(false);
  const [approving, setApproving] = useState(false);
  const [written, setWritten] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [savedNote, setSavedNote] = useState(null);
  const winner = plan.sets?.[0];
  if (!winner) return <p className="fine">no plannable days this week</p>;

  const shown = mode === "naive" && plan.naive ? plan.naive : winner;
  const differ = new Set((plan.contrast?.differing_days || []).map((d) => d.date));
  const byDate = Object.fromEntries((shown.picks || []).map((p) => [p.date, p]));
  const allDates = [...(plan.days_planned || []), ...(plan.days_skipped || [])].sort();
  // Older traces predate the window field on weekly picks; only picks that
  // carry one can be written to the calendar.
  const writable = (winner.picks || []).filter((p) => p.window);

  const approveWeek = async () => {
    if (approving) return; // a double-click must not write the week twice
    setApproving(true);
    const result = await approve({
      events: writable.map((p) => ({
        name: titleCase(p.name), date: p.date, window: p.window,
        reason: `weekly plan pick (${p.category})`,
      })),
    }).catch((error) => ({ error: String(error.message || error) }));
    setApproving(false);
    setConfirmingWeek(false);
    setWritten(result);
  };

  const passPick = (pick) => setFeedback({
    kind: "decision", accepted: false, date: pick.date,
    type: pick.category === "nature" ? "birding" : pick.category === "indoor" ? "museum" : "outdoor_event",
    site: pick.name, agent_score: pick.final_score,
  });

  return (
    <div>
      <div className="statrow">
        <div className="mode-toggle">
          <button className={mode === "naive" ? "on" : ""} onClick={() => setMode("naive")}
            title="pick each day's highest score independently">naive</button>
          <button className={mode === "tot" ? "on" : ""} onClick={() => setMode("tot")}
            title="Tree-of-Thought beam search with the week critic">Tree-of-Thought</button>
        </div>
        <span className="big">{num(shown.adjusted ?? shown.base_sum)}</span>
        <span className="fine">
          {mode === "naive" ? `raw sum ${num(shown.base_sum)} (no critic)` :
            `base ${num(shown.base_sum)} adjusted by the critic`}
        </span>
        {mode === "tot" && Object.entries(winner.penalties || {})
          .filter(([, v]) => v > 0)
          .map(([k, v]) => (
            <span key={k} className="chip neg">{k.replace(/_/g, " ")} -{num(v)}</span>
          ))}
        <span className="chip"><TrainIcon size={12} /> {shown.transit_min} min</span>
        <span className="chip"><WalkIcon size={12} /> {num(shown.walk_miles)} mi</span>
        {writable.length > 0 && (
          <button className="btn primary" style={{ marginLeft: "auto" }}
            onClick={() => setConfirmingWeek(true)}
            title="write every pick to the local calendar copy after one confirm">
            Add week to calendar
          </button>
        )}
      </div>

      <div className="week-strip">
        {allDates.map((d) => {
          const pick = byDate[d];
          const skipped = (plan.days_skipped || []).includes(d);
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
                  <strong><CategoryIcon candidate={pick} size={13} /> {titleCase(pick.name)}</strong>
                  <div className="fine">{num(pick.final_score)} · {pick.transit_min} min transit</div>
                  {changed && <div className="swap">critic changed this day</div>}
                  <button className="pass-mini" onClick={() => passPick(pick)}
                    title="pass on this pick; your reason becomes memory">pass</button>
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

      {(plan.sets || []).slice(1).map((alternate) => (
        <details key={alternate.rank} className="alt">
          <summary>alternate #{alternate.rank} · adjusted {num(alternate.adjusted)}</summary>
          {(alternate.picks || []).map((pick) => (
            <p key={pick.date} className="fine">
              {pick.date}: {titleCase(pick.name)} [{pick.category}] {num(pick.final_score)}
            </p>
          ))}
        </details>
      ))}
      <p className="fine">
        critic calls {plan.critic_calls} (bound {plan.critic_bound}) ·
        arithmetic mismatches {plan.critic_mismatches}
      </p>
      {savedNote && (
        <div className="callout ok" onClick={() => setSavedNote(null)} role="status">
          Saved as <b>{savedNote}</b>. The agent retrieves it from the next
          run on. (click to dismiss)
        </div>
      )}

      {confirmingWeek && (
        <div className="modal-back" onClick={() => setConfirmingWeek(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Add the whole week?</h3>
            <div className="kv">
              {writable.map((p) => (
                <React.Fragment key={p.date}>
                  <span className="k">{p.date}</span>
                  <span>{titleCase(p.name)} · {p.window}</span>
                </React.Fragment>
              ))}
            </div>
            <p className="fine">
              Writes {writable.length} event(s) to the local working copy
              (data/calendar.local.ics). One confirm covers the list above;
              nothing writes without it.
            </p>
            <div className="row">
              <button className="btn quiet" disabled={approving}
                onClick={() => setConfirmingWeek(false)}>Cancel</button>
              <button className="btn primary" disabled={approving} onClick={approveWeek}>
                {approving ? "writing..." : "Confirm all"}
              </button>
            </div>
          </div>
        </div>
      )}
      {written && (
        <div className="modal-back" onClick={() => setWritten(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{written.error ? "Write failed" : `Added ${written.count} event(s)`}</h3>
            {written.error ? (
              <p className="fine">{written.error}</p>
            ) : (
              <div className="kv">
                {(written.written || []).map((diff) => (
                  <React.Fragment key={diff.uid}>
                    <span className="k">{diff.added?.start?.slice(0, 10)}</span>
                    <span>{diff.added?.summary}</span>
                  </React.Fragment>
                ))}
                <span className="k">file</span>
                <span style={{ wordBreak: "break-all" }}>{written.written_to}</span>
              </div>
            )}
            <div className="row">
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

export default function WeekPlan({ active = true }) {
  const [state, setState] = useState({ loading: true });
  const [liveRecords, setLiveRecords] = useState(null);
  const [starting, setStarting] = useState(false);
  const abortRef = useRef(null);
  const watchingRef = useRef(null); // trace id currently being watched

  const load = () => {
    setState({ loading: true });
    getWeek()
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
      const weekPlan = records.filter((r) => r.type === "weekly_plan").pop();
      setLiveRecords(null);
      if (weekPlan) setState({ data: { source: "live", trace: traceId, plan: weekPlan.plan } });
      else load();
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
      const started = await startWeek();
      setStarting(false);
      await watchLive(started.trace_id);
    } catch (error) {
      setStarting(false);
      setState((s) => ({ ...s, error: String(error.message || error) }));
    }
  };

  // When this tab is shown and a live WEEK run is in flight (started from
  // any tab), attach so its progress shows here. If nothing is live, a run
  // may have finished while hidden: silently refetch, swapping state only
  // when the trace changed.
  useEffect(() => {
    if (!active) return;
    getRuns().then((r) => {
      const live = r.find((x) => x.live && x.scenario === "ui-week");
      if (live && watchingRef.current !== live.id) watchLive(live.id);
      else if (!live && !watchingRef.current) {
        const stem = (t) => (t || "").replace(/\.jsonl$/, "");
        getWeek().then((data) => setState((s) =>
          stem(s.data?.trace) === stem(data.trace) ? s : { data })).catch(() => {});
      }
    }).catch(() => {});
  }, [active]);

  if (state.loading) return <Skeleton h={120} n={3} />;

  const liveStart = (liveRecords || []).find((r) => r.type === "run_start");
  return (
    <div>
      <div className="pagehead">
        <h2>Week plan</h2>
        {liveRecords ? (
          <span className="sub">planning the week containing {liveStart?.date || "…"} now</span>
        ) : state.data && (
          <span className="sub">week of {state.data.plan.week_start} · {state.data.trace}</span>
        )}
        <span className="spacer" />
        <button className="btn" onClick={runLive}
          disabled={starting || !!liveRecords}
          title="runs 7 daily plans plus the beam search; several minutes">
          {starting ? "starting…" : liveRecords ? "running…" : "Run live (minutes)"}
        </button>
      </div>
      {liveRecords && <FlowView records={liveRecords} live mode="week" />}
      {state.error && !liveRecords && (
        <div className={state.data ? "callout warn" : "empty"}>
          {!state.data && <div className="big-ico"><CalendarIcon size={34} /></div>}
          <p className="fine">{state.error}</p>
          {!state.data && (
            <button className="btn primary" onClick={runLive}>Run the first weekly plan</button>
          )}
        </div>
      )}
      {state.data && !liveRecords && <WeekView plan={state.data.plan} />}
    </div>
  );
}
