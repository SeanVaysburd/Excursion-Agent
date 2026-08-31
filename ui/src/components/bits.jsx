import React, { useId } from "react";
import { num } from "../helpers.js";

export function ScoreRing({ score = 0, model }) {
  const gradId = useId(); // unique per instance; a shared id breaks under many cards
  const r = 23;
  const c = 2 * Math.PI * r;
  const safe = Number.isFinite(Number(score)) ? Number(score) : 0;
  const frac = Math.max(0, Math.min(1, safe / 10));
  return (
    <div className="ring"
      title={`final score ${num(safe)} of 10 (model gave ${model ?? "?"})`}>
      <svg width="54" height="54">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--accent)" />
            <stop offset="100%" stopColor="var(--accent-2)" />
          </linearGradient>
        </defs>
        <circle className="ring-bg" cx="27" cy="27" r={r} fill="none" strokeWidth="5" />
        <circle
          className="ring-fg" cx="27" cy="27" r={r} fill="none" strokeWidth="5"
          stroke={`url(#${gradId})`}
          strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
        />
      </svg>
      <span className="ring-num">{num(safe)}</span>
    </div>
  );
}

export function Confidence({ level }) {
  return (
    <span className={`conf ${level || "low"}`}>
      <span className="dot" />
      {level || "unknown"}
    </span>
  );
}

export function Skeleton({ h = 90, n = 3 }) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: h }} />
      ))}
    </div>
  );
}

export function ScoreWaterfall({ base = 0, adjustments = [], final: finalScore = 0 }) {
  const max = 10;
  const rows = [
    { lbl: "model score", delta: Number(base) || 0, kind: "base" },
    ...(adjustments || [])
      .filter((a) => a && a.delta !== 0)
      .map((a) => ({
        lbl: String(a.label || "adjustment").replace(/_/g, " "),
        delta: Number(a.delta) || 0,
        kind: (Number(a.delta) || 0) > 0 ? "plus" : "minus",
        note: a.note,
      })),
  ];
  let cursor = 0;
  return (
    <div className="wf">
      {rows.map((row, i) => {
        const start = row.kind === "base" ? 0 : Math.min(cursor, cursor + row.delta);
        const width = Math.abs(row.delta);
        const left = (Math.max(0, start) / max) * 100;
        const w = (width / max) * 100;
        cursor = row.kind === "base" ? row.delta : cursor + row.delta;
        return (
          <div className="wf-row" key={i} title={row.note || ""}>
            <span className="lbl">{row.lbl}</span>
            <span className="wf-bar"><i className={row.kind} style={{ left: `${left}%`, width: `${Math.max(w, 1.5)}%` }} /></span>
            <span className="num">{row.kind === "base" ? row.delta : (row.delta > 0 ? "+" : "") + num(row.delta)}</span>
          </div>
        );
      })}
      <div className="wf-row total">
        <span className="lbl">final</span>
        <span className="wf-bar"><i className="base" style={{ left: 0, width: `${(Math.max(0, Number(finalScore) || 0) / max) * 100}%` }} /></span>
        <span className="num">{num(finalScore)}</span>
      </div>
    </div>
  );
}
