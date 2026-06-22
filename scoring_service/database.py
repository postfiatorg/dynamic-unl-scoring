"""Database connection and migration utilities."""

import os

import psycopg2
import psycopg2.extras

from scoring_service.config import MIGRATIONS_PATH, settings


def get_db():
    """Get a PostgreSQL database connection."""
    connection = psycopg2.connect(settings.database_url)
    connection.autocommit = False
    return connection


def try_advisory_lock(conn, lock_id: int) -> bool:
    """Attempt a non-blocking PostgreSQL session advisory lock."""
    cursor = conn.cursor()
    cursor.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
    acquired = cursor.fetchone()[0]
    cursor.close()
    return acquired


def release_advisory_lock(conn, lock_id: int) -> None:
    """Release a PostgreSQL session advisory lock."""
    cursor = conn.cursor()
    cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
    cursor.close()


def init_db_if_needed():
    """Apply pending SQL migrations from the migrations/ directory."""
    connection = psycopg2.connect(settings.database_url)
    cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    connection.commit()

    migrations_dir = str(MIGRATIONS_PATH)
    if os.path.isdir(migrations_dir):
        for fname in sorted(os.listdir(migrations_dir)):
            if not fname.endswith(".sql"):
                continue
            cursor.execute(
                "SELECT 1 FROM schema_migrations WHERE filename = %s", (fname,)
            )
            if cursor.fetchone():
                continue
            path = os.path.join(migrations_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                sql = f.read()
            print(f"[migrations] Applying: {fname}")
            try:
                cursor.execute(sql)
                connection.commit()
                cursor.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (fname,)
                )
                connection.commit()
            except Exception as e:
                connection.rollback()
                print(f"[migrations] Failed on {fname}: {e}")
                raise

    cursor.close()
    connection.close()
    print("[database] Initialized successfully")
