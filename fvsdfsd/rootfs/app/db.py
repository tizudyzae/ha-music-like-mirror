from __future__ import annotations

import aiosqlite
from typing import Any


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS like_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_service TEXT NOT NULL,
                source_track_id TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                liked_at TEXT,
                artwork_url TEXT,
                raw_json TEXT,
                discovered_at TEXT NOT NULL,
                processed_at TEXT,
                UNIQUE(source_service, source_track_id)
            );

            CREATE TABLE IF NOT EXISTS sync_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                like_event_id INTEGER NOT NULL,
                target_service TEXT NOT NULL,
                search_query TEXT NOT NULL,
                target_track_id TEXT,
                status TEXT NOT NULL,
                error_text TEXT,
                attempted_at TEXT NOT NULL,
                FOREIGN KEY(like_event_id) REFERENCES like_events(id)
            );

            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                summary_json TEXT
            );
            """
        )
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def insert_like_event(self, item: dict[str, Any]) -> bool:
        assert self.conn is not None
        cursor = await self.conn.execute(
            """
            INSERT OR IGNORE INTO like_events (
                source_service, source_track_id, title, artist, album,
                liked_at, artwork_url, raw_json, discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["source_service"],
                item["source_track_id"],
                item["title"],
                item["artist"],
                item.get("album"),
                item.get("liked_at"),
                item.get("artwork_url"),
                item.get("raw_json"),
                item["discovered_at"],
            ),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_pending_events(self) -> list[dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            """
            SELECT *
            FROM like_events
            WHERE processed_at IS NULL
            ORDER BY id ASC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def mark_event_processed(self, event_id: int, processed_at: str) -> None:
        assert self.conn is not None
        await self.conn.execute(
            "UPDATE like_events SET processed_at = ? WHERE id = ?",
            (processed_at, event_id),
        )
        await self.conn.commit()

    async def add_attempt(self, attempt: dict[str, Any]) -> None:
        assert self.conn is not None
        await self.conn.execute(
            """
            INSERT INTO sync_attempts (
                like_event_id, target_service, search_query, target_track_id,
                status, error_text, attempted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt["like_event_id"],
                attempt["target_service"],
                attempt["search_query"],
                attempt.get("target_track_id"),
                attempt["status"],
                attempt.get("error_text"),
                attempt["attempted_at"],
            ),
        )
        await self.conn.commit()

    async def start_run(self, trigger: str, started_at: str) -> int:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "INSERT INTO run_log (trigger, started_at, status) VALUES (?, ?, ?)",
            (trigger, started_at, "running"),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def finish_run(self, run_id: int, finished_at: str, status: str, summary_json: str) -> None:
        assert self.conn is not None
        await self.conn.execute(
            "UPDATE run_log SET finished_at = ?, status = ?, summary_json = ? WHERE id = ?",
            (finished_at, status, summary_json, run_id),
        )
        await self.conn.commit()

    async def get_counts(self) -> dict[str, int]:
        assert self.conn is not None
        counts: dict[str, int] = {}
        for label, query in {
            "like_events": "SELECT COUNT(*) FROM like_events",
            "sync_attempts": "SELECT COUNT(*) FROM sync_attempts",
            "pending_events": "SELECT COUNT(*) FROM like_events WHERE processed_at IS NULL",
        }.items():
            cursor = await self.conn.execute(query)
            row = await cursor.fetchone()
            counts[label] = int(row[0])
        return counts

    async def get_last_runs(self) -> dict[str, Any]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "SELECT started_at, finished_at FROM run_log ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return {"last_poll_started_at": None, "last_poll_finished_at": None}
        return {
            "last_poll_started_at": row["started_at"],
            "last_poll_finished_at": row["finished_at"],
        }

    async def get_recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "SELECT * FROM like_events ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_recent_attempts(self, limit: int = 100) -> list[dict[str, Any]]:
        assert self.conn is not None
        cursor = await self.conn.execute(
            "SELECT * FROM sync_attempts ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
