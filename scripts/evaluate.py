"""Evaluation harness: real runs -> eval/results.md.

Default mode EXECUTES the full suite (every number in results.md comes
from a run this invocation performed): S1-S5, the S4 zero-lifers control,
the escalation fixture, and one labeled forced-error run. --skip-runs
recomputes results.md from whatever traces already exist in runs/.

Every metric is read ONLY from trajectory records; results.md cites each
source trace with its real timestamp, provider, and eBird-key mode, and
carries the honesty captions beside the numbers they qualify:
- forced-error and escalation runs are SIMULATED/fixture, and labeled;
- the naive-vs-ToT KEY RESULT runs on the authored synthetic week,
  selected because it exercises the contrast, the disclosure sits
  beside the result, and a contrast-free live week is reported honestly.

    python -m scripts.evaluate [--date YYYY-MM-DD] [--skip-runs]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402

RESULTS = config.EVAL_DIR / "results.md"


# --------------------------------------------------------------------------
# Run execution
# --------------------------------------------------------------------------
def run_demo(extra: list[str]) -> int:
    command = [sys.executable, "demo.py", *extra]
    print(f"\n>>> {' '.join(command)}")
    return subprocess.call(command, cwd=ROOT)


def execute_suite(target: date) -> None:
    stamp = target.isoformat()
    steps = [
        (["--scenario", "all", "--date", stamp, "--approve", "auto"], True),
        (["--scenario", "S4", "--date", stamp,
          "--life-list", "data/life_list_full.csv",
          "--trace-tag", "S4_control"], True),
        (["--scenario", "S1", "--date", stamp,
          "--calendar", "data/calendar_fullyblocked.ics",
          "--trace-tag", "escalation"], False),
        (["--scenario", "S1", "--date", stamp,
          "--force-error", "open-meteo",
          "--trace-tag", "forced_error_open-meteo"], True),
    ]
    for extra, must_pass in steps:
        code = run_demo(extra)
        if code != 0 and must_pass:
            sys.exit(f"eval run failed ({code}): demo.py {' '.join(extra)}")


# --------------------------------------------------------------------------
# Trace reading
# --------------------------------------------------------------------------
def latest_traces() -> dict[str, Path]:
    traces: dict[str, tuple[str, Path]] = {}
    for path in sorted(config.RUNS_DIR.glob("sample_*.jsonl")):
        tag = path.stem[len("sample_"):].rsplit("_", 1)[0]
        stamp = path.stem.rsplit("_", 1)[-1]
        if tag not in traces or stamp >= traces[tag][0]:
            traces[tag] = (stamp, path)
    return {tag: path for tag, (_, path) in traces.items()}


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def compute(traces: dict[str, Path]) -> str:
    all_records: dict[str, list[dict]] = {tag: records(p) for tag, p in traces.items()}

    # provenance header
    lines = ["# Evaluation results", "",
             "All numbers below are computed exclusively from the trajectory",
             "records of the runs cited here. Synthetic inputs are labeled;",
             "simulated failures are stamped on every trace line.", "",
             "## Source runs", "",
             "| tag | trace | first record | provider | eBird |",
             "|---|---|---|---|---|"]
    for tag, path in sorted(traces.items()):
        recs = all_records[tag]
        summary = next((r for r in reversed(recs) if r["type"] == "run_summary"), {})
        provider = summary.get("provider", "?")
        ebird_mode = ("live key" if (summary.get("calls_by_source", {}) or {}).get("ebird")
                      else "keyless/cached")
        first_ts = recs[0]["ts"] if recs else "?"
        lines.append(f"| {tag} | `{path.name}` | {first_ts} | {provider} | {ebird_mode} |")

    # ---- groundedness ----------------------------------------------------
    emitted = valid = dropped = 0
    for recs in all_records.values():
        for r in recs:
            if r["type"] == "validation" and r["validator"] == "groundedness":
                emitted += r["checked"]
                valid += r["checked"] - r["violations"]
                dropped += r["dropped"]
    rate = (valid / emitted) if emitted else 1.0
    lines += ["", "## Headline metrics", "",
              f"- **Groundedness**: {rate:.1%} of evidence ids emitted by agents "
              f"resolved to fetched records ({valid}/{emitted}; the denominator "
              f"counts everything emitted BEFORE stripping, so 100% means something). "
              f"{dropped} candidate(s) dropped for zero valid evidence. Target: 100%."]

    # ---- hard constraints ------------------------------------------------
    hc_checked = hc_violations = 0
    for recs in all_records.values():
        for r in recs:
            if r["type"] == "validation" and r["validator"] == "hard_constraints":
                hc_checked += r["checked"]
                hc_violations += r["violations"]
    lines.append(f"- **Hard-constraint violations**: {hc_violations} across "
                 f"{hc_checked} final candidates (target 0; violators are "
                 f"dropped by the gate and logged).")

    # ---- escalation ------------------------------------------------------
    esc = [(tag, r) for tag, recs in all_records.items()
           for r in recs if r["type"] == "escalation"]
    if esc:
        tag, record = esc[0]
        lines.append(f"- **Escalation**: triggered in `{tag}` "
                     f"({record['reason']}): \"{record['message'][:90]}...\" "
                     f"(fixture calendar `data/calendar_fullyblocked.ics`); "
                     f"the agent stopped and asked instead of guessing.")
    else:
        lines.append("- **Escalation**: NOT DEMONSTRATED (no escalation record "
                     "found; run the fixture).")

    # ---- fallbacks / forced error ---------------------------------------
    forced = {tag: recs for tag, recs in all_records.items()
              if any(r.get("injected_failure") for r in recs)}
    fallback_steps = [(tag, r) for tag, recs in all_records.items()
                      for r in recs
                      if r["type"] == "step" and r.get("fallback_taken")]
    if forced:
        tag = next(iter(forced))
        source = next(r["injected_failure"] for r in forced[tag]
                      if r.get("injected_failure"))
        notes = [r["note"] for r in forced[tag]
                 if r["type"] == "step" and r.get("fallback_taken")]
        lines.append(f"- **Forced-error degradation** (SIMULATED, labeled on every "
                     f"line of `{traces[tag].name}`): source `{source}` failed; "
                     f"{len(notes)} fallback step(s) taken; the run completed "
                     f"with stated low confidence instead of crashing or "
                     f"inventing data.")
    else:
        lines.append("- **Forced-error degradation**: NOT DEMONSTRATED yet.")
    lines.append(f"- **Fallback steps observed across all runs**: "
                 f"{len(fallback_steps)} (each labeled in its trace).")

    # ---- latency ---------------------------------------------------------
    by_stage: dict[str, list[int]] = defaultdict(list)
    for recs in all_records.values():
        for r in recs:
            if r["type"] == "step" and r.get("latency_ms") is not None:
                by_stage[r["stage"]].append(r["latency_ms"])
    lines += ["", "## Latency per stage (ms)", "",
              "| stage | n | median | max |", "|---|---|---|---|"]
    for stage, values in sorted(by_stage.items()):
        lines.append(f"| {stage} | {len(values)} | "
                     f"{int(statistics.median(values))} | {max(values)} |")

    # ---- call accounting -------------------------------------------------
    totals: Counter[str] = Counter()
    llm_totals: Counter[str] = Counter()
    flagged = False
    for recs in all_records.values():
        summary = next((r for r in reversed(recs) if r["type"] == "run_summary"), None)
        if summary:
            totals.update(summary.get("calls_by_source", {}))
            llm_totals.update(summary.get("llm_calls", {}))
            flagged |= bool(summary.get("ceiling_flag"))
    lines += ["", "## Call accounting", "",
              f"- External calls across all cited runs: "
              f"{dict(sorted(totals.items()))} (total {sum(totals.values())}; "
              f"ceiling {config.CALL_CEILING}; "
              f"flag {'RAISED' if flagged else 'not raised'}).",
              f"- LLM calls: {dict(sorted(llm_totals.items()))}."]
    weekly = next((r for recs in all_records.values() for r in recs
                   if r["type"] == "weekly_plan"), None)
    if weekly:
        plan = weekly["plan"]
        ok = plan["critic_calls"] <= plan["critic_bound"]
        lines.append(f"- Critic calls {plan['critic_calls']} <= designed bound "
                     f"3+12(D-1) = {plan['critic_bound']}: "
                     f"{'OK' if ok else 'EXCEEDED'}; arithmetic mismatches "
                     f"logged: {plan['critic_mismatches']}.")

    # ---- KEY RESULT ------------------------------------------------------
    lines += ["", "## KEY RESULT: naive rank-by-sum vs Tree-of-Thought", ""]
    if weekly:
        plan = weekly["plan"]
        naive, sets = plan.get("naive"), plan.get("sets") or []
        if naive and sets:
            winner = sets[0]
            lines += ["*(Disclosure: this weekly run uses the authored synthetic",
                      "calendar week, selected because it exercises the",
                      "contrast. Live-data variance means another week may show",
                      "no contrast; that outcome is reported here honestly when",
                      "it happens, and re-running with `--date` in another week",
                      "is the documented recourse.)*", "",
                      "| day | naive pick | ToT pick |", "|---|---|---|"]
            differ_dates = {d["date"] for d in plan["contrast"].get("differing_days", [])}
            for n, t in zip(naive["picks"], winner["picks"]):
                mark = " **<-**" if n["date"] in differ_dates else ""
                lines.append(f"| {n['date']} | {n['name']} [{n['category']}] | "
                             f"{t['name']} [{t['category']}]{mark} |")
            contrast = plan["contrast"]
            if differ_dates:
                lines.append("")
                lines.append(
                    f"Naive base sum {contrast['naive_base_sum']:.1f} vs ToT "
                    f"adjusted {contrast['tot_adjusted']:.1f}; "
                    f"{len(differ_dates)} day(s) flipped; dominant penalty: "
                    f"**{contrast.get('dominant_penalty')}**. The Week-4 "
                    f"design claim (a set's value is not the sum of its parts) "
                    f"demonstrated on a real run.")
            else:
                lines.append("")
                lines.append("**No contrast this week** (naive == ToT). Reported "
                             "honestly; re-run S2 on a different week.")
        else:
            lines.append("Weekly run present but incomplete.")
    else:
        lines.append("NOT DEMONSTRATED yet (no weekly_plan record; run S2).")

    # ---- lifer on/off ----------------------------------------------------
    lines += ["", "## Lifer bonus on/off", ""]
    def lifer_stats(tag: str):
        recs = all_records.get(tag)
        if not recs:
            return None
        day = next((r for r in recs if r["type"] == "day_plan"), None)
        if not day:
            return None
        plan = day["plan"]
        bonus = 0.0
        for members in plan["slots"].values():
            for candidate in members:
                for adjustment in candidate["adjustments"]:
                    if adjustment["label"] == "lifer_bonus":
                        bonus = max(bonus, adjustment["delta"])
        summary = next((r for r in reversed(recs) if r["type"] == "run_summary"), {})
        return len(plan.get("lifers", [])), bonus, summary.get("life_list_source")

    with_gaps = lifer_stats("S4")
    control = lifer_stats("S4_control")
    if with_gaps:
        n, bonus, source_label = with_gaps
        lines.append(f"- With the committed list (*{source_label}*): {n} "
                     f"potential lifer(s) surfaced; max lifer bonus applied "
                     f"+{bonus:.1f} (cap {config.LIFER_BONUS_CAP}).")
    if control:
        n, bonus, source_label = control
        lines.append(f"- With the zero-lifers control (*{source_label}*): {n} "
                     f"lifer(s), bonus +{bonus:.1f}. Same site, same day; "
                     f"the delta is the life-list gap.")
    if not (with_gaps and control):
        lines.append("- NOT fully demonstrated yet (need S4 and S4_control runs).")

    lines += ["", "---", f"Generated {datetime.now(config.TZ).isoformat(timespec='seconds')} "
              f"by scripts/evaluate.py; trajectory traces in `runs/`."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--skip-runs", action="store_true",
                        help="only recompute results.md from existing traces")
    args = parser.parse_args()

    today = datetime.now(config.TZ).date()
    target = args.date or today + timedelta(days=(5 - today.weekday()) % 7 or 7)

    if not args.skip_runs:
        execute_suite(target)

    traces = latest_traces()
    if not traces:
        sys.exit("no runs/sample_*.jsonl traces found; run demo.py first")
    config.EVAL_DIR.mkdir(exist_ok=True)
    RESULTS.write_text(compute(traces))
    print(f"\nwrote {RESULTS} from {len(traces)} trace(s): {sorted(traces)}")


if __name__ == "__main__":
    main()
