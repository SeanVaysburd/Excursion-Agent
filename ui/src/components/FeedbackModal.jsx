import React, { useState } from "react";
import { sendFeedback } from "../api.js";
import { FEEDBACK_TYPES } from "../helpers.js";
import { StarIcon } from "./Icons.jsx";

// One modal for the two feedback kinds the memory learns from:
//   outing   - "I did this, here is how it went" (rating 1-10 + notes)
//   decision - "I'm passing on this suggestion" (reason only)
// Saving is the explicit confirm; the backend refuses anything else.

export default function FeedbackModal({ initial, onClose, onSaved }) {
  const kind = initial.kind || "outing";
  const [form, setForm] = useState({
    date: initial.date || new Date().toISOString().slice(0, 10),
    type: initial.type || "birding",
    site: initial.site || "",
    rating: initial.rating ?? 7,
    notes: initial.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await sendFeedback({
        kind,
        date: form.date,
        type: form.type,
        site: form.site,
        notes: form.notes,
        rating: kind === "outing" ? Number(form.rating) : undefined,
        accepted: kind === "decision" ? Boolean(initial.accepted) : undefined,
        agent_score: initial.agent_score,
      });
      onSaved?.(result);
      onClose();
    } catch (err) {
      setError(String(err.message || err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>
          {kind === "decision"
            ? (initial.accepted ? "Why did you take it?" : "Pass on this one?")
            : "Log how it went"}
        </h3>
        {kind === "outing" && (
          <>
            <div className="form-grid">
              <label>
                <span>date</span>
                <input type="date" value={form.date} onChange={set("date")} />
              </label>
              <label>
                <span>type</span>
                <select value={form.type} onChange={set("type")}>
                  {FEEDBACK_TYPES.map((t) => (
                    <option key={t} value={t}>{t.replace("_", " ")}</option>
                  ))}
                </select>
              </label>
            </div>
            <label className="form-row">
              <span>where</span>
              <input value={form.site} onChange={set("site")}
                placeholder="site or venue name" />
            </label>
            <label className="form-row">
              <span className="rating-label">
                rating <b className="rating-val"><StarIcon size={13} /> {form.rating}</b>
              </span>
              <input type="range" min="1" max="10" step="1"
                value={form.rating} onChange={set("rating")} />
            </label>
          </>
        )}
        <label className="form-row">
          <span>{kind === "decision" ? "why (optional, it teaches the agent)" : "how did it go?"}</span>
          <textarea rows={3} value={form.notes} onChange={set("notes")}
            placeholder={kind === "decision"
              ? "e.g. too much transit for a weekday"
              : "a sentence or two; this is what future retrieval matches on"} />
        </label>
        <p className="fine">
          Saves one entry to data/excursions.json and the agent retrieves it
          from the next run on. Nothing writes without this save.
        </p>
        {error && <div className="callout warn">{error}</div>}
        <div className="row">
          <button className="btn quiet" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" onClick={save} disabled={busy}>
            {busy ? "saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
