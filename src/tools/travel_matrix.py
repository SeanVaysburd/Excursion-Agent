"""Static travel-time matrix -- deliberately one swappable function.

Base minutes come from data/travel_times.json (a full GTFS routing engine
is out of scope; this function's signature is the seam a real routing API
would replace). NYC events carry no coordinates, so an unknown destination
falls back to its borough's default entry, flagged as an approximation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from src import config

MATRIX_PATH = config.DATA_DIR / "travel_times.json"


@dataclass(frozen=True)
class Trip:
    minutes: int
    lines: tuple[str, ...]
    approximate: bool  # True when resolved via a borough default
    origin_note: str = "approximate home origin (privacy)"


@lru_cache(maxsize=1)
def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text())


def lookup(dest_id: str, borough: str | None = None) -> Trip | None:
    """Travel from home to a site/venue id, or a borough fallback.

    Returns None when neither resolves -- the caller treats that as
    unreachable-unknown and falls back rather than inventing minutes.
    """
    matrix = _matrix()
    entry = matrix.get("destinations", {}).get(dest_id)
    if entry is not None:
        return Trip(int(entry["minutes"]), tuple(entry.get("lines", [])), False)
    if borough:
        fallback = matrix.get("borough_defaults", {}).get(borough)
        if fallback is not None:
            return Trip(int(fallback["minutes"]), tuple(fallback.get("lines", [])), True)
    return None
