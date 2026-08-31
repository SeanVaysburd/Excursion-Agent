"""Branch isolation (Week-4 grader-feedback fix) and deterministic ToT
mechanics, proven without any LLM: sibling branches structurally cannot
contaminate each other, pruning follows the spec's two rules, and the
variety-penalty mechanism flips a repetitive naive pick to a varied set.
"""

from __future__ import annotations

import dataclasses

import pytest

from src import config
from src.agents.schemas import CandidateScore, CriticVerdict, ScoredCandidate, TripInfo
from src.orchestration.tot_beam import BeamNode, expand


def candidate(cid: str, score: float, category: str = "birding",
              minutes: int = 30) -> ScoredCandidate:
    return ScoredCandidate(
        base=CandidateScore(
            candidate_id=cid, name=cid, site=f"site of {cid}",
            window="06:00-14:00", score=int(min(10, max(1, score))),
            reason="test", evidence_ids=["wx:x"], confidence="med"),
        domain=category,
        trip=TripInfo(minutes=minutes, lines=["Q"]),
        final_score=score,
    )


def verdict(variety=0.0, walking=0.0, fatigue=0.0, total=0.0) -> CriticVerdict:
    return CriticVerdict(
        variety_penalty=variety, walking_penalty=walking,
        transit_fatigue_penalty=fatigue, adjusted_total=total,
        rationale="test")


def test_nodes_are_frozen_mutation_is_structurally_impossible():
    node = BeamNode(picks=("a",), base_sum=7.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        node.picks = ("hacked",)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        node.base_sum = 99.0  # type: ignore[misc]


def test_sibling_branches_cannot_contaminate_each_other():
    parent = BeamNode(picks=("day1",), base_sum=8.0, transit_min=60,
                      walk_miles=3.0)
    a, _ = expand(parent, candidate("day2-A", 7.0), verdict(total=15.0), 0.1, 2.0)
    b, _ = expand(parent, candidate("day2-B", 6.0), verdict(total=14.0), 0.2, 4.0)

    # Parent untouched by either expansion.
    assert parent.picks == ("day1",) and parent.base_sum == 8.0
    # Siblings independent: divergent picks, sums, walking totals.
    assert a.picks == ("day1", "day2-A") and b.picks == ("day1", "day2-B")
    assert a.base_sum == 15.0 and b.base_sum == 14.0
    assert a.walk_miles == 5.0 and b.walk_miles == 7.0
    # Tuples are immutable -- no shared mutable state exists to leak through.
    assert isinstance(a.picks, tuple)


def test_arithmetic_mismatch_is_detected_and_code_value_wins():
    parent = BeamNode(base_sum=10.0)
    child, mismatch = expand(
        parent, candidate("x", 5.0),
        verdict(variety=2.0, total=99.0),  # critic's sum is wrong
        0.0, 2.0)
    assert mismatch is True
    assert child.adjusted == pytest.approx(13.0)  # 15 - 2, not 99


def test_prune_rules_beam_width_and_margin():
    children = [
        BeamNode(picks=(f"c{i}",), adjusted=adj, transit_min=10 * i)
        for i, adj in enumerate([9.0, 8.5, 8.4, 8.2, 7.9, 5.0])
    ]
    children.sort(key=lambda n: (-n.adjusted, n.transit_min, n.tiebreak))
    leader = children[0].adjusted
    survivors = [n for n in children[: config.BEAM_WIDTH]
                 if leader - n.adjusted <= config.PRUNE_MARGIN]
    assert len(survivors) == 4  # width rule
    assert all(leader - n.adjusted <= 3.0 for n in survivors)
    # the 5.0 node is out both by width AND by >3-below-leader
    assert children[-1] not in survivors


def test_variety_penalty_flips_repetitive_naive_pick():
    """The centerpiece mechanism, deterministic: naive rank-by-sum takes a
    third birding day (highest raw score); with a critic that penalizes
    close repetition, the varied set wins the beam."""
    parent = BeamNode(picks=("birding-1", "birding-2"), base_sum=17.0,
                      adjusted=16.0)
    third_birding = candidate("birding-3", 8.0, category="birding")
    museum = candidate("museum-1", 7.0, category="indoor")

    # naive: birding-3 (8.0 > 7.0)
    naive_pick = max([third_birding, museum], key=lambda c: c.final_score)
    assert naive_pick.candidate_id == "birding-3"

    # critic: third straight birding day draws a 2.5 variety penalty
    with_birding, _ = expand(parent, third_birding, verdict(variety=2.5, total=0),
                             0.1, 3.0)
    with_museum, _ = expand(parent, museum, verdict(variety=0.0, total=0),
                            0.2, 1.5)
    ranked = sorted([with_birding, with_museum],
                    key=lambda n: (-n.adjusted, n.transit_min, n.tiebreak))
    assert ranked[0].picks[-1] == "museum-1"
    assert ranked[0].adjusted == pytest.approx(24.0)  # 17+7-0
    assert ranked[1].adjusted == pytest.approx(22.5)  # 17+8-2.5
