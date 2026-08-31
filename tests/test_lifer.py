"""Lifer logic: species-code matching only, taxonomy-filtered, capped."""

from __future__ import annotations

import pytest

from src import config
from src.agents.lifer import bonus, load_life_list, potential_lifers

LIFE = {"norcar", "blujay"}
SPECIES = {"norcar", "blujay", "semplo", "shbdow"}  # taxonomy category==species


def obs(code: str, name: str) -> dict:
    return {"species_code": code, "common_name": name}


def test_lifers_are_species_absent_from_life_list():
    lifers = potential_lifers(
        [obs("semplo", "Semipalmated Plover"), obs("norcar", "Northern Cardinal")],
        LIFE,
        SPECIES,
    )
    assert [l["code"] for l in lifers] == ["semplo"]


def test_non_species_codes_never_become_lifers():
    """spuh/slash/hybrid codes are observations, not countable species."""
    lifers = potential_lifers(
        [obs("gull sp.", "gull sp."), obs("x00123", "hybrid")],
        LIFE,
        SPECIES,
    )
    assert lifers == []


def test_keyless_taxonomy_skips_lifer_logic_entirely():
    assert potential_lifers([obs("semplo", "x")], LIFE, None) == []


def test_matching_is_by_code_never_common_name():
    """Same common name, different code: still a lifer. A name is display
    text; a code is an identity."""
    life = {"norcar"}
    lifers = potential_lifers([obs("semplo", "Northern Cardinal")], life, SPECIES)
    assert [l["code"] for l in lifers] == ["semplo"]


def test_duplicate_observations_count_once():
    lifers = potential_lifers(
        [obs("semplo", "Semipalmated Plover")] * 3, LIFE, SPECIES
    )
    assert len(lifers) == 1


@pytest.mark.parametrize(
    "count, expected",
    [(0, 0.0), (1, 1.5), (2, 2.0), (3, 2.5), (10, 2.5)],
)
def test_bonus_formula_min_cap(count, expected):
    assert bonus(count) == pytest.approx(expected)
    assert bonus(count) <= config.LIFER_BONUS_CAP


def test_committed_life_lists_are_the_s4_pair():
    """The base list is seeded from live regional observations and is
    missing EXACTLY the small deliberate gap (seasonally common species,
    currently the two sandpipers), so live lifer counts stay small and
    believable; the full list is the fuller-life-list eval control.
    scripts/seed_life_list.py maintains this pair."""
    base = load_life_list(config.DATA_DIR / "life_list.csv")
    full = load_life_list(config.DATA_DIR / "life_list_full.csv")
    gap = full - base
    assert base < full  # strict subset: the control closes the gap
    assert 1 <= len(gap) <= 3, f"gap should stay tiny and deliberate: {gap}"
    assert {"semsan", "leasan"} <= gap
    assert bonus(2) == 2.0 and bonus(50) == config.LIFER_BONUS_CAP
