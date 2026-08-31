"""ICS parsing -> free windows per day.

Hard blocks remove time; soft blocks (SUMMARY containing "tentative"/
"optional", X-SOFT:true, native STATUS:TENTATIVE or TRANSP:TRANSPARENT)
survive as a visible score-penalty flag on any window they overlap.

Pre-decided edge rules (RFC 5545 + reviewer-will-ask items):
- all-day events arrive as `date` with EXCLUSIVE DTEND;
- missing DTEND -> DURATION if present, else zero-length (datetime) /
  one day (date);
- overlapping hard blocks are MERGED before subtraction;
- windows shorter than MIN_WINDOW_MINUTES are discarded;
- X-SOFT is icalendar vText, compared as str(...).lower() == "true";
- RRULE is not expanded (documented limitation; the synthetic calendar
  must not use it).
Everything leaves this module tz-aware in America/New_York.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from icalendar import Calendar

from src import config
from src.tools.base import RunContext


@dataclass(frozen=True)
class CalBlock:
    uid: str
    summary: str
    start: datetime
    end: datetime
    soft: bool
    evidence_id: str


@dataclass
class FreeWindow:
    start: datetime
    end: datetime
    soft_conflicts: list[CalBlock] = field(default_factory=list)

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    @property
    def label(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


def _aware(value) -> datetime:
    """Normalize an icalendar DTSTART/DTEND value to tz-aware local time."""
    if isinstance(value, datetime):
        return value.astimezone(config.TZ) if value.tzinfo else value.replace(tzinfo=config.TZ)
    if isinstance(value, date):
        # All-day: exclusive DTEND means "midnight starting that date".
        return datetime.combine(value, time(0, 0), tzinfo=config.TZ)
    raise TypeError(f"unsupported ICS time value: {value!r}")


def _is_soft(component) -> bool:
    summary = str(component.get("SUMMARY", "")).lower()
    if "tentative" in summary or "optional" in summary:
        return True
    if str(component.get("X-SOFT", "")).strip().lower() == "true":
        return True
    if str(component.get("STATUS", "")).upper() == "TENTATIVE":
        return True
    if str(component.get("TRANSP", "")).upper() == "TRANSPARENT":
        return True
    return False


def parse_blocks(ctx: RunContext, path: Path) -> list[CalBlock]:
    calendar = Calendar.from_ical(path.read_bytes())
    blocks: list[CalBlock] = []
    for component in calendar.walk("VEVENT"):
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start = _aware(dtstart.dt)
        dtend = component.get("DTEND")
        if dtend is not None:
            end = _aware(dtend.dt)
        elif component.get("DURATION") is not None:
            end = start + component.get("DURATION").dt
        elif isinstance(dtstart.dt, datetime):
            end = start  # RFC 5545: zero-length
        else:
            end = start + timedelta(days=1)  # all-day default
        uid = str(component.get("UID", f"noUID-{len(blocks)}"))
        summary = str(component.get("SUMMARY", "")).strip()
        soft = _is_soft(component)
        evidence_id = ctx.registry.register(
            f"cal:{uid}",
            {"summary": summary, "start": start.isoformat(), "end": end.isoformat(),
             "soft": soft},
        )
        blocks.append(CalBlock(uid, summary, start, end, soft, evidence_id))
    return blocks


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def free_windows(ctx: RunContext, path: Path, day: date) -> list[FreeWindow]:
    """Free windows for one day: waking hours minus merged hard blocks,
    with overlapping soft blocks attached as penalty flags."""
    blocks = parse_blocks(ctx, path)
    day_start = datetime.combine(day, time(config.WAKING_HOURS[0]), tzinfo=config.TZ)
    day_end = datetime.combine(day, time(config.WAKING_HOURS[1]), tzinfo=config.TZ)

    hard = _merge(
        [
            (max(b.start, day_start), min(b.end, day_end))
            for b in blocks
            if not b.soft and b.start < day_end and b.end > day_start
        ]
    )

    windows: list[FreeWindow] = []
    cursor = day_start
    for start, end in hard + [(day_end, day_end)]:
        if (start - cursor) >= timedelta(minutes=config.MIN_WINDOW_MINUTES):
            windows.append(FreeWindow(start=cursor, end=start))
        cursor = max(cursor, end)

    for window in windows:
        window.soft_conflicts = [
            b
            for b in blocks
            if b.soft and b.start < window.end and b.end > window.start
        ]
    return windows
