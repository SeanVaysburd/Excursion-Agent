"""Natural-language request -> planning intent, with guardrails.

The Ask surface accepts free text ("what should I do saturday morning?")
and must decide: plan a DAY, plan a WEEK, ask a clarifying question, or
politely decline anything that isn't excursion planning. Cheap and
deterministic first: ISO dates, today/tomorrow, weekday names and the
word "week" are parsed in code with zero LLM calls. Only genuinely fuzzy
text goes to one structured LLM call, and its output is still validated
in code (the model never gets to schedule outside the forecast horizon).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from src import config
from src.agents.llm import LLMAdapter
from src.tools.base import RunContext

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]


class Intent(BaseModel):
    kind: Literal["day", "week", "clarify", "unsupported"]
    date: str | None = None  # ISO, for day/week kinds
    reply: str = Field(default="", description="One short sentence to show the user.")


INTENT_PROMPT = """\
You route requests for a personal excursion planner (birding, hikes, city
events, museums in NYC). Today is {today} ({weekday}).

Decide what the user wants:
- kind "day" with an ISO date: they want suggestions for one specific day.
- kind "week" with an ISO date inside that week: they want a weekly plan.
- kind "clarify": it is a planning request but the day is ambiguous. Put a
  short clarifying question in reply.
- kind "unsupported": it is not about planning free time (coding help,
  general chat, anything else). Put one polite sentence in reply saying
  this app only plans excursions.

Rules: never invent a date that is not implied. "weekend" without a day
means clarify (Saturday or Sunday?). Dates in the past mean clarify.

USER REQUEST: {message}
"""


def _horizon(today: date) -> tuple[date, date]:
    return today, today + timedelta(days=config.FORECAST_DAYS - 1)


def _weekday_date(name: str, today: date, next_week: bool) -> date:
    target = WEEKDAYS.index(name)
    delta = (target - today.weekday()) % 7
    if delta == 0 and not next_week:
        return today
    if delta == 0 or next_week:
        delta = delta or 7
        if next_week and delta < 7:
            delta += 0 if delta else 7
    return today + timedelta(days=delta or 7)


def quick_parse(message: str, today: date) -> Intent | None:
    """Deterministic fast path; returns None when the text is fuzzy."""
    text = message.lower().strip()

    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    wants_week = bool(re.search(r"\bweek(ly)?\b", text)) and "weekend" not in text

    if iso:
        return Intent(kind="week" if wants_week else "day", date=iso.group(1))
    if "today" in text:
        return Intent(kind="day", date=today.isoformat())
    if "tomorrow" in text:
        return Intent(kind="day", date=(today + timedelta(days=1)).isoformat())
    if wants_week:
        anchor = today + timedelta(days=7) if "next" in text else today
        return Intent(kind="week", date=anchor.isoformat())
    if "weekend" in text:
        return Intent(kind="clarify",
                      reply="Saturday or Sunday? Tell me which day and I'll plan it.")
    for name in WEEKDAYS:
        if re.search(rf"\b{name}\b", text):
            return Intent(kind="day",
                          date=_weekday_date(name, today, "next" in text).isoformat())
    return None


def validate(intent: Intent, today: date) -> Intent:
    """Code-side guardrail: the model never schedules outside the horizon."""
    if intent.kind not in ("day", "week") or not intent.date:
        return intent
    try:
        target = date.fromisoformat(intent.date)
    except ValueError:
        return Intent(kind="clarify", reply="I could not read that date. Which day do you mean?")
    lo, hi = _horizon(today)
    if target < lo:
        return Intent(kind="clarify",
                      reply=f"{intent.date} is in the past. Which upcoming day should I plan?")
    if target > hi:
        return Intent(kind="clarify",
                      reply=(f"I can only plan with a real forecast, which reaches {hi}. "
                             f"Pick a day on or before then."))
    return intent


async def parse_request(
    adapter: LLMAdapter, ctx: RunContext, message: str, today: date
) -> Intent:
    quick = quick_parse(message, today)
    if quick is not None:
        return validate(quick, today)

    prompt = INTENT_PROMPT.format(
        today=today.isoformat(), weekday=today.strftime("%A"), message=message[:400])
    result = await adapter.structured(prompt, Intent, purpose="intent", ctx=ctx)
    if result.obj is None:
        return Intent(kind="clarify",
                      reply="I did not catch that. Which day should I plan?")
    return validate(result.obj, today)
