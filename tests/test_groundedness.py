"""Groundedness validator: strip, downgrade, drop, and an honest metric."""

from __future__ import annotations

from src.agents.schemas import AgentReport, CandidateScore, report_schema_for
from src.safety.validators import validate_groundedness

REGISTRY = {"wx:20260905T07", "ebird:S1:semplo", "memory:e02"}


def cand(cid: str, ids: list[str], confidence: str = "high") -> CandidateScore:
    return CandidateScore(
        candidate_id=cid,
        name="Test",
        site="Site",
        window="06:00-14:00",
        score=7,
        reason="Because evidence.",
        evidence_ids=ids,
        confidence=confidence,  # type: ignore[arg-type]
    )


def test_fully_grounded_candidate_passes_untouched():
    report = AgentReport(candidates=[cand("a", ["wx:20260905T07"])], self_report="ok")
    kept, stats = validate_groundedness(report, REGISTRY)
    assert len(kept) == 1 and kept[0].confidence == "high"
    assert stats.rate == 1.0 and stats.candidates_dropped == 0


def test_invented_id_is_stripped_and_costs_confidence():
    report = AgentReport(
        candidates=[cand("a", ["wx:20260905T07", "wx:20260905T09"])],  # T09 not fetched
        self_report="ok",
    )
    kept, stats = validate_groundedness(report, REGISTRY)
    assert kept[0].evidence_ids == ["wx:20260905T07"]
    assert kept[0].confidence == "med"
    assert stats.ids_stripped == 1


def test_candidate_with_zero_valid_ids_is_dropped():
    report = AgentReport(
        candidates=[cand("a", ["fake:1", "fake:2"]), cand("b", ["memory:e02"])],
        self_report="ok",
    )
    kept, stats = validate_groundedness(report, REGISTRY)
    assert [c.candidate_id for c in kept] == ["b"]
    assert stats.candidates_dropped == 1


def test_metric_denominator_is_pre_strip_not_survivors():
    """A post-drop rate would be trivially 100% -- the honest metric
    counts every id the agents emitted."""
    report = AgentReport(
        candidates=[cand("a", ["fake:1"]), cand("b", ["memory:e02"])],
        self_report="ok",
    )
    _, stats = validate_groundedness(report, REGISTRY)
    assert stats.ids_emitted == 2
    assert stats.rate == 0.5  # not 1.0


def test_literal_schema_rejects_invented_ids_at_validation_time():
    schema = report_schema_for(["wx:20260905T07"])
    good = {
        "candidates": [cand("a", ["wx:20260905T07"]).model_dump()],
        "self_report": "ok",
    }
    assert schema.model_validate(good)
    bad = {
        "candidates": [cand("a", ["fake:1"]).model_dump()],
        "self_report": "ok",
    }
    import pytest as _pytest

    with _pytest.raises(Exception):
        schema.model_validate(bad)
