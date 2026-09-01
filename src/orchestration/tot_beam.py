"""Weekly Tree-of-Thought beam search over the daily ranked lists.

Why not rank-by-sum: a set's value is not the sum of its parts, three
9-point birding mornings is a worse WEEK than birding + a hike + a museum.
The critic re-scores each partial set for variety, walking load, and
transit fatigue at every expansion; the beam keeps the best 4 sets alive.

Mechanics (frozen spec + plan pre-decisions):
- node = immutable partial set (frozen dataclass; `dataclasses.replace`
  on expand, a parent is structurally impossible to mutate, no deepcopy)
- thought = deciding the next day, Monday -> Sunday; no-window days skipped
- branch = one of that day's top-3 (highest final_score ACROSS the day's
  slots; a day contributes exactly ONE excursion)
- critic = one structured call per expansion; code RECOMPUTES
  adjusted = base_sum - sum(penalties) and logs any arithmetic mismatch
- prune = keep top-4 per depth AND drop sets > 3.0 below the depth leader
- ties = least weekly transit, then a per-run seeded Random, children
  are built from gather()'s argument-ordered return, so completion order
  never influences results
- critic-call bound = 3 + 12*(D-1) for D usable days; asserted in eval
"""

from __future__ import annotations

import asyncio
import json
import random
from functools import lru_cache
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from src import config
from src.agents.llm import LLMAdapter
from src.agents.schemas import CriticVerdict, ScoredCandidate
from src.orchestration.waterfall import DayPlan, run_daily
from src.safety.trajectory import TrajectoryLogger
from src.tools.base import RunContext


# --------------------------------------------------------------------------
# Node
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BeamNode:
    picks: tuple[str, ...] = ()  # candidate_ids in day order
    base_sum: float = 0.0
    adjusted: float = 0.0
    transit_min: int = 0
    walk_miles: float = 0.0
    penalties: tuple[float, float, float] = (0.0, 0.0, 0.0)  # variety/walk/fatigue
    rationale: str = ""
    tiebreak: float = field(default=0.0, compare=False)


def expand(parent: BeamNode, candidate: ScoredCandidate, verdict: CriticVerdict,
           tiebreak: float, walk_delta: float) -> tuple[BeamNode, bool]:
    """Pure expansion: child from parent + candidate + critic verdict.
    Returns (child, arithmetic_mismatch)."""
    trip_min = 2 * candidate.trip.minutes if candidate.trip else 0
    base_sum = parent.base_sum + candidate.final_score
    penalties = (verdict.variety_penalty, verdict.walking_penalty,
                 verdict.transit_fatigue_penalty)
    computed = base_sum - sum(penalties)
    mismatch = abs(verdict.adjusted_total - computed) > 0.01
    child = replace(
        parent,
        picks=parent.picks + (candidate.candidate_id,),
        base_sum=base_sum,
        adjusted=computed,  # code-computed; the critic's itemization is the artifact
        transit_min=parent.transit_min + trip_min,
        walk_miles=parent.walk_miles + walk_delta,
        penalties=penalties,
        rationale=verdict.rationale,
        tiebreak=tiebreak,
    )
    return child, mismatch


# --------------------------------------------------------------------------
# Output models
# --------------------------------------------------------------------------
class WeeklySet(BaseModel):
    rank: int
    picks: list[dict]  # {date, candidate_id, name, category, final_score,
    #                    walk_miles, transit_min}
    base_sum: float
    adjusted: float
    transit_min: int
    walk_miles: float
    penalties: dict[str, float]
    rationale: str


class WeeklyPlan(BaseModel):
    week_start: str
    days_planned: list[str]
    days_skipped: list[str]
    sets: list[WeeklySet]
    naive: WeeklySet | None = None
    contrast: dict = Field(default_factory=dict)
    critic_calls: int = 0
    critic_bound: int = 0
    critic_mismatches: int = 0


# --------------------------------------------------------------------------
# Critic
# --------------------------------------------------------------------------
CRITIC_PROMPT = """\
You are the weekly-schedule critic for a personal excursion planner. A
partial week of excursions is being extended by one more day; re-score the
SET as a whole. A set's value is not the sum of its parts.

PARTIAL SET SO FAR (chronological):
{set_lines}

CANDIDATE BEING ADDED for {day} ({weekday}):
  {candidate_line}

Set totals if added: base score sum {base_sum:.1f}, walking
{walk_miles:.1f} mi (weekly penalty threshold {walk_threshold:.0f} mi),
transit {transit_min} min round-trips (weekly fatigue threshold
{fatigue_threshold} min).

Assess three penalties (each >= 0, in score points):
- variety_penalty: repetition of activity type or site within the week;
  CLOSER repetition is worse (same type on consecutive days > spread out;
  same exact site again is worst). Two different nature settings (forest
  vs salt marsh) is mild; the identical activity+site repeated is severe.
- walking_penalty: only if projected weekly walking exceeds the threshold.
- transit_fatigue_penalty: only if projected weekly transit exceeds the
  threshold.

adjusted_total MUST equal base score sum minus the three penalties.
rationale: at most two sentences naming the dominant factor.
"""


def _critic_prompt(day: date, weekday: str, set_lines: str, candidate_line: str,
                   base_sum: float, walk: float, transit: int) -> str:
    return CRITIC_PROMPT.format(
        set_lines=set_lines or "  (empty, this is the first day)",
        day=day.isoformat(), weekday=weekday, candidate_line=candidate_line,
        base_sum=base_sum, walk_miles=walk,
        walk_threshold=config.WALKING_WEEK_MILES,
        transit_min=transit, fatigue_threshold=config.TRANSIT_FATIGUE_WEEK_MIN,
    )


# --------------------------------------------------------------------------
# The search
# --------------------------------------------------------------------------
async def run_weekly(
    ctx: RunContext,
    adapter: LLMAdapter,
    logger: TrajectoryLogger,
    week_anchor: date,
    calendar_path: Path,
    life_list_path: Path,
) -> tuple[WeeklyPlan, dict[str, DayPlan]]:
    week_start = week_anchor - timedelta(days=week_anchor.weekday())
    days = [week_start + timedelta(days=i) for i in range(config.BEAM_DEPTH)]

    # ---- the 7 daily waterfalls, SEQUENTIAL (politeness pacing) ----------
    day_plans: dict[str, DayPlan] = {}
    day_candidates: list[tuple[date, list[ScoredCandidate]]] = []
    day_walk: dict[str, float] = {}
    skipped: list[str] = []
    for day in days:
        plan = await run_daily(ctx, adapter, logger, day, calendar_path,
                               life_list_path)
        day_plans[day.isoformat()] = plan
        if plan.escalated or not plan.slots:
            skipped.append(day.isoformat())
            continue
        merged = [c for members in plan.slots.values() for c in members]
        top3 = sorted(merged, key=lambda c: (-c.final_score, c.candidate_id))[:3]
        for candidate in top3:
            day_walk[f"{day.isoformat()}|{candidate.candidate_id}"] = (
                _candidate_walk(candidate))
        day_candidates.append((day, top3))

    if not day_candidates:
        logger.escalation("zero_plannable_days",
                          "No day in the week has a usable free window.")
        return WeeklyPlan(week_start=week_start.isoformat(), days_planned=[],
                          days_skipped=skipped, sets=[]), day_plans

    # ---- beam search -----------------------------------------------------
    rng = random.Random(config.SEED)
    beam = [BeamNode()]
    critic_calls = 0
    mismatches = 0
    depth = 0
    for day, candidates in day_candidates:
        depth += 1
        weekday = day.strftime("%A")
        expansions = [(node, candidate) for node in beam for candidate in candidates]
        prompts = []
        for node, candidate in expansions:
            set_lines = "\n".join(
                f"  {d.isoformat()} ({d.strftime('%a')}): {line}"
                for d, line in _picked_lines(node, day_candidates)
            )
            walk = node.walk_miles + day_walk[f"{day.isoformat()}|{candidate.candidate_id}"]
            transit = node.transit_min + (2 * candidate.trip.minutes if candidate.trip else 0)
            prompts.append(_critic_prompt(
                day, weekday, set_lines,
                _candidate_line(candidate, day_walk[f"{day.isoformat()}|{candidate.candidate_id}"]),
                node.base_sum + candidate.final_score, walk, transit))

        verdicts = await asyncio.gather(
            *(adapter.structured(p, CriticVerdict, purpose="critic", ctx=ctx)
              for p in prompts),
            return_exceptions=True,
        )
        critic_calls += len(prompts)

        children: list[BeamNode] = []
        for (node, candidate), outcome in zip(expansions, verdicts):
            if isinstance(outcome, BaseException) or outcome.obj is None:
                error = (str(outcome) if isinstance(outcome, BaseException)
                         else outcome.error)
                verdict = CriticVerdict(
                    variety_penalty=0.0, walking_penalty=0.0,
                    transit_fatigue_penalty=0.0,
                    adjusted_total=node.base_sum + candidate.final_score,
                    rationale="critic unavailable; base sum used (fallback)")
                logger.step("tot", "critic", "error", note=str(error)[:120],
                            fallback_taken=True)
            else:
                verdict = outcome.obj
                logger.llm("critic", adapter.provider, outcome.latency_ms,
                           True, outcome.retried, outcome.error)
            walk_delta = day_walk[f"{day.isoformat()}|{candidate.candidate_id}"]
            child, mismatch = expand(node, candidate, verdict, rng.random(),
                                     walk_delta)
            mismatches += int(mismatch)
            logger.write({
                "type": "critic", "depth": depth, "day": day.isoformat(),
                "picks": list(child.picks), "candidate": candidate.candidate_id,
                "penalties": {"variety": verdict.variety_penalty,
                              "walking": verdict.walking_penalty,
                              "transit_fatigue": verdict.transit_fatigue_penalty},
                "critic_adjusted": verdict.adjusted_total,
                "code_adjusted": child.adjusted,
                "arithmetic_mismatch": mismatch,
                "rationale": verdict.rationale,
            })
            children.append(child)

        children.sort(key=lambda n: (-n.adjusted, n.transit_min, n.tiebreak))
        leader = children[0].adjusted
        survivors = [n for n in children[: config.BEAM_WIDTH]
                     if leader - n.adjusted <= config.PRUNE_MARGIN]
        for node in children:
            if node not in survivors:
                reason = ("beam width" if leader - node.adjusted <= config.PRUNE_MARGIN
                          else f"{leader - node.adjusted:.1f} below depth leader")
                logger.write({"type": "prune", "depth": depth,
                              "picks": list(node.picks), "reason": reason,
                              "adjusted": node.adjusted})
        beam = survivors

    # ---- outputs ---------------------------------------------------------
    bound = 3 + 12 * (len(day_candidates) - 1) if day_candidates else 0
    plan = WeeklyPlan(
        week_start=week_start.isoformat(),
        days_planned=[d.isoformat() for d, _ in day_candidates],
        days_skipped=skipped,
        sets=[_to_set(rank + 1, node, day_candidates, day_walk)
              for rank, node in enumerate(beam[:3])],
        critic_calls=critic_calls, critic_bound=bound,
        critic_mismatches=mismatches,
    )

    # Naive rank-by-sum baseline (code-side, zero extra LLM calls).
    naive_node = BeamNode()
    for day, candidates in day_candidates:
        best = candidates[0]
        naive_node = replace(
            naive_node,
            picks=naive_node.picks + (best.candidate_id,),
            base_sum=naive_node.base_sum + best.final_score,
            transit_min=naive_node.transit_min + (2 * best.trip.minutes if best.trip else 0),
            walk_miles=naive_node.walk_miles + day_walk[f"{day.isoformat()}|{best.candidate_id}"],
        )
    plan.naive = _to_set(0, replace(naive_node, adjusted=naive_node.base_sum),
                         day_candidates, day_walk)

    if plan.sets:
        winner = plan.sets[0]
        differing = [
            {"date": n["date"], "naive": n["name"], "tot": t["name"]}
            for n, t in zip(plan.naive.picks, winner.picks)
            if n["candidate_id"] != t["candidate_id"]
        ]
        plan.contrast = {
            "differing_days": differing,
            "naive_base_sum": plan.naive.base_sum,
            "tot_adjusted": winner.adjusted,
            "dominant_penalty": max(
                winner.penalties, key=lambda k: winner.penalties[k]
            ) if any(winner.penalties.values()) else None,
        }
    logger.write({"type": "weekly_plan", "plan": plan.model_dump()})
    return plan, day_plans


@lru_cache(maxsize=1)
def _walk_catalog() -> dict[str, float]:
    """id -> walk_miles for every site and venue, loaded once. The beam
    calls this for every expansion, so disk reads here would block the
    event loop hundreds of times per weekly run."""
    catalog: dict[str, float] = {}
    for path, key in ((config.DATA_DIR / "sites.json", "sites"),
                      (config.DATA_DIR / "venues.json", "venues")):
        for entry in json.loads(path.read_text())[key]:
            catalog[entry["id"]] = float(entry.get("walk_miles", 2.0))
            catalog[entry["name"]] = float(entry.get("walk_miles", 2.0))
    return catalog


def _candidate_walk(candidate: ScoredCandidate) -> float:
    catalog = _walk_catalog()
    dest = candidate.candidate_id.split("@", 1)[-1]
    return catalog.get(dest) or catalog.get(candidate.base.site, 2.0)


def _picked_lines(node: BeamNode, day_candidates) -> list[tuple[date, str]]:
    lines = []
    for (day, candidates), pick in zip(day_candidates, node.picks):
        chosen = next((c for c in candidates if c.candidate_id == pick), None)
        if chosen:
            lines.append((day, _candidate_line(chosen, _candidate_walk(chosen))))
    return lines


def _candidate_line(candidate: ScoredCandidate, walk: float) -> str:
    category = candidate.candidate_id.split("@")[0]
    transit = 2 * candidate.trip.minutes if candidate.trip else 0
    return (f"{candidate.base.name} [{candidate.domain}/{category}] at "
            f"{candidate.base.site[:40]}, score {candidate.final_score:.1f}, "
            f"walk ~{walk:.1f} mi, transit ~{transit} min round trip")


def _to_set(rank: int, node: BeamNode, day_candidates, day_walk) -> WeeklySet:
    picks = []
    for (day, candidates), pick in zip(day_candidates, node.picks):
        chosen = next((c for c in candidates if c.candidate_id == pick), None)
        if chosen is None:
            continue
        picks.append({
            "date": day.isoformat(), "candidate_id": chosen.candidate_id,
            "name": chosen.base.name,
            "category": chosen.domain,
            "window": chosen.base.window,
            "final_score": chosen.final_score,
            "walk_miles": day_walk.get(f"{day.isoformat()}|{chosen.candidate_id}", 2.0),
            "transit_min": 2 * chosen.trip.minutes if chosen.trip else 0,
            "confidence": chosen.confidence,
        })
    return WeeklySet(
        rank=rank, picks=picks, base_sum=round(node.base_sum, 2),
        adjusted=round(node.adjusted, 2), transit_min=node.transit_min,
        walk_miles=round(node.walk_miles, 1),
        penalties={"variety": node.penalties[0], "walking": node.penalties[1],
                   "transit_fatigue": node.penalties[2]},
        rationale=node.rationale,
    )
