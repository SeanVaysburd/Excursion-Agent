"""The SHARED scoring rubric (Week-5 grader-feedback fix): one prompt
template with identical 1-10 anchors for all three domain agents; only the
domain examples and the evidence differ. Score comparability across
domains is the whole point, the waterfall ranks nature against events
against museums on these numbers.
"""

from __future__ import annotations

RUBRIC_ANCHORS = """\
Score every candidate on the SAME 1-10 scale:
  9-10  exceptional fit: conditions, timing and evidence all align
  7-8   strong: clearly worth doing, minor compromises
  5-6   fine: a reasonable default, nothing special in the evidence
  3-4   weak: real drawbacks in the evidence (conditions, timing, access)
  1-2   poor: evidence argues against it"""

DOMAIN_EXAMPLES = {
    "nature": """\
Example anchors for nature outings:
  9: early-morning window in migration season, strong recent sightings at
     this exact site, favorable tide for a coastal marsh, calm wind
  5: quiet season, few recent observations, conditions merely acceptable
  2: high winds forecast during the whole window, or the window misses the
     tide entirely at a tide-dependent site""",
    "outdoor_event": """\
Example anchors for outdoor city events:
  9: a well-matched permitted event fully inside the free window, good
     weather across the event hours
  5: an event that only partly overlaps the window, or so-so weather
  2: event mostly outside the window, or exposed to gated-adjacent weather""",
    "indoor": """\
Example anchors for museums / indoor venues:
  9: venue open across most of the window with time to do it justice, easy
     transit; especially strong when weather removed outdoor options
  5: open but the usable overlap is tight, or the visit would be rushed
  2: closed that day, or the open hours barely intersect the window""",
}

TEMPLATE = """\
You are the {domain} scoring agent inside a personal excursion planner.
Score how well each candidate excursion fits THIS person, THIS day, using
ONLY the evidence provided below. Do not invent facts, sightings, events,
hours, or conditions.

{anchors}

{examples}

DATE: {date} ({weekday})
FREE WINDOWS: {windows}

DATA SOURCES THIS RUN (base your self_report on these, honestly):
{sources}

EVIDENCE (cite by id; use ONLY these ids in evidence_ids):
{evidence}

RELEVANT PAST EXCURSIONS (this person's own logged feedback):
{memory}

CANDIDATES TO SCORE (score each once, in its best-fitting window):
{candidates}

Rules:
- reason: at most two sentences, grounded in cited evidence.
- evidence_ids: only ids that appear above; cite what the reason uses.
- A high similarity on a past excursion means RELEVANT, not good. Its
  rating tells you how it went; learn from the bad ones too.
- If past feedback for this context is absent, plan from live evidence
  alone, set confidence to "low", and say the cold start out loud in the
  reason.
- self_report: one or two honest sentences about how the data sources
  went (empty feeds, errors, reduced coverage), drawn from DATA SOURCES.
"""


def build_prompt(
    domain: str,
    date: str,
    weekday: str,
    windows: str,
    sources: str,
    evidence: str,
    memory: str,
    candidates: str,
) -> str:
    return TEMPLATE.format(
        domain=domain,
        anchors=RUBRIC_ANCHORS,
        examples=DOMAIN_EXAMPLES[domain],
        date=date,
        weekday=weekday,
        windows=windows,
        sources=sources,
        evidence=evidence,
        memory=memory,
        candidates=candidates,
    )
