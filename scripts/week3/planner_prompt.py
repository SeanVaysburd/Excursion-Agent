"""
The prompts the planner LLM actually receives.

This is the real output of a RAG system: not the answer, but the augmented
prompt. Two builders, matching the two demo conditions.

    build_baseline_prompt()   -- the request alone, no memory
    build_augmented_prompt()  -- the same request plus retrieved history

The only difference between them is the RELEVANT PAST EXCURSIONS block. That
is the whole experiment, so nothing else is allowed to vary: same instructions,
same output contract, same request.

    python demo.py --emit-prompts     # writes prompts/ for inspection
"""

from __future__ import annotations

from src.memory.retrieval import PlanningContext, RetrievalResult

OUTPUT_CONTRACT = """\
Answer in exactly this shape, nothing before or after it:

HEADLINE: one sentence telling me what to do.
WHEN: a concrete time range inside my free window.
CONFIDENCE: low | moderate | high, then " -- " and a short justification.
WHY:
- two to four bullets of reasoning
CAUTIONS:
- zero to three bullets, only if warranted
BASIS: one line naming what you reasoned from.

Rules:
- Be concrete about times. No hedging across the whole window.
- Do not invent facts about the site, the weather, or the wildlife.
- If you cite a past excursion, use its id (e.g. e01) and say what it showed."""


def _request_block(ctx: PlanningContext) -> str:
    activity = ctx.activity_type.replace("_", " ")
    return (
        f"REQUEST\n"
        f"  day:        {ctx.day_of_week}\n"
        f"  season:     {ctx.season}\n"
        f"  free time:  {ctx.window}\n"
        f"  activity:   {activity}\n"
        f"  site:       {ctx.site}\n"
    )


def build_baseline_prompt(ctx: PlanningContext) -> str:
    """Condition (a): no long-term memory. Must not mention that memory exists."""
    return f"""\
You are the planning component of a personal excursion agent. Recommend how \
the user should spend their free time.

{_request_block(ctx)}
You have no record of this user's past excursions. Plan from general knowledge.

{OUTPUT_CONTRACT}
"""


def build_augmented_prompt(ctx: PlanningContext, result: RetrievalResult) -> str:
    """Condition (b): the same request, plus whatever retrieval returned."""
    if result.has_history:
        entries = []
        for c in result.kept:
            md = c.metadata
            entries.append(
                f"  [{md['entry_id']}] {md['date']} | {md['site']} | "
                f"rated {md['rating']}/10 | similarity {c.similarity:.3f} | "
                f"composite {c.composite:.3f}\n"
                f"      \"{c.get_content()}\""
            )
        memory_block = (
            "RELEVANT PAST EXCURSIONS (retrieved from this user's own notes by "
            "semantic search, then re-ranked on season, activity type and "
            "recency)\n" + "\n".join(entries)
        )
        guidance = (
            "These are the user's own notes. Weight them heavily -- they beat "
            "general knowledge about this site. Note that a high similarity "
            "score means the entry is RELEVANT, not that the trip went well; "
            "the rating tells you that. Learn from the bad ones too."
        )
    else:
        memory_block = (
            "RELEVANT PAST EXCURSIONS\n"
            f"  none -- {result.cold_start_reason}"
        )
        guidance = (
            "Memory returned nothing above the relevance threshold, so you are "
            "planning this one blind. Say so plainly in BASIS and set "
            "CONFIDENCE to low. Do not pretend to personal knowledge you do "
            "not have, and do not pad the answer to hide the gap."
        )

    return f"""\
You are the planning component of a personal excursion agent. Recommend how \
the user should spend their free time.

{_request_block(ctx)}
{memory_block}

{guidance}

{OUTPUT_CONTRACT}
"""
