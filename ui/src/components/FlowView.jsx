import React from "react";

// Orchestration flow derived PURELY from trace records: nodes only show
// states the records prove. Serves both live runs (records still growing)
// and finished-run inspection.

function deriveDaily(records, finished) {
  const has = (fn) => records.some(fn);
  const stageStep = (stage) => records.filter((r) => r.type === "step" && r.stage === stage);
  const state = (done, error = false, fallback = false, startedAfter = true) => {
    if (error) return "error";
    if (fallback) return "fallback";
    if (done) return "done";
    if (!finished && startedAfter) return "running";
    return "pending";
  };

  const cal = stageStep("calendar");
  const gate = stageStep("weather_gate");
  const prefetch = stageStep("prefetch");
  const agentsDone = records.filter((r) => r.type === "llm_call" && r.purpose === "agent");
  const agentFallback = has((r) => r.type === "step" && r.stage === "agents" && r.fallback_taken);
  const validations = records.filter((r) => r.type === "validation" && r.validator === "groundedness");
  const planned = has((r) => r.type === "day_plan");
  const escalated = has((r) => r.type === "escalation");

  const agentDetail = {};
  for (const v of validations) {
    const domain = (v.details || "").split(":")[0];
    if (domain) agentDetail[domain] = (v.details || "").split(",")[0].split(":").slice(1).join(":").trim();
  }

  const nodes = [
    { id: "calendar", label: "📅 calendar", state: state(cal.length > 0), detail: cal[0]?.note || "" },
    escalated
      ? { id: "escalate", label: "⛔ escalated", state: "error", detail: "no usable windows; asked instead of guessing" }
      : { id: "gate", label: "🌦 weather gate", state: state(prefetch.length > 0 || gate.length > 0, false, gate.some((g) => g.fallback_taken), cal.length > 0), detail: gate.length ? `${gate.length} gate event(s)` : "no gating" },
  ];
  if (!escalated) {
    nodes.push({ id: "prefetch", label: "🔌 data prefetch", state: state(prefetch.length > 0, false, false, cal.length > 0), detail: prefetch[0]?.latency_ms ? `${prefetch[0].latency_ms} ms` : "" });
    nodes.push({
      id: "agents",
      parallel: ["nature", "outdoor_event", "indoor"].map((domain) => ({
        id: domain,
        label: `🤖 ${domain.replace("_", " ")}`,
        state: state(validations.length >= 3 || agentsDone.length >= 3, false,
          agentFallback, prefetch.length > 0),
        detail: agentDetail[domain] || "",
      })),
    });
    nodes.push({ id: "pipeline", label: "🛡 validate + adjust", state: state(validations.length > 0, false, false, agentsDone.length > 0), detail: validations.length ? `${validations.length} validations` : "" });
    nodes.push({ id: "result", label: "🏁 top picks", state: state(planned, false, false, validations.length > 0), detail: planned ? "plan ready" : "" });
  }
  return nodes;
}

function deriveWeekly(records, finished) {
  const dayPlans = records.filter((r) => r.type === "step" && r.stage === "calendar").length;
  const critics = records.filter((r) => r.type === "critic");
  const prunes = records.filter((r) => r.type === "prune").length;
  const depth = critics.length ? Math.max(...critics.map((c) => c.depth || 0)) : 0;
  const done = records.some((r) => r.type === "weekly_plan");
  const nodes = [
    { id: "days", label: "📅 daily plans", state: dayPlans >= 7 ? "done" : finished ? "done" : "running", detail: `${Math.min(dayPlans, 7)} of 7 days` },
    { id: "beam", label: "🌳 beam search", state: done ? "done" : critics.length ? "running" : "pending", detail: critics.length ? `depth ${depth}, ${critics.length} critic calls, ${prunes} pruned` : "waiting" },
    { id: "winner", label: "🏆 weekly sets", state: done ? "done" : "pending", detail: done ? "top 3 ready" : "" },
  ];
  return nodes;
}

function Node({ node, onClick }) {
  return (
    <div className={`fnode ${node.state}`} onClick={() => onClick && onClick(node.id)}
         title={node.detail}>
      <span className="fl"><span className={`dot s-${node.state}`} />{node.label}</span>
      {node.detail && <div className="fd">{node.detail}</div>}
    </div>
  );
}

export default function FlowView({ records, live = false, onSelect }) {
  const finished = records.some((r) => r.type === "run_summary");
  const weekly = records.some((r) => r.type === "critic" || r.type === "weekly_plan")
    || records.filter((r) => r.type === "step" && r.stage === "calendar").length > 1;
  const nodes = weekly ? deriveWeekly(records, finished) : deriveDaily(records, finished);
  const doneCount = nodes.flatMap((n) => n.parallel || [n]).filter((n) => n.state === "done").length;
  const total = nodes.flatMap((n) => n.parallel || [n]).length;

  return (
    <div className="flow-card">
      {live && !finished && (
        <div className="flow-live">
          <span>live run in progress</span>
          <span className="progressbar"><i style={{ width: `${(doneCount / total) * 100}%` }} /></span>
        </div>
      )}
      <h3>{weekly ? "weekly orchestration" : "daily orchestration"}</h3>
      <div className="flow">
        {nodes.map((node, i) => (
          <React.Fragment key={node.id}>
            {i > 0 && <span className="fjoin" />}
            {node.parallel ? (
              <div className="fstack">
                {node.parallel.map((child) => (
                  <Node key={child.id} node={child} onClick={onSelect} />
                ))}
              </div>
            ) : (
              <Node node={node} onClick={onSelect} />
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
