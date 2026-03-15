# Home Assistant Music Like Mirror

A custom Home Assistant add-on that mirrors new **liked songs** between Spotify and YouTube Music.

It is intentionally append-only:

- It reads liked songs from both services.
- It stores discovered events in a local SQLite database.
- It attempts to mirror new likes to the other service.
- It **never** unlikes, deletes, or removes tracks.

---

## Current capabilities

- Home Assistant add-on with Ingress UI (`ingress_port: 8099`)
- Built-in settings page for Spotify + YouTube Music credentials
- Manual "Run sync now" trigger
- Background polling loop (default every 15 minutes)
- Local persistence under `/data/music_like_mirror/`
  - `settings.json`
  - `mirror.db`
- Activity and attempt logs visible in the UI

## Current limitations

- No guided Spotify OAuth flow in the UI (you must provide a refresh token)
- Matching is currently simple (`title + artist-ish` normalization)
- No retry queue/backoff strategy yet
- No approval queue for ambiguous matches

---

## Repository layout

```text
.
├── repository.yaml
├── README.md
└── music_like_mirror
    ├── build.yaml
    ├── config.yaml
    ├── Dockerfile
    └── rootfs/app
        ├── app.py
        ├── db.py
        ├── requirements.txt
        ├── run.sh
        └── services/
```

---

## End-to-end setup (detailed)

Follow this from top to bottom to avoid common setup issues.

### 1) Add this repository to Home Assistant

1. In Home Assistant, open **Settings → Add-ons → Add-on Store**.
2. Open the **three-dot menu** (top-right) → **Repositories**.
3. Add your repository URL:
   - `https://github.com/tizudyzae/ha-music-like-mirror`
4. Close and refresh the Add-on Store.
5. Find **Music Like Mirror** and open it.

### 2) Install + start the add-on

1. Click **Install**.
2. (Optional) Toggle **Start on boot** and **Watchdog**.
3. Click **Start**.
4. Open **Log** tab and confirm the app starts without crashing.

Expected startup behavior:

- The add-on launches Uvicorn on port `8099`.
- The app creates `/data/music_like_mirror` automatically.
- The DB file (`mirror.db`) is created on first start.

### 3) Open the web UI

- Use **Open Web UI** from the add-on page (recommended via Ingress).
- If using direct port access, ensure networking/firewall allows the mapped port.

### 4) Prepare Spotify credentials

You must provide:

- `spotify_client_id`
- `spotify_client_secret`
- `spotify_refresh_token`

And the token must include scopes that allow reading/writing library tracks.

In the add-on UI, fill:

- **Spotify client ID**
- **Spotify client secret**
- **Spotify refresh token**
- Optional: **Spotify playlist ID** (fallback target)
- Optional: **Spotify market** (default `GB`)

> If refresh token/scopes are wrong, connection tests and sync attempts will fail even if client ID/secret are valid.

### 5) Prepare YouTube Music credentials

You must provide authentication JSON compatible with `ytmusicapi`.

In the UI:

- Paste JSON into **YouTube Music auth JSON**.
- If using oauth-token style auth, also paste client credentials into
  **YouTube Music OAuth client credentials JSON**.

> Invalid JSON, expired auth, or missing OAuth credential pairing are common causes of failures.

### 6) Save settings and validate connections

1. Click **Save settings**.
2. Click **Test Spotify + YouTube Music connections**.
3. Verify both services report success.

If either side fails:

- Re-check pasted secrets for whitespace/newline corruption.
- Re-generate Spotify refresh token with correct scopes.
- Re-export/recreate YouTube Music auth JSON.

### 7) Run your first sync

1. Click **Run sync now**.
2. Review these UI panels:
   - **Status**
   - **Recent like events**
   - **Recent sync attempts**
   - **Verbose activity log**

What "healthy" looks like:

- Event count increases after polling/manual sync.
- Attempt rows appear with success statuses (or clear actionable errors).
- Logs show poll start/finish and service operations.

---

## Configuration reference (UI fields)

- `spotify_client_id`: Spotify app client ID
- `spotify_client_secret`: Spotify app client secret
- `spotify_refresh_token`: refresh token with required scopes
- `spotify_playlist_id`: optional fallback target instead of liked songs
- `spotify_market`: market for Spotify lookup behavior (default `GB`)
- `ytmusic_auth_json`: auth JSON (headers auth or oauth token JSON)
- `ytmusic_oauth_credentials_json`: required when using oauth token JSON mode
- `poll_minutes`: background polling interval (`1` to `1440`)
- `match_mode`: currently `simple`
- `dry_run`: when enabled, records actions without writing likes to targets

---

## How to verify your setup is actually working

Use this checklist after configuration:

1. **Addon is running**
   - Add-on state is "Started" in Home Assistant.
2. **Both integrations configured**
   - Status panel shows Spotify = configured, YT Music = configured.
3. **Connection test passes**
   - Use the built-in test button.
4. **Manual sync executes**
   - Trigger sync and confirm logs show a full run.
5. **DB is accumulating data**
   - Event and attempt counters increase over time.
6. **No repeated auth errors in logs**
   - If auth errors repeat, reissue credentials before further debugging.

If all 6 are true, the base setup is usually correct and any remaining issues are typically match quality or source-data edge cases.

---

## Troubleshooting quick guide

### Add-on starts, but UI is blank/unreachable

- Prefer opening from **Open Web UI** (Ingress path) first.
- Restart add-on after install/update.
- Check add-on logs for Uvicorn startup errors.

### "Configured" shows false after saving

- Settings may not have been valid JSON (for YT fields).
- Re-open Settings page and confirm values persisted.
- Ensure `/data` mount is writable (the add-on uses `/data/music_like_mirror`).

### Sync runs but nothing mirrors

- Turn off `dry_run`.
- Confirm there are new likes to ingest since last run.
- Check **Recent sync attempts** for lookup/match failures.

### Spotify failures

- Refresh token invalid/expired/revoked.
- Missing required scopes for saved tracks.
- Wrong client ID/secret pair for the token.

### YouTube Music failures

- Stale/invalid auth JSON.
- Incorrect JSON format pasted.
- Missing OAuth credential JSON when required.

---

## Data and behavior notes

- Data path: `/data/music_like_mirror/`
- SQLite DB: `/data/music_like_mirror/mirror.db`
- Settings JSON: `/data/music_like_mirror/settings.json`
- Behavior is intentionally append-only and idempotent-friendly:
  - no unlikes
  - no deletes
  - no "remove from target" logic

---

## Development notes

Potential next improvements:

1. Built-in Spotify OAuth helper flow in UI
2. Better track matching/scoring
3. Retry queue with backoff
4. Direction toggles (Spotify→YT, YT→Spotify)
5. HA entities/services for observability and control
