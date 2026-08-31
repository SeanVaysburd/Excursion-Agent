"""eBird recent + notable observations, and the species-category taxonomy
that keeps the lifer bonus honest.

AUTO-DETECT: no EBIRD_API_KEY in the environment -> status="empty" with the
spec-mandated note; the nature agent carries that into its self-report and
the system runs correctly on iNaturalist alone.

Lifer matching filters observations to taxonomy category == "species"
first: recent-obs feeds include spuh/slash/hybrid/subspecies codes, and
diffing those against a life list would manufacture fake lifers, the one
failure mode the S4 headline claim cannot afford.
"""

from __future__ import annotations

import json
import os

from src import config
from src.tools.base import RunContext, ToolResult, fetch

BASE = "https://api.ebird.org/v2"
TAXONOMY_CACHE = config.ROOT / ".cache" / "ebird_taxonomy_species.json"

UNAVAILABLE_NOTE = "eBird unavailable - reduced bird coverage"


def _key() -> str | None:
    return os.environ.get("EBIRD_API_KEY") or None


def _keyless(source: str) -> ToolResult:
    from datetime import datetime

    return ToolResult(
        source=source,
        fetched_at=datetime.now(config.TZ),
        status="empty",
        data=[],
        note=UNAVAILABLE_NOTE,
    )


async def _fetch_obs(
    ctx: RunContext, endpoint: str, lat: float, lon: float
) -> ToolResult:
    key = _key()
    if key is None:
        return _keyless("ebird")
    result = await fetch(
        ctx,
        "ebird",
        f"{BASE}{endpoint}",
        params={
            "lat": round(lat, 4),
            "lng": round(lon, 4),
            "dist": config.EBIRD_DIST_KM,
            "back": config.EBIRD_BACK_DAYS,
        },
        headers={"X-eBirdApiToken": key},
    )
    if result.status != "ok":
        return result
    if not result.data:
        return result.model_copy(update={"status": "empty", "data": []})

    observations = []
    for row in result.data:
        evidence_id = ctx.registry.register(
            f"ebird:{row.get('subId', 'sub?')}:{row.get('speciesCode', '?')}", row
        )
        observations.append(
            {
                "evidence_id": evidence_id,
                "species_code": row.get("speciesCode"),
                "common_name": row.get("comName"),
                "how_many": row.get("howMany"),
                "location": row.get("locName"),
                "observed": row.get("obsDt"),
            }
        )
    return result.model_copy(update={"data": observations})


async def fetch_recent(ctx: RunContext, lat: float, lon: float) -> ToolResult:
    return await _fetch_obs(ctx, "/data/obs/geo/recent", lat, lon)


async def fetch_notable(ctx: RunContext, lat: float, lon: float) -> ToolResult:
    return await _fetch_obs(ctx, "/data/obs/geo/recent/notable", lat, lon)


async def species_codes(ctx: RunContext) -> set[str] | None:
    """Codes whose taxonomy category is 'species', cached to disk once.

    Returns None when eBird is keyless (lifer logic is then skipped
    entirely rather than run against an unverifiable code set).
    """
    if TAXONOMY_CACHE.exists():
        return set(json.loads(TAXONOMY_CACHE.read_text()))
    key = _key()
    if key is None:
        return None
    result = await fetch(
        ctx,
        "ebird",
        f"{BASE}/ref/taxonomy/ebird",
        params={"fmt": "json", "cat": "species"},
        headers={"X-eBirdApiToken": key},
    )
    if result.status != "ok":
        return None
    codes = {row["speciesCode"] for row in result.data if "speciesCode" in row}
    TAXONOMY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TAXONOMY_CACHE.write_text(json.dumps(sorted(codes)))
    return codes
