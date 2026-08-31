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


def _latest_record(record_type: str, want_date: str | None = None,
                   prefer_clean: bool = True) -> dict | None:
    """Newest matching record; with prefer_clean, escalated/fixture plans
    lose to real ones so the default view never opens on the escalation
    fixture."""
    fallback = None
    for path in _iter_traces():
        for line in reversed(path.read_text().splitlines()):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("type") != record_type:
                continue
            if want_date and record.get("plan", {}).get("date") != want_date:
                continue
            found = {"record": record, "trace": path.name}
            if prefer_clean and record.get("plan", {}).get("escalated"):
                fallback = fallback or found
                continue
            return found
    return fallback


def _record_from(run_id: str, record_type: str) -> dict | None:
    path = (config.RUNS_DIR / f"{run_id}.jsonl").resolve()
    if not path.is_relative_to(config.RUNS_DIR.resolve()) or not path.exists():
        return None
    for line in reversed(path.read_text().splitlines()):
        if line.strip():
            record = json.loads(line)
            if record.get("type") == record_type:
                return {"record": record, "trace": path.name}
    return None


# One live UI-triggered run at a time; the trace file is the progress feed.
_LIVE: dict = {"task": None, "trace": None, "kind": None}


def _live_busy() -> bool:
    task = _LIVE["task"]
    return task is not None and not task.done()


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
async def api_day(date_: str | None = None, refresh: bool = False,
                  run: str | None = None):
    target = date.fromisoformat(date_) if date_ else _next_saturday()
    if run:
        if not RUN_ID_RE.match(run):
            raise HTTPException(400, "bad run id")
        found = _record_from(run, "day_plan")
        if not found:
            raise HTTPException(404, "that run has no day plan")
        return {"source": "pinned", "trace": found["trace"],
                "plan": found["record"]["plan"]}
    if not refresh:
        found = _latest_record("day_plan", target.isoformat()) \
            or _latest_record("day_plan")
        if found:
            return {"source": "latest_run", "trace": found["trace"],
                    "plan": found["record"]["plan"]}
        raise HTTPException(
            404, "no completed day run yet. Press Run live, or use "
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
            404, "no completed weekly run yet. Run live builds one "
                 "(several minutes: 7 daily plans plus the beam search)")
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
        live = _live_busy() and path.stem == _LIVE["trace"]
        out.append({"id": path.stem, "scenario": scenario, "live": live,
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


class StartBody(BaseModel):
    date: str | None = None


async def _run_live(kind: str, target: date, trace_path):
    ctx = RunContext(scenario=f"ui-{kind}")
    logger = TrajectoryLogger(trace_path, ctx.run_id, f"ui-{kind}")
    ctx.log = logger.write
    try:
        await probe(ctx)
        if kind == "day":
            plan = await run_daily(ctx, get_llm(), logger, target,
                                   config.DATA_DIR / "calendar.ics",
                                   config.DATA_DIR / "life_list.csv")
            logger.write({"type": "day_plan", "plan": plan.model_dump()})
        else:
            await run_weekly(ctx, get_llm(), logger, target,
                             config.DATA_DIR / "calendar.ics",
                             config.DATA_DIR / "life_list.csv")
        logger.summary(date=target.isoformat(), provider=config.LLM_PROVIDER,
                       calls_by_source=dict(ctx.calls),
                       llm_calls=dict(ctx.llm_calls),
                       ceiling_flag=ctx.ceiling_flagged, escalated=False)
    except Exception as exc:  # surfaced in the trace, never a silent death
        logger.write({"type": "step", "stage": "live", "tool": "runner",
                      "status": "error", "note": str(exc)[:200]})
        logger.summary(date=target.isoformat(), provider=config.LLM_PROVIDER,
                       error=str(exc)[:200])
    finally:
        logger.close()
        await ctx.aclose()


async def _start_live(kind: str, body: StartBody):
    import asyncio as _asyncio
    if _live_busy():
        raise HTTPException(
            409, f"a live {_LIVE['kind']} run is already in progress "
                 f"({_LIVE['trace']}); watch it or wait")
    target = date.fromisoformat(body.date) if body.date else _next_saturday()
    stamp = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S")
    trace_path = config.RUNS_DIR / f"ui_{kind}_{stamp}.jsonl"
    _LIVE.update(task=_asyncio.create_task(_run_live(kind, target, trace_path)),
                 trace=trace_path.stem, kind=kind)
    return {"trace_id": trace_path.stem, "kind": kind,
            "date": target.isoformat()}


@app.post("/api/day/start")
async def api_day_start(body: StartBody):
    return await _start_live("day", body)


@app.post("/api/week/start")
async def api_week_start(body: StartBody):
    return await _start_live("week", body)


class AskBody(BaseModel):
    message: str


@app.post("/api/ask")
async def api_ask(body: AskBody):
    """Conversational entry: parse the request with guardrails, then start
    the same live run the buttons would. Refusals and clarifications come
    back as plain replies; nothing runs for them."""
    from src.agents.intent import parse_request

    if not body.message.strip():
        raise HTTPException(400, "say something to plan")
    ctx = RunContext(scenario="ui-ask")
    try:
        intent = await parse_request(get_llm(), ctx,
                                     body.message,
                                     datetime.now(config.TZ).date())
    finally:
        await ctx.aclose()
    if intent.kind in ("clarify", "unsupported"):
        return {"intent": intent.model_dump()}
    started = await _start_live(intent.kind if intent.kind == "day" else "week",
                                StartBody(date=intent.date))
    return {"intent": intent.model_dump(), **started}


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
                                 "confirm dialog; calendar_write never runs "
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
