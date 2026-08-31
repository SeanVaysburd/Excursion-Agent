import React, { useState } from "react";
import DayPlan from "./components/DayPlan.jsx";
import RunTrace from "./components/RunTrace.jsx";
import WeekPlan from "./components/WeekPlan.jsx";

const TABS = ["Day Plan", "Week Plan", "Run Trace"];

export default function App() {
  const [tab, setTab] = useState(0);
  return (
    <div className="shell">
      <header>
        <h1>Excursion Agent</h1>
        <p className="tagline">
          plan the free hours: birding, hikes, city events, museums
        </p>
        <nav>
          {TABS.map((name, index) => (
            <button
              key={name}
              className={index === tab ? "tab active" : "tab"}
              onClick={() => setTab(index)}
            >
              {name}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === 0 && <DayPlan />}
        {tab === 1 && <WeekPlan />}
        {tab === 2 && <RunTrace />}
      </main>
      <footer>
        synthetic demo data labeled as such · trajectory logs in <code>runs/</code>
      </footer>
    </div>
  );
}
