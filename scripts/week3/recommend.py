"""
The part of the agent that turns a plan request into a recommendation.

This is deliberately rule-based rather than an LLM call: the checkpoint is
about the retrieval layer, and a local rule set keeps the demo key-free and
deterministic. Everything here is a stand-in for the planner prompt --
swapping in a real model means passing the same retrieved nodes as context
instead of pattern-matching them. What the demo needs to show is the delta
between planning with memory and planning without it, and that delta is
visible either way.

Two entry points:
    baseline_plan()         , no memory, generic defaults
    memory_informed_plan()  , same request, conditioned on retrieved history
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from llama_index.core.schema import NodeWithScore

from src.memory.retrieval import BAD_RATING, GOOD_RATING, PlanningContext, RetrievalResult


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------
@dataclass
class Plan:
    basis: str  # what the plan was built from, shown in the trace
    headline: str
    window: str
    bullets: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    confidence: str = "low"


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def _split_window(window: str) -> tuple[datetime, datetime]:
    start, end = window.split("-")
    fmt = "%H:%M"
    return datetime.strptime(start, fmt), datetime.strptime(end, fmt)


def _fmt(t: datetime) -> str:
    return t.strftime("%H:%M")


def _shift(t: datetime, hours: float) -> datetime:
    return t + timedelta(hours=hours)


# --------------------------------------------------------------------------
# Signals: what a retrieved note is actually telling us
# --------------------------------------------------------------------------
# Keyword matching is crude, and it is crude on purpose, it keeps the
# reasoning inspectable, which is the point of the trace. A real planner hands
# these notes to the model and lets it read them.
SIGNALS: dict[str, tuple[str, ...]] = {
    "early": ("early", "6am", "6:15am", "dawn", "sunrise", "overnight"),
    "midday": ("midday", "middle of the day"),
    "crowded": (
        "crowd",
        "packed",
        "busy",
        "shoulder to shoulder",
        "mobbed",
        "heavily birded",
        "line was long",
        "loud",
    ),
    "quiet": ("quiet", "nobody", "no one", "almost no", "calm", "low crowds"),
    "tide": ("tide", "flats"),
    "heat": ("hot", "humid", "buggy"),
    "wind": ("wind",),
    "access": ("gates open", "ferry", "transit", "bus over", "subway", "long walk"),
}


def signals_for(node: NodeWithScore) -> set[str]:
    text = node.get_content().lower()
    return {name for name, cues in SIGNALS.items() if any(c in text for c in cues)}


def _cite(node: NodeWithScore) -> str:
    md = node.metadata
    return f"{md['entry_id']} ({md['date']}, {md['site']}, rated {md['rating']}/10)"


# --------------------------------------------------------------------------
# (a) No memory
# --------------------------------------------------------------------------
GENERIC_OPENERS: dict[str, str] = {
    "birding": "Head out mid-morning once the day has warmed up",
    "hike": "Start late morning and walk through the middle of the day",
    "museum": "Arrive after opening and plan a long visit",
    "outdoor_event": "Arrive around midday when the event is in full swing",
}

GENERIC_CAUTIONS: dict[str, tuple[str, ...]] = {
    "birding": ("Bring binoculars and check the forecast for rain.",),
    "hike": ("Bring water and check the forecast.",),
    "museum": ("Check opening hours and ticket prices.",),
    "outdoor_event": ("Check the event schedule and how to get there.",),
}


def baseline_plan(ctx: PlanningContext) -> Plan:
    """The recommendation the agent gives with no long-term memory.

    Structured feeds could still fill this in, weather, transit, eBird --
    but none of them know how *this user's* previous trips went. Without that,
    the only honest default is the middle of the free window.
    """
    start, end = _split_window(ctx.window)
    activity = ctx.activity_type.replace("_", " ")

    opener = GENERIC_OPENERS.get(
        ctx.activity_type, f"Plan a {activity} outing in the free window"
    )
    # Nothing distinguishes one part of the window from another, so centre a
    # default-length outing in it and call that the recommendation.
    free_hours = (end - start).total_seconds() / 3600
    hours = min(4.0, free_hours)
    plan_start = _shift(start, (free_hours - hours) / 2)
    plan_end = _shift(plan_start, hours)

    return Plan(
        basis="generic defaults, no long-term memory consulted",
        headline=f"{opener} at {ctx.site}.",
        window=f"{_fmt(plan_start)}-{_fmt(plan_end)}",
        bullets=[
            f"{activity.capitalize()} at {ctx.site} for about "
            f"{hours:.0f} hours.",
            f"Anywhere in the {ctx.window} window works; "
            f"{_fmt(plan_start)} is a reasonable default start.",
            "Check weather and transit before leaving.",
        ],
        cautions=list(
            GENERIC_CAUTIONS.get(ctx.activity_type, ("Check conditions before you go.",))
        ),
        confidence="low, nothing here is specific to you or to this site",
    )


# --------------------------------------------------------------------------
# (b) With memory
# --------------------------------------------------------------------------
def memory_informed_plan(ctx: PlanningContext, result: RetrievalResult) -> Plan:
    """The same request, conditioned on what retrieval brought back.

    Falls straight back to baseline_plan() when memory is empty, a cold
    start should look like the unpersonalized system, not like a confident
    system with a thin excuse.
    """
    if not result.has_history:
        plan = baseline_plan(ctx)
        plan.basis = f"no relevant history ({result.cold_start_reason}), unpersonalized fallback"
        plan.cautions.append(
            "First logged outing of this kind. Whatever happens, log it, "
            "it is what makes the next one better."
        )
        return plan

    worked = [n for n in result.kept if n.metadata["rating"] >= GOOD_RATING]
    failed = [n for n in result.kept if n.metadata["rating"] <= BAD_RATING]

    sig_worked: set[str] = set().union(*(signals_for(n) for n in worked)) if worked else set()
    sig_failed: set[str] = set().union(*(signals_for(n) for n in failed)) if failed else set()

    start, end = _split_window(ctx.window)
    bullets: list[str] = []
    cautions: list[str] = []

    #, timing ---------------------------------------------------------
    early_pays_off = "early" in sig_worked
    late_backfires = bool(sig_failed & {"midday", "crowded"})

    if early_pays_off or late_backfires:
        plan_start = start
        plan_end = _shift(start, 3.5)
        headline = (
            f"Go early: be at {ctx.site} for {_fmt(plan_start)}, "
            f"and treat {_fmt(plan_end)} as the soft end of the good part."
        )
        if early_pays_off:
            good = sorted(worked, key=lambda n: -n.metadata["rating"])[0]
            bullets.append(
                f"Your best {ctx.season} outings here started at first light "
                f"-- {_cite(good)} is the pattern to repeat."
            )
        if late_backfires:
            bad = sorted(failed, key=lambda n: n.metadata["rating"])[0]
            bullets.append(
                f"The failure mode is the late start, not the site: "
                f"{_cite(bad)} was the same place in the same season."
            )
        bullets.append(
            f"That leaves {_fmt(plan_end)}-{_fmt(end)} of the free window. "
            f"Spend it somewhere quieter or head home, do not wait it out here."
        )
    else:
        plan_start = _shift(start, 1)
        plan_end = min(_shift(plan_start, 4), end)
        headline = f"{ctx.site} looks workable anywhere in the free window."
        bullets.append("Nothing in your history argues for a specific start time.")

    #, conditions worth a warning --------------------------------------
    if "crowded" in sig_failed or "crowded" in sig_worked:
        cautions.append(
            "Crowds are the recurring complaint at this site, the early "
            "window is what buys you the quiet, not luck."
        )
    if "tide" in (sig_worked | sig_failed):
        cautions.append(
            "Tide has decided past trips in this area. Check the tide table "
            "and aim for a falling tide."
        )
    if "heat" in sig_failed:
        cautions.append("Heat and bugs ruined a past trip in this bucket. Start cool, carry water.")
    if "wind" in (sig_worked | sig_failed):
        cautions.append("Wind has suppressed activity here before, check the forecast.")
    if "access" in (sig_worked | sig_failed):
        cautions.append("Confirm gate hours and transit times; access has bitten before.")

    ratings = [n.metadata["rating"] for n in result.kept]
    same_site = [n for n in result.kept if n.metadata["site"] == ctx.site]
    confidence = (
        f"{'high' if len(same_site) >= 2 else 'moderate'}, "
        f"{len(result.kept)} matched entr{'y' if len(result.kept) == 1 else 'ies'}, "
        f"{len(same_site)} at this exact site, ratings {min(ratings)}-{max(ratings)}/10"
    )

    return Plan(
        basis=f"{len(result.kept)} retrieved excursion(s) above the "
        f"{result.cutoff:.2f} similarity cutoff",
        headline=headline,
        window=f"{_fmt(plan_start)}-{_fmt(plan_end)}",
        bullets=bullets,
        cautions=cautions,
        citations=[_cite(n) for n in result.kept],
        confidence=confidence,
    )
