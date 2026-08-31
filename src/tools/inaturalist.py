"""iNaturalist recent bird observations, the always-available nature feed.

v2 API only: v1 silently ignores `fields=` (verified 125 KB vs 466 bytes
for the same query). One call per site region per run; radius in km.
"""

from __future__ import annotations

from src import config
from src.tools.base import RunContext, ToolResult, fetch

URL = "https://api.inaturalist.org/v2/observations"


async def fetch_recent(ctx: RunContext, lat: float, lon: float, region_id: str) -> ToolResult:
    result = await fetch(
        ctx,
        "inaturalist",
        URL,
        params={
            "taxon_id": 3,  # Aves
            "lat": round(lat, 4),
            "lng": round(lon, 4),
            "radius": config.INAT_RADIUS_KM,
            "verifiable": "true",
            "order_by": "observed_on",
            "per_page": config.INAT_PER_PAGE,
            # v2 field selector syntax is parenthesized, not dotted --
            # dotted paths silently drop nested fields like the common name.
            "fields": "(id:!t,observed_on:!t,taxon:(name:!t,preferred_common_name:!t))",
        },
    )
    if result.status != "ok":
        return result

    rows = result.data.get("results") or []
    if not rows:
        return result.model_copy(
            update={"status": "empty", "data": [], "note": f"no recent obs near {region_id}"}
        )

    observations = []
    for row in rows:
        taxon = row.get("taxon") or {}
        evidence_id = ctx.registry.register(f"inat:{row.get('id')}", row)
        observations.append(
            {
                "evidence_id": evidence_id,
                "observed_on": row.get("observed_on"),
                "common_name": taxon.get("preferred_common_name") or taxon.get("name"),
                "scientific_name": taxon.get("name"),
                "region_id": region_id,
            }
        )
    return result.model_copy(update={"data": observations})
