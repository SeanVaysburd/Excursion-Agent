"""NWS active alerts -- the extreme-weather fallback/corroboration source.

/alerts/active, never /alerts: the bare endpoint returns expired history
(verified: 98 KB of stale alerts vs 233 bytes active).
"""

from __future__ import annotations

from src.tools.base import RunContext, ToolResult, fetch

URL = "https://api.weather.gov/alerts/active"


async def fetch_active_alerts(ctx: RunContext, lat: float, lon: float) -> ToolResult:
    result = await fetch(ctx, "nws", URL, params={"point": f"{lat:.4f},{lon:.4f}"})
    if result.status != "ok":
        return result

    features = result.data.get("features") or []
    if not features:
        return result.model_copy(
            update={"status": "empty", "data": [], "note": "no active alerts"}
        )

    alerts = []
    for feature in features:
        props = feature.get("properties") or {}
        evidence_id = ctx.registry.register(
            f"wxalert:{props.get('id', 'unknown')[-12:]}", props
        )
        alerts.append(
            {
                "evidence_id": evidence_id,
                "event": props.get("event"),
                "severity": props.get("severity"),
                "headline": props.get("headline"),
            }
        )
    return result.model_copy(update={"data": alerts})
