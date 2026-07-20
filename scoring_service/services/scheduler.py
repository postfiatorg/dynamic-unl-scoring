"""Automated scoring round scheduler.

Background task that checks whether a new scoring round is due based on
the persisted `round_schedule.next_due_at` timestamp. The timestamp
advances by whole cadence periods at scheduled round start, so a round's
own duration never shifts the schedule. Uses PostgreSQL advisory locks
to prevent concurrent rounds.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from scoring_service.config import settings
from scoring_service.database import get_db, release_advisory_lock, try_advisory_lock
from scoring_service.services.orchestrator import RoundState, ScoringOrchestrator

logger = logging.getLogger(__name__)

ADVISORY_LOCK_ID = 99001


def ensure_schedule_seeded(conn) -> datetime:
    """Return next_due_at, seeding the row with the legacy formula if missing.

    Seed = COALESCE(completed_at, started_at, created_at) of the newest
    normal round + cadence; with no rounds at all, now (a fresh install
    fires immediately, matching the pre-schedule behavior). Requires an
    autocommit connection; callers must hold advisory lock 99001, which
    serializes seeding against reanchor writes.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT next_due_at FROM round_schedule WHERE id = 1")
        row = cursor.fetchone()
        if row is not None:
            return row[0]

        cursor.execute(
            """
            SELECT COALESCE(completed_at, started_at, created_at)
            FROM scoring_rounds
            WHERE override_type IS NULL
            AND status != %s
            ORDER BY round_number DESC
            LIMIT 1
            """,
            (RoundState.DRY_RUN_COMPLETE.value,),
        )
        last_row = cursor.fetchone()

        if last_row is None:
            next_due = datetime.now(timezone.utc)
            logger.info("No previous normal scoring attempt — seeding schedule as due now")
        else:
            next_due = last_row[0] + timedelta(hours=settings.scoring_cadence_hours)
            logger.info(
                "Seeding schedule from last normal attempt %s + %.1fh cadence: next due %s",
                last_row[0].isoformat(),
                settings.scoring_cadence_hours,
                next_due.isoformat(),
            )

        cursor.execute(
            """
            INSERT INTO round_schedule (id, next_due_at)
            VALUES (1, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (next_due,),
        )
        return next_due
    finally:
        cursor.close()


def _is_round_due(conn) -> bool:
    """Check whether the persisted schedule says a round is due."""
    next_due = ensure_schedule_seeded(conn)
    now = datetime.now(timezone.utc)

    if now >= next_due:
        logger.info("Round is due: next was due %s", next_due.isoformat())
        return True

    logger.debug(
        "Round not yet due: next at %s (%s remaining)",
        next_due.isoformat(),
        next_due - now,
    )
    return False


def _advance_schedule(conn) -> datetime | None:
    """Advance next_due_at by whole cadence periods until it is in the future.

    Called at scheduled round start so a failed round still consumes its
    slot; consuming every missed period yields at most one catch-up round
    after an outage. A restart between the advance and the round run skips
    that slot (sub-second window, accepted). Requires an autocommit
    connection and advisory lock 99001.
    """
    cadence = timedelta(hours=settings.scoring_cadence_hours)
    if cadence <= timedelta(0):
        raise ValueError(f"Cannot advance schedule: cadence {cadence} is not positive")

    cursor = conn.cursor()
    try:
        cursor.execute("SELECT next_due_at FROM round_schedule WHERE id = 1")
        row = cursor.fetchone()
        if row is None:
            logger.error("Cannot advance schedule: round_schedule row is missing")
            return None

        next_due = row[0]
        now = datetime.now(timezone.utc)
        while next_due <= now:
            next_due += cadence

        cursor.execute(
            "UPDATE round_schedule SET next_due_at = %s WHERE id = 1",
            (next_due,),
        )
        logger.info("Schedule advanced: next round due %s", next_due.isoformat())
        return next_due
    finally:
        cursor.close()


def reanchor_schedule(conn) -> datetime:
    """Reset the schedule so the next round is due one cadence from now.

    Upserts, so a manual trigger during the pre-seed window (fresh deploy,
    startup delay still running) creates the row directly. Requires an
    autocommit connection and advisory lock 99001.
    """
    next_due = datetime.now(timezone.utc) + timedelta(hours=settings.scoring_cadence_hours)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO round_schedule (id, next_due_at)
            VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE SET next_due_at = EXCLUDED.next_due_at
            """,
            (next_due,),
        )
    finally:
        cursor.close()
    logger.info("Schedule reanchored: next round due %s", next_due.isoformat())
    return next_due


def _try_acquire_lock(conn) -> bool:
    """Attempt to acquire the scheduler's advisory lock. Non-blocking."""
    return try_advisory_lock(conn, ADVISORY_LOCK_ID)


def _release_lock(conn) -> None:
    """Release the scheduler's advisory lock."""
    release_advisory_lock(conn, ADVISORY_LOCK_ID)


async def scheduler_loop(orchestrator: ScoringOrchestrator | None = None):
    """Background loop that triggers scoring rounds on schedule.

    Waits for a startup delay, then checks every
    `scheduler_check_interval_seconds` whether a round is due. Acquires a
    PostgreSQL advisory lock before running to prevent concurrent rounds.
    """
    startup_delay = settings.scheduler_startup_delay_seconds
    check_interval = settings.scheduler_check_interval_seconds

    logger.info(
        "Scheduler starting — %ds startup delay, %ds check interval, %.1fh cadence",
        startup_delay,
        check_interval,
        settings.scoring_cadence_hours,
    )

    await asyncio.sleep(startup_delay)

    if orchestrator is None:
        orchestrator = ScoringOrchestrator()

    while True:
        try:
            conn = get_db()
            lock_acquired = False
            try:
                conn.autocommit = True
                if not _try_acquire_lock(conn):
                    logger.info("Advisory lock held — another round is in progress, skipping")
                else:
                    lock_acquired = True

                    publication_results = await asyncio.to_thread(
                        orchestrator.publish_due_rounds
                    )
                    if publication_results:
                        logger.info(
                            "Published held scoring rounds: %s",
                            publication_results,
                        )

                    if _is_round_due(conn):
                        logger.info("Triggering scheduled scoring round")
                        _advance_schedule(conn)
                        result = await asyncio.to_thread(orchestrator.run_round)
                        logger.info(
                            "Scheduled round finished: status=%s, round_number=%s",
                            result.get("status"),
                            result.get("round_number"),
                        )

            except Exception:
                logger.exception("Scheduler error during round check/execution")
            finally:
                if lock_acquired:
                    try:
                        _release_lock(conn)
                    except Exception:
                        logger.exception("Failed to release scheduler advisory lock")
                conn.close()

        except Exception:
            logger.exception("Scheduler failed to connect to database")

        await asyncio.sleep(check_interval)
