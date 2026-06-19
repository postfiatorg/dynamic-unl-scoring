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

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

import psycopg2.extras

from scoring_service.config import settings
from scoring_service.services.commit_reveal import (
    CONVERGENCE_REPORT_TYPE,
    MODEL_RESPONSE_HASH,
    PROTOCOL_VERSION,
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
    commit, refreshing outcomes as new submissions arrive. A sealed round is
    final and is skipped — its outcomes no longer change."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT a.round_number
        FROM round_announcements a
        WHERE EXISTS (
            SELECT 1 FROM validator_commits c WHERE c.round_number = a.round_number
        )
        AND NOT EXISTS (
            SELECT 1 FROM convergence_reports r WHERE r.round_number = a.round_number
        )
        """
    )
    rounds = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return [verify_round(conn, round_number) for round_number in rounds]


# ---------------------------------------------------------------------------
# Report assembly and sealing
# ---------------------------------------------------------------------------

_OUTCOME_COLUMNS = (
    "validator_master_key",
    "outcome",
    "accepted_commit_tx",
    "accepted_reveal_tx",
    "conflicting_commit",
    "conflicting_reveal",
    "comparison_levels_matched",
    "divergence_stage",
    "divergence_category",
)


def _load_sealed_report(conn, round_number: int) -> dict | None:
    """Return `{convergence_bundle_cid, anchor_tx_hash}` for a sealed round, or
    None if the round is not sealed yet."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT convergence_bundle_cid, anchor_tx_hash FROM convergence_reports "
        "WHERE round_number = %s",
        (round_number,),
    )
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return None
    return {"convergence_bundle_cid": row[0], "anchor_tx_hash": row[1]}


def _load_announcement_meta(conn, round_number: int) -> dict | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT network, input_package_hash, input_package_cid,
               reveal_opens_at, reveal_closes_at
        FROM round_announcements
        WHERE round_number = %s
        """,
        (round_number,),
    )
    row = cursor.fetchone()
    cursor.close()
    if row is None:
        return None
    return {
        "network": row[0],
        "input_package_hash": row[1],
        "input_package_cid": row[2],
        "reveal_opens_at": row[3],
        "reveal_closes_at": row[4],
    }


def _load_outcome_rows(conn, round_number: int) -> list[dict]:
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        f"SELECT {', '.join(_OUTCOME_COLUMNS)} FROM validator_round_outcomes "
        "WHERE round_number = %s ORDER BY validator_master_key",
        (round_number,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    return rows


def _summarize(participants: list[dict]) -> dict:
    outcomes: dict[str, int] = {}
    levels_matched: dict[str, int] = {}
    divergence_categories: dict[str, int] = {}
    for p in participants:
        outcomes[p["outcome"]] = outcomes.get(p["outcome"], 0) + 1
        if p.get("comparison_levels_matched"):
            for level in p["comparison_levels_matched"].split(","):
                if level:
                    levels_matched[level] = levels_matched.get(level, 0) + 1
        category = p.get("divergence_category")
        if category:
            divergence_categories[category] = divergence_categories.get(category, 0) + 1
    return {
        "committers": len(participants),
        "outcomes": outcomes,
        "levels_matched": levels_matched,
        "divergence_categories": divergence_categories,
    }


def assemble_report(conn, round_number: int) -> dict | None:
    """Build the per-round convergence report from stored outcomes.

    The population is the observed committers (the per-validator outcome rows);
    participation is open, so there is no assumed roster. Returns None when the
    round has no ingested announcement to bind the report to.
    """
    meta = _load_announcement_meta(conn, round_number)
    if meta is None:
        return None
    participants = _load_outcome_rows(conn, round_number)
    return {
        "type": CONVERGENCE_REPORT_TYPE,
        "protocol_version": PROTOCOL_VERSION,
        "network": meta["network"],
        "round_number": round_number,
        "input_package_hash": meta["input_package_hash"],
        "input_package_cid": meta["input_package_cid"],
        "participants": participants,
        "summary": _summarize(participants),
    }


def _seal_grace(reveal_opens_at: datetime, reveal_closes_at: datetime) -> timedelta:
    window_seconds = max(0.0, (reveal_closes_at - reveal_opens_at).total_seconds())
    grace_seconds = max(
        settings.convergence_seal_grace_floor_seconds,
        settings.convergence_seal_grace_fraction * window_seconds,
    )
    return timedelta(seconds=grace_seconds)


def seal_deadline(meta: dict) -> datetime:
    """The instant a round becomes sealable: reveal-close plus the grace period."""
    return meta["reveal_closes_at"] + _seal_grace(
        meta["reveal_opens_at"], meta["reveal_closes_at"]
    )


def _insert_convergence_report(conn, round_number: int, cid: str, report: dict) -> bool:
    """Persist the sealed report. Returns False if the round was already sealed,
    enforcing seal-once via the round_number primary key."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO convergence_reports (round_number, convergence_bundle_cid, report)
        VALUES (%s, %s, %s)
        ON CONFLICT (round_number) DO NOTHING
        """,
        (round_number, cid, json.dumps(report, sort_keys=True, default=str)),
    )
    inserted = cursor.rowcount == 1
    cursor.close()
    return inserted


def _set_anchor_tx(conn, round_number: int, tx_hash: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE convergence_reports SET anchor_tx_hash = %s WHERE round_number = %s",
        (tx_hash, round_number),
    )
    cursor.close()


def _anchor_report(conn, round_number: int, cid: str, onchain_publisher) -> str | None:
    """Submit the on-chain anchor memo and persist its tx hash. On failure the
    anchor_tx_hash is left NULL and an error is logged, so a later pass retries
    rather than dropping the anchor permanently."""
    anchor_tx = onchain_publisher.publish_convergence_report(
        round_number=round_number, convergence_bundle_cid=cid
    )
    if anchor_tx:
        _set_anchor_tx(conn, round_number, anchor_tx)
    else:
        logger.error(
            "Convergence report for round %d is sealed but its on-chain anchor "
            "failed; it will be retried on a later pass",
            round_number,
        )
    return anchor_tx


def seal_round(conn, round_number: int, *, ipfs_publisher, onchain_publisher) -> dict:
    """Assemble, pin, persist, and anchor a round's convergence report once.

    Seal-once is enforced by the convergence_reports primary key. A round that
    is already sealed but whose anchor never landed is re-anchored without
    re-pinning, so a transient chain failure does not permanently drop the
    anchor; pinning the same content again is a no-op, and a duplicate anchor is
    never submitted for an already-anchored round.
    """
    existing = _load_sealed_report(conn, round_number)
    if existing is not None:
        if existing["anchor_tx_hash"]:
            return {"round_number": round_number, "sealed": False, "reason": "already_sealed"}
        anchor_tx = _anchor_report(
            conn, round_number, existing["convergence_bundle_cid"], onchain_publisher
        )
        return {
            "round_number": round_number,
            "sealed": True,
            "convergence_bundle_cid": existing["convergence_bundle_cid"],
            "anchor_tx_hash": anchor_tx,
            "reason": "anchor_retry",
        }

    report = assemble_report(conn, round_number)
    if report is None:
        return {"round_number": round_number, "sealed": False, "reason": "no_announcement"}

    cid = ipfs_publisher.publish_convergence_report(round_number, report)
    if cid is None:
        return {"round_number": round_number, "sealed": False, "reason": "pin_failed"}

    if not _insert_convergence_report(conn, round_number, cid, report):
        # Lost the insert race; re-anchor only if the winner has not anchored yet.
        winner = _load_sealed_report(conn, round_number)
        if winner is not None and not winner["anchor_tx_hash"]:
            anchor_tx = _anchor_report(
                conn, round_number, winner["convergence_bundle_cid"], onchain_publisher
            )
            return {
                "round_number": round_number,
                "sealed": True,
                "convergence_bundle_cid": winner["convergence_bundle_cid"],
                "anchor_tx_hash": anchor_tx,
                "reason": "anchor_retry",
            }
        return {"round_number": round_number, "sealed": False, "reason": "already_sealed"}

    anchor_tx = _anchor_report(conn, round_number, cid, onchain_publisher)
    return {
        "round_number": round_number,
        "sealed": True,
        "convergence_bundle_cid": cid,
        "anchor_tx_hash": anchor_tx,
    }


def _sealable_rounds(conn, now: datetime) -> list[int]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT a.round_number, a.reveal_opens_at, a.reveal_closes_at
        FROM round_announcements a
        WHERE EXISTS (
            SELECT 1 FROM validator_commits c WHERE c.round_number = a.round_number
        )
        AND NOT EXISTS (
            SELECT 1 FROM convergence_reports r WHERE r.round_number = a.round_number
        )
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    due = []
    for round_number, reveal_opens_at, reveal_closes_at in rows:
        deadline = seal_deadline(
            {"reveal_opens_at": reveal_opens_at, "reveal_closes_at": reveal_closes_at}
        )
        if now >= deadline:
            due.append(round_number)
    return due


def _unanchored_rounds(conn) -> list[int]:
    """Sealed rounds whose on-chain anchor has not landed yet, for retry."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT round_number FROM convergence_reports WHERE anchor_tx_hash IS NULL"
    )
    rounds = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return rounds


def seal_due_rounds(conn, now: datetime, *, ipfs_publisher, onchain_publisher) -> list[dict]:
    """Seal every unsealed round whose grace deadline has passed by `now`, and
    re-anchor any already-sealed round whose on-chain anchor failed earlier.

    `now` must be validated-ledger close time, so the foundation and validators
    agree on when each round closed.
    """
    rounds = list(dict.fromkeys([*_sealable_rounds(conn, now), *_unanchored_rounds(conn)]))
    return [
        seal_round(
            conn,
            round_number,
            ipfs_publisher=ipfs_publisher,
            onchain_publisher=onchain_publisher,
        )
        for round_number in rounds
    ]
