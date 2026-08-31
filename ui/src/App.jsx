import React, { useEffect, useState } from "react";
import { getRuns } from "./api.js";
import { relTime, themeInit, themeSet } from "./helpers.js";
import { getProvider, setProvider } from "./provider.js";
import AskTab from "./components/AskTab.jsx";
import DayPlan from "./components/DayPlan.jsx";
import { MapIcon, MoonIcon, SunIcon } from "./components/Icons.jsx";
import RunTrace from "./components/RunTrace.jsx";
import WeekPlan from "./components/WeekPlan.jsx";

const TABS = ["Ask", "Day plan", "Week plan", "Runs"];
const TAB_SLUGS = ["ask", "day", "week", "runs"];

function initialTab() {
  // ?tab=day etc. deep-links straight to a tab (handy for demos).
  try {
    const slug = new URLSearchParams(location.search).get("tab");
    const index = TAB_SLUGS.indexOf(slug || "");
    return index === -1 ? 0 : index;
  } catch {
    return 0;
  }
}

export default function App() {
  const [tab, setTab] = useState(initialTab);
  const [theme, setTheme] = useState(themeInit);
  const [provider, setProviderState] = useState(getProvider);
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
            <div className="brand-mark"><MapIcon size={18} /></div>
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
            <select className="runpick" value={provider}
              onChange={(e) => { setProviderState(e.target.value); setProvider(e.target.value); }}
              title="which model runs the next live runs; every trace records the one that actually ran">
              <option value="">model: default</option>
              <option value="claude-sdk">model: Claude</option>
              <option value="ollama">model: local</option>
            </select>
            <button className="theme-btn" onClick={flip}
              aria-label={theme === "dark" ? "switch to light mode" : "switch to dark mode"}
              title={theme === "dark" ? "switch to light" : "switch to dark"}>
              {theme === "dark" ? <SunIcon size={16} /> : <MoonIcon size={16} />}
            </button>
          </div>
        </div>
      </header>
      <main>
        {/* Tabs stay MOUNTED and are only hidden: an in-progress run (and
            the Ask conversation) must survive switching tabs. Each tab
            gets `active` so it can refresh or attach when shown. */}
        <div className={tab === 0 ? "" : "tab-hidden"}><AskTab active={tab === 0} /></div>
        <div className={tab === 1 ? "" : "tab-hidden"}><DayPlan active={tab === 1} /></div>
        <div className={tab === 2 ? "" : "tab-hidden"}><WeekPlan active={tab === 2} /></div>
        <div className={tab === 3 ? "" : "tab-hidden"}><RunTrace active={tab === 3} /></div>
      </main>
      <footer className="statusbar">
        <div className="statusbar-inner">
          <span>run logs in <b>runs/</b></span>
          {status?.latest && (
            <span>latest run: <b>{status.latest.scenario}</b> {relTime(status.latest.mtime)}</span>
          )}
          <span style={{ marginLeft: "auto" }}>local only · 127.0.0.1</span>
        </div>
      </footer>
    </div>
  );
}
