"""Natural-language request -> planning intent, with guardrails.

The Ask surface accepts free text ("what should I do saturday morning?")
and must decide: plan a DAY, plan a WEEK, ask a clarifying question, or
politely decline anything that isn't excursion planning. Cheap and
deterministic first: ISO dates, "september 7th"-style month-day dates,
today/tomorrow, weekday names and the word "week" are parsed in code with
zero LLM calls, and the fast path refuses to answer at all when the text
carries date words it did not fully parse (a bare month, a lone ordinal,
a numeric date). Everything else goes to one structured LLM call, and its
output is still validated in code (the model never gets to schedule
outside the forecast horizon).
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

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# "september 7", "sept 7th", "jan 5" (forward order; anything fancier is
# the LLM's job).
MONTH_DAY_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b")

# Date-ish text the deterministic branches below do NOT understand: a bare
# month name ("the week of september..."), a lone ordinal ("the 7th"), or
# a numeric date ("9/7"). Seeing one of these after the parsers above have
# already missed means the fast path must NOT guess from the leftover
# words; the LLM (with code-side validation after it) handles it. This is
# the guardrail that keeps "plan the week of september 7th" from being
# silently anchored to the current week just because it contains "week".
# ("may" only counts followed by a digit; it is too common as a verb.)
DATE_HINT_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\b\.?"
    r"|\bmay\s+\d"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b"
    r"|\b\d{1,2}[/.]\d{1,2}\b")


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
    """Nearest upcoming weekday; "next <day>" always lands in the week
    after the nearest one (matching how people say it)."""
    target = WEEKDAYS.index(name)
    delta = (target - today.weekday()) % 7 or 7
    if name == WEEKDAYS[today.weekday()] and not next_week:
        return today
    return today + timedelta(days=delta + (7 if next_week else 0))


def _month_day_date(month: int, day: int, today: date) -> date | None:
    """Next occurrence of a month/day with no year given: this year if it
    has not passed, otherwise next year (asking for "jan 5" in December
    means the coming January). The horizon validation still applies."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None  # e.g. "february 30"; let the LLM ask about it
        if candidate >= today:
            return candidate
    return None


def quick_parse(message: str, today: date) -> Intent | None:
    """Deterministic fast path; returns None when the text is fuzzy.

    The rule that keeps this path safe: it may only answer when it
    understood the WHOLE date phrase. If the text carries date-ish tokens
    the parsers here did not consume, it must defer to the LLM instead of
    guessing from the leftover words ("plan the week of september 7th"
    must never be anchored to today's week just because it says "week")."""
    text = message.lower().strip()

    wants_week = bool(re.search(r"\bweek(ly)?\b", text)) and "weekend" not in text

    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso:
        return Intent(kind="week" if wants_week else "day", date=iso.group(1))

    month_day = MONTH_DAY_RE.search(text)
    if month_day:
        target = _month_day_date(MONTHS[month_day.group(1)[:3]],
                                 int(month_day.group(2)), today)
        if target is not None:
            return Intent(kind="week" if wants_week else "day",
                          date=target.isoformat())

    if DATE_HINT_RE.search(text):
        return None  # date-ish text this parser didn't understand -> LLM

    # "week" outranks "today"/"tomorrow": "plan my week starting tomorrow"
    # is a weekly request anchored there, not a single-day plan.
    if wants_week:
        if "tomorrow" in text:
            anchor = today + timedelta(days=1)
        elif "next" in text:
            anchor = today + timedelta(days=7)
        else:
            anchor = today
        return Intent(kind="week", date=anchor.isoformat())
    if "today" in text:
        return Intent(kind="day", date=today.isoformat())
    if "tomorrow" in text:
        return Intent(kind="day", date=(today + timedelta(days=1)).isoformat())
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
                      reply=(f"I can only plan with a real weather forecast, which reaches {hi}. "
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
    # Model text goes straight to the UI: hold it to the same no-dash house
    # style as our own strings.
    result.obj.reply = (result.obj.reply.replace(" — ", ", ")
                        .replace("—", ", ").replace(" – ", ", ")
                        .replace(" -- ", ", "))
    return validate(result.obj, today)
