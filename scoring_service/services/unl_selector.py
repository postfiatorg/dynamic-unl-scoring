"""UNL inclusion logic with churn control.

Takes scored validators and an optional previous UNL, produces a new UNL
(capped at ``max_size``) and an alternates list. Churn control prevents
UNL oscillation by requiring challengers to exceed the weakest incumbent
by a configurable minimum score gap.

UNL size is a hard cap. If more than ``max_size`` candidates clear the cutoff, 
the top ``max_size`` by rank are placed on the UNL; the remainder go to alternates.
Churn control (``min_gap``) only modifies swap decisions within the cap —
it does not allow the UNL to grow beyond ``max_size`` to protect incumbents.
"""

import logging
from dataclasses import dataclass

from scoring_service.config import settings
from scoring_service.services.response_parser import ScoringResult

logger = logging.getLogger(__name__)


@dataclass
class UNLSelectionResult:
    """Output of the UNL selection algorithm."""

    unl: list[str]
    alternates: list[str]


def select_unl(
    scoring_result: ScoringResult,
    previous_unl: list[str] | None = None,
    cutoff: int | None = None,
    max_size: int | None = None,
    min_gap: int | None = None,
) -> UNLSelectionResult:
    """Select validators for the UNL from a scoring result.

    Args:
        scoring_result: Validated scoring output from the LLM.
        previous_unl: Master keys on the previous round's UNL. None or empty
            for the first round (no churn control applied).
        cutoff: Minimum score to qualify. Defaults to settings.unl_score_cutoff.
        max_size: Maximum UNL size. Defaults to settings.unl_max_size.
        min_gap: Minimum score margin for challenger displacement.
            Defaults to settings.unl_min_score_gap.

    Returns:
        UNLSelectionResult with ordered UNL and alternates lists (master keys).
    """
    cutoff = cutoff if cutoff is not None else settings.unl_score_cutoff
    max_size = max_size if max_size is not None else settings.unl_max_size
    min_gap = min_gap if min_gap is not None else settings.unl_min_score_gap

    qualified = sorted(
        [v for v in scoring_result.validator_scores if v.score >= cutoff],
        key=lambda v: (-v.score, v.master_key),
    )

    if not qualified:
        logger.warning("No validators above cutoff %d — UNL is empty", cutoff)
        return UNLSelectionResult(unl=[], alternates=[])

    is_first_round = not previous_unl
    previous_unl_set = set(previous_unl) if previous_unl else set()

    if is_first_round:
        unl_keys = [v.master_key for v in qualified[:max_size]]
        alternate_keys = [v.master_key for v in qualified[max_size:]]
    else:
        # Incumbents that cleared the cutoff, strongest-first.
        surviving_incumbents = sorted(
            [v for v in qualified if v.master_key in previous_unl_set],
            key=lambda v: (-v.score, v.master_key),
        )

        # Enforce the hard cap on incumbents: if more passing incumbents
        # exist than seats, the lowest-ranked drop to alternates. Churn
        # control is a swap modifier, not a licence to grow past max_size.
        if len(surviving_incumbents) > max_size:
            capped_incumbents = surviving_incumbents[:max_size]
            cap_displaced_incumbents = surviving_incumbents[max_size:]
        else:
            capped_incumbents = surviving_incumbents
            cap_displaced_incumbents = []

        unl = list(capped_incumbents)
        challengers = [
            v for v in qualified if v.master_key not in previous_unl_set
        ]

        # Fill any open seats with the top challengers (no gap required when
        # no incumbent is being displaced), then test remaining challengers
        # against the current weakest for min_gap-qualified swaps.
        open_seats = max_size - len(unl)
        remaining_challengers = []

        for challenger in challengers:
            if open_seats > 0:
                unl.append(challenger)
                open_seats -= 1
                continue

            weakest = min(unl, key=lambda v: (v.score, v.master_key))
            if challenger.score >= weakest.score + min_gap:
                unl.remove(weakest)
                unl.append(challenger)
                remaining_challengers.append(weakest)
            else:
                remaining_challengers.append(challenger)

        unl.sort(key=lambda v: (-v.score, v.master_key))

        # Alternates combine incumbents displaced by the cap, incumbents
        # displaced by a successful challenger swap, and challengers that
        # didn't clear the min_gap bar. All re-sorted by score desc.
        alternates = cap_displaced_incumbents + remaining_challengers
        alternates.sort(key=lambda v: (-v.score, v.master_key))

        unl_keys = [v.master_key for v in unl]
        alternate_keys = [v.master_key for v in alternates]

    logger.info(
        "UNL selected: %d validators, %d alternates (cutoff=%d, max=%d, gap=%d, first_round=%s)",
        len(unl_keys),
        len(alternate_keys),
        cutoff,
        max_size,
        min_gap,
        is_first_round,
    )

    return UNLSelectionResult(unl=unl_keys, alternates=alternate_keys)
