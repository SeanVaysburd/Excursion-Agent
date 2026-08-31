"""Ask-surface guardrails, deterministic paths only (no LLM, no network).

quick_parse handles the unambiguous phrasings in code; validate() is the
horizon clamp that even the LLM path cannot get around.
"""

from __future__ import annotations

from datetime import date, timedelta

from src import config
from src.agents.intent import Intent, quick_parse, validate

TODAY = date(2026, 8, 31)  # a Monday


def test_iso_date_is_a_day_request():
    intent = quick_parse("plan 2026-09-05 for me", TODAY)
    assert intent.kind == "day" and intent.date == "2026-09-05"


def test_today_and_tomorrow():
    assert quick_parse("what about today?", TODAY).date == "2026-08-31"
    assert quick_parse("tomorrow pls", TODAY).date == "2026-09-01"


def test_weekday_lands_on_next_occurrence():
    intent = quick_parse("saturday morning ideas", TODAY)
    assert intent.kind == "day" and intent.date == "2026-09-05"


def test_next_weekday_skips_a_week():
    intent = quick_parse("next saturday?", TODAY)
    assert intent.date == "2026-09-12"


def test_week_and_next_week():
    assert quick_parse("plan my week", TODAY).kind == "week"
    assert quick_parse("next week please", TODAY).date == "2026-09-07"


def test_weekend_is_ambiguous():
    assert quick_parse("this weekend", TODAY).kind == "clarify"


def test_week_of_a_named_date_uses_that_date():
    # The reported bug: this used to anchor to TODAY's week because the
    # fast path stopped at the word "week" and never read the date.
    intent = quick_parse("can you plan the week of september 7th", TODAY)
    assert intent.kind == "week" and intent.date == "2026-09-07"


def test_month_day_is_a_day_request():
    assert quick_parse("plan september 12 for me", TODAY).date == "2026-09-12"
    assert quick_parse("sept 3rd?", TODAY).date == "2026-09-03"


def test_month_day_beats_the_weekday_word():
    assert quick_parse("saturday september 12", TODAY).date == "2026-09-12"


def test_past_month_day_rolls_to_next_year():
    assert quick_parse("plan jan 5", TODAY).date == "2027-01-05"


def test_unconsumed_date_hints_defer_to_the_llm():
    assert quick_parse("plan the week of the 7th", TODAY) is None
    assert quick_parse("anything on 9/7?", TODAY) is None
    assert quick_parse("the week of september", TODAY) is None


def test_fuzzy_text_falls_through_to_the_llm_path():
    assert quick_parse("got any ideas for me?", TODAY) is None


def test_validate_clamps_past_dates():
    intent = validate(Intent(kind="day", date="2026-08-01"), TODAY)
    assert intent.kind == "clarify"


def test_validate_clamps_beyond_forecast_horizon():
    beyond = (TODAY + timedelta(days=config.FORECAST_DAYS)).isoformat()
    intent = validate(Intent(kind="day", date=beyond), TODAY)
    assert intent.kind == "clarify"
    edge = (TODAY + timedelta(days=config.FORECAST_DAYS - 1)).isoformat()
    assert validate(Intent(kind="day", date=edge), TODAY).kind == "day"


def test_validate_rejects_unreadable_dates():
    assert validate(Intent(kind="day", date="not-a-date"), TODAY).kind == "clarify"
