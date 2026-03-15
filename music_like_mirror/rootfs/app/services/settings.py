from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any


class SettingsStore:
    def __init__(self, path: str):
        self.path = path

    def load(self, redact: bool = True) -> dict[str, Any]:
        if not os.path.exists(self.path):
            return {
                "spotify_client_id": "",
                "spotify_client_secret": "",
                "spotify_refresh_token": "",
                "spotify_playlist_id": "",
                "spotify_market": "GB",
                "ytmusic_auth_json": "",
                "ytmusic_oauth_credentials_json": "",
                "poll_minutes": 15,
                "match_mode": "simple",
                "dry_run": False,
            }
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if redact:
            data = deepcopy(data)
            for key in ["spotify_client_secret", "spotify_refresh_token", "ytmusic_auth_json", "ytmusic_oauth_credentials_json"]:
                if data.get(key):
                    data[key] = "***saved***"
        return data

    def save(self, data: dict[str, Any]) -> None:
        current = self.load(redact=False)
        merged = {**current, **data}
        if data.get("spotify_client_secret") == "***saved***":
            merged["spotify_client_secret"] = current.get("spotify_client_secret", "")
        if data.get("spotify_refresh_token") == "***saved***":
            merged["spotify_refresh_token"] = current.get("spotify_refresh_token", "")
        if data.get("ytmusic_auth_json") == "***saved***":
            merged["ytmusic_auth_json"] = current.get("ytmusic_auth_json", "")
        if data.get("ytmusic_oauth_credentials_json") == "***saved***":
            merged["ytmusic_oauth_credentials_json"] = current.get("ytmusic_oauth_credentials_json", "")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
