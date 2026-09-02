"""Excursion Agent demo runner: scenarios S1-S5 end to end.

  S1 daily plan     live weather + memory; the headline daily waterfall
  S2 weekly ToT     naive-vs-ToT contrast (the centerpiece)
  S3 cold start     an activity with no logged history -> low confidence
  S4 lifer bonus    life-list gaps surface named potential lifers
  S5 safety         approval-gated calendar write + semantic diff

Usage:
  python demo.py                          # S1 for next Saturday
  python demo.py --scenario all
  python demo.py --scenario S1 --date 2026-09-05
  python demo.py --calendar path/to/your.ics
  python demo.py --life-list data/life_list_full.csv
  python demo.py --approve auto|deny      # S5 without a TTY
  python demo.py --force-error open-meteo # eval degradation run (labeled)

Every run writes runs/sample_<scenario>_<date>.jsonl (the trajectory) and
prints where artifacts landed plus a per-source call summary.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402  (dotenv must load first)
from src.safety import redaction  # noqa: E402

redaction.install()

from scripts.make_sample_calendar import build_weeks, monday_of  # noqa: E402
from src.agents.llm import get_llm, probe  # noqa: E402
from src.orchestration.waterfall import DayPlan, run_daily  # noqa: E402
from src.safety.trajectory import TrajectoryLogger  # noqa: E402
from src.tools import calendar_write  # noqa: E402
from src.tools.base import RunContext  # noqa: E402

SEBAGO_SITE = {
    # S3's cold-start subject: a real place, an activity type with zero
    # logged history (scenario input, labeled synthetic like all data/).
    "id": "sebago-canoe-club", "name": "Sebago Canoe Club", "category": "kayaking",
    "lat": 40.6323, "lng": -73.9021, "coastal": True, "walk_miles": 1.0,
    "region_id": "brooklyn-coastal", "borough": "Brooklyn",
}


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------
def print_plan(plan: DayPlan) -> None:
    print(f"\n=== DAY PLAN {plan.date} ({plan.weekday}) " + "=" * 30)
    if plan.escalated:
        print(f"  ESCALATION: {plan.escalation_message}")
        return
    for window in plan.windows:
        soft = f"  [soft: {', '.join(window['soft'])}]" if window["soft"] else ""
        gates = plan.gated.get(window["label"])
        gate = f"  [weather-gated: {', '.join(gates)}]" if gates else ""
        print(f"  window {window['label']} ({window['minutes']} min){soft}{gate}")
        for reason in plan.gate_reasons.get(window["label"], [])[:2]:
            print(f"    - {reason}")
    for label, members in plan.slots.items():
        print(f"\n  TOP {len(members)} for {label}:")
        for rank, candidate in enumerate(members, 1):
            base = candidate.base
            adjustments = " ".join(
                f"[{a.label} {a.delta:+.1f}]" for a in candidate.adjustments if a.delta
            )
            lifer = (f"  LIFERS: {', '.join(candidate.lifer_species[:3])}"
                     if candidate.lifer_species else "")
            print(f"   {rank}. {base.name}  final={candidate.final_score:.1f} "
                  f"(model {base.score}) {adjustments} conf={candidate.confidence}")
            print(f"      {base.reason}")
            if candidate.transit_note:
                print(f"      transit: {candidate.transit_note}")
            if candidate.trip:
                approx = " (borough approx.)" if candidate.trip.approximate else ""
                print(f"      {candidate.trip.minutes} min via "
                      f"{'/'.join(candidate.trip.lines)}{approx}")
            print(f"      evidence: {', '.join(base.evidence_ids[:4])}"
                  + (" ..." if len(base.evidence_ids) > 4 else "") + lifer)
    print("\n  self-reports:")
    for domain, text in plan.self_reports.items():
        cold = "  (cold start)" if plan.cold_starts.get(domain) else ""
        print(f"    {domain}{cold}: {text}")
    for note in plan.notes:
        print(f"  note: {note}")


def print_call_summary(ctx: RunContext) -> None:
    print("\n=== EXTERNAL CALL SUMMARY " + "=" * 34)
    for source in sorted(ctx.calls):
        hits = ctx.cache_hits.get(source, 0)
        print(f"  {source:<14} {ctx.calls[source]:>3} call(s)"
              + (f"  (+{hits} served from in-run cache)" if hits else ""))
    print(f"  {'TOTAL':<14} {ctx.total_external_calls():>3}"
          f"   (ceiling {config.CALL_CEILING}"
          f"{', FLAGGED' if ctx.ceiling_flagged else ''})")
    print(f"  LLM calls: {dict(ctx.llm_calls)}")


def print_weekly(plan) -> None:
    print(f"\n=== WEEK PLAN starting {plan.week_start} " + "=" * 28)
    if not plan.sets:
        print("  no plannable days this week")
        return
    if plan.naive:
        print("  NAIVE rank-by-sum (no critic):")
        for pick in plan.naive.picks:
            print(f"    {pick['date']}  {pick['name']}  [{pick['category']}] "
                  f"{pick['final_score']:.1f}")
        print(f"    base sum {plan.naive.base_sum:.1f}")
    winner = plan.sets[0]
    print("  ToT WINNER (critic-adjusted):")
    for pick in winner.picks:
        print(f"    {pick['date']}  {pick['name']}  [{pick['category']}] "
              f"{pick['final_score']:.1f}")
    print(f"    base {winner.base_sum:.1f} -> adjusted {winner.adjusted:.1f}  "
          f"penalties {winner.penalties}")
    print(f"    rationale: {winner.rationale}")
    for alt in plan.sets[1:]:
        print(f"  alt #{alt.rank}: adjusted {alt.adjusted:.1f} "
              f"({', '.join(p['name'][:18] for p in alt.picks)})")
    if plan.contrast.get("differing_days"):
        print("  CONTRAST (naive vs ToT):")
        for d in plan.contrast["differing_days"]:
            print(f"    {d['date']}: naive={d['naive'][:30]} -> tot={d['tot'][:30]}")
        print(f"    dominant penalty: {plan.contrast.get('dominant_penalty')}")
    else:
        print("  contrast: none this week (naive == ToT; reported honestly)")
    print(f"  critic calls: {plan.critic_calls} (bound {plan.critic_bound}), "
          f"arithmetic mismatches: {plan.critic_mismatches}")


# --------------------------------------------------------------------------
# Calendar freshness
# --------------------------------------------------------------------------
def ensure_calendar(calendar_path: Path, target: date) -> None:
    """Auto-shift the DEFAULT synthetic calendar onto the target week when
    stale (never touches a user-supplied --calendar)."""
    if calendar_path != config.DATA_DIR / "calendar.ics":
        return
    week_start = monday_of(target)
    content = calendar_path.read_text() if calendar_path.exists() else ""
    if week_start.isoformat().replace("-", "")[:8] not in content.replace("-", ""):
        from datetime import date as _date
        anchor = monday_of(min(week_start, _date.today()))
        calendar_path.write_bytes(build_weeks(anchor, 5).to_ical())
        print(f"[notice] sample calendar regenerated: 5 synthetic weeks from "
              f"{anchor} (committed sample was stale)")


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
async def scenario_daily(
    ctx: RunContext, logger: TrajectoryLogger, args, extra_sites=None
) -> DayPlan:
    adapter = get_llm()
    await probe(ctx)
    plan = await run_daily(
        ctx, adapter, logger, args.date, args.calendar, args.life_list,
        extra_sites=extra_sites,
    )
    logger.write({"type": "day_plan", "plan": plan.model_dump()})
    print_plan(plan)
    return plan


async def scenario_s5(ctx: RunContext, logger: TrajectoryLogger, args) -> None:
    plan = await scenario_daily(ctx, logger, args)
    if plan.escalated or not plan.slots:
        logger.approval("skipped", detail="nothing to approve")
        return
    label, members = next(iter(plan.slots.items()))
    top = members[0]
    start = datetime.combine(
        args.date, datetime.strptime(label.split("-")[0], "%H:%M").time(),
        tzinfo=config.TZ)
    end = datetime.combine(
        args.date, datetime.strptime(label.split("-")[1], "%H:%M").time(),
        tzinfo=config.TZ)

    print(f"\n=== APPROVAL (S5) === add to calendar: {top.base.name}, "
          f"{args.date} {label}?")
    if args.approve == "prompt":
        answer = input("  approve? [y/N] ").strip().lower()
        decision = "approved" if answer == "y" else "denied"
    else:
        decision = "approved" if args.approve == "auto" else "denied"
        print(f"  --approve {args.approve} -> {decision}")

    if decision != "approved":
        logger.approval("denied", detail=top.base.name)
        print("  not written. (calendar_write never runs without approval)")
        return
    diff = calendar_write.append_event(
        args.calendar, f"Excursion: {top.base.name}", start, end,
        description=top.base.reason)
    logger.approval("approved", event_uid=diff["uid"], detail=top.base.name)
    print(f"  written to {diff['written_to']}")
    print(f"  semantic diff: +VEVENT uid={diff['uid']}")
    for key, value in diff["added"].items():
        print(f"    {key}: {value}")


SCENARIOS = ("S1", "S2", "S3", "S4", "S5")


async def run_scenario(name: str, ctx: RunContext, args) -> None:
    stamp = args.date.isoformat()
    tag = args.trace_tag or name
    trace_path = config.RUNS_DIR / f"sample_{tag}_{stamp}.jsonl"
    trace_path.unlink(missing_ok=True)
    logger = TrajectoryLogger(
        trace_path, run_id=ctx.run_id, scenario=name,
        injected_failure=args.force_error,
    )
    ctx.scenario = name
    ctx.log = logger.write
    before_calls = dict(ctx.calls)
    before_llm = dict(ctx.llm_calls)

    print(f"\n{'#' * 70}\n# SCENARIO {name}  ({stamp}, provider={config.LLM_PROVIDER})\n{'#' * 70}")
    escalated = False
    try:
        if name == "S1":
            plan = await scenario_daily(ctx, logger, args)
            escalated = plan.escalated
        elif name == "S2":
            from src.orchestration.tot_beam import run_weekly
            adapter = get_llm()
            await probe(ctx)
            weekly, _plans = await run_weekly(
                ctx, adapter, logger, args.date, args.calendar, args.life_list)
            escalated = not weekly.sets  # zero plannable days = escalation
            print_weekly(weekly)
        elif name == "S3":
            plan = await scenario_daily(ctx, logger, args, extra_sites=[SEBAGO_SITE])
            escalated = plan.escalated
            sebago = next((c for c in plan.scored_summary
                           if c["candidate_id"] == "site@sebago-canoe-club"), None)
            print("\n  S3 cold-start check:")
            if sebago is None:
                print("    the model omitted the kayaking candidate from its "
                      "scored output this run. Re-run S3 (an honest miss, not "
                      "a crash)")
            else:
                print(f"    {sebago['name']}: final={sebago['final_score']} "
                      f"confidence={sebago['confidence']} "
                      f"cold_start={sebago['cold_start']}")
                print(f"    reason: {sebago['reason'][:140]}")
        elif name == "S4":
            plan = await scenario_daily(ctx, logger, args)
            print(f"\n  S4 lifer check: {len(plan.lifers)} potential lifer(s): "
                  f"{', '.join(l['common_name'] for l in plan.lifers[:5]) or 'none'}")
            escalated = plan.escalated
        elif name == "S5":
            await scenario_s5(ctx, logger, args)
    finally:
        call_delta = {
            source: ctx.calls[source] - before_calls.get(source, 0)
            for source in ctx.calls
            if ctx.calls[source] - before_calls.get(source, 0)
        }
        llm_delta = {
            key: ctx.llm_calls[key] - before_llm.get(key, 0)
            for key in ctx.llm_calls
            if ctx.llm_calls[key] - before_llm.get(key, 0)
        }
        logger.summary(
            date=args.date.isoformat(), provider=config.LLM_PROVIDER,
            calls_by_source=call_delta, llm_calls=llm_delta,
            cache_hits=dict(ctx.cache_hits), ceiling_flag=ctx.ceiling_flagged,
            escalated=escalated,
            life_list_source=(
                "synthetic, intentionally incomplete"
                if args.life_list.name == "life_list.csv"
                else f"synthetic variant: {args.life_list.name}"),
            samples_written=str(trace_path.relative_to(ROOT)),
        )
        logger.close()
        print(f"\n  trace -> {trace_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", default="S1",
                        choices=list(SCENARIOS) + ["all"])
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="target day (default: next Saturday)")
    parser.add_argument("--calendar", type=Path,
                        default=config.DATA_DIR / "calendar.ics")
    parser.add_argument("--life-list", type=Path,
                        default=config.DATA_DIR / "life_list.csv")
    parser.add_argument("--approve", choices=["prompt", "auto", "deny"],
                        default=None,
                        help="S5 approval mode (default: prompt for S5 alone, "
                             "deny under --scenario all)")
    parser.add_argument("--force-error", default=None, metavar="SOURCE",
                        help="eval degradation run: the named source returns "
                             "an error; EVERY trace line is stamped "
                             "injected_failure (simulated, labeled)")
    parser.add_argument("--rebuild-memory", action="store_true")
    parser.add_argument("--trace-tag", default=None,
                        help="override the trace filename tag (eval uses "
                             "'escalation' / 'forced_error_<src>' so fixture "
                             "runs never clobber scenario traces)")
    args = parser.parse_args()

    today = datetime.now(config.TZ).date()
    if args.date is None:
        args.date = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    horizon = today + timedelta(days=config.FORECAST_DAYS - 1)
    if not (today <= args.date <= horizon):
        sys.exit(f"--date {args.date} is outside the live forecast horizon "
                 f"({today}..{horizon}); pick a date inside it.")

    if args.approve is None:
        args.approve = "prompt" if args.scenario == "S5" else "deny"

    ensure_calendar(args.calendar, args.date)

    if args.rebuild_memory:
        from src.memory.retrieval import ExcursionMemory
        ExcursionMemory.build(rebuild=True)
        print("[notice] memory index rebuilt")

    if args.force_error:
        from src.tools import base as tools_base
        target = args.force_error

        original = tools_base._fetch_once

        async def sabotaged(ctx, source, url, params, headers):
            if source == target:
                from src.tools.base import ToolResult
                return ToolResult(
                    source=source, fetched_at=datetime.now(config.TZ),
                    status="error",
                    note=f"SIMULATED failure (--force-error {target})")
            return await original(ctx, source, url, params, headers)

        tools_base._fetch_once = sabotaged
        print(f"[notice] SIMULATED: source {target!r} will fail this run "
              f"(labeled in every trace line)")

    ctx = RunContext(scenario=args.scenario)
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    try:
        for name in names:
            await run_scenario(name, ctx, args)
    finally:
        print_call_summary(ctx)
        await ctx.aclose()


if __name__ == "__main__":
    asyncio.run(main())
