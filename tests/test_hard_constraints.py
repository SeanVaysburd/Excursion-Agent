"""Hard-constraint validator: the 0-violations headline metric must be
falsifiable, so here are the two ways to violate it."""

from __future__ import annotations

from datetime import datetime

from src import config
from src.safety.validators import validate_hard_constraints


def dt(h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, 5, h, m, tzinfo=config.TZ)


def cand(cid: str, start_h: int, end_h: int, window="06:00-14:00", category="birding"):
    return {
        "candidate_id": cid,
        "start": dt(start_h),
        "end": dt(end_h),
        "window_label": window,
        "category": category,
    }


def test_clean_plan_has_zero_violations():
    violations = validate_hard_constraints(
        [cand("a", 6, 10)],
        hard_blocks=[(dt(14), dt(18), "work shift")],
        gated_windows={},
    )
    assert violations == []


def test_hard_block_overlap_is_flagged():
    violations = validate_hard_constraints(
        [cand("a", 13, 16)],
        hard_blocks=[(dt(14), dt(18), "work shift")],
        gated_windows={},
    )
    assert [v.kind for v in violations] == ["hard_block_overlap"]
    assert "work shift" in violations[0].detail


def test_weather_gated_category_surviving_is_flagged():
    violations = validate_hard_constraints(
        [cand("a", 6, 10, category="birding")],
        hard_blocks=[],
        gated_windows={"06:00-14:00": {"birding", "hike"}},
    )
    assert [v.kind for v in violations] == ["weather_gate_survivor"]


def test_indoor_category_survives_a_gated_window():
    violations = validate_hard_constraints(
        [cand("a", 6, 10, category="museum")],
        hard_blocks=[],
        gated_windows={"06:00-14:00": {"birding", "hike"}},
    )
    assert violations == []
