"""Tests for the M2.6 commit/reveal ingestion subsystem."""

import asyncio
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from xrpl.utils import str_to_hex

from scoring_service.services.commit_reveal import (
    ROUND_ANNOUNCEMENT_TYPE,
    VALIDATOR_COMMIT_TYPE,
    VALIDATOR_REVEAL_TYPE,
)
from scoring_service.services import convergence_ingestion as ingest

MASTER_KEY = "nHUtSomeValidatorMasterKey0000000000000"
INPUT_HASH = "a" * 64
ANNOUNCEMENT_CID = "Qm" + "A" * 44


def _announcement_payload(**overrides) -> dict:
    payload = {
        "protocol_version": 1,
        "network": "devnet",
        "round_number": 273,
        "input_package_cid": ANNOUNCEMENT_CID,
        "input_package_hash": INPUT_HASH,
        "commit_opens_at": "2026-05-25T00:05:00+00:00",
        "commit_closes_at": "2026-05-25T00:30:00+00:00",
        "reveal_opens_at": "2026-05-25T00:30:00+00:00",
        "reveal_closes_at": "2026-05-25T01:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _memo(memo_type: str, payload: dict) -> dict:
    return {
        "Memo": {
            "MemoType": str_to_hex(memo_type),
            "MemoData": str_to_hex(json.dumps(payload)),
        }
    }


def _entry(memos, *, tx_hash="TX1", ledger_index=100, tx_index=3, date=773000000):
    return {
        "hash": tx_hash,
        "ledger_index": ledger_index,
        "meta": {"TransactionIndex": tx_index},
        "tx": {"Account": "rRelayWallet", "date": date, "Memos": memos},
    }


def _commit_payload(**overrides) -> dict:
    payload = {
        "type": VALIDATOR_COMMIT_TYPE,
        "protocol_version": 1,
        "network": "devnet",
        "round_number": 273,
        "validator_master_key": MASTER_KEY,
        "input_package_hash": INPUT_HASH,
        "commitment_hash": "b" * 64,
        "signature": "deadbeef",
    }
    payload.update(overrides)
    return payload


def _reveal_payload(**overrides) -> dict:
    payload = {
        "type": VALIDATOR_REVEAL_TYPE,
        "protocol_version": 1,
        "network": "devnet",
        "round_number": 273,
        "validator_master_key": MASTER_KEY,
        "input_package_hash": INPUT_HASH,
        "output_hashes": {
            "model_response_hash": "c" * 64,
            "validator_scores_hash": "d" * 64,
            "selected_unl_hash": "e" * 64,
        },
        "salt": "f" * 64,
        "signature": "deadbeef",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# decode_transaction
# ---------------------------------------------------------------------------


class TestDecodeTransaction:
    def test_decodes_commit_memo(self):
        records = ingest.decode_transaction(_entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())]))

        assert len(records) == 1
        record = records[0]
        assert record["kind"] == ingest.COMMIT_KIND
        assert record["tx_hash"] == "TX1"
        assert record["round_number"] == 273
        assert record["validator_master_key"] == MASTER_KEY
        assert record["commitment_hash"] == "b" * 64
        assert record["input_package_hash"] == INPUT_HASH
        assert record["sender_account"] == "rRelayWallet"

    def test_decodes_reveal_memo_with_output_hashes(self):
        records = ingest.decode_transaction(_entry([_memo(VALIDATOR_REVEAL_TYPE, _reveal_payload())]))

        assert len(records) == 1
        record = records[0]
        assert record["kind"] == ingest.REVEAL_KIND
        assert record["model_response_hash"] == "c" * 64
        assert record["validator_scores_hash"] == "d" * 64
        assert record["selected_unl_hash"] == "e" * 64
        assert record["salt"] == "f" * 64

    def test_captures_ledger_metadata(self):
        record = ingest.decode_transaction(
            _entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())], ledger_index=4242, tx_index=7)
        )[0]

        assert record["ledger_index"] == 4242
        assert record["transaction_index"] == 7
        assert isinstance(record["ledger_close_time"], datetime)

    def test_handles_tx_json_shape(self):
        entry = {
            "hash": "TXJSON",
            "ledger_index": 50,
            "meta": {"TransactionIndex": 0},
            "tx_json": {"Account": "rRelay", "date": 773000000,
                        "Memos": [_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())]},
        }
        records = ingest.decode_transaction(entry)

        assert len(records) == 1
        assert records[0]["tx_hash"] == "TXJSON"
        assert records[0]["transaction_index"] == 0

    def test_ignores_unrelated_memo_types(self):
        other = _memo("pf_dynamic_unl", {"round_number": 273})
        assert ingest.decode_transaction(_entry([other])) == []

    def test_skips_memo_without_integer_round_number(self):
        payload = _commit_payload(round_number="not-an-int")
        assert ingest.decode_transaction(_entry([_memo(VALIDATOR_COMMIT_TYPE, payload)])) == []

    def test_retains_well_formed_but_invalid_submission(self):
        # Missing signature and a malformed commitment hash: still a commit memo
        # for a known round, so it must be retained for downstream bucketing.
        payload = _commit_payload(commitment_hash="too-short")
        payload.pop("signature")
        records = ingest.decode_transaction(_entry([_memo(VALIDATOR_COMMIT_TYPE, payload)]))

        assert len(records) == 1
        assert records[0]["signature"] is None
        assert records[0]["commitment_hash"] == "too-short"

    def test_skips_entry_without_ledger_position(self):
        entry = _entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())])
        del entry["meta"]["TransactionIndex"]
        assert ingest.decode_transaction(entry) == []

    def test_skips_non_json_memo_data(self):
        entry = _entry([{"Memo": {
            "MemoType": str_to_hex(VALIDATOR_COMMIT_TYPE),
            "MemoData": str_to_hex("not json"),
        }}])
        assert ingest.decode_transaction(entry) == []


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


class TestPersistSubmission:
    def _conn_with_rowcount(self, rowcount):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = rowcount
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_commit_insert_is_idempotent(self):
        conn, cursor = self._conn_with_rowcount(1)
        record = ingest.decode_transaction(_entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())]))[0]

        assert ingest.persist_submission(conn, record) is True
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO validator_commits" in sql
        assert "ON CONFLICT (tx_hash) DO NOTHING" in sql

    def test_reingestion_returns_false(self):
        conn, _ = self._conn_with_rowcount(0)
        record = ingest.decode_transaction(_entry([_memo(VALIDATOR_REVEAL_TYPE, _reveal_payload())]))[0]

        assert ingest.persist_submission(conn, record) is False

    def test_payload_serialized_to_json_string(self):
        conn, cursor = self._conn_with_rowcount(1)
        record = ingest.decode_transaction(_entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())]))[0]

        ingest.persist_submission(conn, record)
        params = cursor.execute.call_args[0][1]
        assert isinstance(params["payload"], str)
        assert json.loads(params["payload"])["round_number"] == 273

    def test_conflicting_duplicates_are_each_inserted(self):
        # Same validator and round, two different transactions: both must be
        # written so the downstream first-valid-by-ledger-order selection can
        # see the conflict rather than silently dropping the second.
        conn, cursor = self._conn_with_rowcount(1)
        first = ingest.decode_transaction(
            _entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload(commitment_hash="1" * 64))], tx_hash="TXA")
        )[0]
        second = ingest.decode_transaction(
            _entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload(commitment_hash="2" * 64))], tx_hash="TXB")
        )[0]

        ingest.persist_submission(conn, first)
        ingest.persist_submission(conn, second)

        inserted_tx_hashes = {call.args[1]["tx_hash"] for call in cursor.execute.call_args_list}
        assert inserted_tx_hashes == {"TXA", "TXB"}


class TestCursor:
    def test_read_cursor_returns_value(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = (512,)

        assert ingest.read_cursor(conn, "rAcc") == 512

    def test_read_cursor_returns_none_when_absent(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        assert ingest.read_cursor(conn, "rAcc") is None

    def test_write_cursor_upserts(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        ingest.write_cursor(conn, "rAcc", 999)
        sql = cursor.execute.call_args[0][0]
        params = cursor.execute.call_args[0][1]
        assert "ON CONFLICT (account) DO UPDATE" in sql
        assert params[0] == "rAcc"
        assert params[1] == 999


# ---------------------------------------------------------------------------
# run_ingestion_pass
# ---------------------------------------------------------------------------


class TestRunIngestionPass:
    def test_paginates_and_advances_cursor(self):
        client = MagicMock()
        client.account_tx.side_effect = [
            {
                "transactions": [
                    _entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())], tx_hash="T1", ledger_index=100),
                    _entry([_memo(VALIDATOR_REVEAL_TYPE, _reveal_payload())], tx_hash="T2", ledger_index=101),
                ],
                "marker": "PAGE2",
            },
            {
                "transactions": [
                    _entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())], tx_hash="T3", ledger_index=105),
                ],
            },
        ]
        conn = MagicMock()

        with patch.object(ingest, "persist_submission", return_value=True) as persist, \
                patch.object(ingest, "write_cursor") as write_cursor:
            stats = ingest.run_ingestion_pass(
                client, conn, "rAcc", start_ledger_index=0, page_limit=200, max_pages=20
            )

        assert client.account_tx.call_count == 2
        assert stats["pages"] == 2
        assert stats["decoded"] == 3
        assert stats["inserted_commits"] == 2
        assert stats["inserted_reveals"] == 1
        assert persist.call_count == 3
        write_cursor.assert_called_once_with(conn, "rAcc", 105)

    def test_scans_forward_from_cursor(self):
        client = MagicMock()
        client.account_tx.return_value = {"transactions": []}
        conn = MagicMock()

        with patch.object(ingest, "write_cursor"):
            ingest.run_ingestion_pass(
                client, conn, "rAcc", start_ledger_index=777, page_limit=50, max_pages=20
            )

        kwargs = client.account_tx.call_args.kwargs
        assert kwargs["ledger_index_min"] == 777
        assert kwargs["forward"] is True
        assert kwargs["limit"] == 50

    def test_stops_at_max_pages(self):
        client = MagicMock()
        client.account_tx.return_value = {"transactions": [], "marker": "ALWAYS"}
        conn = MagicMock()

        with patch.object(ingest, "write_cursor"):
            stats = ingest.run_ingestion_pass(
                client, conn, "rAcc", start_ledger_index=0, page_limit=200, max_pages=3
            )

        assert client.account_tx.call_count == 3
        assert stats["pages"] == 3

    def test_counts_duplicates(self):
        client = MagicMock()
        client.account_tx.return_value = {
            "transactions": [_entry([_memo(VALIDATOR_COMMIT_TYPE, _commit_payload())], tx_hash="T1")],
        }
        conn = MagicMock()

        with patch.object(ingest, "persist_submission", return_value=False), \
                patch.object(ingest, "write_cursor"):
            stats = ingest.run_ingestion_pass(
                client, conn, "rAcc", start_ledger_index=0, page_limit=200, max_pages=20
            )

        assert stats["duplicates"] == 1
        assert stats["inserted_commits"] == 0

    def test_advances_cursor_past_pages_without_records(self):
        # Pages dominated by the publisher's own VL/announcement traffic carry
        # no commit/reveal memos, but the cursor must still advance to the
        # scanned frontier so the watcher makes forward progress.
        client = MagicMock()
        client.account_tx.return_value = {
            "transactions": [
                _entry([_memo("pf_dynamic_unl", {"round_number": 1})], tx_hash="V1", ledger_index=900),
            ],
        }
        conn = MagicMock()

        with patch.object(ingest, "write_cursor") as write_cursor:
            stats = ingest.run_ingestion_pass(
                client, conn, "rAcc", start_ledger_index=0, page_limit=200, max_pages=20
            )

        assert stats["decoded"] == 0
        write_cursor.assert_called_once_with(conn, "rAcc", 900)


@pytest.mark.asyncio
class TestIngestionLoop:
    @patch("scoring_service.services.convergence_ingestion.settings")
    async def test_returns_when_disabled(self, mock_settings):
        mock_settings.convergence_ingestion_enabled = False
        await ingest.convergence_ingestion_loop(client=MagicMock())

    @patch("scoring_service.services.convergence_ingestion.settings")
    async def test_returns_when_pftl_disabled(self, mock_settings):
        mock_settings.convergence_ingestion_enabled = True
        mock_settings.pftl_enabled = False
        await ingest.convergence_ingestion_loop(client=MagicMock())

    @patch("scoring_service.services.convergence_ingestion.get_db")
    @patch("scoring_service.services.convergence_ingestion._try_acquire_lock")
    @patch("scoring_service.services.convergence_ingestion.asyncio.sleep")
    @patch("scoring_service.services.convergence_ingestion.settings")
    async def test_skips_when_lock_held(self, mock_settings, mock_sleep, mock_lock, mock_get_db):
        mock_settings.convergence_ingestion_enabled = True
        mock_settings.pftl_enabled = True
        mock_settings.convergence_ingestion_startup_delay_seconds = 0
        mock_settings.convergence_ingestion_poll_interval_seconds = 300
        conn = MagicMock()
        mock_get_db.return_value = conn
        mock_lock.return_value = False
        client = MagicMock()
        client.publisher_address = "rPub"

        call_count = 0

        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        with pytest.raises(asyncio.CancelledError):
            await ingest.convergence_ingestion_loop(client=client)

        conn.close.assert_called_once()

    @patch("scoring_service.services.convergence_ingestion.get_db")
    @patch("scoring_service.services.convergence_ingestion._release_lock")
    @patch("scoring_service.services.convergence_ingestion._try_acquire_lock")
    @patch("scoring_service.services.convergence_ingestion._run_pass_with_own_connection")
    @patch("scoring_service.services.convergence_ingestion.asyncio.sleep")
    @patch("scoring_service.services.convergence_ingestion.settings")
    async def test_runs_pass_and_releases_lock(
        self, mock_settings, mock_sleep, mock_run, mock_lock, mock_release, mock_get_db
    ):
        mock_settings.convergence_ingestion_enabled = True
        mock_settings.pftl_enabled = True
        mock_settings.convergence_ingestion_startup_delay_seconds = 0
        mock_settings.convergence_ingestion_poll_interval_seconds = 300
        conn = MagicMock()
        mock_get_db.return_value = conn
        mock_lock.return_value = True
        mock_run.return_value = {"decoded": 0}
        client = MagicMock()
        client.publisher_address = "rPub"

        call_count = 0

        async def stop_after_one(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        mock_sleep.side_effect = stop_after_one

        with pytest.raises(asyncio.CancelledError):
            await ingest.convergence_ingestion_loop(client=client)

        mock_run.assert_called_once_with(client, "rPub")
        mock_release.assert_called_once_with(conn)
        conn.close.assert_called_once()


class TestDecodeAnnouncement:
    def test_decodes_announcement_with_parsed_windows(self):
        records = ingest.decode_transaction(
            _entry([_memo(ROUND_ANNOUNCEMENT_TYPE, _announcement_payload())])
        )
        assert len(records) == 1
        rec = records[0]
        assert rec["kind"] == ingest.ANNOUNCEMENT_KIND
        assert rec["round_number"] == 273
        assert rec["input_package_cid"] == ANNOUNCEMENT_CID
        assert isinstance(rec["commit_opens_at"], datetime)
        assert isinstance(rec["reveal_closes_at"], datetime)

    def test_skips_malformed_announcement(self):
        bad = _announcement_payload(commit_opens_at="not-a-date")
        assert ingest.decode_transaction(_entry([_memo(ROUND_ANNOUNCEMENT_TYPE, bad)])) == []


class TestPersistAnnouncement:
    def test_inserts_into_round_announcements(self):
        rec = ingest.decode_transaction(
            _entry([_memo(ROUND_ANNOUNCEMENT_TYPE, _announcement_payload())])
        )[0]
        conn = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = 1
        conn.cursor.return_value = cursor

        assert ingest.persist_submission(conn, rec) is True
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO round_announcements" in sql
        assert "ON CONFLICT (round_number) DO NOTHING" in sql
