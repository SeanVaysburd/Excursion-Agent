"""Self-report check: a regex/keyword pass plus a light negative-lexicon
pass over each agent's self_report.

Rationale (also in README): agents narrate their own tool failures --
"no data came back, I assumed seasonal defaults", and narrated
uncertainty should cost confidence even when every schema field validates.
The adversarial threat model does not apply here (the agents are ours);
this catches honest self-described degradation, not deception.

The spec-mandated keyless-eBird sentence is whitelisted: it must appear in
keyless runs by design, and letting it downgrade every nature report would
silently collapse confidence across the whole domain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.tools.ebird import UNAVAILABLE_NOTE

# The spec's keyword list, verbatim.
SPEC_PATTERNS = [
    r"\bestimated\b",
    r"\bassumed\b",
    r"\bno data\b",
    r"\bguessed\b",
    r"\bmade up\b",
]

# Light negative lexicon for the sentiment-ish pass.
NEGATIVE_LEXICON = [
    r"\bfailed\b",
    r"\berror\b",
    r"\bempty\b",
    r"\bunavailable\b",
    r"\bmissing\b",
    r"\bunable\b",
    r"\btimed out\b",
    r"\bfell back\b",
    r"\bfallback\b",
]

WHITELIST = [UNAVAILABLE_NOTE.lower()]


@dataclass
class SelfReportFinding:
    hits: list[str]
    downgrade: bool

    @property
    def summary(self) -> str:
        return ", ".join(self.hits) if self.hits else "clean"


NEGATORS = re.compile(r"\b(no|not|without|zero|never)\b[\s\w]{0,16}$")


def _negated(text: str, start: int) -> bool:
    """True when the 20 chars before the hit contain a negator, so a healthy
    sentence like "no errors or missing coverage" never costs confidence.
    Applied only to the lexicon additions; the spec keywords match raw
    ("no data" is itself a negation and must keep firing)."""
    return bool(NEGATORS.search(text[max(0, start - 20):start]))


def scan(self_report: str) -> SelfReportFinding:
    text = self_report.lower()
    for allowed in WHITELIST:
        text = text.replace(allowed, "")
    hits = [
        pattern.strip("\\b")
        for pattern in SPEC_PATTERNS
        if re.search(pattern, text)
    ]
    for pattern in NEGATIVE_LEXICON:
        match = re.search(pattern, text)
        if match and not _negated(text, match.start()):
            hits.append(pattern.strip("\\b"))
    return SelfReportFinding(hits=hits, downgrade=bool(hits))
