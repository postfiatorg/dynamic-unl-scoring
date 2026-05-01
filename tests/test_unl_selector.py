"""Tests for UNL inclusion logic and churn control."""

from scoring_service.services.response_parser import ScoringResult, ValidatorScore
from scoring_service.services.unl_selector import UNLSelectionResult, select_unl


def _score(master_key: str, score: int) -> ValidatorScore:
    return ValidatorScore(
        master_key=master_key,
        score=score,
        consensus=score,
        reliability=score,
        software=score,
        diversity=score,
        identity=score,
        reasoning="test",
    )


def _result(scores: list[tuple[str, int]]) -> ScoringResult:
    return ScoringResult(
        validator_scores=[_score(k, s) for k, s in scores],
        network_summary="test",
        raw_response="{}",
        complete=True,
        errors=[],
    )


# ---------------------------------------------------------------------------
# Round 1 — no previous UNL, pure score ranking
# ---------------------------------------------------------------------------


class TestFirstRound:
    def test_basic_ranking(self):
        result = select_unl(
            _result([("A", 90), ("B", 80), ("C", 70)]),
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == ["A", "B", "C"]
        assert result.alternates == []

    def test_cutoff_filters_low_scores(self):
        result = select_unl(
            _result([("A", 90), ("B", 30), ("C", 10)]),
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == ["A"]
        assert result.alternates == []

    def test_cap_at_max_size(self):
        validators = [(f"V{i:03d}", 90 - i) for i in range(10)]
        result = select_unl(
            _result(validators),
            cutoff=40,
            max_size=5,
            min_gap=5,
        )
        assert len(result.unl) == 5
        assert result.unl == ["V000", "V001", "V002", "V003", "V004"]
        assert result.alternates == ["V005", "V006", "V007", "V008", "V009"]

    def test_all_below_cutoff_produces_empty_unl(self):
        result = select_unl(
            _result([("A", 30), ("B", 20), ("C", 10)]),
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == []
        assert result.alternates == []

    def test_empty_scoring_result(self):
        result = select_unl(
            _result([]),
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == []
        assert result.alternates == []

    def test_tie_breaking_by_master_key(self):
        result = select_unl(
            _result([("C", 80), ("A", 80), ("B", 80)]),
            cutoff=40,
            max_size=2,
            min_gap=5,
        )
        assert result.unl == ["A", "B"]
        assert result.alternates == ["C"]


# ---------------------------------------------------------------------------
# Churn control — round > 1
# ---------------------------------------------------------------------------


class TestChurnControl:
    def test_incumbent_stays_when_gap_insufficient(self):
        """Challenger scores higher but not by enough to displace."""
        result = select_unl(
            _result([("INC", 42), ("CHL", 45)]),
            previous_unl=["INC"],
            cutoff=40,
            max_size=1,
            min_gap=5,
        )
        assert result.unl == ["INC"]
        assert result.alternates == ["CHL"]

    def test_challenger_displaces_when_gap_met(self):
        """Challenger exceeds incumbent by exactly the gap."""
        result = select_unl(
            _result([("INC", 42), ("CHL", 47)]),
            previous_unl=["INC"],
            cutoff=40,
            max_size=1,
            min_gap=5,
        )
        assert result.unl == ["CHL"]
        assert result.alternates == ["INC"]

    def test_challenger_displaces_when_gap_exceeded(self):
        result = select_unl(
            _result([("INC", 42), ("CHL", 55)]),
            previous_unl=["INC"],
            cutoff=40,
            max_size=1,
            min_gap=5,
        )
        assert result.unl == ["CHL"]
        assert result.alternates == ["INC"]

    def test_incumbent_below_cutoff_loses_protection(self):
        """Incumbency does not protect against the cutoff threshold."""
        result = select_unl(
            _result([("INC", 35), ("CHL", 50)]),
            previous_unl=["INC"],
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == ["CHL"]
        assert result.alternates == []

    def test_open_seats_filled_without_gap_requirement(self):
        """Challengers fill vacancies from dropped incumbents freely."""
        result = select_unl(
            _result([("INC1", 80), ("INC2", 35), ("CHL", 41)]),
            previous_unl=["INC1", "INC2"],
            cutoff=40,
            max_size=2,
            min_gap=5,
        )
        assert result.unl == ["INC1", "CHL"]
        assert result.alternates == []

    def test_progressive_displacement(self):
        """Each successful displacement raises the bar for the next challenger."""
        result = select_unl(
            _result([
                ("INC1", 80), ("INC2", 44), ("INC3", 42),
                ("CHL1", 55), ("CHL2", 53),
            ]),
            previous_unl=["INC1", "INC2", "INC3"],
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        # CHL1 (55) vs weakest INC3 (42): 55 >= 42+5 → displaces
        # CHL2 (53) vs new weakest INC2 (44): 53 >= 44+5=49 → displaces
        assert result.unl == ["INC1", "CHL1", "CHL2"]
        assert set(result.alternates) == {"INC2", "INC3"}

    def test_progressive_displacement_second_challenger_fails(self):
        """Second challenger doesn't clear the raised bar."""
        result = select_unl(
            _result([
                ("INC1", 80), ("INC2", 44), ("INC3", 42),
                ("CHL1", 55), ("CHL2", 48),
            ]),
            previous_unl=["INC1", "INC2", "INC3"],
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        # CHL1 (55) vs INC3 (42): 55 >= 47 → displaces
        # CHL2 (48) vs INC2 (44): 48 >= 49? No → stays alternate
        assert result.unl == ["INC1", "CHL1", "INC2"]
        assert set(result.alternates) == {"CHL2", "INC3"}

    def test_more_incumbents_leave_than_challengers(self):
        """UNL shrinks when there aren't enough challengers to fill vacancies."""
        result = select_unl(
            _result([("INC1", 80), ("INC2", 30), ("INC3", 20), ("CHL", 50)]),
            previous_unl=["INC1", "INC2", "INC3"],
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        assert result.unl == ["INC1", "CHL"]
        assert result.alternates == []

    def test_all_incumbents_below_cutoff(self):
        """All incumbents drop out — challengers fill freely."""
        result = select_unl(
            _result([("INC1", 30), ("INC2", 20), ("CHL1", 60), ("CHL2", 50)]),
            previous_unl=["INC1", "INC2"],
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == ["CHL1", "CHL2"]
        assert result.alternates == []

    def test_all_validators_below_cutoff_with_previous_unl(self):
        result = select_unl(
            _result([("INC", 30), ("CHL", 20)]),
            previous_unl=["INC"],
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == []
        assert result.alternates == []

    def test_incumbent_disappears_from_network(self):
        """Validator on previous UNL is absent from scoring result entirely."""
        result = select_unl(
            _result([("INC1", 80), ("CHL", 50)]),
            previous_unl=["INC1", "GONE"],
            cutoff=40,
            max_size=2,
            min_gap=5,
        )
        assert result.unl == ["INC1", "CHL"]
        assert result.alternates == []

    def test_empty_previous_unl_treated_as_first_round(self):
        result = select_unl(
            _result([("A", 90), ("B", 80)]),
            previous_unl=[],
            cutoff=40,
            max_size=35,
            min_gap=5,
        )
        assert result.unl == ["A", "B"]
        assert result.alternates == []


# ---------------------------------------------------------------------------
# Alternates ordering
# ---------------------------------------------------------------------------


class TestAlternatesOrdering:
    def test_alternates_ordered_by_score_descending(self):
        validators = [(f"V{i:03d}", 90 - i) for i in range(8)]
        result = select_unl(
            _result(validators),
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        assert result.alternates == ["V003", "V004", "V005", "V006", "V007"]

    def test_displaced_incumbents_appear_in_alternates(self):
        result = select_unl(
            _result([("INC1", 80), ("INC2", 42), ("CHL", 55)]),
            previous_unl=["INC1", "INC2"],
            cutoff=40,
            max_size=2,
            min_gap=5,
        )
        assert result.alternates == ["INC2"]


# ---------------------------------------------------------------------------
# Hard cap enforcement — Design.md lines 81–87
# ---------------------------------------------------------------------------


class TestHardCapEnforcement:
    def test_oversize_surviving_incumbents_trimmed_to_max_size(self):
        """Four incumbents all clearing the cutoff with max_size=3 → three on UNL."""
        result = select_unl(
            _result([("A", 88), ("B", 85), ("C", 85), ("D", 83)]),
            previous_unl=["A", "B", "C", "D"],
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        assert len(result.unl) == 3
        # The lowest-scored incumbent (D) drops to alternates by the cap.
        assert result.unl == ["A", "B", "C"]
        assert result.alternates == ["D"]

    def test_churn_protection_operates_inside_cap_only(self):
        """Challenger below min_gap above weakest incumbent stays in alternates."""
        result = select_unl(
            _result([("A", 80), ("B", 50), ("CHL", 52)]),
            previous_unl=["A", "B"],
            cutoff=40,
            max_size=2,
            min_gap=5,
        )
        # CHL (52) vs weakest incumbent B (50) — gap 2 < 5 → incumbent stays.
        # UNL size remains exactly max_size; CHL does not grow it.
        assert len(result.unl) == 2
        assert result.unl == ["A", "B"]
        assert result.alternates == ["CHL"]

    def test_cap_tightening_convergence_in_one_round(self):
        """
        Devnet scenario: a previous UNL of size 4 under max_size=3
        converges to a UNL of size 3 on the next round (no waiting needed).
        """
        result = select_unl(
            _result(
                [("V1", 90), ("V2", 85), ("V3", 80), ("V4", 75), ("CHL", 60)]
            ),
            previous_unl=["V1", "V2", "V3", "V4"],
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        # Four cutoff-passing incumbents with max_size=3 must converge to
        # exactly 3 on the UNL — no "effective max = previous_unl_size" drift.
        assert len(result.unl) == 3
        assert result.unl == ["V1", "V2", "V3"]
        # V4 drops to alternates by the cap; CHL fails min_gap vs V3 (80),
        # so CHL also goes to alternates. Sorted by score desc.
        assert result.alternates == ["V4", "CHL"]

    def test_cutoff_interaction_with_hard_cap(self):
        """
        Cutoff-failing incumbents do not count as "surviving", so cap
        enforcement operates on the post-cutoff incumbent set. A previous
        UNL of size 4 with one incumbent dropping below cutoff has 3
        survivors — the same size as max_size — so no incumbent is
        cap-displaced; a challenger must instead clear min_gap against
        the weakest surviving incumbent to enter.
        """
        result = select_unl(
            _result(
                [
                    ("A", 80),  # incumbent, passes cutoff
                    ("B", 70),  # incumbent, passes cutoff
                    ("C", 30),  # incumbent, FAILS cutoff (not "surviving")
                    ("D", 50),  # incumbent, passes cutoff
                    ("CHL", 60),  # new challenger
                ]
            ),
            previous_unl=["A", "B", "C", "D"],
            cutoff=40,
            max_size=3,
            min_gap=5,
        )
        # Surviving incumbents (post-cutoff): {A, B, D} — fits max_size, no
        # cap trim. CHL (60) vs weakest surviving incumbent D (50) — gap 10
        # ≥ 5 → swap succeeds; D moves to alternates.
        assert len(result.unl) == 3
        assert result.unl == ["A", "B", "CHL"]
        assert result.alternates == ["D"]


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    def test_uses_settings_when_no_overrides(self):
        result = select_unl(
            _result([("A", 90), ("B", 80)]),
        )
        assert isinstance(result, UNLSelectionResult)
        assert "A" in result.unl
