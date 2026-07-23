"""Tests for M2.6 commitment verification (per-validator outcome classification)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from xrpl.constants import CryptoAlgorithm
from xrpl.core import addresscodec, keypairs
from xrpl.utils import str_to_hex

from scoring_service.services.commit_reveal import (
    ROUND_ANNOUNCEMENT_TYPE,
    VALIDATOR_COMMIT_TYPE,
    VALIDATOR_REVEAL_TYPE,
    build_commit_payload,
    build_commit_signing_bytes,
    build_reveal_payload,
    build_reveal_signing_bytes,
    compute_commitment_hash,
)
from scoring_service.services import convergence_ingestion as ingest
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


def signed_commit_variant(
    master,
    priv,
    *,
    protocol_version=PROTO,
    network=NETWORK,
    round_number=ROUND,
    input_package_hash=INPUT_HASH,
    output_hashes=OUTPUT_HASHES,
    salt=SALT,
):
    commitment = compute_commitment_hash(
        protocol_version=protocol_version, network=network, round_number=round_number,
        validator_master_key=master, input_package_hash=input_package_hash,
        output_hashes=output_hashes, salt=salt,
    )
    msg = build_commit_signing_bytes(
        protocol_version=protocol_version, network=network, round_number=round_number,
        validator_master_key=master, input_package_hash=input_package_hash,
        commitment_hash=commitment,
    )
    return build_commit_payload(
        protocol_version=protocol_version, network=network, round_number=round_number,
        validator_master_key=master, input_package_hash=input_package_hash,
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


def signed_reveal_variant(
    master,
    priv,
    *,
    protocol_version=PROTO,
    network=NETWORK,
    round_number=ROUND,
    input_package_hash=INPUT_HASH,
    output_hashes=OUTPUT_HASHES,
    salt=SALT,
):
    msg = build_reveal_signing_bytes(
        protocol_version=protocol_version, network=network, round_number=round_number,
        validator_master_key=master, input_package_hash=input_package_hash,
        output_hashes=output_hashes, salt=salt,
    )
    return build_reveal_payload(
        protocol_version=protocol_version, network=network, round_number=round_number,
        validator_master_key=master, input_package_hash=input_package_hash,
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


def announcement(**overrides):
    values = {
        "protocol_version": PROTO,
        "network": NETWORK,
        "round_number": ROUND,
        "input_package_cid": "Qm" + "A" * 44,
        "input_package_hash": INPUT_HASH,
        "commit_opens_at": COMMIT_OPENS,
        "commit_closes_at": COMMIT_CLOSES,
        "reveal_opens_at": REVEAL_OPENS,
        "reveal_closes_at": REVEAL_CLOSES,
    }
    values.update(overrides)
    return cv.RoundAnnouncement(**values)


def classify_validator(*args, **kwargs):
    if "announcement" not in kwargs and len(args) < 6:
        kwargs["announcement"] = announcement()
    return cv.classify_validator(*args, **kwargs)


def memo(memo_type: str, payload: dict) -> dict:
    return {
        "Memo": {
            "MemoType": str_to_hex(memo_type),
            "MemoData": str_to_hex(json.dumps(payload, sort_keys=True, default=str)),
        }
    }


def tx_entry(
    memo_payload: dict,
    *,
    memo_type: str,
    tx_hash: str,
    ledger_index: int,
    tx_index: int,
    close_time: datetime,
) -> dict:
    return {
        "hash": tx_hash,
        "ledger_index": ledger_index,
        "close_time_iso": close_time.isoformat(),
        "meta": {"TransactionIndex": tx_index},
        "tx": {
            "Account": "rRelayWallet",
            "Memos": [memo(memo_type, memo_payload)],
        },
    }


def announcement_payload(**overrides) -> dict:
    payload = {
        "protocol_version": PROTO,
        "network": NETWORK,
        "round_number": ROUND,
        "input_package_cid": "Qm" + "A" * 44,
        "input_package_hash": INPUT_HASH,
        "commit_opens_at": COMMIT_OPENS.isoformat(),
        "commit_closes_at": COMMIT_CLOSES.isoformat(),
        "reveal_opens_at": REVEAL_OPENS.isoformat(),
        "reveal_closes_at": REVEAL_CLOSES.isoformat(),
    }
    payload.update(overrides)
    return payload


class FakeConvergenceCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._one = None
        self._many = []

    def execute(self, sql, params=None):
        compact = " ".join(sql.split())
        self.rowcount = 0
        self._one = None
        self._many = []

        if "INSERT INTO round_announcements" in compact:
            round_number = params["round_number"]
            if round_number not in self.conn.announcements:
                self.conn.announcements[round_number] = dict(params)
                self.rowcount = 1
            return
        if "INSERT INTO validator_commits" in compact:
            if params["tx_hash"] not in {r["tx_hash"] for r in self.conn.commits}:
                row = dict(params)
                row["payload"] = json.loads(row["payload"])
                self.conn.commits.append(row)
                self.rowcount = 1
            return
        if "INSERT INTO validator_reveals" in compact:
            if params["tx_hash"] not in {r["tx_hash"] for r in self.conn.reveals}:
                row = dict(params)
                row["payload"] = json.loads(row["payload"])
                self.conn.reveals.append(row)
                self.rowcount = 1
            return
        if compact.startswith("SELECT commit_opens_at"):
            ann = self.conn.announcements.get(params[0])
            self._one = (
                (
                    ann["commit_opens_at"],
                    ann["commit_closes_at"],
                    ann["reveal_opens_at"],
                    ann["reveal_closes_at"],
                )
                if ann
                else None
            )
            return
        if compact.startswith("SELECT protocol_version"):
            ann = self.conn.announcements.get(params[0])
            self._one = (
                (
                    ann["protocol_version"],
                    ann["network"],
                    ann["round_number"],
                    ann["input_package_cid"],
                    ann["input_package_hash"],
                    ann["commit_opens_at"],
                    ann["commit_closes_at"],
                    ann["reveal_opens_at"],
                    ann["reveal_closes_at"],
                )
                if ann
                else None
            )
            return
        if "SELECT content FROM audit_trail_files" in compact:
            self._one = self.conn.audit_files.get((params[0], params[1]))
            self._one = (self._one,) if self._one is not None else None
            return
        if "SELECT * FROM validator_commits" in compact:
            self._many = [r for r in self.conn.commits if r["round_number"] == params[0]]
            return
        if "SELECT * FROM validator_reveals" in compact:
            self._many = [r for r in self.conn.reveals if r["round_number"] == params[0]]
            return
        if "INSERT INTO validator_round_outcomes" in compact:
            row = {
                "validator_master_key": params[1],
                "outcome": params[2],
                "accepted_commit_tx": params[3],
                "accepted_reveal_tx": params[4],
                "conflicting_commit": params[5],
                "conflicting_reveal": params[6],
                "comparison_levels_matched": params[7],
                "divergence_stage": params[8],
                "divergence_category": params[9],
            }
            self.conn.outcomes[params[0], params[1]] = row
            self.rowcount = 1
            return
        if compact.startswith("SELECT network, input_package_hash"):
            ann = self.conn.announcements.get(params[0])
            self._one = (
                (
                    ann["network"],
                    ann["input_package_hash"],
                    ann["input_package_cid"],
                    ann["reveal_opens_at"],
                    ann["reveal_closes_at"],
                )
                if ann
                else None
            )
            return
        if "FROM validator_round_outcomes" in compact:
            round_number = params[0]
            self._many = [
                row
                for (stored_round, _key), row in self.conn.outcomes.items()
                if stored_round == round_number
            ]
            self._many.sort(key=lambda row: row["validator_master_key"])
            return
        if compact.startswith(
            "SELECT convergence_bundle_cid, anchor_tx_hash FROM convergence_reports"
        ):
            sealed = self.conn.convergence_reports.get(params[0])
            self._one = (
                (sealed["cid"], sealed.get("anchor_tx_hash"))
                if sealed is not None
                else None
            )
            return
        if "INSERT INTO convergence_reports" in compact:
            if params[0] not in self.conn.convergence_reports:
                self.conn.convergence_reports[params[0]] = {
                    "cid": params[1],
                    "report": json.loads(params[2]),
                    "anchor_tx_hash": None,
                }
                self.rowcount = 1
            return
        if compact.startswith("UPDATE convergence_reports SET anchor_tx_hash"):
            self.conn.convergence_reports[params[1]]["anchor_tx_hash"] = params[0]
            return
        raise AssertionError(f"Unexpected SQL: {compact}")

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many

    def close(self):
        return None


class FakeConvergenceConn:
    def __init__(self):
        self.announcements = {}
        self.commits = []
        self.reveals = []
        self.audit_files = {}
        self.outcomes = {}
        self.convergence_reports = {}

    def cursor(self, *args, **kwargs):
        return FakeConvergenceCursor(self)


class TestClassifyValidator:
    def test_valid_when_reveal_matches_foundation(self):
        m, p = make_validator()
        out = classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))],
            WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.VALID
        assert out.accepted_commit_tx == "C1"
        assert out.accepted_reveal_tx == "R1"

    def test_divergent_when_output_differs_from_foundation(self):
        m, p = make_validator()
        out = classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))],
            WINDOWS, OTHER_OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.DIVERGENT

    def test_missing_reveal_when_commit_only(self):
        m, p = make_validator()
        out = classify_validator(m, [commit_row(signed_commit(m, p))], [], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.MISSING_REVEAL
        assert out.accepted_reveal_tx is None

    def test_late_commit_at_window_close_is_excluded(self):
        m, p = make_validator()
        out = classify_validator(
            m, [commit_row(signed_commit(m, p), close_time=COMMIT_CLOSES)], [], WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.LATE

    def test_late_reveal_outside_window(self):
        m, p = make_validator()
        out = classify_validator(
            m, [commit_row(signed_commit(m, p))],
            [reveal_row(signed_reveal(m, p), close_time=REVEAL_CLOSES)],
            WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.LATE

    def test_commitment_mismatch_when_reveal_does_not_bind(self):
        m, p = make_validator()
        commit = commit_row(signed_commit(m, p, output_hashes=OUTPUT_HASHES, salt=SALT))
        reveal = reveal_row(signed_reveal(m, p, output_hashes=OTHER_OUTPUT_HASHES, salt=OTHER_SALT))
        out = classify_validator(m, [commit], [reveal], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.COMMITMENT_MISMATCH

    def test_signature_invalid_commit(self):
        m, p = make_validator()
        payload = {**signed_commit(m, p), "signature": "0" * 128}
        out = classify_validator(m, [commit_row(payload)], [], WINDOWS, OUTPUT_HASHES)
        assert out.outcome is Outcome.SIGNATURE_INVALID

    def test_signature_invalid_reveal(self):
        m, p = make_validator()
        reveal = {**signed_reveal(m, p), "signature": "0" * 128}
        out = classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(reveal)], WINDOWS, OUTPUT_HASHES,
        )
        assert out.outcome is Outcome.SIGNATURE_INVALID

    def test_commit_window_open_boundary_is_inclusive(self):
        m, p = make_validator()
        out = classify_validator(
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
        out = classify_validator(m, [late, early], [reveal], WINDOWS, OUTPUT_HASHES)
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
        out = classify_validator(m, [commit], [first, second], WINDOWS, OUTPUT_HASHES)
        assert out.conflicting_reveal is True
        assert out.outcome is Outcome.VALID
        assert out.accepted_reveal_tx == "RA"

    def test_no_divergence_claimed_without_foundation_hashes(self):
        m, p = make_validator()
        out = classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))], WINDOWS, None,
        )
        assert out.outcome is Outcome.VALID

    def test_commit_bound_to_wrong_announcement_is_mismatch(self):
        m, p = make_validator()
        payload = signed_commit_variant(m, p, input_package_hash="b" * 64)
        out = classify_validator(
            m,
            [commit_row(payload)],
            [],
            WINDOWS,
            OUTPUT_HASHES,
            announcement(),
        )
        assert out.outcome is Outcome.ANNOUNCEMENT_MISMATCH
        assert out.accepted_commit_tx is None

    def test_commit_protocol_network_and_round_mismatch(self):
        m, p = make_validator()
        variants = [
            (signed_commit_variant(m, p), announcement(protocol_version=PROTO + 1)),
            (signed_commit_variant(m, p, network="testnet"), announcement()),
            (signed_commit_variant(m, p, round_number=ROUND + 1), announcement()),
        ]
        for payload, round_announcement in variants:
            out = classify_validator(
                m,
                [commit_row(payload)],
                [],
                WINDOWS,
                OUTPUT_HASHES,
                round_announcement,
            )
            assert out.outcome is Outcome.ANNOUNCEMENT_MISMATCH

    def test_reveal_bound_to_wrong_announcement_is_mismatch(self):
        m, p = make_validator()
        commit = commit_row(signed_commit(m, p))
        reveal = reveal_row(
            signed_reveal_variant(m, p, input_package_hash="b" * 64)
        )
        out = classify_validator(
            m,
            [commit],
            [reveal],
            WINDOWS,
            OUTPUT_HASHES,
            announcement(),
        )
        assert out.outcome is Outcome.ANNOUNCEMENT_MISMATCH


class TestAnnouncementBindingRegression:
    def test_ingested_mismatch_seals_as_announcement_mismatch(self):
        conn = FakeConvergenceConn()
        master, private = make_validator()
        wrong_input_hash = "b" * 64

        records = []
        records.extend(
            ingest.decode_transaction(
                tx_entry(
                    announcement_payload(),
                    memo_type=ROUND_ANNOUNCEMENT_TYPE,
                    tx_hash="ANN",
                    ledger_index=90,
                    tx_index=0,
                    close_time=COMMIT_OPENS,
                )
            )
        )
        records.extend(
            ingest.decode_transaction(
                tx_entry(
                    signed_commit_variant(
                        master,
                        private,
                        input_package_hash=wrong_input_hash,
                    ),
                    memo_type=VALIDATOR_COMMIT_TYPE,
                    tx_hash="COMMIT",
                    ledger_index=100,
                    tx_index=0,
                    close_time=IN_COMMIT,
                )
            )
        )
        records.extend(
            ingest.decode_transaction(
                tx_entry(
                    signed_reveal_variant(
                        master,
                        private,
                        input_package_hash=wrong_input_hash,
                    ),
                    memo_type=VALIDATOR_REVEAL_TYPE,
                    tx_hash="REVEAL",
                    ledger_index=200,
                    tx_index=0,
                    close_time=IN_REVEAL,
                )
            )
        )
        for record in records:
            assert ingest.persist_submission(conn, record) is True

        conn.audit_files[(ROUND, cv.VERIFICATION_HASHES_FILE_PATH)] = OUTPUT_HASHES

        verified = cv.verify_round(conn, ROUND)
        assert verified["verified"] is True
        assert verified["outcomes"] == {Outcome.ANNOUNCEMENT_MISMATCH.value: 1}

        ipfs = MagicMock()
        ipfs.publish_convergence_report.return_value = "QmReportCID"
        onchain = MagicMock()
        onchain.publish_convergence_report.return_value = "ANCHORTX"

        sealed = cv.seal_round(
            conn,
            ROUND,
            ipfs_publisher=ipfs,
            onchain_publisher=onchain,
        )

        assert sealed["sealed"] is True
        report = ipfs.publish_convergence_report.call_args.args[1]
        assert report["summary"]["outcomes"] == {
            Outcome.ANNOUNCEMENT_MISMATCH.value: 1
        }
        assert report["participants"][0]["outcome"] == (
            Outcome.ANNOUNCEMENT_MISMATCH.value
        )


class TestPerLevelComparison:
    def _outcome(self, foundation):
        m, p = make_validator()
        return classify_validator(
            m, [commit_row(signed_commit(m, p))], [reveal_row(signed_reveal(m, p))],
            WINDOWS, foundation,
        )

    def test_all_levels_match(self):
        out = self._outcome(OUTPUT_HASHES)
        assert out.outcome is Outcome.VALID
        assert out.comparison_levels_matched == "RAW,PARSED,SELECTED_UNL"
        assert out.divergence_stage is None
        assert out.divergence_category is None

    def test_divergence_at_raw_stage(self):
        out = self._outcome({**OUTPUT_HASHES, "model_response_hash": "9" * 64})
        assert out.outcome is Outcome.DIVERGENT
        assert out.divergence_stage == "RAW"
        assert out.divergence_category == "OUTPUT_DIVERGENCE"
        assert out.comparison_levels_matched == "PARSED,SELECTED_UNL"

    def test_divergence_at_parsed_stage(self):
        out = self._outcome({**OUTPUT_HASHES, "validator_scores_hash": "9" * 64})
        assert out.outcome is Outcome.DIVERGENT
        assert out.divergence_stage == "PARSED"
        assert out.comparison_levels_matched == "RAW,SELECTED_UNL"

    def test_selected_unl_mismatch_is_diagnostic_not_divergent(self):
        # The LLM-output levels are the acceptance bar; the selected-UNL hash
        # only localizes divergence (docs/DeterministicFinalScore.md). The
        # mismatch stays visible as the level missing from levels_matched.
        out = self._outcome({**OUTPUT_HASHES, "selected_unl_hash": "9" * 64})
        assert out.outcome is Outcome.VALID
        assert out.divergence_stage is None
        assert out.divergence_category is None
        assert out.comparison_levels_matched == "RAW,PARSED"

    def test_missing_foundation_artifact_is_not_comparable(self):
        out = self._outcome(None)
        assert out.outcome is Outcome.VALID
        assert out.comparison_levels_matched is None
        assert out.divergence_stage is None
        assert out.divergence_category is None

    def test_first_divergence_stage_is_earliest_in_pipeline(self):
        out = self._outcome(
            {**OUTPUT_HASHES, "model_response_hash": "9" * 64, "selected_unl_hash": "8" * 64}
        )
        assert out.divergence_stage == "RAW"
        assert out.comparison_levels_matched == "PARSED"

    def test_taxonomy_values_match_spec(self):
        assert cv.CATEGORY_OUTPUT_DIVERGENCE == "OUTPUT_DIVERGENCE"
        assert (cv.LEVEL_RAW, cv.LEVEL_PARSED, cv.LEVEL_SELECTED_UNL) == (
            "RAW", "PARSED", "SELECTED_UNL",
        )


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
