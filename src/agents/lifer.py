"""Life-list logic: species-CODE matching only, never common-name strings
(a common name is display text; a code is an identity).

The taxonomy filter is load-bearing: eBird recent-obs feeds include spuh,
slash, hybrid and subspecies codes, and diffing those against a life list
would manufacture "lifers" that aren't countable species, on the one
scenario (S4) whose headline claim is the named lifers.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from src import config


def load_life_list(path: Path) -> set[str]:
    with path.open() as handle:
        return {
            row["species_code"].strip()
            for row in csv.DictReader(handle)
            if row.get("species_code", "").strip()
        }


def potential_lifers(
    observations: Iterable[dict],
    life_list: set[str],
    valid_species: set[str] | None,
) -> list[dict]:
    """Observed species absent from the life list, restricted to real
    species-category codes. Returns [{code, common_name}] de-duplicated,
    ordered by first appearance.

    valid_species=None means the taxonomy was unavailable (keyless eBird):
    the caller must SKIP lifer logic entirely rather than diff against an
    unverifiable code set.
    """
    if valid_species is None:
        return []
    seen: dict[str, str] = {}
    for obs in observations:
        code = obs.get("species_code")
        if not code or code in seen:
            continue
        if code not in valid_species:
            continue  # spuh/slash/hybrid/subspecies: not a countable lifer
        if code in life_list:
            continue
        seen[code] = obs.get("common_name") or code
    return [{"code": code, "common_name": name} for code, name in seen.items()]


def bonus(lifer_count: int) -> float:
    """min(2.5, 1.0 + 0.5 * lifer_count); zero when there are no lifers."""
    if lifer_count <= 0:
        return 0.0
    return min(
        config.LIFER_BONUS_CAP,
        config.LIFER_BONUS_BASE + config.LIFER_BONUS_PER_SPECIES * lifer_count,
    )
