"""Daily waterfall: plain async Python, cheapest-first (Checkpoint-1
design answer): calendar (free) -> weather gate (one cheap call) -> three
domain agents in parallel (the expensive step, run only on what survived)
-> transit adjustment inside the post-processing pipeline.

Every stage is trajectory-logged with latency. Zero usable windows is an
ESCALATION: the run stops with a clarification message instead of
guessing. Data-level fallbacks (widened radius, seasonal defaults) and
LLM-level fallbacks (unpersonalized template candidates) both surface as
confidence=low with the reason stated -- never invented data.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from src import config
from src.agents import lifer as lifer_mod
from src.agents.domain_agents import EvidencePack, run_agent
from src.agents.llm import LLMAdapter
from src.agents.pipeline import process_report, top_per_window
from src.agents.schemas import AgentReport, CandidateScore, ScoredCandidate
from src.memory.retrieval import ExcursionMemory, PlanningContext
from src.safety.trajectory import TrajectoryLogger
from src.safety.validators import validate_hard_constraints
from src.tools import (
    calendar_tool,
    ebird,
    inaturalist,
    mta_alerts,
    nyc_events,
    tides,
    weather,
)
from src.tools.base import RunContext

OUTDOOR_CATEGORIES = {"birding", "hike", "outdoor_event"}


# --------------------------------------------------------------------------
# Static catalogs + memory singleton
# --------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


_MEMORY: ExcursionMemory | None = None


def get_memory() -> ExcursionMemory:
    """Process-level singleton: build() loads the embedding model and owns
    llama-index's global Settings, so it must happen exactly once."""
    global _MEMORY
    if _MEMORY is None:
        _MEMORY = ExcursionMemory.build()
    return _MEMORY


def season_of(day: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "fall",
            10: "fall", 11: "fall"}[day.month]


def time_of_day(start: datetime) -> str:
    if start.hour < 12:
        return "morning"
    if start.hour < 17:
        return "afternoon"
    return "evening"


# --------------------------------------------------------------------------
# Output model
# --------------------------------------------------------------------------
class DayPlan(BaseModel):
    date: str
    weekday: str
    escalated: bool = False
    escalation_message: str = ""
    windows: list[dict] = Field(default_factory=list)
    gated: dict[str, list[str]] = Field(default_factory=dict)
    gate_reasons: dict[str, list[str]] = Field(default_factory=dict)
    slots: dict[str, list[ScoredCandidate]] = Field(default_factory=dict)
    scored_summary: list[dict] = Field(default_factory=list)  # ALL scored
    cold_candidates: list[str] = Field(default_factory=list)
    self_reports: dict[str, str] = Field(default_factory=dict)
    cold_starts: dict[str, bool] = Field(default_factory=dict)
    groundedness: dict[str, dict] = Field(default_factory=dict)
    lifers: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class _Timer:
    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.monotonic() - self.t0) * 1000)


# --------------------------------------------------------------------------
# Memory querying
# --------------------------------------------------------------------------
async def _memory_lines(
    ctx: RunContext,
    season: str,
    activity: str,
    site_name: str,
    when: str,
    weekday: str,
    window: str,
) -> list[str]:
    memory = get_memory()
    planning_ctx = PlanningContext(
        label=f"{season}/{activity}/{site_name}",
        season=season,
        activity_type=activity,
        site=site_name,
        time_of_day=when,
        day_of_week=weekday,
        window=window,
    )
    result = await asyncio.to_thread(memory.retrieve, planning_ctx)
    lines: list[str] = []
    for candidate in result.kept:
        md = candidate.metadata
        evidence_id = ctx.registry.register(
            f"memory:{md['entry_id']}",
            {"site": md["site"], "rating": md["rating"], "notes": candidate.get_content()},
        )
        lines.append(
            f"{evidence_id} | {md['site']} ({md['season']}, rated {md['rating']}/10, "
            f"similarity {candidate.similarity:.2f}): {candidate.get_content()}"
        )
    return lines


# --------------------------------------------------------------------------
# The waterfall
# --------------------------------------------------------------------------
async def run_daily(
    ctx: RunContext,
    adapter: LLMAdapter,
    logger: TrajectoryLogger,
    day: date,
    calendar_path: Path,
    life_list_path: Path,
    extra_sites: list[dict] | None = None,
) -> DayPlan:
    weekday = day.strftime("%A")
    plan = DayPlan(date=day.isoformat(), weekday=weekday)

    sites = _load_json(config.DATA_DIR / "sites.json")["sites"] + (extra_sites or [])
    venues = _load_json(config.DATA_DIR / "venues.json")["venues"]

    # ---- stage 1: calendar (free) ---------------------------------------
    with _Timer() as t:
        windows = calendar_tool.free_windows(ctx, calendar_path, day)
    logger.step("calendar", "calendar_tool", "ok", t.ms,
                note=f"{len(windows)} free window(s)")
    if not windows:
        message = (
            f"No usable free windows on {day.isoformat()} ({weekday}) after "
            f"hard calendar blocks. I won't guess -- free up a slot or pick "
            f"another day (demo.py --date)."
        )
        logger.escalation("zero_free_windows", message)
        plan.escalated = True
        plan.escalation_message = message
        return plan

    window_minutes = {w.label: w.minutes for w in windows}
    window_starts = {w.label: w.start for w in windows}
    soft_windows = {w.label for w in windows if w.soft_conflicts}
    plan.windows = [
        {"label": w.label, "minutes": w.minutes,
         "soft": [b.summary for b in w.soft_conflicts]}
        for w in windows
    ]

    # ---- stage 2: weather gate (one cheap call) --------------------------
    with _Timer() as t:
        wx = await weather.fetch_forecast(ctx, config.HOME_LAT, config.HOME_LON)
    wx_hours = wx.data if wx.status == "ok" else []
    gated: dict[str, set[str]] = {}
    for w in windows:
        hours = weather.slice_hours(wx_hours, day, w.start.hour, w.end.hour)
        is_gated, reasons, evidence = weather.gate_outdoor(hours)
        if is_gated:
            gated[w.label] = set(OUTDOOR_CATEGORIES)
            plan.gate_reasons[w.label] = reasons
            logger.step("weather_gate", "open-meteo", "ok", t.ms,
                        evidence_ids=evidence,
                        note=f"window {w.label} gated: {'; '.join(reasons[:2])}")
    plan.gated = {k: sorted(v) for k, v in gated.items()}
    if wx.status != "ok":
        logger.step("weather_gate", "open-meteo", wx.status, t.ms,
                    note=f"forecast unavailable ({wx.note}); no gate applied",
                    fallback_taken=True)
        plan.notes.append("weather unavailable -- outdoor candidates carry low confidence")

    # ---- stage 3: prefetch + evidence packs + parallel agents ------------
    season = season_of(day)
    with _Timer() as t:
        events_r, mta_r = await asyncio.gather(
            nyc_events.fetch_events(ctx, day), mta_alerts.fetch_alerts(ctx)
        )
        regions: dict[str, dict] = {}
        for site in sites:
            # Bird feeds are only fetched for regions that actually contain
            # birding candidates -- a hike-only region gets no eBird/iNat
            # calls (call-budget discipline, not a coverage loss).
            if site["category"] in ("birding", "kayaking"):
                regions.setdefault(site["region_id"], site)
        bird_results: dict[str, dict] = {}
        taxonomy = await ebird.species_codes(ctx)
        for region_id, anchor in regions.items():
            recent, notable, inat = await asyncio.gather(
                ebird.fetch_recent(ctx, anchor["lat"], anchor["lng"]),
                ebird.fetch_notable(ctx, anchor["lat"], anchor["lng"]),
                inaturalist.fetch_recent(ctx, anchor["lat"], anchor["lng"], region_id),
            )
            if inat.status == "empty":
                logger.step("prefetch", "inaturalist", "empty", None,
                            note=f"{region_id}: widening radius once", fallback_taken=True)
            bird_results[region_id] = {"recent": recent, "notable": notable, "inat": inat}
        coastal_station = next(
            (s.get("tide_station", config.TIDE_STATION_DEFAULT)
             for s in sites if s.get("coastal")), None)
        tides_r = await tides.fetch_tides(ctx, day, coastal_station) if coastal_station else None
    logger.step("prefetch", "sources", "ok", t.ms,
                note=f"calls so far: {dict(ctx.calls)}")

    mta_by_route = mta_r.data if mta_r.status == "ok" else {}

    # window assignment heuristics
    def first_ok_window(category: str) -> str | None:
        for w in windows:
            if category not in gated.get(w.label, set()):
                return w.label
        return None

    windows_meta = [
        {"label": w.label, "minutes": w.minutes, "soft": bool(w.soft_conflicts)}
        for w in windows
    ]
    wx_lines: list[str] = []
    for w in windows:
        for h in weather.slice_hours(wx_hours, day, w.start.hour, w.end.hour):
            wx_lines.append(
                f"{h.evidence_id} | {h.dt:%H:%M} {h.temp_f:.0f}F, rain {h.precip_prob}%"
                f", wind {h.wind_mph:.0f} mph"
            )
    sources_common = [
        {"source": "open-meteo", "status": wx.status, "note": wx.note},
        {"source": "mta", "status": mta_r.status, "note": mta_r.note},
    ]

    # ---------- nature pack ----------
    nature_candidates, nature_lines, dest_meta = [], [], {}
    life_list = lifer_mod.load_life_list(life_list_path)
    all_lifers: list[dict] = []
    lifer_evidence: list[str] = []
    for site in sites:
        window = first_ok_window(site["category"])
        if window is None:
            continue
        cid = f"site@{site['id']}"
        evidence_id = ctx.registry.register(f"site:{site['id']}", site)
        nature_lines.append(
            f"{evidence_id} | {site['name']} -- {site['category']}, "
            f"{'coastal, ' if site.get('coastal') else ''}typical walk {site['walk_miles']} mi"
        )
        nature_candidates.append(
            {"candidate_id": cid, "name": site["name"], "site": site["name"], "window": window}
        )
        dest_meta[cid] = {"dest_id": site["id"], "borough": site.get("borough"),
                          "category": site["category"]}
    for region_id, feeds in bird_results.items():
        recent_obs = feeds["recent"].data or []
        notable_obs = feeds["notable"].data or []
        seen_species: set[str] = set()
        for obs in notable_obs[:8]:
            nature_lines.append(
                f"{obs['evidence_id']} | NOTABLE {obs['common_name']} at "
                f"{obs['location'][:40]} ({obs['observed']})"
            )
        for obs in recent_obs:
            if obs["species_code"] in seen_species or len(seen_species) >= 10:
                continue
            seen_species.add(obs["species_code"])
            nature_lines.append(
                f"{obs['evidence_id']} | {obs['common_name']} x{obs.get('how_many') or '?'} "
                f"at {obs['location'][:40]} ({obs['observed']})"
            )
        region_lifers = lifer_mod.potential_lifers(
            recent_obs + notable_obs, life_list, taxonomy
        )
        for entry in region_lifers:
            if entry not in all_lifers:
                all_lifers.append(entry)
        lifer_evidence.extend(
            o["evidence_id"] for o in recent_obs + notable_obs
            if o.get("species_code") in {l["code"] for l in region_lifers}
        )
        for obs in (feeds["inat"].data or [])[:5]:
            nature_lines.append(
                f"{obs['evidence_id']} | iNat: {obs['common_name']} ({obs['observed_on']})"
            )
    if tides_r and tides_r.status == "ok":
        for tide in tides_r.data:
            nature_lines.append(
                f"{tide['evidence_id']} | {tide['type']} tide {tide['dt']:%H:%M} "
                f"({tide['height_ft']:.1f} ft)"
            )
    plan.lifers = all_lifers

    nature_memory: list[str] = []
    cold_candidate_ids: set[str] = set()
    for site in sites:
        window = first_ok_window(site["category"])
        if window is None:
            continue
        site_lines = await _memory_lines(
            ctx, season, site["category"], site["name"],
            time_of_day(window_starts[window]), weekday, window)
        nature_memory.extend(site_lines)
        if not site_lines:
            # Cold start is a per-CONTEXT fact, not a per-domain one: one
            # unlogged activity inside a well-logged domain must still get
            # the low-confidence override (spec: reason states the cold
            # start; code enforces).
            cold_candidate_ids.add(f"site@{site['id']}")
    nature_sources = sources_common + [
        {"source": "ebird",
         "status": bird_results[r]["recent"].status,
         "note": bird_results[r]["recent"].note} for r in list(regions)[:1]
    ] + [
        {"source": "inaturalist",
         "status": bird_results[r]["inat"].status,
         "note": bird_results[r]["inat"].note} for r in list(regions)[:1]
    ] + ([{"source": "noaa-tides", "status": tides_r.status, "note": tides_r.note}]
         if tides_r else [])

    # ---------- outdoor events pack ----------
    event_candidates, event_lines = [], []
    if events_r.status == "ok":
        for event in events_r.data[:10]:
            window = None
            for w in windows:
                if ("outdoor_event" not in gated.get(w.label, set())
                        and event["start"] < w.end and event["end"] > w.start):
                    window = w.label
                    break
            if window is None:
                continue
            cid = f"event@{event['id']}"
            event_lines.append(
                f"{event['evidence_id']} | {event['name']} ({event['type']}), "
                f"{event['borough']}, {event['start']:%H:%M}-{event['end']:%H:%M}, "
                f"{event['location'][:50]}"
            )
            event_candidates.append(
                {"candidate_id": cid, "name": event["name"],
                 "site": event["location"][:60] or event["borough"], "window": window}
            )
            dest_meta[cid] = {"dest_id": cid, "borough": event["borough"],
                              "category": "outdoor_event"}
    event_memory = await _memory_lines(
        ctx, season, "outdoor_event", "New York City permitted events",
        time_of_day(windows[0].start), weekday, windows[0].label)

    # ---------- indoor pack ----------
    indoor_candidates, indoor_lines = [], []
    for venue in venues:
        hours = venue["hours"]
        if weekday in hours.get("closed_days", []):
            continue
        open_t = datetime.combine(day, datetime.strptime(hours["open"], "%H:%M").time(),
                                  tzinfo=config.TZ)
        close_t = datetime.combine(day, datetime.strptime(hours["close"], "%H:%M").time(),
                                   tzinfo=config.TZ)
        window = None
        for w in windows:
            overlap = (min(w.end, close_t) - max(w.start, open_t)).total_seconds() / 60
            if overlap >= config.MIN_WINDOW_MINUTES:
                window = w.label
                break
        if window is None:
            continue
        cid = f"venue@{venue['id']}"
        evidence_id = ctx.registry.register(f"venue:{venue['id']}", venue)
        indoor_lines.append(
            f"{evidence_id} | {venue['name']}, open {hours['open']}-{hours['close']} "
            f"({'closed ' + '/'.join(hours['closed_days']) if hours['closed_days'] else 'daily'}), "
            f"{'/'.join(venue['lines'])} at {venue['nearest_stop']}"
        )
        indoor_candidates.append(
            {"candidate_id": cid, "name": venue["name"], "site": venue["name"],
             "window": window}
        )
        dest_meta[cid] = {"dest_id": venue["id"], "borough": venue.get("borough"),
                          "category": "museum"}
    indoor_memory: list[str] = []
    for venue in venues[:8]:
        indoor_memory.extend(
            await _memory_lines(ctx, season, "museum", venue["name"],
                                time_of_day(windows[0].start), weekday, windows[0].label)
        )

    def build_pack(domain: str, candidates: list[dict], lines: list[str],
                   memory_lines: list[str], sources: list[dict]) -> EvidencePack:
        memory_block = "\n".join(f"  {line}" for line in dict.fromkeys(memory_lines))
        cold = not memory_lines
        if cold:
            memory_block = (
                "  none -- no relevant history above the similarity cutoff "
                "(cold start: plan from live evidence, confidence=low, say so)"
            )
        evidence = list(dict.fromkeys((wx_lines if domain != "indoor" else wx_lines[:4]) + lines))
        allowed = [line.split(" | ")[0] for line in evidence] + [
            line.split(" | ")[0].strip() for line in memory_lines
        ]
        return EvidencePack(
            domain=domain, date=day.isoformat(), weekday=weekday,
            windows=windows_meta, sources=sources, evidence_lines=evidence,
            allowed_ids=list(dict.fromkeys(a.strip() for a in allowed)),
            memory_block=memory_block, candidates=candidates, cold_start=cold,
        )

    packs = {
        "nature": build_pack("nature", nature_candidates, nature_lines,
                             nature_memory, nature_sources),
        "outdoor_event": build_pack(
            "outdoor_event", event_candidates, event_lines, event_memory,
            sources_common + [{"source": "nyc-events", "status": events_r.status,
                               "note": events_r.note}]),
        "indoor": build_pack("indoor", indoor_candidates, indoor_lines,
                             indoor_memory, sources_common),
    }

    with _Timer() as t:
        agent_results = await asyncio.gather(
            *(run_agent(adapter, ctx, pack) for pack in packs.values()),
            return_exceptions=True,
        )
    logger.step("agents", "domain_agents", "ok", t.ms,
                note=f"3 agents (parallel), provider={adapter.provider}")

    # ---- stage 4: pipeline (incl. transit) per agent ---------------------
    all_scored: list[ScoredCandidate] = []
    for (domain, pack), outcome in zip(packs.items(), agent_results):
        if isinstance(outcome, BaseException):
            report, error_note = None, f"{type(outcome).__name__}: {outcome}"
        else:
            report, llm_result = outcome
            error_note = llm_result.error or ""
            logger.llm("agent", adapter.provider, 0, report is not None,
                       llm_result.retried, llm_result.error)
        if report is None:
            report = _fallback_report(domain, pack, error_note)
            logger.step("agents", f"{domain}_agent", "error", None,
                        note=f"LLM fallback: {error_note[:120]}", fallback_taken=True)
        plan.self_reports[domain] = report.self_report
        plan.cold_starts[domain] = pack.cold_start

        scored, stats, finding = process_report(
            domain=domain, report=report, registry_ids=ctx.registry.ids,
            cold_start=pack.cold_start, lifers=all_lifers if domain == "nature" else [],
            lifer_evidence=lifer_evidence, soft_windows=soft_windows,
            window_minutes=window_minutes, window_starts=window_starts,
            dest_meta=dest_meta, mta_by_route=mta_by_route,
            cold_candidate_ids=cold_candidate_ids if domain == "nature" else set(),
        )
        logger.validation("groundedness", stats.ids_emitted,
                          stats.candidates_dropped, stats.ids_stripped,
                          details=f"{domain}: rate={stats.rate:.2%}, "
                                  f"self_report={finding}")
        plan.groundedness[domain] = {
            "ids_emitted": stats.ids_emitted, "ids_valid": stats.ids_valid,
            "rate": stats.rate, "dropped": stats.candidates_dropped,
        }
        for candidate in scored:
            if candidate.pruned:
                logger.write({"type": "prune", "candidate": candidate.candidate_id,
                              "reason": candidate.prune_reason})
        all_scored.extend(scored)

    plan.slots = top_per_window(all_scored)
    plan.cold_candidates = sorted(cold_candidate_ids)
    plan.scored_summary = [
        {
            "candidate_id": c.candidate_id, "name": c.base.name,
            "domain": c.domain, "window": c.base.window,
            "final_score": round(c.final_score, 1), "confidence": c.confidence,
            "pruned": c.pruned, "prune_reason": c.prune_reason,
            "cold_start": any(a.label == "cold_start" for a in c.adjustments),
            "reason": c.base.reason,
        }
        for c in sorted(all_scored, key=lambda c: (-c.final_score, c.candidate_id))
    ]

    # ---- final hard-constraint gate (0-violations metric) ----------------
    hard_blocks = [
        (b.start, b.end, b.summary)
        for b in calendar_tool.parse_blocks(ctx, calendar_path)
        if not b.soft and b.start.date() == day
    ]
    window_ends = {w.label: w.end for w in windows}
    finals = [
        {
            "candidate_id": candidate.candidate_id,
            "start": window_starts[label],
            "end": window_ends[label],
            "window_label": label,
            "category": dest_meta.get(candidate.candidate_id, {}).get("category", ""),
        }
        for label, members in plan.slots.items()
        for candidate in members
    ]
    violations = validate_hard_constraints(
        finals, hard_blocks, {k: set(v) for k, v in gated.items()}
    )
    if violations:
        bad = {v.candidate_id for v in violations}
        plan.slots = {
            label: [c for c in members if c.candidate_id not in bad]
            for label, members in plan.slots.items()
        }
        plan.notes.append(f"hard-constraint gate dropped {len(bad)} candidate(s)")
    logger.validation("hard_constraints", len(finals), len(violations),
                      len(violations))
    return plan


def _fallback_report(domain: str, pack: EvidencePack, error: str) -> AgentReport:
    """Unpersonalized template when the planner LLM fails: never invented
    data -- one safe default built from real fetched records, confidence
    low, the failure stated in the reason (spec fallback rule)."""
    candidates: list[CandidateScore] = []
    if pack.candidates:
        first = pack.candidates[0]
        evidence = [pack.allowed_ids[0]] if pack.allowed_ids else []
        candidates.append(
            CandidateScore(
                candidate_id=first["candidate_id"], name=first["name"],
                site=first["site"], window=first["window"], score=5,
                reason=("Unpersonalized default: the planner LLM output could not "
                        "be parsed, so this is the first viable option, unranked."),
                evidence_ids=evidence, confidence="low",
            )
        )
    return AgentReport(
        candidates=candidates,
        self_report=f"planner LLM failed for {domain}: {error[:140]}; "
                    f"fell back to an unpersonalized default",
    )
