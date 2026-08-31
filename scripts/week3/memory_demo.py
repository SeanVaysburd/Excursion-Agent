"""
Demo: the same planning request answered with and without long-term memory.

Prints four blocks, in order:

    BLOCK 1  scenario setup      , planning context and the query string
    BLOCK 2  retrieval trace     , 7 hits, the re-rank, the final 3
    BLOCK 3  output comparison   , (a) without retrieval vs (b) with
    BLOCK 4  cold start          , a request nothing in the log covers

Usage:
    python -m scripts.week3.memory_demo
    python -m scripts.week3.memory_demo --rebuild                 # re-embed from data/excursions.json
    python demo.py --llm                     # include the saved Claude answers
    python demo.py --emit-prompts            # write prompts/ for inspection
    python demo.py --cold-start backpacking  # use the other cold-start case

Plain text only, no colour, no emoji, wrapped to 78 columns.
"""

from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path

from src.memory.retrieval import (
    CANDIDATE_K,
    SIMILARITY_CUTOFF,
    TOP_K,
    WEIGHTS,
    ExcursionMemory,
    PlanningContext,
)
from scripts.week3.planner_prompt import build_augmented_prompt, build_baseline_prompt
from scripts.week3.recommend import Plan, baseline_plan, memory_informed_plan

WIDTH = 78
EXCERPT_WORDS = 15
ROOT = Path(__file__).resolve().parents[2]  # scripts/week3/ -> repo root
PROMPT_DIR = ROOT / "docs" / "week3" / "prompts"
LLM_DIR = ROOT / "docs" / "week3" / "llm_output"


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def block(number: int, title: str) -> None:
    print()
    print("=" * WIDTH)
    print(f"BLOCK {number}, {title}")
    print("=" * WIDTH)


def sub(title: str) -> None:
    print()
    print(f"  {title}")
    print(f"  {'-' * (WIDTH - 4)}")


def wrap(text: str, indent: str = "  ", hang: str | None = None) -> str:
    return textwrap.fill(
        text,
        width=WIDTH,
        initial_indent=indent,
        subsequent_indent=hang if hang is not None else indent,
    )


def conf_level(confidence: str) -> str:
    """Leading confidence word only. Tolerates every delimiter in play: the
    current " | " contract, the frozen replay files' " -- ", and a comma."""
    return re.split(r"\s*(?:\||--|,)\s*", confidence, maxsplit=1)[0]


def kv(label: str, value: str, indent: int = 4, label_w: int = 16) -> str:
    # Never let a long label run into its value.
    width = max(label_w, len(label) + 1)
    pad = " " * (indent + width)
    return textwrap.fill(
        value,
        width=WIDTH,
        initial_indent=f"{' ' * indent}{label:<{width}}",
        subsequent_indent=pad,
    )


def excerpt(text: str, words: int = EXCERPT_WORDS) -> str:
    parts = text.split()
    if len(parts) <= words:
        return f'"{text}"'
    return f'"{" ".join(parts[:words])} ..."'


def truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


# --------------------------------------------------------------------------
# BLOCK 1, scenario setup
# --------------------------------------------------------------------------
def print_setup(ctx: PlanningContext, result, number: int = 1) -> None:
    block(number, "SCENARIO SETUP")

    sub("Planning context")
    print(kv("date", ctx.date_label or ctx.day_of_week))
    print(kv("season", ctx.season))
    print(kv("free window", ctx.window))
    print(kv("time of day", ctx.time_of_day))
    print(kv("activity", ctx.activity_type.replace("_", " ")))
    print(kv("site", ctx.site))

    sub("Query string sent to the retriever")
    print()
    print(wrap(f'"{result.query}"', indent="    "))


# --------------------------------------------------------------------------
# BLOCK 2, retrieval trace
# --------------------------------------------------------------------------
def print_candidates(result) -> None:
    """Stage 1: the raw semantic hits."""
    print()
    print(
        f"    {'#':<3}{'entry':<7}{'site':<29}{'date':<12}"
        f"{'rating':>7}{'similarity':>12}"
    )
    print(f"    {'-' * 70}")
    for i, c in enumerate(result.candidates, start=1):
        md = c.metadata
        print(
            f"    {i:<3}{c.entry_id:<7}{truncate(md['site'], 28):<29}"
            f"{md['date']:<12}{str(md.get('rating', '-')) + '/10':>7}{c.similarity:>12.3f}"
        )
        print(wrap(excerpt(c.get_content()), indent="        "))


def print_rerank(result) -> None:
    """Stage 2: component scores and composite, for every candidate."""
    w = WEIGHTS
    print()
    print(wrap(
        f"composite = {w['similarity']:.3f}*semantic + {w['season']:.3f}*season "
        f"+ {w['type']:.3f}*type + {w['recency']:.3f}*recency",
        indent="    ",
    ))
    print()
    print(
        f"    {'entry':<7}{'semantic':>10}{'season':>9}{'type':>8}"
        f"{'recency':>10}{'composite':>12}{'cutoff':>9}"
    )
    print(f"    {'-' * 65}")

    for c in sorted(result.candidates, key=lambda c: c.composite, reverse=True):
        print(
            f"    {c.entry_id:<7}{c.similarity:>10.3f}{c.season:>9.3f}"
            f"{c.type_match:>8.3f}{c.recency:>10.3f}{c.composite:>12.3f}"
            f"{'pass' if c.passed_cutoff else 'DROP':>9}"
        )

    if result.dropped:
        print()
        print(wrap(
            f"{len(result.dropped)} of {len(result.candidates)} scored below the "
            f"{result.cutoff:.3f} similarity cutoff and are ineligible whatever "
            f"their composite. The cutoff is applied to raw semantic similarity "
            f"before re-ranking, so a season or recency bonus cannot lift an "
            f"irrelevant entry over the bar.",
            indent="    ",
        ))


def print_selection(result) -> None:
    """Stage 3: what the planner actually receives."""
    eligible = [c.entry_id for c in result.candidates if c.passed_cutoff]
    reranked = [c.entry_id for c in result.ranked]

    print()
    for i, c in enumerate(result.kept, start=1):
        md = c.metadata
        print(
            f"    {i}. {c.entry_id}   composite {c.composite:.3f}   "
            f"semantic {c.similarity:.3f}   rated {md.get('rating', '-')}/10"
        )
        print(f"       {md['site']}  |  {md['date']}  |  {md['season']}  |  {md['type']}")
        print(wrap(excerpt(c.get_content()), indent="       "))
        print()

    print(wrap(f"semantic order:  {' > '.join(eligible)}", indent="    "))
    print(wrap(f"after re-rank:   {' > '.join(reranked)}", indent="    "))
    if eligible != reranked:
        print(wrap(
            "Re-ranking changed the order, so the top 3 is not the top 3 by "
            "similarity alone.",
            indent="    ",
        ))


def print_retrieval(result) -> None:
    block(2, "RETRIEVAL TRACE")

    sub(
        f"Stage 1, semantic search over {result.corpus_size} entries, "
        f"top_k = {CANDIDATE_K}"
    )
    print_candidates(result)

    sub("Stage 2, composite re-rank")
    print_rerank(result)

    sub(f"Stage 3, final {TOP_K} handed to the planner")
    print_selection(result)


# --------------------------------------------------------------------------
# BLOCK 3, output comparison
# --------------------------------------------------------------------------
def print_llm(number: int, condition: str) -> None:
    path = LLM_DIR / f"s{number}_{condition}.md"
    if not path.exists():
        return
    print()
    print(f"      planner LLM (Claude), replayed from prompts/s{number}_{condition}.txt")
    print()
    for line in path.read_text().strip().splitlines():
        if not line.strip():
            print()
        elif line.startswith("- "):
            print(wrap(line, indent="        ", hang="          "))
        else:
            print(wrap(line, indent="      ", hang="        "))


def print_recommendation(plan: Plan, cited: list[str] | None = None) -> None:
    print()
    print(kv("recommendation", plan.headline, indent=6, label_w=16))
    print(kv("time window", plan.window, indent=6, label_w=16))
    print(kv("confidence", plan.confidence, indent=6, label_w=16))
    print()
    print("      reasoning")
    for bullet in plan.bullets:
        print(wrap(f"- {bullet}", indent="        ", hang="          "))
    if plan.cautions:
        print()
        print("      cautions")
        for caution in plan.cautions:
            print(wrap(f"- {caution}", indent="        ", hang="          "))
    if cited:
        print()
        print("      driven by these retrieved entries")
        for citation in cited:
            print(wrap(citation, indent="        ", hang="          "))


def print_comparison(
    before: Plan, after: Plan, result, number: int, llm: bool
) -> None:
    block(3, "OUTPUT COMPARISON")

    sub("(a) WITHOUT RETRIEVAL, no long-term memory consulted")
    print_recommendation(before)
    if llm:
        print_llm(number, "a")

    sub("(b) WITH RETRIEVAL, conditioned on the entries selected above")
    print_recommendation(after, cited=after.citations)
    if llm:
        print_llm(number, "b")

    evidence = ", ".join(c.entry_id for c in result.kept) or "none"
    sub("DIFFERENCE")
    print()
    print(f"      {'':<16}{'(a) without':<24}(b) with")
    print(f"      {'-' * 62}")
    print(f"      {'time window':<16}{before.window:<24}{after.window}")
    print(
        f"      {'confidence':<16}{conf_level(before.confidence):<24}"
        f"{conf_level(after.confidence)}"
    )
    print(f"      {'basis':<16}{'generic defaults':<24}{evidence}")
    print()
    if before.window != after.window:
        print(wrap(
            f"The recommended window moved from {before.window} to "
            f"{after.window}. The reasoning changed with it: (a) argues from "
            f"generic defaults, (b) argues from {evidence} and names them.",
            indent="      ",
        ))
    else:
        print(wrap(
            "The window did not move. Retrieval returned nothing that cleared "
            "the cutoff, so (b) falls back to (a).",
            indent="      ",
        ))


# --------------------------------------------------------------------------
# BLOCK 4, cold start
# --------------------------------------------------------------------------
def print_cold_start(
    ctx: PlanningContext, result, after: Plan, number: int, llm: bool
) -> None:
    block(4, "COLD START / THRESHOLD DEMO")

    sub("Planning context")
    print(kv("date", ctx.date_label or ctx.day_of_week))
    print(kv("season", ctx.season))
    print(kv("free window", ctx.window))
    print(kv("activity", ctx.activity_type.replace("_", " ")))
    print(kv("site", ctx.site))

    sub("Query string sent to the retriever")
    print()
    print(wrap(f'"{result.query}"', indent="    "))

    sub(f"Retrieved candidates, all scored against a {result.cutoff:.3f} cutoff")
    print()
    print(
        f"    {'#':<3}{'entry':<7}{'site':<29}{'date':<12}"
        f"{'similarity':>11}{'status':>8}"
    )
    print(f"    {'-' * 70}")
    for i, c in enumerate(result.candidates, start=1):
        md = c.metadata
        print(
            f"    {i:<3}{c.entry_id:<7}{truncate(md['site'], 28):<29}"
            f"{md['date']:<12}{c.similarity:>11.3f}"
            f"{'below' if not c.passed_cutoff else 'pass':>8}"
        )

    best = max(c.similarity for c in result.candidates) if result.candidates else 0.0
    sub("Threshold decision")
    print()
    print(kv("best similarity", f"{best:.3f}", label_w=18))
    print(kv("cutoff", f"{result.cutoff:.3f}", label_w=18))
    print(kv("entries clearing", f"{len(result.kept)}", label_w=18))
    print(kv("outcome", "NO RELEVANT HISTORY, cold-start fallback", label_w=18))
    print()
    print(wrap(
        "Nothing reached the re-ranking stage, so the composite score never "
        "ran. The agent returns no history rather than serving the closest "
        "available note as if it were experience.",
        indent="    ",
    ))

    sub("Fallback recommendation, unpersonalized scoring")
    print_recommendation(after)
    if llm:
        print_llm(number, "b")

    print()
    print(wrap(
        f"Confidence is reported as "
        f"'{conf_level(after.confidence)}', and the basis line states the "
        f"cold start outright: {after.basis}",
        indent="    ",
    ))


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
MAIN = PlanningContext(
    label="Mid-May Saturday, free 06:00-14:00, birding at Jamaica Bay",
    season="spring",
    activity_type="birding",
    site="Jamaica Bay Wildlife Refuge",
    time_of_day="morning",
    day_of_week="Saturday",
    window="06:00-14:00",
    date_label="Saturday, 16 May 2026",
)

# Each cold-start case keeps a stable scenario number, because prompts/ and
# llm_output/ are keyed by it: kayaking is s2, backpacking is s3.
COLD_START_NUMBER = {"kayaking": 2, "backpacking": 3}

COLD_STARTS = {
    # Nothing in the log is tagged kayaking; the nearest notes are hikes and
    # outdoor events, and none of them clears the cutoff.
    "kayaking": PlanningContext(
        label="July Saturday, free 08:00-13:00, kayaking at Sebago Canoe Club",
        season="summer",
        activity_type="kayaking",
        site="Sebago Canoe Club",
        time_of_day="morning",
        day_of_week="Saturday",
        window="08:00-13:00",
        date_label="Saturday, 11 July 2026",
    ),
    # A logged activity type used for a different kind of outing: the log has
    # day hikes, this is a multi-day backpacking trip.
    "backpacking": PlanningContext(
        label="October Saturday, free 06:00-20:00, Catskills backpacking",
        season="fall",
        activity_type="hike",
        site="Catskills overnight backpacking trip",
        time_of_day="overnight",
        day_of_week="Saturday",
        window="06:00-20:00",
        date_label="Saturday, 17 October 2026",
    ),
}


def emit_prompts(ctx: PlanningContext, result, number: int) -> None:
    PROMPT_DIR.mkdir(exist_ok=True)
    (PROMPT_DIR / f"s{number}_a.txt").write_text(build_baseline_prompt(ctx))
    (PROMPT_DIR / f"s{number}_b.txt").write_text(build_augmented_prompt(ctx, result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="re-embed the store")
    parser.add_argument(
        "--llm", action="store_true", help="include saved Claude completions"
    )
    parser.add_argument(
        "--emit-prompts", action="store_true", help="write planner prompts to prompts/"
    )
    parser.add_argument(
        "--cold-start",
        choices=sorted(COLD_STARTS),
        default="kayaking",
        help="which cold-start case to use for block 4",
    )
    args = parser.parse_args()

    memory = ExcursionMemory.build(rebuild=args.rebuild)
    w = WEIGHTS

    print("=" * WIDTH)
    print("EXCURSION AGENT, SEMANTIC MEMORY OVER PAST EXCURSION FEEDBACK")
    print("=" * WIDTH)
    print()
    print(wrap(
        "Retrieval covers one thing: the free-text notes from past excursions. "
        "Weather, eBird, transit and calendar are structured API calls and are "
        "not part of this layer."
    ))
    print()
    print(kv("entries indexed", str(memory.collection.count()), indent=2, label_w=18))
    print(kv("chunking", "one entry = one node, no splitting", indent=2, label_w=18))
    print(kv("embedding model", "all-MiniLM-L6-v2 (local, no API key)", indent=2, label_w=18))
    print(kv("vector store", "Chroma, persistent, cosine space", indent=2, label_w=18))
    print(kv("pre-filter", "none, semantic search over the full corpus", indent=2, label_w=18))
    print(kv("candidates", f"{CANDIDATE_K}, re-ranked down to {TOP_K}", indent=2, label_w=18))
    print(kv(
        "weights",
        f"semantic {w['similarity']}, season {w['season']}, "
        f"type {w['type']}, recency {w['recency']}",
        indent=2,
        label_w=18,
    ))
    print(kv("similarity cutoff", f"{SIMILARITY_CUTOFF:.3f}", indent=2, label_w=18))

    # -- blocks 1 to 3: the scenario with history behind it ----------------
    result = memory.retrieve(MAIN)
    before = baseline_plan(MAIN)
    after = memory_informed_plan(MAIN, result)

    print_setup(MAIN, result, number=1)
    print_retrieval(result)
    print_comparison(before, after, result, number=1, llm=args.llm)

    # -- block 4: the scenario with nothing behind it ----------------------
    cold_ctx = COLD_STARTS[args.cold_start]
    cold_number = COLD_START_NUMBER[args.cold_start]
    cold_result = memory.retrieve(cold_ctx)
    cold_after = memory_informed_plan(cold_ctx, cold_result)

    print_cold_start(cold_ctx, cold_result, cold_after, cold_number, llm=args.llm)

    if args.emit_prompts:
        emit_prompts(MAIN, result, 1)
        emit_prompts(cold_ctx, cold_result, cold_number)
        print()
        print(wrap("prompts written to prompts/", indent="  "))

    print()


if __name__ == "__main__":
    main()
