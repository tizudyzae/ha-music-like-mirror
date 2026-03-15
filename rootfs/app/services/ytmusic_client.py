from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from ytmusicapi import YTMusic
from ytmusicapi.models.content.enums import LikeStatus


class YTMusicClient:
    def __init__(self, auth_json_text: str):
        self.auth_json_text = auth_json_text
        self._tmp_path: str | None = None
        self._client: YTMusic | None = None

    def _ensure_client(self) -> YTMusic:
        if self._client is not None:
            return self._client
        fd, path = tempfile.mkstemp(prefix="ytmusic_auth_", suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            parsed = json.loads(self.auth_json_text)
            json.dump(parsed, f)
        self._tmp_path = path
        self._client = YTMusic(path)
        return self._client

    async def get_liked_songs(self, limit: int = 5000) -> list[dict[str, Any]]:
        client = self._ensure_client()
        payload = client.get_liked_songs(limit)
        return payload.get("tracks", [])

    async def search_song(self, query: str) -> dict[str, Any] | None:
        client = self._ensure_client()
        results = client.search(query, filter="songs", limit=1)
        return results[0] if results else None

    async def like_song(self, video_id: str) -> None:
        client = self._ensure_client()
        client.rate_song(video_id, LikeStatus.LIKE)
