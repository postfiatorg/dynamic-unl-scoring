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


# ---------------------------------------------------------------------------
# Round 15 regression — testnet, published outputs/validator_scores.json
# ---------------------------------------------------------------------------

# (master_key, overall score) pairs from testnet round 15
# (final bundle QmWh2yoq1N1dvrAYLsWjTQXWMqGucRLUGNKUDCpoCyBLcx). The round's
# rank-1 validator scored 92 while a validator with identical scoring
# evidence scored 88 — the model inconsistency that prompt v7 outlaws.
ROUND15_SCORES = [
    ("nHBM2nzq3pZUg8JsxvEt3G7gAAtc5Sukaef6YmvVx64uAoRK4QWM", 92),
    ("nHUUXMXfPEdnKAT8u2AB89LxTWT1tWsTecDPQURoMw2XJ2WP85MK", 92),
    ("nHBcLEB4S6moQGrhMjJo1jbp58WL5psHY9EMDWNAtdqykUYiA1rF", 91),
    ("nHByMXejvHJgjcGJ1f9bhcAGcFeNR6ecsDmzN4t3HkhyRHZtM6Lj", 91),
    ("nHDHCvsJi8UwHMAbkinuJhPYsG5ZR9rtmGAjJZwo8uibf8N1tz3e", 91),
    ("nHDfSHLutR7QqttAkx3AiYG2bukCdfAa3P9hrYL4yNJZQpvEpW1A", 91),
    ("nHUCEXpC5LhFAm1Mmf8TqrzVGt3QCuwWoW2V8PYynDpjZe8m8mHj", 91),
    ("nHUWciHX8W9PgM3sQmgkRiKpkuaJjTxFSyvZce4bP4WeMz81HefX", 91),
    ("nHUhL4QzULuXt2WK5v5mvzEMZSo6wM9ZWUaaQC1eYw2qa1ATFw1c", 91),
    ("nHBVTAUpHEoEctXcAWyC7nJhxUYULWKz1WZCuC1tSm2VnCxDshVS", 90),
    ("nHBgZupJspDsrg7mex4Z2vBQXqoN2aTHaLgf8jGxMDPw4MWLh3J6", 90),
    ("nHD3sPmhNtVXTXrZAGhsfHRhxhzFXKHNNxemTtGFr69SRd9q88dZ", 90),
    ("nHU74qX4tCQDSpE6zBS5PB3jybuGZJ7QMbeyLWDQRy3Lhb4DYDSR", 90),
    ("nHUif4sukXu9pJGyyBaeVMwmE8L1fJ5KJj4X4ksgTKhgjG6k96s2", 90),
    ("nHB81SsiwsituuAUrSx2j6kho5YdY5AwQ6SZLSqEiAKhzUQVHq53", 88),
    ("nHBcnQZ9a9UjZ7hbj9zWVXZ9kTcqheUkui32YdBTpQeAsE6BxWNG", 88),
    ("nHUc7VSYA6xvFakSvuTojJQucBNukKwmtguUG2HMT9Xp9dKzkpvJ", 88),
    ("nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe", 88),
    ("nHUso5gdgQnewAsk5QT1aFr897g6YLaL697iyuknmSqd7pbqz5Td", 88),
    ("nHUzc5XzsmweRV6aNyUQJD5eRUM4TT4tVCBv5DKx6T7Buq4gn9Lr", 88),
    ("nHBYKjxjbzxRzrS3XkhpgM7KXJ25jbgPHkbAjjSCQPm8PaPS5y4v", 86),
    ("nHBoG3rHafA3U3Yfs388GTA9z8t5ocE67qjhgb8aXkfYnDCM5CNE", 86),
    ("nHUSghNbHJoUbgAHsWHNb5Vu3E6YWrzGw1tYWtyTbP8WAf5v6Et1", 86),
    ("nHBSFFXC3UPAWgjZ4kCPr3jVPS9kXoJq5jCuzSKkAKqF9p6p5RMC", 85),
    ("nHUVtfC7ciU6ZdgN6hqhTMZGa6VPg5bketAtRhjA9qVo1n9HZRYk", 85),
    ("nHBWFVzxVYAVQNUFHoqnHw2SWhXKy1kKRr7oYAMFeu22rqsCLYCN", 82),
    ("nHU187ZGFcGHbLPbpdTgQyN3Ehp7dJJzr8huvEpeF3EziSsWhJuR", 82),
    ("nHUdwzTWTQJzebbxcanZG2ERXikMLU9aAZa8cHtxosfiKq5N7Vd5", 82),
    ("nHUmoQrfBrSE3yjCtk5ZrCUTqwKCLv6t6SgK9oCuuMkoExEYxc8i", 82),
    ("nHBAToXoTH6eZtC1cMJDvjG7eRb7ufZ3GUpeisvNVT4ofruRdVvd", 78),
    ("nHDDmWaS6iP8HNJ6rMGL2LupMVkVaCv3C9yaKnoQ39eQR79EUj48", 78),
    ("nHDUqGoM7KR1pgbdYBRgKpGKdFLhpnMzVbECs8RE73RGZm3Va6MJ", 78),
    ("nHUUz9WsyGPkNgEyLkuQGofh4PP2kXTq9XBjS1JiNRfFaZL8HnkH", 78),
    ("nHUW82415dUNULY4juLTFzoWpqZSPbrXv2uPRnijX8vuJCjNs3eY", 78),
    ("nHUXzRZk3CYqATxqjBdaKSvcmNDJLiYxkUcFiK4yVLSnzrZMBGdP", 78),
    ("nHUus5vM4463rd82Ws3YpcrREVrjHTBdoYgA6BdwDR3YcBiwG6hN", 78),
    ("nHBcLk5r1DVTpAGK8BkBtL7DPpGgp6mmB5MfkzB23MhcAEQHKCf1", 75),
    ("nHUganJh2fSS4QxYnsAUphNo3ZKHLQ15ExX29QpAGkvu6vFajnuQ", 75),
    ("nHBRLUW3tRVq1LyvSV6atV3xYbdnw6rigRi6rNwSGFCBnkTAyj3o", 72),
    ("nHDBj6Mq1DSpTRS4s2MKDfCEUk3iLa5JyS5JFZQUPpUcUy2m2fpk", 70),
    ("nHDEUdawsDpQYxKNohxTaHBVnfdnjSwsPGX5vtRN7m62NvEuxJYF", 70),
    ("nHUzVW1uviFL8YKAARxihiST1shYdKWKTgJTpTFDDgBxUydURwbE", 70),
    ("nHBTv4UpxUn2TWcLQHkKPWtycNXkbFeggFmbXtQYRd6kq5XH2J4B", 68),
    ("nHB6Zc7mhr7swksEgpwTE7Hw7SvZ9cz22T2MECMSXjBeMTeHXQB7", 65),
    ("nHBtS3cC2UDzoSANr9nz6HrLYaDY9uYJD2zs649dkLxN6pBfLFiu", 65),
    ("nHU7VBYL9Ux1dKAitMQo6YcF554i4yDSncRenpT34zhk4fG7CZxg", 60),
    ("nHU9mVWtfMxsmDGJYSwTHjAjuQDv817k6Y8VAw1DJjEgQoNMysDP", 55),
    ("nHUgi9MxYymj7CGS48gjm9TPZQcfRA47XUHFk9Vu5wDq1PqTZdYr", 25),
    ("nHUVxTi8XfXjaaJppw7mLSrYDRpkDpf8H9ypzgVKxfSXShcWwAoK", 20),
    ("nHDUU4JpcBy6MQuZDizyqMFyvrPjGusJYnBybwgnL1s1h9zfwr8D", 15),
]

ROUND15_OUTLIER_KEY = "nHBM2nzq3pZUg8JsxvEt3G7gAAtc5Sukaef6YmvVx64uAoRK4QWM"
ROUND15_TWIN_KEY = "nHUzc5XzsmweRV6aNyUQJD5eRUM4TT4tVCBv5DKx6T7Buq4gn9Lr"
ROUND15_TWIN_SCORE = 88
ROUND15_SELECTOR_PARAMS = {"cutoff": 40, "max_size": 20, "min_gap": 5}

# Round 14's published UNL (unl.json) — the churn-control context round 15's
# selection actually ran with.
ROUND14_UNL = [
    "nHBcLEB4S6moQGrhMjJo1jbp58WL5psHY9EMDWNAtdqykUYiA1rF",
    "nHB81SsiwsituuAUrSx2j6kho5YdY5AwQ6SZLSqEiAKhzUQVHq53",
    "nHByMXejvHJgjcGJ1f9bhcAGcFeNR6ecsDmzN4t3HkhyRHZtM6Lj",
    "nHDHCvsJi8UwHMAbkinuJhPYsG5ZR9rtmGAjJZwo8uibf8N1tz3e",
    "nHDfSHLutR7QqttAkx3AiYG2bukCdfAa3P9hrYL4yNJZQpvEpW1A",
    "nHUCEXpC5LhFAm1Mmf8TqrzVGt3QCuwWoW2V8PYynDpjZe8m8mHj",
    "nHUWciHX8W9PgM3sQmgkRiKpkuaJjTxFSyvZce4bP4WeMz81HefX",
    "nHUhL4QzULuXt2WK5v5mvzEMZSo6wM9ZWUaaQC1eYw2qa1ATFw1c",
    "nHBM2nzq3pZUg8JsxvEt3G7gAAtc5Sukaef6YmvVx64uAoRK4QWM",
    "nHBVTAUpHEoEctXcAWyC7nJhxUYULWKz1WZCuC1tSm2VnCxDshVS",
    "nHD3sPmhNtVXTXrZAGhsfHRhxhzFXKHNNxemTtGFr69SRd9q88dZ",
    "nHUc7VSYA6xvFakSvuTojJQucBNukKwmtguUG2HMT9Xp9dKzkpvJ",
    "nHUdwzTWTQJzebbxcanZG2ERXikMLU9aAZa8cHtxosfiKq5N7Vd5",
    "nHUif4sukXu9pJGyyBaeVMwmE8L1fJ5KJj4X4ksgTKhgjG6k96s2",
    "nHUkhbZe9ncdmhn6dbd5x7391ymwCS3YZEMWjysP9fSiDtau9YEe",
    "nHUso5gdgQnewAsk5QT1aFr897g6YLaL697iyuknmSqd7pbqz5Td",
    "nHUzc5XzsmweRV6aNyUQJD5eRUM4TT4tVCBv5DKx6T7Buq4gn9Lr",
    "nHBgZupJspDsrg7mex4Z2vBQXqoN2aTHaLgf8jGxMDPw4MWLh3J6",
    "nHU74qX4tCQDSpE6zBS5PB3jybuGZJ7QMbeyLWDQRy3Lhb4DYDSR",
    "nHUUXMXfPEdnKAT8u2AB89LxTWT1tWsTecDPQURoMw2XJ2WP85MK",
]


def _round15_corrected_scores() -> list[tuple[str, int]]:
    return [
        (key, ROUND15_TWIN_SCORE if key == ROUND15_OUTLIER_KEY else score)
        for key, score in ROUND15_SCORES
    ]


class TestRound15SelectionRegression:
    """Selection robustness against the round 15 overall-score anomaly.

    The v7 prompt rule that identical sub-score vectors yield identical
    overall scores would place the round 15 outlier at its evidence-twin's
    score of 88 instead of the published 92 — replays show the model does
    not reliably enforce this rule (see docs/ScoringPromptV7.md). Selection
    must be invariant to that correction: the same 20 validators are
    selected either way, so the anomaly class affects leaderboard optics
    only. Invariance is asserted both in pure ranking mode and with the
    round's real churn context (round 14's UNL).
    """

    def test_published_scores_select_twenty(self):
        result = select_unl(_result(ROUND15_SCORES), **ROUND15_SELECTOR_PARAMS)
        assert len(result.unl) == 20
        assert ROUND15_OUTLIER_KEY in result.unl

    def test_selection_invariant_to_outlier_correction(self):
        published = select_unl(_result(ROUND15_SCORES), **ROUND15_SELECTOR_PARAMS)
        corrected = select_unl(
            _result(_round15_corrected_scores()), **ROUND15_SELECTOR_PARAMS
        )

        assert set(corrected.unl) == set(published.unl)
        assert ROUND15_OUTLIER_KEY in corrected.unl
        assert ROUND15_TWIN_KEY in corrected.unl

    def test_selection_invariant_with_round14_churn_context(self):
        published = select_unl(
            _result(ROUND15_SCORES),
            previous_unl=ROUND14_UNL,
            **ROUND15_SELECTOR_PARAMS,
        )
        corrected = select_unl(
            _result(_round15_corrected_scores()),
            previous_unl=ROUND14_UNL,
            **ROUND15_SELECTOR_PARAMS,
        )

        assert len(published.unl) == 20
        assert set(corrected.unl) == set(published.unl)
        assert ROUND15_OUTLIER_KEY in corrected.unl
