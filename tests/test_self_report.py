"""Self-report scanner: spec keywords fire raw, lexicon additions respect
negation, and the mandated keyless-eBird sentence stays whitelisted."""

from __future__ import annotations

from src.safety.self_report import scan
from src.tools.ebird import UNAVAILABLE_NOTE


def test_healthy_report_with_negated_terms_is_clean():
    finding = scan("All sources returned successfully with no errors or "
                   "missing coverage noted.")
    assert not finding.downgrade, finding.hits


def test_actual_degradation_still_fires():
    assert scan("coverage was missing for two regions").downgrade
    assert scan("the events feed failed midway").downgrade


def test_spec_keywords_fire_even_when_negation_shaped():
    # "no data" is a spec keyword and itself contains a negation.
    assert scan("there was no data for tides").downgrade
    assert scan("values were estimated from seasonal norms").downgrade


def test_mandated_ebird_sentence_is_whitelisted():
    finding = scan(f"{UNAVAILABLE_NOTE}. Otherwise all sources nominal.")
    assert not finding.downgrade, finding.hits
