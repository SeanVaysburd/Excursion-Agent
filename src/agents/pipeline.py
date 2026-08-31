"""The ordered post-processing pipeline between an agent's structured
output and the candidates the planner may actually show.

Order is load-bearing and fixed (plan decision closing the biggest critic
finding):

  1 groundedness      strip invented ids / drop ungrounded candidates
  2 cold-start        confidence override when memory had nothing
  3 lifer bonus       nature only, code-side arithmetic
  4 soft-conflict     penalty when the window carries a soft calendar flag
  5 transit           matrix minutes + live MTA alerts (penalty/prune,
                      alert text into transit_note, never into reason)
  6 self-report scan  narrated degradation costs confidence
  7 final_score       clamp(score + sum(deltas)); rank; top-3 per slot

Every mutation is an attributable Adjustment; the model's raw 1-10 score
is never edited.
"""

from __future__ import annotations

from src import config
from src.agents import lifer as lifer_mod
from src.agents.schemas import (
    Adjustment,
    AgentReport,
    ScoredCandidate,
    TripInfo,
    downgrade,
)
from src.safety.self_report import scan as scan_self_report
from src.safety.validators import GroundednessStats, validate_groundedness
from src.tools import mta_alerts as mta_mod
from src.tools import travel_matrix


def process_report(
    *,
    domain: str,
    report: AgentReport,
    registry_ids: set[str],
    cold_start: bool,
    lifers: list[dict],
    lifer_evidence: list[str],
    soft_windows: set[str],
    window_minutes: dict[str, int],
    window_starts: dict,
    dest_meta: dict[str, dict],
    mta_by_route: dict[str, list[dict]],
    cold_candidate_ids: set[str] | None = None,
) -> tuple[list[ScoredCandidate], GroundednessStats, str]:
    """Run steps 1-7 for one agent's report. Returns (survivors sorted by
    final_score desc, groundedness stats, self-report finding summary)."""

    # 1, groundedness
    grounded, stats = validate_groundedness(report, registry_ids)

    # 6 (computed once; applied per candidate below to keep the order
    # readable, the scan itself has no per-candidate state)
    finding = scan_self_report(report.self_report)

    survivors: list[ScoredCandidate] = []
    for base in grounded:
        candidate = ScoredCandidate(base=base, domain=domain, confidence=base.confidence)

        # 2, cold-start override: per-domain (the whole pack was cold) OR
        # per-candidate (one unlogged context inside a warm domain, e.g.
        # kayaking among well-logged birding sites).
        candidate_cold = base.candidate_id in (cold_candidate_ids or set())
        if cold_start or candidate_cold:
            candidate.confidence = "low"
            candidate.adjustments.append(
                Adjustment(
                    label="cold_start", delta=0.0,
                    note=("no relevant history above the similarity cutoff"
                          if cold_start else
                          "no logged history for this activity/site "
                          "(cold start within a warm domain)"))
            )

        # 3, lifer bonus (nature only; code-side; species NAMED)
        if domain == "nature" and lifers:
            delta = lifer_mod.bonus(len(lifers))
            names = ", ".join(l["common_name"] for l in lifers[:5])
            candidate.lifer_species = [l["common_name"] for l in lifers]
            candidate.adjustments.append(
                Adjustment(
                    label="lifer_bonus",
                    delta=delta,
                    evidence_ids=lifer_evidence[:5],
                    note=f"potential lifers: {names}",
                )
            )

        # 4, soft calendar conflict
        if base.window in soft_windows:
            candidate.adjustments.append(
                Adjustment(
                    label="soft_conflict",
                    delta=config.SOFT_CONFLICT_PENALTY,
                    note="overlaps a tentative/optional calendar block",
                )
            )

        # 5, transit
        meta = dest_meta.get(base.candidate_id, {})
        trip = travel_matrix.lookup(
            meta.get("dest_id", base.candidate_id), meta.get("borough")
        )
        if trip is None:
            candidate.pruned = True
            candidate.prune_reason = "no travel-time entry (unreachable-unknown)"
        else:
            candidate.trip = TripInfo(
                minutes=trip.minutes, lines=list(trip.lines), approximate=trip.approximate
            )
            window_len = window_minutes.get(base.window, 0)
            if window_len and 2 * trip.minutes > config.UNREACHABLE_FRACTION * window_len:
                candidate.pruned = True
                candidate.prune_reason = (
                    f"round-trip transit {2 * trip.minutes} min exceeds "
                    f"{config.UNREACHABLE_FRACTION:.0%} of the {window_len}-min window"
                )
            else:
                when = window_starts.get(base.window)
                hits = (
                    mta_mod.alerts_for_trip(mta_by_route, list(trip.lines), when)
                    if when is not None
                    else []
                )
                for hit in hits:
                    action, delta = config.MTA_ALERT_ACTIONS[hit["alert_type"]]
                    if action == "prune":
                        candidate.pruned = True
                        candidate.prune_reason = (
                            f"{hit['line']} line {hit['alert_type']}: {hit['header'][:80]}"
                        )
                        break
                    candidate.adjustments.append(
                        Adjustment(
                            label="transit_alert",
                            delta=delta,
                            evidence_ids=[hit["evidence_id"]],
                            note=f"{hit['line']}: {hit['alert_type']}",
                        )
                    )
                    candidate.transit_note = (
                        f"{hit['line']} line: {hit['header'][:140]}"
                        if hit["header"]
                        else f"{hit['line']} line {hit['alert_type']}"
                    )

        # 6, self-report scan applies to the whole report's candidates
        if finding.downgrade:
            candidate.confidence = downgrade(candidate.confidence)
            candidate.adjustments.append(
                Adjustment(
                    label="self_report",
                    delta=0.0,
                    note=f"self-report flagged: {finding.summary}",
                )
            )

        # 7, final score
        candidate.final_score = max(
            config.FINAL_SCORE_MIN,
            min(
                config.FINAL_SCORE_MAX,
                base.score + sum(a.delta for a in candidate.adjustments),
            ),
        )
        survivors.append(candidate)

    survivors.sort(key=lambda c: (-c.final_score, c.candidate_id))
    return survivors, stats, finding.summary


def top_per_window(
    candidates: list[ScoredCandidate], top_n: int = 3
) -> dict[str, list[ScoredCandidate]]:
    """Top-N unpruned candidates per free-window label (spec: per slot)."""
    slots: dict[str, list[ScoredCandidate]] = {}
    for candidate in candidates:
        if candidate.pruned:
            continue
        slots.setdefault(candidate.base.window, []).append(candidate)
    return {
        window: sorted(members, key=lambda c: (-c.final_score, c.candidate_id))[:top_n]
        for window, members in slots.items()
    }
