"""VL sequence and storage management.

Tracks the monotonically increasing sequence number for Validator Lists
and stores the latest signed VL JSON for serving via the /vl.json endpoint.

postfiatd nodes reject any VL with a sequence <= the last one they accepted,
so this counter must never go backwards.

The reserve/confirm/release pattern ensures failed rounds don't burn
sequence numbers.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def reserve_next_sequence(conn) -> int:
    """Reserve the next sequence number for VL generation.

    Atomically reads the current confirmed sequence, increments it, and
    stores the reservation. Only one reservation can be active at a time —
    a stale reservation from a failed round is overwritten.

    Args:
        conn: psycopg2 connection (caller manages transaction).

    Returns:
        The reserved sequence number.

    Raises:
        RuntimeError: If the sequence row is missing (migration not applied).
    """
    cursor = conn.cursor()
    cursor.execute("SELECT confirmed_sequence FROM vl_sequence WHERE id = 1 FOR UPDATE")
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("vl_sequence row missing — migration 004 not applied")

    confirmed = row[0]
    next_seq = confirmed + 1

    cursor.execute(
        "UPDATE vl_sequence SET reserved_sequence = %s, reserved_at = %s WHERE id = 1",
        (next_seq, datetime.now(timezone.utc)),
    )
    cursor.close()

    logger.info("Reserved VL sequence %d (confirmed: %d)", next_seq, confirmed)
    return next_seq


def confirm_sequence(conn, sequence: int) -> None:
    """Confirm a reserved sequence number after successful VL publication.

    Updates the confirmed high-water mark and clears the reservation.

    Args:
        conn: psycopg2 connection (caller manages transaction).
        sequence: The sequence number to confirm.

    Raises:
        ValueError: If the sequence doesn't match the current reservation,
            or if it's not greater than the confirmed value.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT confirmed_sequence, reserved_sequence FROM vl_sequence WHERE id = 1 FOR UPDATE"
    )
    row = cursor.fetchone()
    confirmed, reserved = row[0], row[1]

    if reserved is None or reserved != sequence:
        raise ValueError(
            f"Cannot confirm sequence {sequence} — "
            f"current reservation is {reserved}"
        )

    if sequence <= confirmed:
        raise ValueError(
            f"Cannot confirm sequence {sequence} — "
            f"not greater than confirmed value {confirmed}"
        )

    cursor.execute(
        "UPDATE vl_sequence SET confirmed_sequence = %s, reserved_sequence = NULL, "
        "reserved_at = NULL, confirmed_at = %s WHERE id = 1",
        (sequence, datetime.now(timezone.utc)),
    )
    cursor.close()

    logger.info("Confirmed VL sequence %d", sequence)


def release_sequence(conn) -> None:
    """Release a reserved sequence number after a failed round.

    Clears the reservation without advancing the confirmed counter,
    so the next round can reuse the same number.

    Args:
        conn: psycopg2 connection (caller manages transaction).
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE vl_sequence SET reserved_sequence = NULL, reserved_at = NULL WHERE id = 1"
    )
    released = cursor.rowcount > 0
    cursor.close()

    if released:
        logger.info("Released VL sequence reservation")


def get_confirmed_sequence(conn) -> int:
    """Read the last confirmed sequence number.

    Args:
        conn: psycopg2 connection.

    Returns:
        The confirmed sequence number (0 if no VL has been published yet).
    """
    cursor = conn.cursor()
    cursor.execute("SELECT confirmed_sequence FROM vl_sequence WHERE id = 1")
    row = cursor.fetchone()
    cursor.close()

    if row is None:
        return 0
    return row[0]


def store_vl(conn, vl_data: dict) -> None:
    """Persist a signed VL JSON to the database.

    Called by the orchestrator after VL generation and before sequence
    confirmation, in the same transaction.

    Args:
        conn: psycopg2 connection (caller manages transaction).
        vl_data: The complete signed VL document (dict).
    """
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE vl_sequence SET vl_data = %s, vl_updated_at = %s WHERE id = 1",
        (json.dumps(vl_data), datetime.now(timezone.utc)),
    )
    cursor.close()

    logger.info("Stored signed VL in database")


def get_current_vl(conn) -> Optional[dict]:
    """Read the latest signed VL from the database.

    Args:
        conn: psycopg2 connection.

    Returns:
        The signed VL document (dict), or None if no VL has been published.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT vl_data FROM vl_sequence WHERE id = 1")
    row = cursor.fetchone()
    cursor.close()

    if row is None or row[0] is None:
        return None
    return row[0]
