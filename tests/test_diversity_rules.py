"""Tests for the deterministic diversity equality / ordering rule check (issue #65)."""

import json
import logging

import pytest

from scoring_service.services.diversity_rules import (
    DiversityEvidence,
    apply_diversity_rules,
    check_diversity_rules,
    diversity_evidence,
)
from scoring_service.services.response_parser import ScoringResult, ValidatorScore


# ---------------------------------------------------------------------------
# Fixture builders: a request in the production prompt shape
# ---------------------------------------------------------------------------


def _request(entries, concentration):
    """A model_request whose user message carries the two blocks the
    prompt builder renders, in the same order as prompts/scoring_v11.txt."""
    content = (
        "Score every validator listed below.\n\n"
        "NETWORK CONCENTRATION:\n"
        + json.dumps(concentration, separators=(",", ":"))
        + "\n\nVALIDATOR DATA:\n"
        + json.dumps(entries, separators=(",", ":"))
        + "\n\nRespond with ONLY a valid JSON object."
    )
    return {
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": content},
        ]
    }


def _entry(validator_id, family, country):
    return {
        "validator_id": validator_id,
        "provider_family": family,
        "geolocation": {"country": country, "city": None},
        "asn": {"as_name": family.upper(), "asn": 1},
    }


def _concentration(families, countries, unresolved=0):
    return {
        "provider_families": [
            {"family": name, "validators": count} for name, count in families.items()
        ],
        "countries": [
            {"country": name, "validators": count} for name, count in countries.items()
        ],
        "unresolved_endpoints": unresolved,
    }


def _id_map(validator_ids):
    return {
        vid: {"master_key": f"nHB{vid}", "signing_key": f"n9{vid}"}
        for vid in validator_ids
    }


def _result(diversity_by_id, complete=True, errors=None):
    scores = [
        ValidatorScore(
            master_key=f"nHB{vid}",
            score=80,
            consensus=90,
            reliability=80,
            software=80,
            diversity=diversity,
            identity=70,
            reasoning="test",
        )
        for vid, diversity in diversity_by_id.items()
    ]
    return ScoringResult(
        validator_scores=scores,
        network_summary="summary",
        raw_response="{}",
        complete=complete,
        errors=list(errors or []),
    )


# The round-26 pool from issue #65: counts come straight from the issue's
# table (provider_family count, country count).
ROUND_26_ENTRIES = [
    _entry("v001", "google", "Switzerland"),  # app.w.ai            google 1, CH 1
    _entry("v002", "upcloud", "Poland"),  # snakespartan        upcloud 1, PL 1
    _entry("v003", "vultr", "Australia"),  # jollydinger          vultr 10, AU 1
    _entry("v004", "vultr", "Brazil"),  # pftperry              vultr 10, BR 1
    _entry("v005", "vultr", "South Africa"),  # wizbubba           vultr 10, ZA 1
    _entry("v006", "vultr", "South Korea"),  # pftmeech            vultr 10, KR 1
    _entry("v007", "akamai", "Japan"),  # qwerky                 akamai 1, JP 2
    _entry("v008", "cherryservers", "Singapore"),  # sendoeth     cherry 1, SG 2
]
ROUND_26_CONCENTRATION = _concentration(
    families={
        "vultr": 10,
        "google": 1,
        "upcloud": 1,
        "akamai": 1,
        "cherryservers": 1,
    },
    countries={
        "Switzerland": 1,
        "Poland": 1,
        "Australia": 1,
        "Brazil": 1,
        "South Africa": 1,
        "South Korea": 1,
        "Japan": 2,
        "Singapore": 2,
    },
)
ROUND_26_REQUEST = _request(ROUND_26_ENTRIES, ROUND_26_CONCENTRATION)
ROUND_26_ID_MAP = _id_map([e["validator_id"] for e in ROUND_26_ENTRIES])

# The published round-26 diversity sub-scores from the issue.
ROUND_26_PUBLISHED = {
    "v001": 90,  # app.w.ai: 1/1 but scored below the 10/1 validators
    "v002": 95,
    "v003": 95,
    "v004": 95,
    "v005": 95,
    "v006": 85,  # pftmeech: same 10/1 evidence as v003-v005 but 85
    "v007": 95,
    "v008": 95,
}


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


def test_evidence_is_derived_from_the_concentration_block():
    evidence = diversity_evidence(ROUND_26_REQUEST)
    assert evidence["v001"] == DiversityEvidence("v001", country_count=1, family_count=1)
    assert evidence["v003"] == DiversityEvidence("v003", country_count=1, family_count=10)
    assert evidence["v007"] == DiversityEvidence("v007", country_count=2, family_count=1)
    assert len(evidence) == 8


def test_evidence_is_empty_without_a_concentration_block():
    request = {"messages": [{"role": "user", "content": "VALIDATOR DATA:\n[]"}]}
    assert diversity_evidence(request) == {}
    assert diversity_evidence({"messages": [{"role": "user", "content": "test"}]}) == {}
    assert diversity_evidence({"messages": []}) == {}


def test_unresolved_endpoints_are_not_comparable():
    entries = [
        _entry("v001", "unknown", "Germany"),
        {"validator_id": "v002", "provider_family": "vultr", "geolocation": {"country": None}},
        _entry("v003", "vultr", "Germany"),
    ]
    request = _request(entries, _concentration({"vultr": 2}, {"Germany": 2}, unresolved=1))
    assert set(diversity_evidence(request)) == {"v003"}


def test_malformed_concentration_block_is_reported_not_raised():
    request = {
        "messages": [
            {"role": "user", "content": "NETWORK CONCENTRATION:\n{not json\nVALIDATOR DATA:\n[]"}
        ]
    }
    errors = check_diversity_rules(request, _result({}), {})
    assert len(errors) == 1
    assert errors[0].startswith("diversity rule check could not read the request")


def test_dominates_requires_no_axis_worse_and_one_strictly_better():
    a = DiversityEvidence("a", country_count=1, family_count=1)
    b = DiversityEvidence("b", country_count=1, family_count=10)
    c = DiversityEvidence("c", country_count=2, family_count=1)
    assert a.dominates(b)
    assert a.dominates(c)
    assert not b.dominates(a)
    assert not b.dominates(c)  # better family axis, worse country axis
    assert not c.dominates(b)
    assert not a.dominates(a)


# ---------------------------------------------------------------------------
# Round-26 reproduction (issue #65)
# ---------------------------------------------------------------------------


def test_round_26_equality_violation_same_counts_scored_90_vs_95():
    """app.w.ai (google 1 / Switzerland 1) scored 90 while snakespartan
    (upcloud 1 / Poland 1) scored 95: identical concentration counts must
    give identical diversity sub-scores."""
    errors = check_diversity_rules(ROUND_26_REQUEST, _result(ROUND_26_PUBLISHED), ROUND_26_ID_MAP)
    equality = [e for e in errors if e.startswith("diversity equality violation")]
    assert any(
        "v001=90, v002=95" in e and "country count 1 and provider-family count 1" in e
        for e in equality
    ), equality


def test_round_26_equality_violation_pftmeech_85_vs_95():
    """Four vultr-10 / one-country validators: three scored 95, pftmeech 85."""
    errors = check_diversity_rules(ROUND_26_REQUEST, _result(ROUND_26_PUBLISHED), ROUND_26_ID_MAP)
    equality = [e for e in errors if e.startswith("diversity equality violation")]
    assert any(
        "v003=95, v004=95, v005=95, v006=85" in e
        and "country count 1 and provider-family count 10" in e
        for e in equality
    ), equality


def test_round_26_ordering_violation_one_one_below_ten_one():
    """app.w.ai (1/1) strictly dominates every vultr-10 / one-country
    validator and both 1 / two-country validators, yet scored 90 below
    their 95."""
    errors = check_diversity_rules(ROUND_26_REQUEST, _result(ROUND_26_PUBLISHED), ROUND_26_ID_MAP)
    ordering = [e for e in errors if e.startswith("diversity ordering violation")]
    dominated_by_v001 = {
        e.split(" is strictly less concentrated than ")[1].split(" ")[0]
        for e in ordering
        if e.startswith("diversity ordering violation: v001 ")
    }
    # The five validators the issue lists, each at 95 against v001's 90.
    assert {"v003", "v004", "v005", "v007", "v008"} <= dominated_by_v001
    assert any("but scores 90 versus 95" in e for e in ordering)


def test_round_26_corrected_scores_pass():
    """Scores that honour both rules: equal evidence equal, dominance strict."""
    corrected = {
        "v001": 95,  # 1/1
        "v002": 95,  # 1/1
        "v003": 85,  # 10/1
        "v004": 85,
        "v005": 85,
        "v006": 85,
        "v007": 90,  # 1/2
        "v008": 90,
    }
    assert check_diversity_rules(ROUND_26_REQUEST, _result(corrected), ROUND_26_ID_MAP) == []


def test_tie_at_the_ceiling_is_not_an_ordering_violation():
    entries = [_entry("v001", "a", "X"), _entry("v002", "b", "Y")]
    request = _request(entries, _concentration({"a": 1, "b": 5}, {"X": 1, "Y": 1}))
    id_map = _id_map(["v001", "v002"])
    # v001 dominates v002; both at 100 is the cap working, not a defect.
    assert check_diversity_rules(request, _result({"v001": 100, "v002": 100}), id_map) == []
    # ...but an equal score below the cap is a violation.
    errors = check_diversity_rules(request, _result({"v001": 90, "v002": 90}), id_map)
    assert len(errors) == 1 and errors[0].startswith("diversity ordering violation: v001 ")


def test_errors_are_deterministically_ordered():
    first = check_diversity_rules(ROUND_26_REQUEST, _result(ROUND_26_PUBLISHED), ROUND_26_ID_MAP)
    shuffled = dict(reversed(list(ROUND_26_PUBLISHED.items())))
    second = check_diversity_rules(ROUND_26_REQUEST, _result(shuffled), ROUND_26_ID_MAP)
    assert first == second
    assert first == sorted(first, key=lambda e: (not e.startswith("diversity equality"), first.index(e)))


def test_scores_for_validators_outside_the_evidence_are_ignored():
    """A parsed score whose master key is not in the identity map, or whose
    validator is not comparable, never participates."""
    id_map = {**ROUND_26_ID_MAP, "v999": {"master_key": "nHBv999", "signing_key": "x"}}
    scores = {**ROUND_26_PUBLISHED, "v999": 5}
    with_extra = check_diversity_rules(ROUND_26_REQUEST, _result(scores), id_map)
    without = check_diversity_rules(ROUND_26_REQUEST, _result(ROUND_26_PUBLISHED), ROUND_26_ID_MAP)
    assert with_extra == without


# ---------------------------------------------------------------------------
# Enforcement modes
# ---------------------------------------------------------------------------


def test_reject_mode_marks_the_result_incomplete_and_keeps_prior_errors():
    result = _result(ROUND_26_PUBLISHED, errors=["earlier parse warning"])
    applied = apply_diversity_rules(ROUND_26_REQUEST, result, ROUND_26_ID_MAP, mode="reject")
    assert applied.complete is False
    assert applied.errors[0] == "earlier parse warning"
    assert any(e.startswith("diversity equality violation") for e in applied.errors)
    assert any(e.startswith("diversity ordering violation") for e in applied.errors)
    # The input is not mutated.
    assert result.complete is True
    assert result.errors == ["earlier parse warning"]


def test_reject_mode_returns_a_clean_result_unchanged():
    corrected = {vid: 85 for vid in ROUND_26_PUBLISHED}
    corrected.update({"v001": 95, "v002": 95, "v007": 90, "v008": 90})
    result = _result(corrected)
    assert apply_diversity_rules(ROUND_26_REQUEST, result, ROUND_26_ID_MAP, mode="reject") is result


def test_warn_mode_logs_and_returns_the_result_unchanged(caplog):
    result = _result(ROUND_26_PUBLISHED)
    with caplog.at_level(logging.WARNING, logger="scoring_service.services.diversity_rules"):
        applied = apply_diversity_rules(ROUND_26_REQUEST, result, ROUND_26_ID_MAP, mode="warn")
    assert applied is result
    assert applied.complete is True
    assert any("warn-only" in record.getMessage() for record in caplog.records)


def test_off_mode_skips_the_check():
    result = _result(ROUND_26_PUBLISHED)
    assert apply_diversity_rules(ROUND_26_REQUEST, result, ROUND_26_ID_MAP, mode="off") is result


def test_default_mode_comes_from_settings(monkeypatch):
    from scoring_service.services import diversity_rules

    monkeypatch.setattr(diversity_rules.settings, "diversity_rule_enforcement", "warn")
    result = _result(ROUND_26_PUBLISHED)
    assert apply_diversity_rules(ROUND_26_REQUEST, result, ROUND_26_ID_MAP) is result
    monkeypatch.setattr(diversity_rules.settings, "diversity_rule_enforcement", "reject")
    assert apply_diversity_rules(ROUND_26_REQUEST, result, ROUND_26_ID_MAP).complete is False


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="diversity_rule_enforcement"):
        apply_diversity_rules(ROUND_26_REQUEST, _result({}), {}, mode="maybe")


def test_requests_without_concentration_block_pass_through():
    """Prompt eras before v9 carry no block, so the rules do not apply."""
    request = {"messages": [{"role": "user", "content": "test"}]}
    result = _result(ROUND_26_PUBLISHED)
    assert apply_diversity_rules(request, result, ROUND_26_ID_MAP, mode="reject") is result
