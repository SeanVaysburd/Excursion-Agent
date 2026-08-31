import React from "react";

export function ScoreRing({ score, model }) {
  const r = 23;
  const c = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, score / 10));
  return (
    <div className="ring" title={`final score ${score.toFixed(1)} of 10 (model gave ${model})`}>
      <svg width="54" height="54">
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#4f5df0" />
            <stop offset="100%" stopColor="#7c5cf0" />
          </linearGradient>
        </defs>
        <circle className="ring-bg" cx="27" cy="27" r={r} fill="none" strokeWidth="5" />
        <circle
          className="ring-fg" cx="27" cy="27" r={r} fill="none" strokeWidth="5"
          strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
        />
      </svg>
      <span className="ring-num">{score.toFixed(1)}</span>
    </div>
  );
}

export function Confidence({ level }) {
  return (
    <span className={`conf ${level}`}>
      <span className="dot" />
      {level}
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

export function ScoreWaterfall({ base, adjustments, final: finalScore }) {
  const max = 10;
  const rows = [
    { lbl: "model score", delta: base, kind: "base" },
    ...adjustments
      .filter((a) => a.delta !== 0)
      .map((a) => ({ lbl: a.label.replace(/_/g, " "), delta: a.delta, kind: a.delta > 0 ? "plus" : "minus", note: a.note })),
  ];
  let cursor = 0;
  return (
    <div className="wf">
      {rows.map((row, i) => {
        const start = row.kind === "base" ? 0 : Math.min(cursor, cursor + row.delta);
        const width = Math.abs(row.kind === "base" ? row.delta : row.delta);
        const left = (Math.max(0, start) / max) * 100;
        const w = (width / max) * 100;
        cursor = row.kind === "base" ? row.delta : cursor + row.delta;
        return (
          <div className="wf-row" key={i} title={row.note || ""}>
            <span className="lbl">{row.lbl}</span>
            <span className="wf-bar"><i className={row.kind} style={{ left: `${left}%`, width: `${Math.max(w, 1.5)}%` }} /></span>
            <span className="num">{row.kind === "base" ? row.delta : (row.delta > 0 ? "+" : "") + row.delta.toFixed(1)}</span>
          </div>
        );
      })}
      <div className="wf-row total">
        <span className="lbl">final</span>
        <span className="wf-bar"><i className="base" style={{ left: 0, width: `${(finalScore / max) * 100}%` }} /></span>
        <span className="num">{finalScore.toFixed(1)}</span>
      </div>
    </div>
  );
}
