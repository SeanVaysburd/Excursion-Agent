"""MTA service alerts (GTFS-realtime JSON, keyless, ~1.3 MB) -- fetched
once per run and indexed by subway route.

Live-verified parsing rules the naive reading gets wrong:
- 135/331 alerts carry MULTIPLE active_period entries; a period without an
  `end` is open-ended; a missing active_period list means "active".
- 2 informed_entity rows lack route_id -- use .get().
- header_text.translation always has BOTH "en" and "en-html"; select
  language == "en" explicitly and never render the HTML variant.
- Severity lives in the Mercury extension's alert_type; the exact-string
  mapping to prune/penalty/ignore is config.MTA_ALERT_ACTIONS.
- Entity ids like "lmm:alert:265394:34" carry a churning sort suffix --
  the evidence id keeps the stable prefix only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src import config
from src.tools.base import RunContext, ToolResult, fetch

URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fall-alerts.json"


def _english(translated: dict | None) -> str:
    for t in (translated or {}).get("translation", []):
        if t.get("language") == "en":
            return t.get("text", "")
    return ""


def _stable_id(entity_id: str) -> str:
    parts = entity_id.split(":")
    return ":".join(parts[:3]) if len(parts) >= 3 else entity_id


def _active_at(periods: list[dict], when: datetime) -> bool:
    if not periods:
        return True  # missing active_period = treat as active
    ts = when.timestamp()
    for p in periods:
        start = p.get("start", 0)
        end = p.get("end")  # missing end = open-ended
        if start <= ts and (end is None or ts <= end):
            return True
    return False


async def fetch_alerts(ctx: RunContext) -> ToolResult:
    result = await fetch(ctx, "mta", URL)
    if result.status != "ok":
        return result

    by_route: dict[str, list[dict]] = {}
    for entity in result.data.get("entity", []):
        alert = entity.get("alert") or {}
        mercury = alert.get("transit_realtime.mercury_alert") or {}
        alert_type = mercury.get("alert_type", "")
        if alert_type not in config.MTA_ALERT_ACTIONS:
            continue  # informational types are ignored on purpose
        header = _english(alert.get("header_text"))
        periods = alert.get("active_period") or []
        evidence_id = f"alert:{_stable_id(entity.get('id', 'unknown'))}"
        record = {
            "evidence_id": evidence_id,
            "alert_type": alert_type,
            "header": header,
            "periods": periods,
        }
        routes = {
            ie.get("route_id")
            for ie in alert.get("informed_entity", [])
            if ie.get("route_id")
        }
        if not routes:
            continue
        ctx.registry.register(evidence_id, record)
        for route in routes:
            by_route.setdefault(route, []).append(record)

    if not by_route:
        return result.model_copy(
            update={"status": "empty", "data": {}, "note": "no actionable alerts"}
        )
    return result.model_copy(update={"data": by_route})


def alerts_for_trip(
    by_route: dict[str, list[dict]], lines: list[str], when: datetime
) -> list[dict]:
    """Actionable alerts touching any line this trip uses, active at `when`.

    `when` must be tz-aware; GTFS periods are POSIX UTC seconds, so the
    comparison happens in epoch space.
    """
    if when.tzinfo is None:
        raise ValueError("naive datetime crossed a module edge")
    hits: list[dict] = []
    seen: set[str] = set()
    for line in lines:
        for alert in by_route.get(line, []):
            if alert["evidence_id"] in seen:
                continue
            if _active_at(alert["periods"], when.astimezone(timezone.utc)):
                seen.add(alert["evidence_id"])
                hits.append({**alert, "line": line})
    return hits
