from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from ytmusicapi import YTMusic
from ytmusicapi.models.content.enums import LikeStatus

OAUTH_TOKEN_KEYS = {"access_token", "refresh_token", "expires_at"}


class YTMusicClient:
    def __init__(self, auth_json_text: str, oauth_credentials_json_text: str = ""):
        self.auth_json_text = auth_json_text
        self.oauth_credentials_json_text = oauth_credentials_json_text
        self._tmp_path: str | None = None
        self._client: YTMusic | None = None

    def _ensure_client(self) -> YTMusic:
        if self._client is not None:
            return self._client

        parsed_auth = json.loads(self.auth_json_text)
        oauth_credentials: dict[str, Any] | None = None

        if isinstance(parsed_auth, dict) and "auth" in parsed_auth:
            embedded_oauth = parsed_auth.get("oauth_credentials")
            if isinstance(embedded_oauth, dict):
                oauth_credentials = embedded_oauth
            parsed_auth = parsed_auth["auth"]

        if self.oauth_credentials_json_text:
            parsed_oauth = json.loads(self.oauth_credentials_json_text)
            if isinstance(parsed_oauth, dict):
                oauth_credentials = parsed_oauth

        if isinstance(parsed_auth, dict) and "oauth_credentials" in parsed_auth and oauth_credentials is None:
            embedded_oauth = parsed_auth.get("oauth_credentials")
            if isinstance(embedded_oauth, dict):
                oauth_credentials = embedded_oauth
                parsed_auth = {k: v for k, v in parsed_auth.items() if k != "oauth_credentials"}

        if isinstance(parsed_auth, dict) and OAUTH_TOKEN_KEYS.issubset(parsed_auth.keys()) and oauth_credentials is None:
            raise ValueError(
                "OAuth token JSON was provided as YouTube Music auth, but oauth credentials are missing. "
                "Paste your OAuth credentials JSON in the 'YouTube Music OAuth credentials JSON' field."
            )

        fd, path = tempfile.mkstemp(prefix="ytmusic_auth_", suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(parsed_auth, f)
        self._tmp_path = path

        if oauth_credentials:
            self._client = YTMusic(path, oauth_credentials=oauth_credentials)
        else:
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
