"""NYC Open Data permitted events (Socrata tvpp-9vvx).

The spec's "filter out film permits" is an ALLOW-list here because the live
vocabulary has no film event_type at all -- film/TV shows up as "Production
Event" / "Theater Load in and Load Outs", and 82% of raw rows are permitted
youth/adult sports that aren't excursions either. Rows carry no coordinates,
so transit downstream falls back to per-borough matrix entries.
"""

from __future__ import annotations

from datetime import date, datetime

from src import config
from src.tools.base import RunContext, ToolResult, fetch

URL = "https://data.cityofnewyork.us/resource/tvpp-9vvx.json"


async def fetch_events(ctx: RunContext, day: date) -> ToolResult:
    start = day.strftime("%Y-%m-%dT00:00:00")
    end = day.strftime("%Y-%m-%dT23:59:59")
    result = await fetch(
        ctx,
        "nyc-events",
        URL,
        params={
            "$where": f"start_date_time between '{start}' and '{end}'",
            "$limit": 200,
            "$order": "start_date_time",
        },
    )
    if result.status != "ok":
        return result

    events = []
    for row in result.data:
        etype = row.get("event_type", "")
        if etype not in config.EVENT_TYPE_ALLOW:
            continue  # excludes film permits and non-excursion permit noise
        try:
            # Socrata timestamps are floating local time.
            start_dt = datetime.fromisoformat(row["start_date_time"]).replace(
                tzinfo=config.TZ
            )
            end_dt = datetime.fromisoformat(row["end_date_time"]).replace(
                tzinfo=config.TZ
            )
        except (KeyError, ValueError):
            continue
        event_id = row.get("event_id") or f"row{len(events)}"
        evidence_id = ctx.registry.register(f"event:{event_id}", row)
        events.append(
            {
                "evidence_id": evidence_id,
                "id": event_id,
                "name": row.get("event_name", "").strip(),
                "type": etype,
                "borough": row.get("event_borough", ""),
                "location": row.get("event_location", "")[:120],
                "start": start_dt,
                "end": end_dt,
            }
        )

    if not events:
        return result.model_copy(
            update={
                "status": "empty",
                "data": [],
                "note": f"no allow-listed events on {day.isoformat()}",
            }
        )
    return result.model_copy(update={"data": events})
