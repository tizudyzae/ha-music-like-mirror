# Home Assistant Music Like Mirror

Base version of a custom Home Assistant add-on that:

- reads your Spotify liked tracks
- reads your YouTube Music liked tracks
- stores them in a local SQLite database
- mirrors each new like to the other service
- never removes anything
- never unlikes anything
- does not check the remote service first, it just attempts the add

This is intentionally a rough but usable starting point for further refinement in Codex.

## What this version does

- FastAPI web UI exposed via Home Assistant Ingress
- SQLite database stored in `/data/music_like_mirror/mirror.db`
- append-only event ingestion
- manual sync button
- background polling loop
- simple track matching using `title + first artist-ish text`
- writes to:
  - YouTube Music likes via `ytmusicapi.rate_song(..., LIKE)`
  - Spotify saved tracks via Web API
- optional Spotify playlist fallback if you prefer mirroring into a playlist instead of likes

## What this version does not do yet

- polished Spotify OAuth setup inside the UI
- proper retry queue / backoff
- better matching heuristics
- per-direction enable/disable toggles
- review / approve queue
- companion Home Assistant integration entities
- strict ingress IP filtering
- unit tests

## Important caveats

### Spotify auth

This scaffold expects you to already have:

- Spotify client ID
- Spotify client secret
- Spotify refresh token

It does **not** yet include a polished in-app OAuth dance. That should be one of the first Codex refinements.

Spotify library read/write requires the relevant library scopes in the app authorization flow. Spotify documents the library endpoints and scopes in the Web API docs. citeturn179843search1turn179843search4turn179843search6turn179843search8

### YouTube Music auth

This scaffold expects you to paste a valid `headers_auth.json` or equivalent auth JSON into the settings page. `ytmusicapi` is unofficial and works by emulating browser requests, so it is more brittle than the Spotify side. Its docs expose both `get_liked_songs()` and `rate_song()`. citeturn179843search2turn179843search5turn179843search17

### Home Assistant add-on shape

The add-on uses Home Assistant's normal add-on structure with `config.yaml`, Docker build files, and Ingress enabled. Home Assistant's developer docs document `config.yaml` and the `ingress: true` / `ingress_port` setup. citeturn179843search0turn179843search3

## Folder layout

```text
.
├── build.yaml
├── config.yaml
├── Dockerfile
├── README.md
└── rootfs
    └── app
        ├── app.py
        ├── db.py
        ├── requirements.txt
        ├── run.sh
        └── services
            ├── normalise.py
            ├── settings.py
            ├── spotify_client.py
            ├── sync_engine.py
            └── ytmusic_client.py
```

## Suggested next Codex tasks

1. Add real Spotify OAuth setup in the UI.
2. Add a settings toggle for mirror direction:
   - Spotify -> YT Music
   - YT Music -> Spotify
3. Add a retry queue for failed matches.
4. Add a track review page for ambiguous matches.
5. Add a proper Home Assistant service endpoint and status sensors.
6. Add logs page and export page.
7. Harden security around secrets and ingress access.

## Notes on behaviour

This project is built around your stated rules:

- no unlikes
- no deletes
- no remote existence check before writing
- local processed-event tracking only
- okay to attempt the same like again on the target service

That makes the architecture much less haunted.
