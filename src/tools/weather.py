"""Open-Meteo forecast: ONE call per run per location covers the whole
16-day horizon; everything downstream slices it in memory.

The four query pins are load-bearing: the API defaults to GMT + metric,
which would shift the weather gate four hours and misread every threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src import config
from src.tools.base import RunContext, ToolResult, fetch

URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class WxHour:
    dt: datetime  # tz-aware America/New_York
    temp_f: float | None
    precip_prob: int | None  # %
    precip_in: float | None
    wind_mph: float | None
    evidence_id: str


async def fetch_forecast(ctx: RunContext, lat: float, lon: float) -> ToolResult:
    result = await fetch(
        ctx,
        "open-meteo",
        URL,
        params={
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m",
            "forecast_days": config.FORECAST_DAYS,
            "timezone": "America/New_York",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        },
    )
    if result.status != "ok":
        return result

    hourly = result.data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return result.model_copy(update={"status": "empty", "note": "no hourly data"})

    hours: list[WxHour] = []
    for i, stamp in enumerate(times):
        # API returns local-naive ISO because we pinned timezone=, attach
        # the zone at this boundary; nothing naive leaves this module.
        dt = datetime.fromisoformat(stamp).replace(tzinfo=config.TZ)
        evidence_id = ctx.registry.register(
            f"wx:{dt.strftime('%Y%m%dT%H')}",
            {
                "time": stamp,
                "temp_f": hourly["temperature_2m"][i],
                "precip_prob": hourly["precipitation_probability"][i],
                "precip_in": hourly["precipitation"][i],
                "wind_mph": hourly["wind_speed_10m"][i],
            },
        )
        hours.append(
            WxHour(
                dt=dt,
                temp_f=hourly["temperature_2m"][i],
                precip_prob=hourly["precipitation_probability"][i],
                precip_in=hourly["precipitation"][i],
                wind_mph=hourly["wind_speed_10m"][i],
                evidence_id=evidence_id,
            )
        )
    return result.model_copy(update={"data": hours})


def slice_hours(hours: list[WxHour], day: date, start_h: int, end_h: int) -> list[WxHour]:
    return [h for h in hours if h.dt.date() == day and start_h <= h.dt.hour < end_h]


def gate_outdoor(window_hours: list[WxHour]) -> tuple[bool, list[str], list[str]]:
    """Apply the extreme-weather thresholds to one free window.

    Returns (gated, human reasons, evidence ids of the offending hours).
    Missing data never gates, an absent forecast is a fallback situation,
    not evidence of bad weather.
    """
    reasons: list[str] = []
    evidence: list[str] = []
    for h in window_hours:
        hh = h.dt.strftime("%H:%M")
        if h.precip_prob is not None and h.precip_prob >= config.PRECIP_PROB_GATE:
            reasons.append(f"{h.precip_prob}% rain chance at {hh}")
            evidence.append(h.evidence_id)
        elif h.precip_in is not None and h.precip_in >= config.PRECIP_IN_GATE:
            reasons.append(f'{h.precip_in:.2f}" rain forecast at {hh}')
            evidence.append(h.evidence_id)
        elif h.temp_f is not None and not (config.TEMP_MIN_F <= h.temp_f <= config.TEMP_MAX_F):
            reasons.append(f"{h.temp_f:.0f}F at {hh}")
            evidence.append(h.evidence_id)
        elif h.wind_mph is not None and h.wind_mph >= config.WIND_GATE_MPH:
            reasons.append(f"{h.wind_mph:.0f} mph wind at {hh}")
            evidence.append(h.evidence_id)
    return bool(reasons), reasons[:4], evidence[:4]
