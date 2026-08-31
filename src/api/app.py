"""FastAPI backend: a localhost window onto the agent.

Serving model: /api/day and /api/week return the LATEST COMPLETED run from
runs/ by default (instant; the UI must never hang while filming), and
launch a fresh live run when ?refresh=true (a weekly refresh takes minutes
-- the UI shows a loading state and says so).

Run:  uvicorn src.api.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402
from src.safety import redaction  # noqa: E402

redaction.install()

from src.agents.llm import get_llm, probe  # noqa: E402
from src.orchestration.tot_beam import run_weekly  # noqa: E402
from src.orchestration.waterfall import run_daily  # noqa: E402
from src.safety.trajectory import TrajectoryLogger  # noqa: E402
from src.tools import calendar_write  # noqa: E402
from src.tools.base import RunContext  # noqa: E402

app = FastAPI(title="Excursion Agent", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.UI_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


# --------------------------------------------------------------------------
# Trace reading
# --------------------------------------------------------------------------
def _iter_traces() -> list[Path]:
    return sorted(config.RUNS_DIR.glob("*.jsonl"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _latest_record(record_type: str, want_date: str | None = None) -> dict | None:
    for path in _iter_traces():
        for line in reversed(path.read_text().splitlines()):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("type") != record_type:
                continue
            if want_date and record.get("plan", {}).get("date") != want_date:
                continue
            return {"record": record, "trace": path.name}
    return None


def _next_saturday() -> date:
    today = datetime.now(config.TZ).date()
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


async def _live_context(tag: str) -> tuple[RunContext, TrajectoryLogger]:
    ctx = RunContext(scenario=tag)
    stamp = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S")
    logger = TrajectoryLogger(config.RUNS_DIR / f"ui_{tag}_{stamp}.jsonl",
                              ctx.run_id, tag)
    ctx.log = logger.write
    await probe(ctx)
    return ctx, logger


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/day")
async def api_day(date_: str | None = None, refresh: bool = False):
    target = date.fromisoformat(date_) if date_ else _next_saturday()
    if not refresh:
        found = _latest_record("day_plan", target.isoformat()) \
            or _latest_record("day_plan")
        if found:
            return {"source": "latest_run", "trace": found["trace"],
                    "plan": found["record"]["plan"]}
        raise HTTPException(
            404, "no completed day run yet -- press Refresh (live run) or "
                 "`python demo.py`")
    ctx, logger = await _live_context("day")
    try:
        plan = await run_daily(ctx, get_llm(), logger, target,
                               config.DATA_DIR / "calendar.ics",
                               config.DATA_DIR / "life_list.csv")
        logger.write({"type": "day_plan", "plan": plan.model_dump()})
        return {"source": "live", "trace": logger.path.name,
                "plan": plan.model_dump()}
    finally:
        logger.close()
        await ctx.aclose()


@app.get("/api/week")
async def api_week(date_: str | None = None, refresh: bool = False):
    target = date.fromisoformat(date_) if date_ else _next_saturday()
    if not refresh:
        found = _latest_record("weekly_plan")
        if found:
            return {"source": "latest_run", "trace": found["trace"],
                    "plan": found["record"]["plan"]}
        raise HTTPException(
            404, "no completed weekly run yet -- Refresh runs live "
                 "(several minutes: 7 daily plans + the beam search)")
    ctx, logger = await _live_context("week")
    try:
        plan, _days = await run_weekly(ctx, get_llm(), logger, target,
                                       config.DATA_DIR / "calendar.ics",
                                       config.DATA_DIR / "life_list.csv")
        return {"source": "live", "trace": logger.path.name,
                "plan": plan.model_dump()}
    finally:
        logger.close()
        await ctx.aclose()


@app.get("/api/runs")
async def api_runs():
    out = []
    for path in _iter_traces()[:50]:
        first = path.read_text().split("\n", 1)[0]
        scenario = json.loads(first).get("scenario", "?") if first.strip() else "?"
        out.append({"id": path.stem, "scenario": scenario,
                    "mtime": datetime.fromtimestamp(
                        path.stat().st_mtime, config.TZ).isoformat(timespec="seconds"),
                    "records": sum(1 for _ in path.open())})
    return out


@app.get("/api/runs/{run_id}")
async def api_run(run_id: str):
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(400, "bad run id")
    path = (config.RUNS_DIR / f"{run_id}.jsonl").resolve()
    if not path.is_relative_to(config.RUNS_DIR.resolve()) or not path.exists():
        raise HTTPException(404, "no such run")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class ApproveBody(BaseModel):
    name: str
    date: str
    window: str  # "HH:MM-HH:MM"
    reason: str = ""
    confirmed: bool = False


@app.post("/api/approve")
async def api_approve(body: ApproveBody):
    if not body.confirmed:
        raise HTTPException(400, "approval requires confirmed=true from the "
                                 "confirm dialog -- calendar_write never runs "
                                 "autonomously")
    day = date.fromisoformat(body.date)
    start_s, end_s = body.window.split("-")
    start = datetime.combine(day, datetime.strptime(start_s, "%H:%M").time(),
                             tzinfo=config.TZ)
    end = datetime.combine(day, datetime.strptime(end_s, "%H:%M").time(),
                           tzinfo=config.TZ)
    diff = calendar_write.append_event(
        config.DATA_DIR / "calendar.ics",
        f"Excursion: {body.name}", start, end, description=body.reason)
    stamp = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S")
    logger = TrajectoryLogger(config.RUNS_DIR / f"ui_approval_{stamp}.jsonl",
                              f"ui{stamp}", "ui-approval")
    logger.approval("approved", event_uid=diff["uid"], detail=body.name)
    logger.close()
    return diff
