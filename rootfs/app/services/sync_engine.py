from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from services.normalise import make_search_query
from services.settings import SettingsStore
from services.spotify_client import SpotifyClient
from services.ytmusic_client import YTMusicClient


class SyncEngine:
    def __init__(self, db, settings_store: SettingsStore):
        self.db = db
        self.settings_store = settings_store
        self._task: asyncio.Task | None = None
        self._running = False
        self._stop = asyncio.Event()

    async def start_background_loop(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._background_loop())

    async def stop_background_loop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def reload_settings(self) -> None:
        return

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "background_task": bool(self._task and not self._task.done()),
        }

    async def _background_loop(self) -> None:
        while not self._stop.is_set():
            settings = self.settings_store.load(redact=False)
            wait_seconds = int(settings.get("poll_minutes", 15)) * 60
            try:
                if settings.get("spotify_client_id") and settings.get("spotify_refresh_token") and settings.get("ytmusic_auth_json"):
                    await self.run_once(trigger="scheduled")
            except Exception:
                # swallow errors here so the loop keeps limping onward instead of dying dramatically
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                continue

    async def run_once(self, trigger: str = "manual") -> dict[str, Any]:
        if self._running:
            return {"ok": False, "message": "sync already running"}

        settings = self.settings_store.load(redact=False)
        missing = []
        if not (settings.get("spotify_client_id") and settings.get("spotify_client_secret") and settings.get("spotify_refresh_token")):
            missing.append("spotify credentials")
        if not settings.get("ytmusic_auth_json"):
            missing.append("ytmusic auth json")
        if missing:
            return {"ok": False, "message": f"Missing: {', '.join(missing)}"}

        self._running = True
        started_at = utcnow()
        run_id = await self.db.start_run(trigger=trigger, started_at=started_at)
        summary: dict[str, Any] = {
            "new_events": 0,
            "attempts": 0,
            "added_to_spotify": 0,
            "added_to_ytmusic": 0,
            "failed": 0,
            "dry_run": bool(settings.get("dry_run")),
        }

        try:
            spotify = SpotifyClient(
                client_id=settings["spotify_client_id"],
                client_secret=settings["spotify_client_secret"],
                refresh_token=settings["spotify_refresh_token"],
                market=settings.get("spotify_market", "GB"),
            )
            ytmusic = YTMusicClient(settings["ytmusic_auth_json"])

            summary["new_events"] += await self._ingest_spotify(spotify)
            summary["new_events"] += await self._ingest_ytmusic(ytmusic)

            pending = await self.db.get_pending_events()
            for event in pending:
                result = await self._mirror_event(event, spotify, ytmusic, settings)
                summary["attempts"] += 1
                if result == "added_to_spotify":
                    summary["added_to_spotify"] += 1
                elif result == "added_to_ytmusic":
                    summary["added_to_ytmusic"] += 1
                elif result == "failed":
                    summary["failed"] += 1
                await self.db.mark_event_processed(event["id"], utcnow())

            await self.db.finish_run(run_id, utcnow(), "ok", json.dumps(summary))
            return {"ok": True, "summary": summary}
        except Exception as exc:
            await self.db.finish_run(run_id, utcnow(), "error", json.dumps({"error": str(exc), **summary}))
            return {"ok": False, "message": str(exc), "summary": summary}
        finally:
            self._running = False

    async def _ingest_spotify(self, spotify: SpotifyClient) -> int:
        count = 0
        rows = await spotify.get_saved_tracks(limit=50)
        for row in rows:
            track = row.get("track") or {}
            artists = track.get("artists") or []
            item = {
                "source_service": "spotify",
                "source_track_id": track.get("id") or "",
                "title": track.get("name") or "",
                "artist": ", ".join(a.get("name", "") for a in artists if a.get("name")),
                "album": (track.get("album") or {}).get("name"),
                "liked_at": row.get("added_at"),
                "artwork_url": ((track.get("album") or {}).get("images") or [{}])[0].get("url"),
                "raw_json": json.dumps(row),
                "discovered_at": utcnow(),
            }
            if item["source_track_id"] and await self.db.insert_like_event(item):
                count += 1
        return count

    async def _ingest_ytmusic(self, ytmusic: YTMusicClient) -> int:
        count = 0
        rows = await ytmusic.get_liked_songs(limit=5000)
        for track in rows:
            artists = track.get("artists") or []
            thumbs = track.get("thumbnails") or []
            item = {
                "source_service": "ytmusic",
                "source_track_id": track.get("videoId") or "",
                "title": track.get("title") or "",
                "artist": ", ".join(a.get("name", "") for a in artists if a.get("name")),
                "album": (track.get("album") or {}).get("name") if isinstance(track.get("album"), dict) else None,
                "liked_at": None,
                "artwork_url": thumbs[-1].get("url") if thumbs else None,
                "raw_json": json.dumps(track),
                "discovered_at": utcnow(),
            }
            if item["source_track_id"] and await self.db.insert_like_event(item):
                count += 1
        return count

    async def _mirror_event(self, event: dict[str, Any], spotify: SpotifyClient, ytmusic: YTMusicClient, settings: dict[str, Any]) -> str:
        query = make_search_query(event["title"], event["artist"])
        attempted_at = utcnow()
        dry_run = bool(settings.get("dry_run"))

        if event["source_service"] == "spotify":
            try:
                result = await ytmusic.search_song(query)
                if not result:
                    await self.db.add_attempt({
                        "like_event_id": event["id"],
                        "target_service": "ytmusic",
                        "search_query": query,
                        "target_track_id": None,
                        "status": "no_result",
                        "error_text": None,
                        "attempted_at": attempted_at,
                    })
                    return "failed"
                if not dry_run:
                    await ytmusic.like_song(result["videoId"])
                await self.db.add_attempt({
                    "like_event_id": event["id"],
                    "target_service": "ytmusic",
                    "search_query": query,
                    "target_track_id": result.get("videoId"),
                    "status": "added" if not dry_run else "dry_run",
                    "error_text": None,
                    "attempted_at": attempted_at,
                })
                return "added_to_ytmusic"
            except Exception as exc:
                await self.db.add_attempt({
                    "like_event_id": event["id"],
                    "target_service": "ytmusic",
                    "search_query": query,
                    "target_track_id": None,
                    "status": "failed",
                    "error_text": str(exc),
                    "attempted_at": attempted_at,
                })
                return "failed"

        try:
            result = await spotify.search_track(query)
            if not result:
                await self.db.add_attempt({
                    "like_event_id": event["id"],
                    "target_service": "spotify",
                    "search_query": query,
                    "target_track_id": None,
                    "status": "no_result",
                    "error_text": None,
                    "attempted_at": attempted_at,
                })
                return "failed"
            if not dry_run:
                if settings.get("spotify_playlist_id"):
                    await spotify.add_to_playlist(settings["spotify_playlist_id"], result["id"])
                else:
                    await spotify.save_track(result["id"])
            await self.db.add_attempt({
                "like_event_id": event["id"],
                "target_service": "spotify",
                "search_query": query,
                "target_track_id": result.get("id"),
                "status": "added" if not dry_run else "dry_run",
                "error_text": None,
                "attempted_at": attempted_at,
            })
            return "added_to_spotify"
        except Exception as exc:
            await self.db.add_attempt({
                "like_event_id": event["id"],
                "target_service": "spotify",
                "search_query": query,
                "target_track_id": None,
                "status": "failed",
                "error_text": str(exc),
                "attempted_at": attempted_at,
            })
            return "failed"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
