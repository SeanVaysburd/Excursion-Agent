"""Pydantic models for every LLM I/O in the system (quality-bar rule:
no untyped dict crosses an LLM boundary).

`CandidateScore.score` is the model's raw 1-10 judgment. Everything that
happens to a score after the model speaks, lifer bonus, soft-conflict
penalty, transit adjustment, is a code-owned `Adjustment` on the wrapping
`ScoredCandidate`, and `final_score` is the only number the UI, the weekly
ToT, and the eval consume. Keeping the model's integer and the code's
arithmetic in separate fields is what lets the trace show exactly who
contributed what to a recommendation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, create_model

Confidence = Literal["high", "med", "low"]

CONFIDENCE_ORDER = ("high", "med", "low")


def downgrade(confidence: Confidence) -> Confidence:
    index = CONFIDENCE_ORDER.index(confidence)
    return CONFIDENCE_ORDER[min(index + 1, len(CONFIDENCE_ORDER) - 1)]


class CandidateScore(BaseModel):
    """One scored excursion candidate, identical schema for all three
    domain agents (frozen-spec requirement)."""

    candidate_id: str
    name: str
    site: str
    window: str  # e.g. "06:00-14:00", must match a free window label
    score: int = Field(ge=1, le=10)
    reason: str = Field(description="At most two sentences.")
    evidence_ids: list[str]
    confidence: Confidence


class AgentReport(BaseModel):
    candidates: list[CandidateScore]
    self_report: str = Field(
        description="How the data sources behind this report actually went."
    )


def report_schema_for(allowed_ids: list[str]) -> type[AgentReport]:
    """Per-call schema whose evidence_ids are Literal-constrained to the
    evidence pack's real ids.

    Under json_schema structured output, Ollama's grammar decoder then
    REJECTS invented ids at generation time; the claude-sdk prompt path
    can't enforce it, which is why the groundedness validator re-checks
    membership afterwards (belt and braces).
    """
    if not allowed_ids:
        return AgentReport
    id_literal = Literal[tuple(allowed_ids)]  # type: ignore[valid-type]
    constrained_candidate = create_model(
        "CandidateScoreConstrained",
        __base__=CandidateScore,
        evidence_ids=(list[id_literal], ...),
    )
    return create_model(
        "AgentReportConstrained",
        __base__=AgentReport,
        candidates=(list[constrained_candidate], ...),
    )


class Adjustment(BaseModel):
    """One code-owned score delta, always attributable."""

    label: str  # "lifer_bonus" | "soft_conflict" | "transit_alert" | ...
    delta: float
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


class TripInfo(BaseModel):
    minutes: int
    lines: list[str]
    approximate: bool = False


class ScoredCandidate(BaseModel):
    """A candidate after the ordered post-processing pipeline."""

    base: CandidateScore
    domain: str
    adjustments: list[Adjustment] = Field(default_factory=list)
    transit_note: str = ""
    trip: TripInfo | None = None
    lifer_species: list[str] = Field(default_factory=list)
    final_score: float = 0.0
    confidence: Confidence = "low"  # post-pipeline (may be downgraded)
    pruned: bool = False
    prune_reason: str = ""

    @property
    def candidate_id(self) -> str:
        return self.base.candidate_id

    @property
    def all_evidence_ids(self) -> list[str]:
        ids = list(self.base.evidence_ids)
        for adjustment in self.adjustments:
            ids.extend(adjustment.evidence_ids)
        return ids


class CriticVerdict(BaseModel):
    """Weekly ToT critic output: adjusted total + ITEMIZED penalties.

    The orchestrator recomputes adjusted_total = base_sum - penalties and
    logs any disagreement with the model's arithmetic, the itemization is
    the graded artifact, the subtraction is not the model's job to get
    wrong silently.
    """

    variety_penalty: float = Field(ge=0)
    walking_penalty: float = Field(ge=0)
    transit_fatigue_penalty: float = Field(ge=0)
    adjusted_total: float
    rationale: str = Field(description="At most two sentences.")
