"""Deterministic synthetic-week generator for data/calendar.ics.

The committed sample must stay inside the live forecast horizon (~16
days), so demo.py regenerates the SAME structure onto the current week
when the file goes stale, always with a printed notice. Structure
(labeled synthetic; RRULE deliberately unused, the parser doesn't
expand it):

  Mon-Fri  09:00-17:30  Work (hard)
  Tue      18:00-20:00  Evening class (hard)
  Sat      10:30-11:30  Brunch with Alex (tentative)   <- soft via SUMMARY
  Sat      14:00-20:00  Family afternoon (hard)        <- S1's 06:00-14:00 window
  Sun      08:00-09:30  Volunteer shift                <- soft via X-SOFT:true
  Sun      18:00-21:00  Dinner at parents' (hard)

Usage:
  python -m scripts.make_sample_calendar [--week-start YYYY-MM-DD] [--out PATH]
  python -m scripts.make_sample_calendar --fully-blocked  (escalation fixture)
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from pathlib import Path

from icalendar import Calendar, Event

from src import config

PRODID = "-//excursion-agent capstone//synthetic sample week//EN"


def _event(day: date, start: time, end: time, summary: str, soft_x: bool = False) -> Event:
    event = Event()
    event.add("UID", f"sample-{day.isoformat()}-{start:%H%M}@excursion-agent")
    event.add("DTSTAMP", datetime(2026, 1, 1, tzinfo=config.TZ))  # deterministic
    event.add("SUMMARY", summary)
    event.add("DTSTART", datetime.combine(day, start, tzinfo=config.TZ))
    event.add("DTEND", datetime.combine(day, end, tzinfo=config.TZ))
    if soft_x:
        event.add("X-SOFT", "true")
    return event


def build_week(week_start: date) -> Calendar:
    assert week_start.weekday() == 0, "week_start must be a Monday"
    calendar = Calendar()
    calendar.add("PRODID", PRODID)
    calendar.add("VERSION", "2.0")
    days = [week_start + timedelta(days=i) for i in range(7)]
    for weekday_index in range(5):  # Mon-Fri work
        calendar.add_component(
            _event(days[weekday_index], time(9, 0), time(17, 30), "Work")
        )
    calendar.add_component(_event(days[1], time(18, 0), time(20, 0), "Evening class"))
    calendar.add_component(
        _event(days[5], time(10, 30), time(11, 30), "Brunch with Alex (tentative)")
    )
    calendar.add_component(_event(days[5], time(14, 0), time(20, 0), "Family afternoon"))
    calendar.add_component(
        _event(days[6], time(8, 0), time(9, 30), "Volunteer shift", soft_x=True)
    )
    calendar.add_component(_event(days[6], time(18, 0), time(21, 0), "Dinner at parents'"))
    return calendar


def build_fully_blocked(week_start: date) -> Calendar:
    calendar = Calendar()
    calendar.add("PRODID", PRODID + " fully-blocked fixture")
    calendar.add("VERSION", "2.0")
    for i in range(7):
        day = week_start + timedelta(days=i)
        calendar.add_component(
            _event(day, time(config.WAKING_HOURS[0], 0),
                   time(config.WAKING_HOURS[1], 0), "Blocked (escalation fixture)")
        )
    return calendar


def build_weeks(first_monday: date, weeks: int = 5) -> Calendar:
    """Several deterministic weeks with varied availability, so different
    questions in the Ask tab hit genuinely different free windows:
      week 0: the standard sample week
      week 1: class moves to Thursday; Wednesday afternoon off
      week 2: Saturday fully booked (family trip); Sunday wide open
      week 3: Friday off; Sunday brunch is soft
      week 4+: standard again
    """
    assert first_monday.weekday() == 0
    calendar = Calendar()
    calendar.add("PRODID", PRODID + f" {weeks} weeks")
    calendar.add("VERSION", "2.0")
    for w in range(weeks):
        days = [first_monday + timedelta(days=w * 7 + i) for i in range(7)]
        variant = w % 4
        for i in range(5):
            if variant == 1 and i == 2:  # Wednesday: half day
                calendar.add_component(_event(days[i], time(9, 0), time(13, 0), "Work"))
            elif variant == 3 and i == 4:  # Friday off
                continue
            else:
                calendar.add_component(_event(days[i], time(9, 0), time(17, 30), "Work"))
        class_day = 3 if variant == 1 else 1
        calendar.add_component(_event(days[class_day], time(18, 0), time(20, 0), "Evening class"))
        if variant == 2:
            calendar.add_component(_event(days[5], time(6, 0), time(22, 0), "Family trip upstate"))
        else:
            calendar.add_component(
                _event(days[5], time(10, 30), time(11, 30), "Brunch with Alex (tentative)"))
            calendar.add_component(_event(days[5], time(14, 0), time(20, 0), "Family afternoon"))
        if variant == 3:
            calendar.add_component(
                _event(days[6], time(10, 0), time(11, 30), "Brunch with Sam (tentative)"))
        elif variant != 2:
            calendar.add_component(
                _event(days[6], time(8, 0), time(9, 30), "Volunteer shift", soft_x=True))
        if variant not in (2,):
            calendar.add_component(_event(days[6], time(18, 0), time(21, 0), "Dinner at parents'"))
    return calendar


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def write(calendar: Calendar, out: Path) -> None:
    out.write_bytes(calendar.to_ical())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week-start", type=date.fromisoformat, default=None)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "calendar.ics")
    parser.add_argument("--fully-blocked", action="store_true")
    parser.add_argument("--weeks", type=int, default=5)
    args = parser.parse_args()

    week_start = args.week_start or monday_of(date.today() + timedelta(days=7))
    if week_start.weekday() != 0:
        week_start = monday_of(week_start)

    if args.fully_blocked:
        out = (args.out if args.out != config.DATA_DIR / "calendar.ics"
               else config.DATA_DIR / "calendar_fullyblocked.ics")
        write(build_fully_blocked(week_start), out)
    else:
        out = args.out
        write(build_weeks(week_start, args.weeks), out)
    print(f"wrote {args.weeks} synthetic week(s) starting {week_start} -> {out}")


if __name__ == "__main__":
    main()
