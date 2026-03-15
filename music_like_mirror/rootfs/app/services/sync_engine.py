from __future__ import annotations

import asyncio
import json
from collections import deque
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
        self._recent_logs: deque[dict[str, Any]] = deque(maxlen=800)
        self._current_run_logs: list[dict[str, Any]] = []

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

    def recent_logs(self, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 1000)
        return list(self._recent_logs)[-safe_limit:]

    def _log(self, level: str, message: str, **context: Any) -> None:
        entry = {
            "ts": utcnow(),
            "level": level,
            "message": message,
            "context": context,
        }
        self._recent_logs.append(entry)
        if self._running:
            self._current_run_logs.append(entry)

    async def _background_loop(self) -> None:
        self._log("info", "Background sync loop started")
        while not self._stop.is_set():
            settings = self.settings_store.load(redact=False)
            wait_seconds = int(settings.get("poll_minutes", 15)) * 60
            try:
                if settings.get("spotify_client_id") and settings.get("spotify_refresh_token") and settings.get("ytmusic_auth_json"):
                    self._log("info", "Scheduled sync triggered from background loop", poll_minutes=settings.get("poll_minutes", 15))
                    await self.run_once(trigger="scheduled")
                else:
                    self._log("debug", "Scheduled sync skipped due to incomplete settings")
            except Exception:
                # swallow errors here so the loop keeps limping onward instead of dying dramatically
                self._log("error", "Scheduled sync crashed unexpectedly", error="background loop exception")
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                continue
        self._log("info", "Background sync loop stopped")

    async def run_once(self, trigger: str = "manual") -> dict[str, Any]:
        if self._running:
            self._log("warning", "Sync ignored because one is already running", trigger=trigger)
            return {"ok": False, "message": "sync already running"}

        settings = self.settings_store.load(redact=False)
        missing = []
        if not (settings.get("spotify_client_id") and settings.get("spotify_client_secret") and settings.get("spotify_refresh_token")):
            missing.append("spotify credentials")
        if not settings.get("ytmusic_auth_json"):
            missing.append("ytmusic auth json")
        if missing:
            self._log("warning", "Sync blocked by missing configuration", trigger=trigger, missing=missing)
            return {"ok": False, "message": f"Missing: {', '.join(missing)}"}

        self._running = True
        self._current_run_logs = []
        started_at = utcnow()
        self._log("info", "Sync run started", trigger=trigger, started_at=started_at)
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
            ytmusic = YTMusicClient(
                settings["ytmusic_auth_json"],
                settings.get("ytmusic_oauth_credentials_json", ""),
            )
            self._log("debug", "Clients initialized", spotify_market=settings.get("spotify_market", "GB"), dry_run=bool(settings.get("dry_run")))

            spotify_new = await self._ingest_spotify(spotify)
            summary["new_events"] += spotify_new
            self._log("info", "Spotify likes ingested", discovered=spotify_new)

            ytmusic_new = await self._ingest_ytmusic(ytmusic)
            summary["new_events"] += ytmusic_new
            self._log("info", "YouTube Music likes ingested", discovered=ytmusic_new)

            pending = await self.db.get_pending_events()
            self._log("info", "Pending events ready for mirroring", pending_count=len(pending))
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
                self._log(
                    "debug",
                    "Event mirrored and marked processed",
                    event_id=event["id"],
                    source_service=event["source_service"],
                    title=event["title"],
                    artist=event["artist"],
                    result=result,
                )

            summary["run_logs"] = self._current_run_logs

            await self.db.finish_run(run_id, utcnow(), "ok", json.dumps(summary))
            self._log("info", "Sync run completed", run_id=run_id, summary=summary)
            return {"ok": True, "summary": summary}
        except Exception as exc:
            error_summary = {"error": str(exc), **summary, "run_logs": self._current_run_logs}
            await self.db.finish_run(run_id, utcnow(), "error", json.dumps(error_summary))
            self._log("error", "Sync run failed", run_id=run_id, error=str(exc), summary=summary)
            return {"ok": False, "message": str(exc), "summary": summary}
        finally:
            self._running = False

    async def test_connections(self) -> dict[str, Any]:
        settings = self.settings_store.load(redact=False)
        result: dict[str, Any] = {
            "spotify": {"ok": False, "message": "not configured"},
            "ytmusic": {"ok": False, "message": "not configured"},
        }

        if settings.get("spotify_client_id") and settings.get("spotify_client_secret") and settings.get("spotify_refresh_token"):
            try:
                spotify = SpotifyClient(
                    client_id=settings["spotify_client_id"],
                    client_secret=settings["spotify_client_secret"],
                    refresh_token=settings["spotify_refresh_token"],
                    market=settings.get("spotify_market", "GB"),
                )
                await spotify.get_saved_tracks(limit=1)
                result["spotify"] = {"ok": True, "message": "connection successful"}
                self._log("info", "Spotify connection test passed")
            except Exception as exc:
                result["spotify"] = {"ok": False, "message": str(exc)}
                self._log("error", "Spotify connection test failed", error=str(exc))

        if settings.get("ytmusic_auth_json"):
            try:
                ytmusic = YTMusicClient(
                    settings["ytmusic_auth_json"],
                    settings.get("ytmusic_oauth_credentials_json", ""),
                )
                await ytmusic.get_liked_songs(limit=1)
                result["ytmusic"] = {"ok": True, "message": "connection successful"}
                self._log("info", "YouTube Music connection test passed")
            except Exception as exc:
                result["ytmusic"] = {"ok": False, "message": str(exc)}
                self._log("error", "YouTube Music connection test failed", error=str(exc))

        return result

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
                    self._log("warning", "No YouTube Music match found for Spotify event", event_id=event["id"], query=query)
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
                    self._log("info", "Liked song on YouTube Music", event_id=event["id"], query=query, target_track_id=result.get("videoId"))
                else:
                    self._log("info", "Dry-run: would like song on YouTube Music", event_id=event["id"], query=query, target_track_id=result.get("videoId"))
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
                self._log("error", "Failed mirroring Spotify event to YouTube Music", event_id=event["id"], query=query, error=str(exc))
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
                self._log("warning", "No Spotify match found for YouTube Music event", event_id=event["id"], query=query)
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
                    self._log("info", "Added track to Spotify playlist", event_id=event["id"], query=query, target_track_id=result.get("id"), playlist_id=settings.get("spotify_playlist_id"))
                else:
                    await spotify.save_track(result["id"])
                    self._log("info", "Saved track to Spotify library", event_id=event["id"], query=query, target_track_id=result.get("id"))
            else:
                self._log("info", "Dry-run: would add track to Spotify", event_id=event["id"], query=query, target_track_id=result.get("id"), playlist_id=settings.get("spotify_playlist_id") or None)
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
            self._log("error", "Failed mirroring YouTube Music event to Spotify", event_id=event["id"], query=query, error=str(exc))
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
