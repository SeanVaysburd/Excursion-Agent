"""Self-report check: a regex/keyword pass plus a light negative-lexicon
pass over each agent's self_report.

Rationale (also in README): agents narrate their own tool failures --
"no data came back, I assumed seasonal defaults" -- and narrated
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


def scan(self_report: str) -> SelfReportFinding:
    text = self_report.lower()
    for allowed in WHITELIST:
        text = text.replace(allowed, "")
    hits = [
        pattern.strip("\\b")
        for pattern in SPEC_PATTERNS + NEGATIVE_LEXICON
        if re.search(pattern, text)
    ]
    return SelfReportFinding(hits=hits, downgrade=bool(hits))
