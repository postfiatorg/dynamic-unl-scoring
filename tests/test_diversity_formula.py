"""Tests for diversity formula v1 and its frozen inputs."""

import pytest

from scoring_service.models import ASNInfo, GeoLocation, ValidatorProfile
from scoring_service.services.diversity_formula import (
    AXIS_PENALTY,
    AXIS_POINTS,
    UNKNOWN_AXIS_POINTS,
    apply_diversity_formula,
    compute_diversity,
    diversity_formula_parameters,
)
from scoring_service.services.provider_families import build_diversity_inputs
from scoring_service.services.response_parser import ScoringResult, ValidatorScore

# Testnet round 26: 44 resolved endpoints; the values below are the design
# doc's worked examples.
ROUND_26_RESOLVED = 44


class TestComputeDiversity:
    @pytest.mark.parametrize(
        ("country", "provider", "expected"),
        [
            (1, 1, 100),  # unique on both axes
            (1, 10, 75),  # Vultr (10) in a unique country
            (2, 1, 97),  # Akamai (1) in Japan (2)
            (9, 14, 42),  # Hetzner (14) in Germany (9)
            (15, 14, 25),  # Hetzner (14) in the United States (15)
            (3, None, 54),  # Canada (3), provider unknown
            (None, None, 20),  # location unknown
        ],
    )
    def test_round_26_worked_examples(self, country, provider, expected):
        assert compute_diversity(country, provider, ROUND_26_RESOLVED) == expected

    def test_strictly_less_crowded_scores_strictly_higher(self):
        for country, provider in ((2, 5), (5, 2), (10, 10), (1, 17)):
            less_crowded = compute_diversity(country, provider, ROUND_26_RESOLVED)
            assert less_crowded > compute_diversity(country + 1, provider, ROUND_26_RESOLVED)
            assert less_crowded > compute_diversity(country, provider + 1, ROUND_26_RESOLVED)

    def test_an_axis_bottoms_out_at_zero_before_full_crowding(self):
        # With 44 resolved endpoints an axis rounds to nothing from 19 sharers
        # on; beyond that point extra crowding on that axis costs no more.
        assert (
            compute_diversity(1, 18, ROUND_26_RESOLVED)
            > compute_diversity(1, 19, ROUND_26_RESOLVED)
            == AXIS_POINTS
        )
        assert compute_diversity(1, 19, ROUND_26_RESOLVED) == compute_diversity(
            1, ROUND_26_RESOLVED, ROUND_26_RESOLVED
        )
        assert compute_diversity(ROUND_26_RESOLVED, ROUND_26_RESOLVED, ROUND_26_RESOLVED) == 0

    def test_unknown_axis_is_worth_a_fixed_fraction(self):
        assert compute_diversity(None, 1, ROUND_26_RESOLVED) == UNKNOWN_AXIS_POINTS + AXIS_POINTS
        assert compute_diversity(None, None, ROUND_26_RESOLVED) == 2 * UNKNOWN_AXIS_POINTS

    def test_a_lone_resolved_validator_scores_full_points(self):
        assert compute_diversity(1, 1, 1) == 100
        assert compute_diversity(None, 1, 1) == UNKNOWN_AXIS_POINTS + AXIS_POINTS
        assert compute_diversity(None, None, 0) == 2 * UNKNOWN_AXIS_POINTS

    def test_rounds_half_up_without_floating_point(self):
        # others = 2: numerator 50*2 - 119 = -19 -> 0 for the shared axis,
        # 100 for the unique axis: (100 + 0) / 2 = 50 exactly.
        assert compute_diversity(2, 1, 3) == 50
        # others = 3: shared axis 150 - 119 = 31, unique axis 150: 181 / 3 = 60.33 -> 60.
        assert compute_diversity(2, 1, 4) == 60

    def test_parameters_are_published(self):
        assert diversity_formula_parameters() == {
            "axis_points": AXIS_POINTS,
            "axis_penalty": AXIS_PENALTY,
            "unknown_axis_points": UNKNOWN_AXIS_POINTS,
        }


def _validator(index, country=None, as_name=None):
    return ValidatorProfile(
        master_key=f"nHB{index}",
        signing_key=f"n9{index}",
        asn=ASNInfo(asn=index, as_name=as_name) if as_name else None,
        geolocation=GeoLocation(country=country) if country else None,
    )


class TestBuildDiversityInputs:
    def test_counts_each_validator_against_its_own_axes(self):
        validators = [
            _validator(1, "Germany", "HETZNER-AS, DE"),
            _validator(2, "Germany", "HETZNER-AS, DE"),
            _validator(3, "Poland", "UPCLOUD, FI"),
            _validator(4, "Canada", None),
            _validator(5, None, None),
        ]

        inputs = build_diversity_inputs(validators)

        assert inputs["resolved_endpoints"] == 3
        assert inputs["validators"] == [
            {"master_key": "nHB1", "country_validators": 2, "provider_validators": 2},
            {"master_key": "nHB2", "country_validators": 2, "provider_validators": 2},
            {"master_key": "nHB3", "country_validators": 1, "provider_validators": 1},
            {"master_key": "nHB4", "country_validators": 1, "provider_validators": None},
            {"master_key": "nHB5", "country_validators": None, "provider_validators": None},
        ]

    def test_entries_are_sorted_by_master_key(self):
        inputs = build_diversity_inputs([_validator(2, "Poland", "UPCLOUD, FI"), _validator(1, "Japan", "AKAMAI")])
        assert [e["master_key"] for e in inputs["validators"]] == ["nHB1", "nHB2"]

    def test_empty_set(self):
        assert build_diversity_inputs([]) == {"resolved_endpoints": 0, "validators": []}


def _score(master_key, diversity):
    return ValidatorScore(
        master_key=master_key, score=80, consensus=90, reliability=90,
        software=100, diversity=diversity, identity=80, reasoning="",
    )


def _result(*scores):
    return ScoringResult(validator_scores=list(scores), raw_response="", complete=True, errors=[])


class TestApplyDiversityFormula:
    INPUTS = {
        "resolved_endpoints": 44,
        "validators": [
            {"master_key": "nHB1", "country_validators": 1, "provider_validators": 1},
            {"master_key": "nHB2", "country_validators": 9, "provider_validators": 14},
        ],
    }

    def test_replaces_only_the_diversity_sub_score(self):
        original = _result(_score("nHB1", 90), _score("nHB2", 40))

        computed = apply_diversity_formula(original, self.INPUTS)

        assert [v.diversity for v in computed.validator_scores] == [100, 42]
        assert [v.diversity for v in original.validator_scores] == [90, 40]
        for before, after in zip(original.validator_scores, computed.validator_scores):
            assert after.model_dump(exclude={"diversity"}) == before.model_dump(exclude={"diversity"})

    def test_fails_closed_on_a_validator_without_inputs(self):
        with pytest.raises(ValueError, match="nHB3"):
            apply_diversity_formula(_result(_score("nHB1", 90), _score("nHB3", 50)), self.INPUTS)
