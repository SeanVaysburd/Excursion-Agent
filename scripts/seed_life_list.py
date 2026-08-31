"""Reseed the synthetic life lists from LIVE regional observations.

The demo list must track what is actually being seen: a list that misses
most of the current migration makes every bird a "lifer" (the 72-per-card
absurdity) and defeats S4, whose design is a NEARLY complete list missing
a couple of seasonally common species so the bonus is small, named, and
believable.

  data/life_list.csv       = everything currently observed + the old list,
                             MINUS a small deliberate gap (printed)
  data/life_list_full.csv  = the same union INCLUDING the gap species,
                             the fuller-life-list control for S4

Run when the season shifts enough that live runs start showing silly
lifer counts:  python -m scripts.seed_life_list
"""

from __future__ import annotations

import asyncio
import csv
import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from src import config  # noqa: E402
from src.tools import ebird  # noqa: E402
from src.tools.base import RunContext  # noqa: E402

# Seasonally common shorebirds, in preference order; the first two that
# the live feeds actually contain become the deliberate gap.
PREFERRED_GAP = ["semsan", "leasan", "bkbplo", "greyel", "semplo"]
GAP_SIZE = 2


def _read(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open() as handle:
        return {row["species_code"]: row["common_name"]
                for row in csv.DictReader(handle) if row.get("species_code")}


def _write(path: Path, species: dict[str, str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["species_code", "common_name"])
        for code, name in sorted(species.items(), key=lambda kv: kv[1]):
            writer.writerow([code, name])


async def main() -> None:
    sites = json.loads((config.DATA_DIR / "sites.json").read_text())["sites"]
    regions: dict[str, dict] = {}
    for site in sites:
        if site["category"] in ("birding", "kayaking"):
            regions.setdefault(site["region_id"], site)

    ctx = RunContext(scenario="seed-life-list")
    try:
        taxonomy = await ebird.species_codes(ctx)
        if not taxonomy:
            raise SystemExit("eBird taxonomy unavailable (is EBIRD_API_KEY set?); "
                             "refusing to seed from unverifiable codes")
        observed: dict[str, str] = {}
        freq: Counter[str] = Counter()
        for region_id, anchor in regions.items():
            recent = await ebird.fetch_recent(ctx, anchor["lat"], anchor["lng"])
            notable = await ebird.fetch_notable(ctx, anchor["lat"], anchor["lng"])
            for obs in (recent.data or []) + (notable.data or []):
                code = obs.get("species_code")
                if not code or code not in taxonomy:
                    continue  # spuh/slash/hybrid: not a countable species
                observed.setdefault(code, obs.get("common_name") or code)
                freq[code] += 1
        print(f"observed now: {len(observed)} species across {len(regions)} regions")
    finally:
        await ctx.aclose()

    default_path = config.DATA_DIR / "life_list.csv"
    full_path = config.DATA_DIR / "life_list_full.csv"
    union = {**_read(default_path), **_read(full_path), **observed}

    gap = [c for c in PREFERRED_GAP if c in observed][:GAP_SIZE]
    for code, _ in freq.most_common():  # top up from the most-seen species
        if len(gap) >= GAP_SIZE:
            break
        if code not in gap:
            gap.append(code)

    _write(full_path, union)
    _write(default_path, {c: n for c, n in union.items() if c not in gap})
    print(f"gap (stay OFF data/life_list.csv, ON the full control): "
          f"{', '.join(f'{observed[c]} ({c})' for c in gap)}")
    print(f"wrote {default_path.name} ({len(union) - len(gap)} species) and "
          f"{full_path.name} ({len(union)} species)")


if __name__ == "__main__":
    asyncio.run(main())
