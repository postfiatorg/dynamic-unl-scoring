"""Automated scoring round scheduler.

Background task that checks whether a new scoring round is due based on
the configured cadence and the last normal scoring attempt's timestamp.
Uses PostgreSQL advisory locks to prevent concurrent rounds.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from scoring_service.config import settings
from scoring_service.database import get_db
from scoring_service.services.orchestrator import RoundState, ScoringOrchestrator

logger = logging.getLogger(__name__)

ADVISORY_LOCK_ID = 99001


def _is_round_due(conn) -> bool:
    """Check if enough time has passed since the last normal scoring attempt."""
    cursor = conn.cursor()
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
    row = cursor.fetchone()
    cursor.close()

    if row is None:
        logger.info("No previous normal scoring attempt — first round is due")
        return True

    last_attempt = row[0]
    cadence = timedelta(hours=settings.scoring_cadence_hours)
    now = datetime.now(timezone.utc)
    next_due = last_attempt + cadence

    if now >= next_due:
        logger.info(
            "Round is due: last normal attempt %s, cadence %.1fh, next was due %s",
            last_attempt.isoformat(),
            settings.scoring_cadence_hours,
            next_due.isoformat(),
        )
        return True

    logger.debug(
        "Round not yet due: next at %s (%s remaining)",
        next_due.isoformat(),
        next_due - now,
    )
    return False


def _try_acquire_lock(conn) -> bool:
    """Attempt to acquire a PostgreSQL advisory lock. Non-blocking."""
    cursor = conn.cursor()
    cursor.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
    acquired = cursor.fetchone()[0]
    cursor.close()
    return acquired


def _release_lock(conn) -> None:
    """Release the PostgreSQL advisory lock."""
    cursor = conn.cursor()
    cursor.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
    cursor.close()


async def scheduler_loop(orchestrator: ScoringOrchestrator | None = None):
    """Background loop that triggers scoring rounds on schedule.

    Waits for a startup delay, then checks hourly whether a round is due.
    Acquires a PostgreSQL advisory lock before running to prevent
    concurrent rounds.
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
            try:
                if not _is_round_due(conn):
                    conn.close()
                    await asyncio.sleep(check_interval)
                    continue

                if not _try_acquire_lock(conn):
                    logger.info("Advisory lock held — another round is in progress, skipping")
                    conn.close()
                    await asyncio.sleep(check_interval)
                    continue

                conn.close()

                logger.info("Triggering scheduled scoring round")
                result = await asyncio.to_thread(orchestrator.run_round)
                logger.info(
                    "Scheduled round finished: status=%s, round_number=%s",
                    result.get("status"),
                    result.get("round_number"),
                )

            except Exception:
                logger.exception("Scheduler error during round check/execution")
            finally:
                try:
                    release_conn = get_db()
                    _release_lock(release_conn)
                    release_conn.close()
                except Exception:
                    pass

        except Exception:
            logger.exception("Scheduler failed to connect to database")

        await asyncio.sleep(check_interval)
