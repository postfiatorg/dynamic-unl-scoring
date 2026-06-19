"""Foundation-side commitment verification for M2.6 convergence monitoring.

Turns the raw commit and reveal memos ingested by the chain watcher into a
per-validator participation verdict for each scoring round. For every observed
committer it selects the accepted commit and reveal by validated-ledger order,
verifies the validator master-key signatures, recomputes the commitment to
confirm the reveal binds to its commit, classifies submission timing against the
round's announced windows, and — for an accepted reveal — compares the revealed
output hashes to the foundation's own.

The cryptography is not reimplemented here: the shared `commit_reveal` module is
reused verbatim, the same module the validator sidecar vendors, so both sides
agree exactly on what a valid submission is. This stage is strictly
observational and never affects canonical Validator List publication.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import psycopg2.extras

from scoring_service.services.commit_reveal import (
    MODEL_RESPONSE_HASH,
    SELECTED_UNL_HASH,
    VALIDATOR_SCORES_HASH,
    reveal_matches_commit,
    validate_commit_payload,
    validate_reveal_payload,
    verify_commit_signature,
    verify_reveal_signature,
)

logger = logging.getLogger(__name__)

VERIFICATION_HASHES_FILE_PATH = "outputs/verification_hashes.json"
# Convergence comparison levels, in pipeline order, named to match the shared
# failure taxonomy in docs/phase2/SidecarScoringSpec.md.
LEVEL_RAW = "RAW"
LEVEL_PARSED = "PARSED"
LEVEL_SELECTED_UNL = "SELECTED_UNL"
CATEGORY_OUTPUT_DIVERGENCE = "OUTPUT_DIVERGENCE"
_LEVELS = (
    (LEVEL_RAW, MODEL_RESPONSE_HASH),
    (LEVEL_PARSED, VALIDATOR_SCORES_HASH),
    (LEVEL_SELECTED_UNL, SELECTED_UNL_HASH),
)


class Outcome(str, Enum):
    VALID = "valid"
    DIVERGENT = "divergent"
    MISSING_REVEAL = "missing_reveal"
    LATE = "late"
    COMMITMENT_MISMATCH = "commitment_mismatch"
    SIGNATURE_INVALID = "signature_invalid"


@dataclass(frozen=True)
class RoundWindows:
    commit_opens_at: datetime
    commit_closes_at: datetime
    reveal_opens_at: datetime
    reveal_closes_at: datetime


@dataclass(frozen=True)
class ValidatorOutcome:
    validator_master_key: str
    outcome: Outcome
    accepted_commit_tx: str | None
    accepted_reveal_tx: str | None
    conflicting_commit: bool
    conflicting_reveal: bool
    comparison_levels_matched: str | None = None
    divergence_stage: str | None = None
    divergence_category: str | None = None


@dataclass(frozen=True)
class LevelComparison:
    levels_matched: str | None       # comma-joined RAW,PARSED,SELECTED_UNL; None when not comparable
    divergence_stage: str | None     # first diverging level, or None when all match / not comparable
    divergence_category: str | None  # OUTPUT_DIVERGENCE when diverged, else None
    divergent: bool


# ---------------------------------------------------------------------------
# Pure classification
# ---------------------------------------------------------------------------


def _ledger_key(row: dict) -> tuple[int, int]:
    return (row["ledger_index"], row["transaction_index"])


def _within(close_time, opens_at, closes_at) -> bool:
    """Protocol half-open window membership: opens_at <= t < closes_at."""
    if close_time is None or opens_at is None or closes_at is None:
        return False
    return opens_at <= close_time < closes_at


def _commit_signature_ok(row: dict) -> bool:
    try:
        return verify_commit_signature(row["payload"])
    except Exception:
        return False


def _reveal_signature_ok(row: dict) -> bool:
    try:
        return verify_reveal_signature(row["payload"])
    except Exception:
        return False


def _reveal_binds_to_commit(reveal_row: dict, commit_row: dict) -> bool:
    try:
        return reveal_matches_commit(
            validate_reveal_payload(reveal_row["payload"]),
            validate_commit_payload(commit_row["payload"]),
        )
    except Exception:
        return False


def _reveal_fingerprint(row: dict) -> tuple:
    return (
        row.get("model_response_hash"),
        row.get("validator_scores_hash"),
        row.get("selected_unl_hash"),
        row.get("salt"),
    )


def compare_levels(reveal_row: dict, foundation_hashes: dict | None) -> LevelComparison:
    """Compare a reveal's output hashes to the foundation's at each level.

    Walks the reproducible levels in pipeline order (raw response, parsed
    scores, selected UNL), recording which matched and the first that diverged.
    Divergence requires positive evidence — absent foundation hashes (or an
    absent level) cannot prove it, so an unpublished foundation artifact yields
    a non-divergent, not-comparable result rather than a false divergence.
    """
    if not foundation_hashes:
        return LevelComparison(
            levels_matched=None,
            divergence_stage=None,
            divergence_category=None,
            divergent=False,
        )
    matched: list[str] = []
    first_divergence: str | None = None
    for level, field in _LEVELS:
        revealed = reveal_row.get(field)
        expected = foundation_hashes.get(field)
        if revealed is None or expected is None:
            continue
        if revealed == expected:
            matched.append(level)
        elif first_divergence is None:
            first_divergence = level
    divergent = first_divergence is not None
    return LevelComparison(
        levels_matched=",".join(matched),
        divergence_stage=first_divergence,
        divergence_category=CATEGORY_OUTPUT_DIVERGENCE if divergent else None,
        divergent=divergent,
    )


def classify_validator(
    validator_master_key: str,
    commit_rows: list[dict],
    reveal_rows: list[dict],
    windows: RoundWindows,
    foundation_hashes: dict | None,
) -> ValidatorOutcome:
    """Classify one committer's participation for a round.

    Accepted submissions are the first valid ones by validated-ledger order.
    Conflicting same-validator submissions are flagged, not dropped.
    """
    commits = sorted(commit_rows, key=_ledger_key)
    signed_commits = [c for c in commits if _commit_signature_ok(c)]
    valid_commits = [
        c
        for c in signed_commits
        if _within(c["ledger_close_time"], windows.commit_opens_at, windows.commit_closes_at)
    ]
    # Conflicts are scoped to valid (signed, in-window) submissions — the same
    # set the accepted submission is drawn from — so an early or out-of-window
    # stray is not mistaken for a conflicting duplicate.
    conflicting_commit = len({c["commitment_hash"] for c in valid_commits}) > 1
    accepted_commit = valid_commits[0] if valid_commits else None

    if accepted_commit is None:
        outcome = Outcome.LATE if signed_commits else Outcome.SIGNATURE_INVALID
        return ValidatorOutcome(
            validator_master_key, outcome, None, None, conflicting_commit, False
        )

    reveals = sorted(reveal_rows, key=_ledger_key)
    signed_reveals = [r for r in reveals if _reveal_signature_ok(r)]
    valid_reveals = [
        r
        for r in signed_reveals
        if _within(r["ledger_close_time"], windows.reveal_opens_at, windows.reveal_closes_at)
    ]
    conflicting_reveal = len({_reveal_fingerprint(r) for r in valid_reveals}) > 1

    accepted_reveal = next(
        (r for r in valid_reveals if _reveal_binds_to_commit(r, accepted_commit)),
        None,
    )

    if accepted_reveal is not None:
        comparison = compare_levels(accepted_reveal, foundation_hashes)
        outcome = Outcome.DIVERGENT if comparison.divergent else Outcome.VALID
        return ValidatorOutcome(
            validator_master_key,
            outcome,
            accepted_commit["tx_hash"],
            accepted_reveal["tx_hash"],
            conflicting_commit,
            conflicting_reveal,
            comparison.levels_matched,
            comparison.divergence_stage,
            comparison.divergence_category,
        )

    # No accepted reveal: report the strongest anomaly in a fixed precedence —
    # a valid-but-non-binding reveal (a changed answer) outranks a bad
    # signature, which outranks a correct-but-late reveal, which outranks no
    # reveal at all.
    if any(not _reveal_binds_to_commit(r, accepted_commit) for r in valid_reveals):
        outcome = Outcome.COMMITMENT_MISMATCH
    elif any(not _reveal_signature_ok(r) for r in reveals):
        outcome = Outcome.SIGNATURE_INVALID
    elif any(_reveal_binds_to_commit(r, accepted_commit) for r in signed_reveals):
        outcome = Outcome.LATE
    else:
        outcome = Outcome.MISSING_REVEAL

    return ValidatorOutcome(
        validator_master_key,
        outcome,
        accepted_commit["tx_hash"],
        None,
        conflicting_commit,
        conflicting_reveal,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def load_round_windows(conn, round_number: int) -> RoundWindows | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT commit_opens_at, commit_closes_at, reveal_opens_at, reveal_closes_at
        FROM round_announcements
        WHERE round_number = %s
        """,
        (round_number,),
    )
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return None
    return RoundWindows(row[0], row[1], row[2], row[3])


def _load_submissions(conn, table: str, round_number: int) -> list[dict]:
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        f"SELECT * FROM {table} WHERE round_number = %s",  # noqa: S608 - fixed table names
        (round_number,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    return rows


def load_commits(conn, round_number: int) -> list[dict]:
    return _load_submissions(conn, "validator_commits", round_number)


def load_reveals(conn, round_number: int) -> list[dict]:
    return _load_submissions(conn, "validator_reveals", round_number)


def load_foundation_hashes(conn, round_number: int) -> dict | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT content FROM audit_trail_files
        WHERE round_number = %s AND file_path = %s
        """,
        (round_number, VERIFICATION_HASHES_FILE_PATH),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


def upsert_outcome(conn, round_number: int, outcome: ValidatorOutcome) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO validator_round_outcomes (
            round_number, validator_master_key, outcome, accepted_commit_tx,
            accepted_reveal_tx, conflicting_commit, conflicting_reveal,
            comparison_levels_matched, divergence_stage, divergence_category
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (round_number, validator_master_key) DO UPDATE SET
            outcome = EXCLUDED.outcome,
            accepted_commit_tx = EXCLUDED.accepted_commit_tx,
            accepted_reveal_tx = EXCLUDED.accepted_reveal_tx,
            conflicting_commit = EXCLUDED.conflicting_commit,
            conflicting_reveal = EXCLUDED.conflicting_reveal,
            comparison_levels_matched = EXCLUDED.comparison_levels_matched,
            divergence_stage = EXCLUDED.divergence_stage,
            divergence_category = EXCLUDED.divergence_category,
            computed_at = now()
        """,
        (
            round_number,
            outcome.validator_master_key,
            outcome.outcome.value,
            outcome.accepted_commit_tx,
            outcome.accepted_reveal_tx,
            outcome.conflicting_commit,
            outcome.conflicting_reveal,
            outcome.comparison_levels_matched,
            outcome.divergence_stage,
            outcome.divergence_category,
        ),
    )
    cursor.close()


def verify_round(conn, round_number: int) -> dict:
    """Recompute and persist every committer's outcome for one round.

    Returns a summary; a round with no ingested announcement has no window
    source and is reported as unverifiable rather than guessed.
    """
    windows = load_round_windows(conn, round_number)
    if windows is None:
        return {"round_number": round_number, "verified": False, "reason": "no_announcement"}

    foundation_hashes = load_foundation_hashes(conn, round_number)
    grouped: dict[str, dict[str, list[dict]]] = {}
    for commit in load_commits(conn, round_number):
        key = commit.get("validator_master_key")
        if key is None:
            continue
        grouped.setdefault(key, {"commits": [], "reveals": []})["commits"].append(commit)
    for reveal in load_reveals(conn, round_number):
        key = reveal.get("validator_master_key")
        if key in grouped:
            grouped[key]["reveals"].append(reveal)

    counts: dict[str, int] = {}
    for key, group in grouped.items():
        outcome = classify_validator(
            key, group["commits"], group["reveals"], windows, foundation_hashes
        )
        upsert_outcome(conn, round_number, outcome)
        counts[outcome.outcome.value] = counts.get(outcome.outcome.value, 0) + 1

    return {
        "round_number": round_number,
        "verified": True,
        "committers": len(grouped),
        "outcomes": counts,
    }


def verify_active_rounds(conn) -> list[dict]:
    """Verify every round that has an ingested announcement and at least one
    commit, refreshing outcomes as new submissions arrive."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT a.round_number
        FROM round_announcements a
        WHERE EXISTS (
            SELECT 1 FROM validator_commits c WHERE c.round_number = a.round_number
        )
        """
    )
    rounds = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return [verify_round(conn, round_number) for round_number in rounds]
