from __future__ import annotations

import base64
from typing import Any

import httpx

SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, market: str = "GB"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.market = market
        self._access_token: str | None = None

    async def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                headers={"Authorization": f"Basic {basic}"},
            )
            response.raise_for_status()
            payload = response.json()
            self._access_token = payload["access_token"]
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, f"{SPOTIFY_API_BASE}{path}", headers=headers, **kwargs)
            if response.status_code == 401:
                self._access_token = None
                token = await self._ensure_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await client.request(method, f"{SPOTIFY_API_BASE}{path}", headers=headers, **kwargs)
            response.raise_for_status()
            return response

    async def get_saved_tracks(self, limit: int = 50) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = await self._request(
                "GET",
                "/me/tracks",
                params={"limit": min(limit, 50), "offset": offset, "market": self.market},
            )
            payload = response.json()
            batch = payload.get("items", [])
            items.extend(batch)
            if not payload.get("next"):
                break
            offset += len(batch)
            if len(batch) == 0:
                break
        return items

    async def search_track(self, query: str) -> dict[str, Any] | None:
        response = await self._request(
            "GET",
            "/search",
            params={"q": query, "type": "track", "limit": 1, "market": self.market},
        )
        items = response.json().get("tracks", {}).get("items", [])
        return items[0] if items else None

    async def save_track(self, track_id: str) -> None:
        await self._request("PUT", "/me/tracks", params={"ids": track_id})

    async def add_to_playlist(self, playlist_id: str, track_id: str) -> None:
        await self._request("POST", f"/playlists/{playlist_id}/tracks", json={"uris": [f"spotify:track:{track_id}"]})
