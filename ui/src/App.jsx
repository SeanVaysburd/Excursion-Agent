import React, { useEffect, useState } from "react";
import { getRuns } from "./api.js";
import { relTime, themeInit, themeSet } from "./helpers.js";
import AskTab from "./components/AskTab.jsx";
import DayPlan from "./components/DayPlan.jsx";
import RunTrace from "./components/RunTrace.jsx";
import WeekPlan from "./components/WeekPlan.jsx";

const TABS = ["Ask", "Day plan", "Week plan", "Runs"];

export default function App() {
  const [tab, setTab] = useState(0);
  const [theme, setTheme] = useState(themeInit);
  const [status, setStatus] = useState(null);

  useEffect(() => {
    getRuns().then((runs) => {
      if (!runs.length) return;
      setStatus({ latest: runs[0] });
    }).catch(() => {});
  }, [tab]);

  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    themeSet(next);
  };

  return (
    <div className="shell">
      <header className="chrome">
        <div className="chrome-inner">
          <div className="brand">
            <div className="brand-mark">🗺️</div>
            <div>
              <h1>Excursion Agent</h1>
              <small>plan the free hours</small>
            </div>
          </div>
          <nav className="tabs">
            {TABS.map((name, index) => (
              <button key={name}
                className={index === tab ? "tab active" : "tab"}
                onClick={() => setTab(index)}>
                {name}
              </button>
            ))}
          </nav>
          <div className="chrome-right">
            <button className="theme-btn" onClick={flip}
              title={theme === "dark" ? "switch to light" : "switch to dark"}>
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
          </div>
        </div>
      </header>
      <main>
        {tab === 0 && <AskTab />}
        {tab === 1 && <DayPlan />}
        {tab === 2 && <WeekPlan />}
        {tab === 3 && <RunTrace />}
      </main>
      <footer className="statusbar">
        <div className="statusbar-inner">
          <span>synthetic demo data, labeled as such</span>
          <span>audit logs in <b>runs/</b></span>
          {status?.latest && (
            <span>latest run: <b>{status.latest.scenario}</b> {relTime(status.latest.mtime)}</span>
          )}
          <span style={{ marginLeft: "auto" }}>local only · 127.0.0.1</span>
        </div>
      </footer>
    </div>
  );
}
