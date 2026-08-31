"""Trajectory log: runs/<name>.jsonl, one JSON record per step.

This file is simultaneously the audit trail, the eval's only data source,
and the video's Run Trace material, which is why the record types are a
schema, not ad-hoc dicts. Every metric in eval/results.md reads ONLY these
records. Every line passes through the redactor before it touches disk.

Record types: step, llm_call, validation, prune, critic, escalation,
approval, run_summary. Forced-error runs stamp injected_failure on EVERY
line so a simulated outage can never masquerade as a real one.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src import config
from src.safety.redaction import Redactor


class TrajectoryLogger:
    def __init__(
        self,
        path: Path,
        run_id: str,
        scenario: str,
        redactor: Redactor | None = None,
        injected_failure: str | None = None,
    ):
        self.path = path
        self.run_id = run_id
        self.scenario = scenario
        self.injected_failure = injected_failure
        self._redactor = redactor or Redactor()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a")

    #, core --------------------------------------------------------------
    def write(self, record: dict[str, Any]) -> None:
        record.setdefault("type", "step")
        record["ts"] = datetime.now(config.TZ).isoformat(timespec="milliseconds")
        record["run_id"] = self.run_id
        record["scenario"] = self.scenario
        if self.injected_failure:
            record["injected_failure"] = self.injected_failure
        line = json.dumps(record, default=str, ensure_ascii=False)
        self._handle.write(self._redactor.redact(line) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    #, typed helpers -------------------------------------------------------
    def step(self, stage: str, tool: str, status: str, latency_ms: int | None = None,
             evidence_ids: list[str] | None = None, note: str = "",
             fallback_taken: bool = False, **extra: Any) -> None:
        self.write({
            "type": "step", "stage": stage, "tool": tool, "status": status,
            "latency_ms": latency_ms, "evidence_ids": (evidence_ids or [])[:12],
            "note": note, "fallback_taken": fallback_taken, **extra,
        })

    def llm(self, purpose: str, provider: str, latency_ms: int, ok: bool,
            retried: bool, error: str | None = None) -> None:
        self.write({
            "type": "llm_call", "purpose": purpose, "provider": provider,
            "latency_ms": latency_ms, "ok": ok, "retried": retried,
            "error": error,
        })

    def validation(self, validator: str, checked: int, dropped: int,
                   violations: int, details: str = "") -> None:
        self.write({
            "type": "validation", "validator": validator, "checked": checked,
            "dropped": dropped, "violations": violations, "details": details,
        })

    def escalation(self, reason: str, message: str) -> None:
        self.write({"type": "escalation", "reason": reason, "message": message})

    def approval(self, decision: str, event_uid: str = "", detail: str = "") -> None:
        self.write({"type": "approval", "decision": decision,
                    "event_uid": event_uid, "detail": detail})

    def summary(self, **fields: Any) -> None:
        self.write({"type": "run_summary", **fields})
