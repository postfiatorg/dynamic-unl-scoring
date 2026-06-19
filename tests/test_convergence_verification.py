"""Tests for M2.6 commitment verification (per-validator outcome classification)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from xrpl.constants import CryptoAlgorithm
from xrpl.core import addresscodec, keypairs

from scoring_service.services.commit_reveal import (
    build_commit_payload,
    build_commit_signing_bytes,
    build_reveal_payload,
    build_reveal_signing_bytes,
    compute_commitment_hash,
)
from scoring_service.services import convergence_verification as cv
from scoring_service.services.convergence_verification import Outcome, RoundWindows

PROTO = 1
NETWORK = "devnet"
ROUND = 273
INPUT_HASH = "a" * 64
OUTPUT_HASHES = {
    "model_response_hash": "1" * 64,
    "validator_scores_hash": "2" * 64,
    "selected_unl_hash": "3" * 64,
}
OTHER_OUTPUT_HASHES = {
    "model_response_hash": "4" * 64,
    "validator_scores_hash": "5" * 64,
    "selected_unl_hash": "6" * 64,
}
SALT = "f" * 64
OTHER_SALT = "e" * 64

COMMIT_OPENS = datetime(2026, 5, 25, 0, 5, tzinfo=timezone.utc)
COMMIT_CLOSES = datetime(2026, 5, 25, 0, 30, tzinfo=timezone.utc)
REVEAL_OPENS = datetime(2026, 5, 25, 0, 30, tzinfo=timezone.utc)
REVEAL_CLOSES = datetime(2026, 5, 25, 1, 0, tzinfo=timezone.utc)
WINDOWS = RoundWindows(COMMIT_OPENS, COMMIT_CLOSES, REVEAL_OPENS, REVEAL_CLOSES)

IN_COMMIT = COMMIT_OPENS
IN_REVEAL = REVEAL_OPENS


def make_validator() -> tuple[str, str]:
    seed = keypairs.generate_seed(algorithm=CryptoAlgorithm.ED25519)
    public, private = keypairs.derive_keypair(seed)
    return addresscodec.encode_node_public_key(bytes.fromhex(public)), private


def signed_commit(master, priv, *, output_hashes=OUTPUT_HASHES, salt=SALT):
    commitment = compute_commitment_hash(
        protocol_version=PROTO, network=NETWORK, round_number=ROUND,
        validator_master_key=master, input_package_hash=INPUT_HASH,
        output_hashes=output_hashes, salt=salt,
    )
    msg = build_commit_signing_bytes(
        protocol_version=PROTO, network=NETWORK, round_number=ROUND,
        validator_master_key=master, input_package_hash=INPUT_HASH,
        commitment_hash=commitment,
    )
    return build_commit_payload(
        protocol_version=PROTO, network=NETWORK, round_number=ROUND,
        validator_master_key=master, input_package_hash=INPUT_HASH,
        commitment_hash=commitment, signature=keypairs.sign(msg, priv),
    )


def signed_reveal(master, priv, *, output_hashes=OUTPUT_HASHES, salt=SALT):
    msg = build_reveal_signing_bytes(
        protocol_version=PROTO, network=NETWORK, round_number=ROUND,
        validator_master_key=master, input_package_hash=INPUT_HASH,
        output_hashes=output_hashes, salt=salt,
    )
    return build_reveal_payload(
        protocol_version=PROTO, network=NETWORK, round_number=ROUND,
        validator_master_key=master, input_package_hash=INPUT_HASH,
        output_hashes=output_hashes, salt=salt, signature=keypairs.sign(msg, priv),
    )


def commit_row(payload, *, ledger_index=100, tx_index=0, close_time=IN_COMMIT, tx_hash="C1"):
    return {
        "tx_hash": tx_hash, "round_number": payload["round_number"],
        "validator_master_key": payload["validator_master_key"],
        "input_package_hash": payload["input_package_hash"],
        "commitment_hash": payload["commitment_hash"],
        "ledger_index": ledger_index, "transaction_index": tx_index,
        "ledger_close_time": close_time, "payload": payload,
    }


def reveal_row(payload, *, ledger_index=200, tx_index=0, close_time=IN_REVEAL, tx_hash="R1"):
    oh = payload["output_hashes"]
    return {
        "tx_hash": tx_hash, "round_number": payload["round_number"],
        "validator_master_key": payload["validator_master_key"],
        "input_package_hash": payload["input_package_hash"],
        "model_response_hash": oh["model_response_hash"],
        "validator_scores_hash": oh["validator_scores_hash"],
        "selected_unl_hash": oh["selected_unl_hash"], "salt": payload["salt"],
        "ledger_index": ledger_index, "transaction_index": tx_index,
        "ledger_close_time": close_time, "payload": payload,
    }


class TestClassifyValidator:
    def test_valid_when_reveal_matches_foundation(self):
        m, p = make_validator()
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))],
            WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.VALID
        assert out.accepted_commit_tx == "C1"
        assert out.accepted_reveal_tx == "R1"

    def test_divergent_when_output_differs_from_foundation(self):
        m, p = make_validator()
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))],
            WINDOWS, OTHER_OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.DIVERGENT

    def test_missing_reveal_when_commit_only(self):
        m, p = make_validator()
        out = cv.classify_validator(m, [commit_row(signed_commit(m, p))], [], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.MISSING_REVEAL
        assert out.accepted_reveal_tx is None

    def test_late_commit_at_window_close_is_excluded(self):
        m, p = make_validator()
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p), close_time=COMMIT_CLOSES)], [], WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.LATE

    def test_late_reveal_outside_window(self):
        m, p = make_validator()
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p))],
            [reveal_row(signed_reveal(m, p), close_time=REVEAL_CLOSES)],
            WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.LATE

    def test_commitment_mismatch_when_reveal_does_not_bind(self):
        m, p = make_validator()
        commit = commit_row(signed_commit(m, p, output_hashes=OUTPUT_HASHES, salt=SALT))
        reveal = reveal_row(signed_reveal(m, p, output_hashes=OTHER_OUTPUT_HASHES, salt=OTHER_SALT))
        out = cv.classify_validator(m, [commit], [reveal], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.COMMITMENT_MISMATCH

    def test_signature_invalid_commit(self):
        m, p = make_validator()
        payload = {**signed_commit(m, p), "signature": "0" * 128}
        out = cv.classify_validator(m, [commit_row(payload)], [], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.SIGNATURE_INVALID

    def test_signature_invalid_reveal(self):
        m, p = make_validator()
        reveal = {**signed_reveal(m, p), "signature": "0" * 128}
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(reveal)], WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.SIGNATURE_INVALID

    def test_commit_window_open_boundary_is_inclusive(self):
        m, p = make_validator()
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p), close_time=COMMIT_OPENS)],
            [reveal_row(signed_reveal(m, p))], WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.VALID

    def test_first_valid_commit_by_ledger_order_and_conflict_flag(self):
        m, p = make_validator()
        early = commit_row(signed_commit(m, p, output_hashes=OUTPUT_HASHES, salt=SALT),
                           ledger_index=100, tx_hash="EARLY")
        late = commit_row(signed_commit(m, p, output_hashes=OTHER_OUTPUT_HASHES, salt=OTHER_SALT),
                          ledger_index=101, tx_hash="LATE")
        reveal = reveal_row(signed_reveal(m, p, output_hashes=OUTPUT_HASHES, salt=SALT))
        out = cv.classify_validator(m, [late, early], [reveal], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.VALID
        assert out.accepted_commit_tx == "EARLY"
        assert out.conflicting_commit is True

    def test_conflicting_reveal_flag_when_two_signed_reveals_differ(self):
        m, p = make_validator()
        commit = commit_row(signed_commit(m, p))
        first = reveal_row(
            signed_reveal(m, p, output_hashes=OUTPUT_HASHES, salt=SALT),
            ledger_index=200, tx_hash="RA",
        )
        second = reveal_row(
            signed_reveal(m, p, output_hashes=OTHER_OUTPUT_HASHES, salt=OTHER_SALT),
            ledger_index=201, tx_hash="RB",
        )
        out = cv.classify_validator(m, [commit], [first, second], WINDOWS, OUTPUT_HASHES)
        assert out.conflicting_reveal is True
        assert out.outcome is Outcome.VALID
        assert out.accepted_reveal_tx == "RA"

    def test_no_divergence_claimed_without_foundation_hashes(self):
        m, p = make_validator()
        out = cv.classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))], WINDOWS, None,
        )
        assert out.outcome is Outcome.VALID


class TestPersistence:
    def test_upsert_outcome_upserts(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        outcome = cv.ValidatorOutcome("nHUkey", Outcome.VALID, "C1", "R1", False, False)

        cv.upsert_outcome(conn, ROUND, outcome)
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO validator_round_outcomes" in sql
        assert "ON CONFLICT (round_number, validator_master_key) DO UPDATE" in sql

    def test_load_windows_returns_none_when_absent(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None
        assert cv.load_round_windows(conn, ROUND) is None

    def test_verify_round_without_announcement_is_unverifiable(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None
        result = cv.verify_round(conn, ROUND)
        assert result == {"round_number": ROUND, "verified": False, "reason": "no_announcement"}

    def test_verify_active_rounds_verifies_each(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [(273,), (274,)]
        with patch.object(cv, "verify_round", return_value={"ok": True}) as vr:
            cv.verify_active_rounds(conn)
        assert vr.call_args_list[0].args[1] == 273
        assert vr.call_args_list[1].args[1] == 274
