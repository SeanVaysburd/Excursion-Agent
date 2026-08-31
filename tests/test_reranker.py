"""Retrieval mechanics: cosine round-trip, cutoff-before-rerank ordering,
composite reordering, the calibration bands behind the 0.55 cutoff, and
the corpus facts the demo scenarios depend on (S1's e02 citation, S3's
cold start)."""

from __future__ import annotations

import math

import pytest

from src import config
from src.memory.retrieval import (
    SIMILARITY_CUTOFF,
    ExcursionMemory,
    PlanningContext,
    to_cosine,
)


@pytest.fixture(scope="module")
def memory() -> ExcursionMemory:
    return ExcursionMemory.build()


def ctx(season: str, activity: str, site: str) -> PlanningContext:
    return PlanningContext(
        label=f"{season}/{activity}",
        season=season,
        activity_type=activity,
        site=site,
        time_of_day="morning",
        day_of_week="Saturday",
        window="06:00-14:00",
    )


S1 = ("spring", "birding", "Jamaica Bay Wildlife Refuge")
COLD = ("summer", "kayaking", "Sebago Canoe Club")


def test_to_cosine_inverts_chroma_score_exactly():
    for cos in (-0.2, 0.0, 0.31, 0.55, 0.82, 1.0):
        store_score = math.exp(cos - 1.0)  # exp(-distance), distance = 1-cos
        assert to_cosine(store_score) == pytest.approx(cos, abs=1e-12)
    assert to_cosine(0.0) == -1.0  # degenerate guard


def test_cutoff_applies_to_raw_similarity_before_rerank(memory):
    result = memory.retrieve(ctx(*S1))
    assert result.kept, "S1 context must retrieve history"
    for candidate in result.kept:
        assert candidate.passed_cutoff
        assert candidate.similarity >= SIMILARITY_CUTOFF, (
            "a composite bonus must never lift a below-cutoff candidate"
        )
    composites = [c.composite for c in result.ranked]
    assert composites == sorted(composites, reverse=True)
    assert [c.entry_id for c in result.kept] == [
        c.entry_id for c in result.ranked[:3]
    ]


def test_rerank_orders_differently_than_similarity_alone(memory):
    result = memory.retrieve(ctx(*S1))
    by_similarity = [
        c.entry_id
        for c in sorted(result.candidates, key=lambda c: -c.similarity)
        if c.passed_cutoff
    ]
    by_composite = [c.entry_id for c in result.ranked]
    assert by_similarity[0] == "e02", "highest-similarity hit is the 4/10 midday entry"
    assert by_composite != by_similarity, (
        "season/type/recency must be able to reorder the semantic ranking"
    )


def test_s1_required_memory_citation_present(memory):
    """The spec's S1 narrative cites the 4/10 midday-crowds memory -- hold
    the corpus + retrieval to that, so the scenario never silently loses
    its graded citation."""
    result = memory.retrieve(ctx(*S1))
    kept = {c.entry_id: c for c in result.kept}
    assert "e02" in kept
    assert kept["e02"].similarity >= SIMILARITY_CUTOFF
    assert kept["e02"].metadata["rating"] <= 5


def test_cold_start_signals_no_relevant_history(memory):
    result = memory.retrieve(ctx(*COLD))
    assert not result.has_history
    assert "cutoff" in result.cold_start_reason


def test_calibration_bands_still_separate_at_cutoff(memory):
    genuine_best = memory.retrieve(ctx(*S1)).candidates[0].similarity
    cold_best = memory.retrieve(ctx(*COLD)).candidates[0].similarity
    assert genuine_best > SIMILARITY_CUTOFF > cold_best, (
        f"bands crossed the cutoff: genuine={genuine_best:.3f}, "
        f"cold={cold_best:.3f} -- re-run scripts/week3/calibrate.py"
    )
    assert config.SIMILARITY_CUTOFF == SIMILARITY_CUTOFF  # single source
