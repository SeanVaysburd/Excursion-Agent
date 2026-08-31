"""Groundedness and hard-constraint validators.

Groundedness metric honesty: the rate is computed over evidence ids the
agents EMITTED (pre-strip), not over survivors, a post-drop rate would
be 100% by construction and prove nothing. The 0-violations target belongs
to the hard-constraint validator, which runs on final outputs where zero
is a real, falsifiable claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.agents.schemas import AgentReport, CandidateScore, downgrade


@dataclass
class GroundednessStats:
    ids_emitted: int = 0
    ids_valid: int = 0
    ids_stripped: int = 0
    candidates_in: int = 0
    candidates_dropped: int = 0
    stripped_examples: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.ids_valid / self.ids_emitted if self.ids_emitted else 1.0


def validate_groundedness(
    report: AgentReport, registry_ids: set[str]
) -> tuple[list[CandidateScore], GroundednessStats]:
    """Strip invented ids (downgrading confidence); drop a candidate only
    when nothing valid remains. Order matters: this runs FIRST, before any
    code-owned adjustment attaches its own (pre-registered) evidence."""
    stats = GroundednessStats(candidates_in=len(report.candidates))
    kept: list[CandidateScore] = []
    for candidate in report.candidates:
        valid = [i for i in candidate.evidence_ids if i in registry_ids]
        invalid = [i for i in candidate.evidence_ids if i not in registry_ids]
        stats.ids_emitted += len(candidate.evidence_ids)
        stats.ids_valid += len(valid)
        stats.ids_stripped += len(invalid)
        stats.stripped_examples.extend(invalid[:2])
        if not valid:
            stats.candidates_dropped += 1
            continue
        if invalid:
            candidate = candidate.model_copy(
                update={
                    "evidence_ids": valid,
                    "confidence": downgrade(candidate.confidence),
                }
            )
        kept.append(candidate)
    return kept, stats


@dataclass
class Violation:
    kind: str  # "hard_block_overlap" | "weather_gate_survivor"
    candidate_id: str
    detail: str


def _overlaps(
    start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime
) -> bool:
    return start_a < end_b and end_a > start_b


def validate_hard_constraints(
    final_candidates: list[dict],
    hard_blocks: list[tuple[datetime, datetime, str]],
    gated_windows: dict[str, set[str]],
) -> list[Violation]:
    """Final-output gate. Each candidate dict needs: candidate_id, start,
    end (tz-aware), window_label, category. gated_windows maps a window
    label to the categories weather removed for it."""
    violations: list[Violation] = []
    for candidate in final_candidates:
        for block_start, block_end, summary in hard_blocks:
            if _overlaps(candidate["start"], candidate["end"], block_start, block_end):
                violations.append(
                    Violation(
                        kind="hard_block_overlap",
                        candidate_id=candidate["candidate_id"],
                        detail=f"overlaps hard calendar block {summary!r}",
                    )
                )
        gated = gated_windows.get(candidate["window_label"], set())
        if candidate["category"] in gated:
            violations.append(
                Violation(
                    kind="weather_gate_survivor",
                    candidate_id=candidate["candidate_id"],
                    detail=(
                        f"category {candidate['category']!r} was weather-gated "
                        f"for window {candidate['window_label']}"
                    ),
                )
            )
    return violations
