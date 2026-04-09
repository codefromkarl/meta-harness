from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
INITIAL_MIGRATION = "0001_projection_entries"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_db_projection_store(db_path: Path) -> dict[str, Any]:
    with _connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row["version"]): str(row["name"])
            for row in connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        }
        if SCHEMA_VERSION not in applied:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projection_entries (
                    projection_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (projection_type, target_id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (SCHEMA_VERSION, INITIAL_MIGRATION, _utc_now()),
            )
        connection.commit()
        migration_names = [
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
    return {
        "db_path": str(db_path),
        "schema_version": SCHEMA_VERSION,
        "migrations": migration_names,
    }


def upsert_db_projection(
    *,
    db_path: Path,
    projection_type: str,
    target_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    ensure_db_projection_store(db_path)
    serialized = json.dumps(payload, sort_keys=True)
    updated_at = _utc_now()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO projection_entries(projection_type, target_id, payload_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(projection_type, target_id)
            DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
            """,
            (projection_type, target_id, serialized, updated_at),
        )
        connection.commit()
    return {
        "projection_type": projection_type,
        "target_id": target_id,
        "updated_at": updated_at,
    }


def load_db_projection(
    *,
    db_path: Path,
    projection_type: str,
    target_id: str,
) -> dict[str, Any] | None:
    ensure_db_projection_store(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT projection_type, target_id, payload_json, updated_at
            FROM projection_entries
            WHERE projection_type = ? AND target_id = ?
            """,
            (projection_type, target_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "projection_type": str(row["projection_type"]),
        "target_id": str(row["target_id"]),
        "payload": json.loads(str(row["payload_json"])),
        "updated_at": str(row["updated_at"]),
    }


def list_db_projections(
    *,
    db_path: Path,
    projection_type: str | None = None,
) -> list[dict[str, Any]]:
    ensure_db_projection_store(db_path)
    query = """
        SELECT projection_type, target_id, payload_json, updated_at
        FROM projection_entries
    """
    params: tuple[Any, ...] = ()
    if projection_type is not None:
        query += " WHERE projection_type = ?"
        params = (projection_type,)
    query += " ORDER BY projection_type, target_id"
    with _connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "projection_type": str(row["projection_type"]),
            "target_id": str(row["target_id"]),
            "payload": json.loads(str(row["payload_json"])),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]
