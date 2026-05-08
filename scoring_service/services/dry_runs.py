"""Private dry-run persistence helpers."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def _content_hash(data: object) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_dry_run(conn) -> int:
    """Create a private dry-run row and return its dry_run_id."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO dry_runs (status, started_at)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("COLLECTING", datetime.now(timezone.utc)),
    )
    dry_run_id = cursor.fetchone()[0]
    cursor.close()
    conn.commit()
    return dry_run_id


def update_dry_run(conn, dry_run_id: int, **fields) -> None:
    """Update a private dry-run row."""
    if not fields:
        return
    set_clause = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values()) + [dry_run_id]
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE dry_runs SET {set_clause} WHERE id = %s",
        values,
    )
    cursor.close()
    conn.commit()


def fail_dry_run(conn, dry_run_id: int, error: str) -> None:
    """Mark a private dry-run as failed."""
    update_dry_run(
        conn,
        dry_run_id,
        status="FAILED",
        error_message=error,
        completed_at=datetime.now(timezone.utc),
    )


def store_dry_run_raw_evidence(
    conn,
    dry_run_id: int,
    source: str,
    raw_data: object,
    publishable: bool,
) -> None:
    """Persist one raw evidence payload in the private dry-run namespace."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO dry_run_raw_evidence
            (dry_run_id, source, raw_data, content_hash, publishable)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (dry_run_id, source) DO UPDATE SET
            raw_data = EXCLUDED.raw_data,
            content_hash = EXCLUDED.content_hash,
            publishable = EXCLUDED.publishable,
            captured_at = now()
        """,
        (
            dry_run_id,
            source,
            json.dumps(raw_data, default=str),
            _content_hash(raw_data),
            publishable,
        ),
    )
    cursor.close()


def store_dry_run_artifacts(
    conn,
    dry_run_id: int,
    files: dict[str, Any],
) -> None:
    """Persist private dry-run review artifacts."""
    cursor = conn.cursor()
    for file_path, content in files.items():
        cursor.execute(
            """
            INSERT INTO dry_run_artifacts (dry_run_id, file_path, content)
            VALUES (%s, %s, %s)
            ON CONFLICT (dry_run_id, file_path) DO UPDATE SET
                content = EXCLUDED.content,
                created_at = now()
            """,
            (dry_run_id, file_path, json.dumps(content, sort_keys=True, default=str)),
        )
    cursor.close()


def get_dry_run_artifact(conn, dry_run_id: int, file_path: str) -> dict | None:
    """Retrieve one private dry-run review artifact."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT content
        FROM dry_run_artifacts
        WHERE dry_run_id = %s
        AND file_path = %s
        """,
        (dry_run_id, file_path),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


def _serialize_dry_run(row) -> dict:
    return {
        "dry_run_id": row[0],
        "status": row[1],
        "snapshot_hash": row[2],
        "scores_hash": row[3],
        "error_message": row[4],
        "started_at": row[5].isoformat() if row[5] else None,
        "completed_at": row[6].isoformat() if row[6] else None,
        "created_at": row[7].isoformat() if row[7] else None,
    }


def list_dry_runs(conn, limit: int, offset: int) -> tuple[list[dict], int]:
    """List private dry-runs for admin review."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, status, snapshot_hash, scores_hash, error_message,
               started_at, completed_at, created_at
        FROM dry_runs
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )
    rows = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM dry_runs")
    count_row = cursor.fetchone()
    cursor.close()
    total = count_row[0] if count_row else 0
    return [_serialize_dry_run(row) for row in rows], total


def get_dry_run(conn, dry_run_id: int) -> dict | None:
    """Get one private dry-run status record."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, status, snapshot_hash, scores_hash, error_message,
               started_at, completed_at, created_at
        FROM dry_runs
        WHERE id = %s
        """,
        (dry_run_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    return _serialize_dry_run(row) if row else None
