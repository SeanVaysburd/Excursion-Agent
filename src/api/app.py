"""FastAPI backend: a localhost window onto the agent.

Serving model: /api/day and /api/week return the latest completed run from
runs/ instantly, so the UI never hangs. Live runs start through the
/start endpoints on a server-side task and stream their progress through
the growing trace file, which the UI polls.

Run:  uvicorn src.api.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402
from src.safety import redaction  # noqa: E402

redaction.install()

from src.agents.llm import get_llm, probe  # noqa: E402
from src.orchestration.tot_beam import run_weekly  # noqa: E402
from src.orchestration.waterfall import (  # noqa: E402
    invalidate_memory,
    run_daily,
    season_of,
)
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
    paths = []
    for path in config.RUNS_DIR.glob("*.jsonl"):
        try:
            paths.append((path.stat().st_mtime, path))
        except FileNotFoundError:
            continue  # removed between glob and stat
    return [path for _, path in sorted(paths, reverse=True)]


def _records_of(path: Path) -> list[dict]:
    """Parse a trace, skipping a torn final line if the run is mid-write."""
    records = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _latest_record(record_type: str, want_date: str | None = None,
                   prefer_clean: bool = True) -> dict | None:
    """Newest matching record; with prefer_clean, escalated and
    simulated-failure fixture plans lose to real ones so the default view
    never opens on a test fixture."""
    fallback = None
    for path in _iter_traces():
        for record in reversed(_records_of(path)):
            if record.get("type") != record_type:
                continue
            if want_date and record.get("plan", {}).get("date") != want_date:
                continue
            found = {"record": record, "trace": path.name}
            if prefer_clean and (record.get("plan", {}).get("escalated")
                                 or record.get("injected_failure")):
                fallback = fallback or found
                continue
            return found
    return fallback


def _record_from(run_id: str, record_type: str) -> dict | None:
    path = (config.RUNS_DIR / f"{run_id}.jsonl").resolve()
    if not path.is_relative_to(config.RUNS_DIR.resolve()) or not path.exists():
        return None
    for record in reversed(_records_of(path)):
        if record.get("type") == record_type:
            return {"record": record, "trace": path.name}
    return None


def _next_saturday() -> date:
    today = datetime.now(config.TZ).date()
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7)


# --------------------------------------------------------------------------
# Live runs: one at a time; the trace file is the progress feed
# --------------------------------------------------------------------------
_LIVE: dict[str, Any] = {"task": None, "trace": None, "kind": None}
# The busy-check, the provider probe (a real LLM call that yields the
# loop for seconds) and the task creation must be one atomic step, or two
# quick requests both pass the check and start overlapping runs.
_START_LOCK = asyncio.Lock()


def _live_busy() -> bool:
    task = _LIVE["task"]
    return task is not None and not task.done()


async def _run_live(kind: str, target: date, trace_path: Path,
                    provider: str | None = None) -> None:
    """The background body of a live run. Every failure lands in the trace
    (and a run_summary always closes it, so UI polling always terminates)."""
    ctx = RunContext(scenario=f"ui-{kind}")
    logger: TrajectoryLogger | None = None
    error: str | None = None
    adapter = get_llm(provider)
    try:
        logger = TrajectoryLogger(trace_path, ctx.run_id, f"ui-{kind}")
        ctx.log = logger.write
        # First record carries the target so a tab attaching mid-run can
        # say WHAT is being planned instead of headlining stale data.
        logger.write({"type": "run_start", "kind": kind,
                      "date": target.isoformat()})
        await probe(ctx, provider)
        escalated = False
        if kind == "day":
            plan = await run_daily(ctx, adapter, logger, target,
                                   config.DATA_DIR / "calendar.ics",
                                   config.DATA_DIR / "life_list.csv")
            escalated = plan.escalated
            logger.write({"type": "day_plan", "plan": plan.model_dump()})
        else:
            week_plan, _ = await run_weekly(ctx, adapter, logger, target,
                                            config.DATA_DIR / "calendar.ics",
                                            config.DATA_DIR / "life_list.csv")
            escalated = not week_plan.sets
    except Exception as exc:  # noqa: BLE001 - surfaced in the trace
        error = str(exc)[:200]
        escalated = False
        if logger is not None:
            logger.write({"type": "step", "stage": "live", "tool": "runner",
                          "status": "error", "note": error})
    finally:
        if logger is not None:
            summary: dict[str, Any] = {
                "date": target.isoformat(), "provider": adapter.provider,
                "calls_by_source": dict(ctx.calls),
                "llm_calls": dict(ctx.llm_calls),
                "ceiling_flag": ctx.ceiling_flagged, "escalated": escalated,
            }
            if error:
                summary["error"] = error
            logger.summary(**summary)
            logger.close()
        await ctx.aclose()


class StartBody(BaseModel):
    date: str | None = None
    provider: str | None = None  # "claude-sdk" | "ollama"; None = .env default


async def _start_live(kind: str, body: StartBody) -> dict:
    try:
        target = date.fromisoformat(body.date) if body.date else _next_saturday()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD") from None
    async with _START_LOCK:
        if _live_busy():
            raise HTTPException(
                409, f"a live {_LIVE['kind']} run is already in progress "
                     f"({_LIVE['trace']}); watch it or wait")
        # Validate the provider choice and probe it BEFORE starting the
        # task, so "Ollama isn't running" comes back as an immediate clear
        # error instead of a failed background run. Under the lock, so a
        # second click during the probe waits and then gets the 409.
        ctx = RunContext(scenario="ui-probe")
        try:
            await probe(ctx, body.provider)
        except Exception as exc:  # noqa: BLE001 - config errors -> client
            raise HTTPException(400, str(exc)[:300]) from exc
        finally:
            await ctx.aclose()
        stamp = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S")
        suffix = uuid.uuid4().hex[:6]  # two starts in one second stay distinct
        trace_path = config.RUNS_DIR / f"ui_{kind}_{stamp}_{suffix}.jsonl"
        task = asyncio.create_task(_run_live(kind, target, trace_path,
                                             body.provider))
        # Retrieve the exception so a failed task never dies unobserved;
        # the trace already carries the details for the UI.
        task.add_done_callback(lambda t: t.exception())
        _LIVE.update(task=task, trace=trace_path.stem, kind=kind)
    return {"trace_id": trace_path.stem, "kind": kind,
            "date": target.isoformat(),
            "provider": get_llm(body.provider).provider}


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/day")
async def api_day(date_: str | None = Query(None, alias="date"),
                  refresh: bool = False,
                  run: str | None = None) -> dict:
    try:
        target = date.fromisoformat(date_) if date_ else None
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD") from None
    if run:
        if not RUN_ID_RE.match(run):
            raise HTTPException(400, "bad run id")
        found = _record_from(run, "day_plan")
        if not found:
            raise HTTPException(404, "that run has no day plan")
        return {"source": "pinned", "trace": found["trace"],
                "plan": found["record"]["plan"]}
    # No explicit date means "whatever was planned most recently": the tab
    # must follow an Ask run for any date, not stick to next Saturday.
    found = (_latest_record("day_plan", target.isoformat())
             or _latest_record("day_plan")) if target \
        else _latest_record("day_plan")
    if not found and not refresh:
        raise HTTPException(
            404, "no completed day run yet. Press Run live, or use "
                 "`python demo.py`")
    if found and not refresh:
        return {"source": "latest_run", "trace": found["trace"],
                "plan": found["record"]["plan"]}
    # Blocking refresh kept for curl users; the UI uses /api/day/start.
    trace_path = config.RUNS_DIR / (
        "ui_day_" + datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S") + ".jsonl")
    await _run_live("day", target or _next_saturday(), trace_path)
    found = _record_from(trace_path.stem, "day_plan")
    if not found:
        raise HTTPException(502, "live run produced no plan; see its trace")
    return {"source": "live", "trace": found["trace"],
            "plan": found["record"]["plan"]}


@app.get("/api/week")
async def api_week(date_: str | None = None) -> dict:
    found = _latest_record("weekly_plan")
    if found:
        return {"source": "latest_run", "trace": found["trace"],
                "plan": found["record"]["plan"]}
    raise HTTPException(
        404, "no completed weekly run yet. Run live builds one "
             "(several minutes: 7 daily plans plus the beam search)")


@app.post("/api/day/start")
async def api_day_start(body: StartBody) -> dict:
    return await _start_live("day", body)


@app.post("/api/week/start")
async def api_week_start(body: StartBody) -> dict:
    return await _start_live("week", body)


class AskBody(BaseModel):
    message: str
    provider: str | None = None


@app.post("/api/ask")
async def api_ask(body: AskBody) -> dict:
    """Conversational entry: parse the request with guardrails, then start
    the same live run the buttons would. Clarifications and refusals come
    back as plain replies; nothing runs for them."""
    from src.agents.intent import parse_request

    if not body.message.strip():
        raise HTTPException(400, "say something to plan")
    ctx = RunContext(scenario="ui-ask")
    try:
        intent = await parse_request(get_llm(body.provider), ctx, body.message,
                                     datetime.now(config.TZ).date())
    except Exception as exc:  # noqa: BLE001 - provider config -> client
        raise HTTPException(400, str(exc)[:300]) from exc
    finally:
        await ctx.aclose()
    if intent.kind in ("clarify", "unsupported"):
        return {"intent": intent.model_dump()}
    started = await _start_live(intent.kind if intent.kind == "day" else "week",
                                StartBody(date=intent.date, provider=body.provider))
    return {"intent": intent.model_dump(), **started}


@app.get("/api/runs")
async def api_runs() -> list[dict]:
    out = []
    for path in _iter_traces()[:50]:
        try:
            text = path.read_text()
        except FileNotFoundError:
            continue
        first_line = text.split("\n", 1)[0]
        try:
            scenario = json.loads(first_line).get("scenario", "?")
        except json.JSONDecodeError:
            scenario = "?"
        live = _live_busy() and path.stem == _LIVE["trace"]
        out.append({
            "id": path.stem, "scenario": scenario, "live": live,
            "mtime": datetime.fromtimestamp(
                path.stat().st_mtime, config.TZ).isoformat(timespec="seconds"),
            "records": sum(1 for line in text.splitlines() if line.strip()),
            # Flags the UI uses to keep test fixtures out of the demo
            # surface (they stay listed, labeled, for the guardrail story).
            "has_day_plan": '"type": "day_plan"' in text,
            "has_week_plan": '"type": "weekly_plan"' in text,
            "simulated": '"injected_failure": "' in text,
            "escalated": '"type": "escalation"' in text,
            "approval": '"type": "approval"' in text and '"type": "step"' not in text,
        })
    return out


@app.get("/api/runs/{run_id}")
async def api_run(run_id: str) -> list[dict]:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(400, "bad run id")
    path = (config.RUNS_DIR / f"{run_id}.jsonl").resolve()
    if not path.is_relative_to(config.RUNS_DIR.resolve()) or not path.exists():
        raise HTTPException(404, "no such run")
    return _records_of(path)


class ApproveEvent(BaseModel):
    name: str
    date: str
    window: str  # "HH:MM-HH:MM"
    reason: str = ""


class ApproveBody(BaseModel):
    # Single-event form (kept for existing callers)...
    name: str | None = None
    date: str | None = None
    window: str | None = None
    reason: str = ""
    # ...or the batch form: the whole week after ONE confirm dialog.
    events: list[ApproveEvent] | None = None
    confirmed: bool = False


def _write_approved(event: ApproveEvent) -> dict:
    try:
        day = date.fromisoformat(event.date)
        start_s, end_s = event.window.split("-")
        start = datetime.combine(day, datetime.strptime(start_s, "%H:%M").time(),
                                 tzinfo=config.TZ)
        end = datetime.combine(day, datetime.strptime(end_s, "%H:%M").time(),
                               tzinfo=config.TZ)
    except ValueError:
        raise HTTPException(
            400, "bad event date or window (want YYYY-MM-DD and HH:MM-HH:MM)",
        ) from None
    return calendar_write.append_event(
        config.DATA_DIR / "calendar.ics",
        f"Excursion: {event.name}", start, end, description=event.reason)


@app.post("/api/approve")
async def api_approve(body: ApproveBody) -> dict:
    if not body.confirmed:
        raise HTTPException(400, "approval requires confirmed=true from the "
                                 "confirm dialog; calendar_write never runs "
                                 "autonomously")
    if body.events:
        events = body.events
    elif body.name and body.date and body.window:
        events = [ApproveEvent(name=body.name, date=body.date,
                               window=body.window, reason=body.reason)]
    else:
        raise HTTPException(400, "provide name/date/window or an events list")
    try:
        diffs = [_write_approved(event) for event in events]
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"bad event fields: {exc}") from exc
    stamp = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S")
    logger = TrajectoryLogger(config.RUNS_DIR / f"ui_approval_{stamp}.jsonl",
                              f"ui{stamp}", "ui-approval")
    try:
        for event, diff in zip(events, diffs):
            logger.approval("approved", event_uid=diff["uid"], detail=event.name)
    finally:
        logger.close()
    return {"written": diffs, "count": len(diffs),
            "written_to": diffs[0]["written_to"]}


# --------------------------------------------------------------------------
# Feedback: the second explicitly-gated write path (feeds retrieval)
# --------------------------------------------------------------------------
_FEEDBACK_LOCK = asyncio.Lock()


class FeedbackBody(BaseModel):
    kind: Literal["outing", "decision"] = "outing"
    date: str
    type: str
    site: str
    notes: str = ""
    rating: int | None = None       # outings: 1-10, required
    accepted: bool | None = None    # decisions: required
    agent_score: float | None = None
    conditions: str = ""
    confirmed: bool = False


@app.post("/api/feedback")
async def api_feedback(body: FeedbackBody) -> dict:
    """Append one feedback entry to data/excursions.json. Outings are
    post-trip ratings; decisions are accept/pass calls on a suggestion.
    Both become retrievable memory on the next run in THIS process (the
    corpus-hash rebuild re-embeds through the same chroma client)."""
    if not body.confirmed:
        raise HTTPException(400, "feedback requires confirmed=true from the "
                                 "save control; nothing writes without an "
                                 "explicit confirm")
    try:
        day = date.fromisoformat(body.date)
    except ValueError as exc:
        raise HTTPException(400, "bad date") from exc
    notes = body.notes.strip()[:600]
    if not body.site.strip():
        raise HTTPException(400, "name the site or venue; retrieval keys on it")
    if body.kind == "outing":
        if body.rating is None or not 1 <= body.rating <= 10:
            raise HTTPException(400, "an outing entry needs a rating from 1 to 10")
        if not notes:
            raise HTTPException(400, "a few words on how it went are what "
                                     "retrieval matches on; notes are required")
    else:
        if body.accepted is None:
            raise HTTPException(400, "a decision entry needs accepted true or false")
        if not notes:
            notes = ("took this suggestion" if body.accepted
                     else "passed on this suggestion")

    entry: dict[str, Any] = {
        "id": "",  # assigned under the lock
        "date": day.isoformat(),
        "season": season_of(day),
        "type": (body.type.strip()[:40] or "other"),
        "site": body.site.strip()[:80],
        "notes": notes,
        "kind": body.kind,
        "source": "user",
    }
    if body.kind == "outing":
        entry["rating"] = body.rating
    else:
        entry["accepted"] = body.accepted
    if body.agent_score is not None:
        entry["agent_score"] = round(body.agent_score, 1)
    if body.conditions.strip():
        entry["conditions"] = body.conditions.strip()[:200]

    path = config.DATA_DIR / "excursions.json"
    async with _FEEDBACK_LOCK:
        entries = json.loads(path.read_text())
        next_num = 1 + max(
            (int(e["id"][1:]) for e in entries
             if re.fullmatch(r"e\d+", str(e.get("id", "")))), default=0)
        entry["id"] = f"e{next_num:02d}"
        entries.append(entry)
        tmp = path.with_suffix(".json.tmp")
        try:
            # One entry per line, matching the file's committed style.
            body_text = ",\n".join(
                " " + json.dumps(e, ensure_ascii=False) for e in entries)
            tmp.write_text("[\n" + body_text + "\n]\n")
            os.replace(tmp, path)  # atomic
        finally:
            tmp.unlink(missing_ok=True)
    invalidate_memory()

    stamp = datetime.now(config.TZ).strftime("%Y%m%dT%H%M%S")
    logger = TrajectoryLogger(config.RUNS_DIR / f"ui_feedback_{stamp}.jsonl",
                              f"ui{stamp}", "ui-feedback")
    try:
        logger.write({"type": "feedback", "entry_id": entry["id"],
                      "kind": body.kind, "site": entry["site"],
                      "confirmed": True})
    finally:
        logger.close()
    return {"id": entry["id"], "kind": body.kind, "count": len(entries)}
