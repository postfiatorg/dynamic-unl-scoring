"""Foundation-side commit/reveal ingestion for M2.6 convergence monitoring.

Background watcher that reads validator commit and reveal memos off the PFT
Ledger and lands them in PostgreSQL for the downstream verification and
output-comparison steps. Every validator commit/reveal Payment targets the
foundation publisher address as its destination, so scanning that single
account's `account_tx` history surfaces all participants regardless of which
relay wallet sent each transaction.

This layer is strictly observational: it reads chain history and writes its
own tables, and never blocks, delays, or alters canonical VL publication. It
decodes and stores every well-formed commit/reveal memo for a known round,
including ones that later prove invalid (bad signature, commitment mismatch,
late, duplicate) — validity bucketing belongs to M2.6.2, and filtering here
would erase the divergence signals the convergence report exists to surface.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from xrpl.utils import hex_to_str, ripple_time_to_datetime

from scoring_service.clients.pftl import PFTLClient
from scoring_service.config import settings
from scoring_service.database import get_db, release_advisory_lock, try_advisory_lock
from scoring_service.services.commit_reveal import (
    MODEL_RESPONSE_HASH,
    SELECTED_UNL_HASH,
    VALIDATOR_COMMIT_TYPE,
    VALIDATOR_REVEAL_TYPE,
    VALIDATOR_SCORES_HASH,
)

logger = logging.getLogger(__name__)

INGESTION_ADVISORY_LOCK_ID = 99002

COMMIT_KIND = "commit"
REVEAL_KIND = "reveal"

_MEMO_TYPE_TO_KIND = {
    VALIDATOR_COMMIT_TYPE: COMMIT_KIND,
    VALIDATOR_REVEAL_TYPE: REVEAL_KIND,
}

_KIND_STAT_KEY = {
    COMMIT_KIND: "inserted_commits",
    REVEAL_KIND: "inserted_reveals",
}


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def _decode_hex(value) -> str | None:
    """Decode a hex-encoded memo field to UTF-8, or None if it is not."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return hex_to_str(value)
    except (ValueError, UnicodeDecodeError):
        return None


def _ledger_close_time(date_value, close_time_iso) -> datetime | None:
    """Resolve a memo's validated-ledger close time.

    Prefers the transaction's ripple-epoch `date`; falls back to a clio-style
    ISO `close_time_iso`. Returns None when neither is present or parseable.
    """
    if isinstance(date_value, int):
        try:
            return ripple_time_to_datetime(date_value)
        except (ValueError, OverflowError):
            return None
    if isinstance(close_time_iso, str):
        try:
            return datetime.fromisoformat(close_time_iso.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _entry_ledger_index(entry: dict) -> int | None:
    """The validated ledger index an account_tx entry settled in, or None."""
    tx = entry.get("tx") or entry.get("tx_json") or {}
    ledger_index = entry.get("ledger_index")
    if ledger_index is None:
        ledger_index = tx.get("ledger_index")
    return ledger_index if isinstance(ledger_index, int) else None


def _output_hash(payload: dict, field: str) -> str | None:
    output_hashes = payload.get("output_hashes")
    if not isinstance(output_hashes, dict):
        return None
    value = output_hashes.get(field)
    return value if isinstance(value, str) else None


def decode_transaction(entry: dict) -> list[dict]:
    """Decode one `account_tx` entry into commit/reveal submission records.

    Returns a record per commit/reveal memo whose payload is a JSON object
    carrying an integer `round_number`. Records preserve the full decoded
    payload plus the validated-ledger position (index, in-ledger order, close
    time) needed for deterministic window evaluation downstream. Entries that
    carry no qualifying memo, or that lack a ledger position, yield nothing.
    """
    tx = entry.get("tx") or entry.get("tx_json") or {}
    tx_hash = entry.get("hash") or tx.get("hash")
    ledger_index = _entry_ledger_index(entry)
    meta = entry.get("meta") or entry.get("metaData") or {}
    transaction_index = meta.get("TransactionIndex") if isinstance(meta, dict) else None

    if not tx_hash or ledger_index is None or not isinstance(transaction_index, int):
        return []

    close_time = _ledger_close_time(tx.get("date"), entry.get("close_time_iso"))
    sender_account = tx.get("Account")
    memos = tx.get("Memos") or []

    records: list[dict] = []
    for memo_entry in memos:
        memo = memo_entry.get("Memo") if isinstance(memo_entry, dict) else None
        if not isinstance(memo, dict):
            continue
        kind = _MEMO_TYPE_TO_KIND.get(_decode_hex(memo.get("MemoType")))
        if kind is None:
            continue
        decoded = _decode_hex(memo.get("MemoData"))
        if decoded is None:
            continue
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not isinstance(
            payload.get("round_number"), int
        ):
            continue

        record = {
            "kind": kind,
            "tx_hash": tx_hash,
            "round_number": payload["round_number"],
            "validator_master_key": payload.get("validator_master_key"),
            "input_package_hash": payload.get("input_package_hash"),
            "protocol_version": payload.get("protocol_version"),
            "network": payload.get("network"),
            "signature": payload.get("signature"),
            "sender_account": sender_account,
            "ledger_index": ledger_index,
            "transaction_index": transaction_index,
            "ledger_close_time": close_time,
            "payload": payload,
        }
        if kind == COMMIT_KIND:
            record["commitment_hash"] = payload.get("commitment_hash")
        else:
            record["model_response_hash"] = _output_hash(payload, MODEL_RESPONSE_HASH)
            record["validator_scores_hash"] = _output_hash(payload, VALIDATOR_SCORES_HASH)
            record["selected_unl_hash"] = _output_hash(payload, SELECTED_UNL_HASH)
            record["salt"] = payload.get("salt")
        if close_time is None:
            logger.warning(
                "Ingested %s memo %s (round %s) has no resolvable ledger close "
                "time; downstream window evaluation will lack a timestamp",
                kind,
                tx_hash,
                record["round_number"],
            )
        records.append(record)

    return records


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_INSERT_COMMIT = """
    INSERT INTO validator_commits (
        tx_hash, round_number, validator_master_key, input_package_hash,
        commitment_hash, protocol_version, network, signature, sender_account,
        ledger_index, transaction_index, ledger_close_time, payload
    ) VALUES (
        %(tx_hash)s, %(round_number)s, %(validator_master_key)s,
        %(input_package_hash)s, %(commitment_hash)s, %(protocol_version)s,
        %(network)s, %(signature)s, %(sender_account)s, %(ledger_index)s,
        %(transaction_index)s, %(ledger_close_time)s, %(payload)s
    )
    ON CONFLICT (tx_hash) DO NOTHING
"""

_INSERT_REVEAL = """
    INSERT INTO validator_reveals (
        tx_hash, round_number, validator_master_key, input_package_hash,
        model_response_hash, validator_scores_hash, selected_unl_hash, salt,
        protocol_version, network, signature, sender_account, ledger_index,
        transaction_index, ledger_close_time, payload
    ) VALUES (
        %(tx_hash)s, %(round_number)s, %(validator_master_key)s,
        %(input_package_hash)s, %(model_response_hash)s,
        %(validator_scores_hash)s, %(selected_unl_hash)s, %(salt)s,
        %(protocol_version)s, %(network)s, %(signature)s, %(sender_account)s,
        %(ledger_index)s, %(transaction_index)s, %(ledger_close_time)s,
        %(payload)s
    )
    ON CONFLICT (tx_hash) DO NOTHING
"""


def persist_submission(conn, record: dict) -> bool:
    """Insert one submission idempotently. Returns True if a row was written,
    False if the tx_hash was already ingested."""
    params = dict(record)
    params["payload"] = json.dumps(record["payload"], sort_keys=True)
    statement = _INSERT_COMMIT if record["kind"] == COMMIT_KIND else _INSERT_REVEAL
    cursor = conn.cursor()
    cursor.execute(statement, params)
    inserted = cursor.rowcount == 1
    cursor.close()
    return inserted


def read_cursor(conn, account: str) -> int | None:
    """Return the highest ledger index already scanned for an account."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT last_ledger_index FROM convergence_ingestion_cursor WHERE account = %s",
        (account,),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


def write_cursor(conn, account: str, last_ledger_index: int) -> None:
    """Advance the watcher's forward cursor for an account."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO convergence_ingestion_cursor (account, last_ledger_index, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (account) DO UPDATE
            SET last_ledger_index = EXCLUDED.last_ledger_index,
                updated_at = EXCLUDED.updated_at
        """,
        (account, last_ledger_index, datetime.now(timezone.utc)),
    )
    cursor.close()


def run_ingestion_pass(
    client: PFTLClient,
    conn,
    account: str,
    *,
    start_ledger_index: int,
    page_limit: int,
    max_pages: int,
) -> dict:
    """Scan an account's history forward from the cursor and persist memos.

    Pages through `account_tx` (oldest-first) up to `max_pages`, decoding and
    idempotently storing every commit/reveal submission, then advances the
    cursor to the highest ledger seen. Re-scanning the boundary ledger across
    passes is harmless because inserts dedupe on tx_hash.
    """
    stats = {
        "decoded": 0,
        "inserted_commits": 0,
        "inserted_reveals": 0,
        "duplicates": 0,
        "pages": 0,
    }
    marker = None
    highest_ledger = start_ledger_index

    for _ in range(max_pages):
        result = client.account_tx(
            account,
            ledger_index_min=start_ledger_index,
            ledger_index_max=-1,
            limit=page_limit,
            marker=marker,
            forward=True,
        )
        for entry in result.get("transactions") or []:
            # Advance the frontier off every scanned ledger, not only ledgers
            # that carried a commit/reveal memo — otherwise the cursor stalls
            # across the long stretches of publisher traffic that hold none.
            entry_ledger = _entry_ledger_index(entry)
            if entry_ledger is not None:
                highest_ledger = max(highest_ledger, entry_ledger)
            try:
                records = decode_transaction(entry)
            except Exception:
                logger.exception("Failed to decode an account_tx entry; skipping")
                continue
            for record in records:
                stats["decoded"] += 1
                if persist_submission(conn, record):
                    stats[_KIND_STAT_KEY[record["kind"]]] += 1
                else:
                    stats["duplicates"] += 1

        stats["pages"] += 1
        marker = result.get("marker")
        if not marker:
            break

    if highest_ledger > start_ledger_index:
        write_cursor(conn, account, highest_ledger)

    return stats


def _run_pass_with_own_connection(client: PFTLClient, account: str) -> dict:
    """Open a dedicated connection and run a single ingestion pass."""
    conn = get_db()
    conn.autocommit = True
    try:
        cursor_ledger = read_cursor(conn, account)
        start = (
            cursor_ledger
            if cursor_ledger is not None
            else settings.convergence_ingestion_start_ledger
        )
        return run_ingestion_pass(
            client,
            conn,
            account,
            start_ledger_index=start,
            page_limit=settings.convergence_ingestion_page_limit,
            max_pages=settings.convergence_ingestion_max_pages,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Advisory lock
# ---------------------------------------------------------------------------


def _try_acquire_lock(conn) -> bool:
    return try_advisory_lock(conn, INGESTION_ADVISORY_LOCK_ID)


def _release_lock(conn) -> None:
    release_advisory_lock(conn, INGESTION_ADVISORY_LOCK_ID)


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------


async def convergence_ingestion_loop(client: PFTLClient | None = None):
    """Background loop that ingests validator commit/reveal memos.

    Waits for a startup delay, then on each interval acquires a PostgreSQL
    advisory lock and runs one ingestion pass in a worker thread (xrpl-py and
    psycopg2 are blocking). Disabled cleanly when convergence ingestion is
    switched off or PFTL is not configured.
    """
    if not settings.convergence_ingestion_enabled:
        logger.info("Convergence ingestion disabled — watcher not started")
        return
    if not settings.pftl_enabled:
        logger.info("PFTL not configured — convergence ingestion watcher not started")
        return

    await asyncio.sleep(settings.convergence_ingestion_startup_delay_seconds)

    if client is None:
        try:
            client = PFTLClient()
        except Exception:
            logger.exception("Convergence ingestion: PFTL client init failed")
            return

    account = client.publisher_address
    interval = settings.convergence_ingestion_poll_interval_seconds
    logger.info(
        "Convergence ingestion watching %s every %ds", account, interval
    )

    while True:
        try:
            conn = get_db()
            lock_acquired = False
            try:
                conn.autocommit = True
                if not _try_acquire_lock(conn):
                    logger.debug("Ingestion advisory lock held — skipping pass")
                    await asyncio.sleep(interval)
                    continue

                lock_acquired = True
                stats = await asyncio.to_thread(
                    _run_pass_with_own_connection, client, account
                )
                logger.info("Convergence ingestion pass complete: %s", stats)

            except Exception:
                logger.exception("Convergence ingestion pass error")
            finally:
                if lock_acquired:
                    try:
                        _release_lock(conn)
                    except Exception:
                        logger.exception("Failed to release ingestion advisory lock")
                conn.close()

        except Exception:
            logger.exception("Convergence ingestion failed to connect to database")

        await asyncio.sleep(interval)
