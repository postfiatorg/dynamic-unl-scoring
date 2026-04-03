"""UNL inclusion logic with churn control.

Takes scored validators and an optional previous UNL, produces a new UNL
(up to max_size validators) and an alternates list. Churn control prevents
UNL oscillation by requiring challengers to exceed the weakest incumbent
by a configurable minimum score gap.
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

    scores = {v.master_key: v.score for v in scoring_result.validator_scores}
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
        surviving_incumbents = [v for v in qualified if v.master_key in previous_unl_set]
        challengers = [v for v in qualified if v.master_key not in previous_unl_set]

        unl = list(surviving_incumbents)

        open_seats = max_size - len(unl)
        remaining_challengers = []

        for challenger in challengers:
            if open_seats > 0:
                unl.append(challenger)
                open_seats -= 1
            else:
                weakest = min(unl, key=lambda v: (v.score, v.master_key))
                if challenger.score >= weakest.score + min_gap:
                    unl.remove(weakest)
                    unl.append(challenger)
                    remaining_challengers.append(weakest)
                else:
                    remaining_challengers.append(challenger)

        unl.sort(key=lambda v: (-v.score, v.master_key))
        remaining_challengers.sort(key=lambda v: (-v.score, v.master_key))

        unl_keys = [v.master_key for v in unl]
        alternate_keys = [v.master_key for v in remaining_challengers]

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
