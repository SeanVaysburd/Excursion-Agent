"""NOAA CO-OPS tide predictions for coastal sites.

datum=MLLW is mandatory (omission is a hard 400, which under the no-4xx-
retry rule means instant fallback); interval=hilo keeps it to ~4 rows/day
instead of 240. Timestamps arrive naive-local (lst_ldt), the zone is
attached here and nothing naive leaves this module.
"""

from __future__ import annotations

from datetime import date, datetime

from src import config
from src.tools.base import RunContext, ToolResult, compact_ts, fetch

URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


async def fetch_tides(
    ctx: RunContext, day: date, station: str = config.TIDE_STATION_DEFAULT
) -> ToolResult:
    stamp = day.strftime("%Y%m%d")
    result = await fetch(
        ctx,
        "noaa-tides",
        URL,
        params={
            "product": "predictions",
            "datum": "MLLW",
            "interval": "hilo",
            "station": station,
            "begin_date": stamp,
            "end_date": stamp,
            "time_zone": "lst_ldt",
            "units": "english",
            "format": "json",
        },
    )
    if result.status != "ok":
        return result

    predictions = result.data.get("predictions") or []
    if not predictions:
        return result.model_copy(
            update={"status": "empty", "note": "no tide predictions returned"}
        )

    tides = []
    for p in predictions:
        dt = datetime.strptime(p["t"], "%Y-%m-%d %H:%M").replace(tzinfo=config.TZ)
        evidence_id = ctx.registry.register(f"tide:{station}:{compact_ts(dt)}", p)
        tides.append(
            {
                "evidence_id": evidence_id,
                "dt": dt,
                "type": "high" if p.get("type") == "H" else "low",
                "height_ft": float(p.get("v", "nan")),
            }
        )
    return result.model_copy(update={"data": tides})
