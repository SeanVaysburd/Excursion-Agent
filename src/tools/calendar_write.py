"""The ONLY write tool in the system, and it never runs autonomously.

Writes go to a gitignored working copy (data/calendar.local.ics, created
from the committed sample on first write) so the committed graded input is
never mutated and demo runs stay reproducible. "Append" is semantically
parse -> add_component -> atomic rewrite: a literal file append after
END:VCALENDAR would be invalid ICS. The returned diff is semantic
(summary/start/end), because the rewrite re-folds lines.
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from icalendar import Calendar, Event

from src import config


def working_copy(committed: Path) -> Path:
    local = committed.with_name("calendar.local.ics")
    if not local.exists():
        shutil.copy2(committed, local)
    return local


def append_event(
    committed_path: Path,
    summary: str,
    start: datetime,
    end: datetime,
    description: str = "",
) -> dict:
    """Append one VEVENT to the working copy. Caller MUST have approval."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("naive datetime crossed a module edge")

    path = working_copy(committed_path)
    calendar = Calendar.from_ical(path.read_bytes())

    event = Event()
    uid = f"excursion-{uuid.uuid4().hex[:12]}@excursion-agent"
    event.add("UID", uid)
    event.add("DTSTAMP", datetime.now(config.TZ))
    event.add("SUMMARY", summary)
    event.add("DTSTART", start)
    event.add("DTEND", end)
    if description:
        event.add("DESCRIPTION", description)
    calendar.add_component(event)

    tmp = path.with_suffix(".ics.tmp")
    tmp.write_bytes(calendar.to_ical())
    os.replace(tmp, path)  # atomic

    return {
        "written_to": str(path),
        "uid": uid,
        "added": {
            "summary": summary,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
    }
