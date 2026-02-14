from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class SQLiteCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv_cache (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY(namespace, key)
                )
                """
            )

    def get(self, namespace: str, key: str) -> Any | None:
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM kv_cache WHERE namespace=? AND key=?",
                (namespace, key),
            ).fetchone()
            if not row:
                return None
            value, expires_at = row
            if expires_at < now:
                conn.execute(
                    "DELETE FROM kv_cache WHERE namespace=? AND key=?",
                    (namespace, key),
                )
                return None
            return json.loads(value)

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = int(time.time()) + ttl_seconds
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO kv_cache(namespace, key, value, expires_at)
                VALUES(?, ?, ?, ?)
                """,
                (namespace, key, json.dumps(value), expires_at),
            )
