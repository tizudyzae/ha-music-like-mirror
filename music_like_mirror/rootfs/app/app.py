from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from db import Database
from services.sync_engine import SyncEngine
from services.settings import SettingsStore

APP_DATA_DIR = os.environ.get("APP_DATA_DIR", "/data/music_like_mirror")
SETTINGS_PATH = os.path.join(APP_DATA_DIR, "settings.json")
DB_PATH = os.path.join(APP_DATA_DIR, "mirror.db")

app = FastAPI(title="Music Like Mirror")
settings_store = SettingsStore(SETTINGS_PATH)
db = Database(DB_PATH)
engine = SyncEngine(db=db, settings_store=settings_store)


class SettingsPayload(BaseModel):
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_refresh_token: str = ""
    spotify_playlist_id: str = ""
    spotify_market: str = "GB"
    ytmusic_auth_json: str = ""
    ytmusic_oauth_credentials_json: str = ""
    poll_minutes: int = Field(default=15, ge=1, le=1440)
    match_mode: str = "simple"
    dry_run: bool = False


@app.on_event("startup")
async def startup() -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    await db.init()
    await engine.start_background_loop()


@app.on_event("shutdown")
async def shutdown() -> None:
    await engine.stop_background_loop()
    await db.close()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.get("/api/status")
async def api_status() -> JSONResponse:
    settings = settings_store.load()
    counts = await db.get_counts()
    last_runs = await db.get_last_runs()
    return JSONResponse(
        {
            "settings_present": {
                "spotify": bool(settings.get("spotify_client_id") and settings.get("spotify_refresh_token")),
                "ytmusic": bool(settings.get("ytmusic_auth_json")),
            },
            "counts": counts,
            "last_runs": last_runs,
            "poll_minutes": settings.get("poll_minutes", 15),
            "engine_state": engine.state_snapshot(),
        }
    )


@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    current = settings_store.load(redact=False)
    return JSONResponse(current)


@app.post("/api/settings")
async def save_settings(payload: SettingsPayload) -> JSONResponse:
    settings_store.save(payload.model_dump())
    await engine.reload_settings()
    return JSONResponse({"ok": True})


@app.post("/api/sync")
async def sync_now() -> JSONResponse:
    result = await engine.run_once(trigger="manual")
    return JSONResponse(result)


@app.post("/api/test-connections")
async def test_connections() -> JSONResponse:
    result = await engine.test_connections()
    return JSONResponse(result)


@app.get("/api/events")
async def events(limit: int = 100) -> JSONResponse:
    rows = await db.get_recent_events(limit=min(max(limit, 1), 500))
    return JSONResponse({"items": rows})


@app.get("/api/attempts")
async def attempts(limit: int = 100) -> JSONResponse:
    rows = await db.get_recent_attempts(limit=min(max(limit, 1), 500))
    return JSONResponse({"items": rows})


@app.get("/api/logs")
async def logs(limit: int = 200) -> JSONResponse:
    rows = engine.recent_logs(limit=min(max(limit, 1), 1000))
    return JSONResponse({"items": rows})


INDEX_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Music Like Mirror</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #111827; color: #f3f4f6; }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .card { background: #1f2937; border: 1px solid #374151; border-radius: 12px; padding: 16px; }
    input, textarea, select, button { width: 100%; box-sizing: border-box; margin-top: 6px; margin-bottom: 12px; border-radius: 8px; border: 1px solid #4b5563; background: #0f172a; color: #f3f4f6; padding: 10px; }
    textarea { min-height: 140px; }
    button { cursor: pointer; background: #2563eb; border: none; }
    button.secondary { background: #374151; }
    .pill { display: inline-block; padding: 6px 10px; border-radius: 999px; background: #374151; margin-right: 8px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 8px; border-bottom: 1px solid #374151; vertical-align: top; }
    .muted { color: #9ca3af; }
    .row { margin-bottom: 8px; }
    .ok { color: #86efac; }
    .bad { color: #fca5a5; }
    .small { font-size: 12px; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>Music Like Mirror</h1>
  <p class="muted">Append-only like mirroring between Spotify and YouTube Music. It never removes or unlikes anything.</p>
  <div class="grid">
    <div class="card">
      <h2>Status</h2>
      <div id="status">Loading...</div>
      <button onclick="runSync()">Run sync now</button>
      <button class="secondary" onclick="testConnections()">Test Spotify + YouTube Music connections</button>
      <div id="connection_test_result" class="small muted"></div>
    </div>
    <div class="card">
      <h2>Settings</h2>
      <label>Spotify client ID</label>
      <input id="spotify_client_id">
      <label>Spotify client secret</label>
      <input id="spotify_client_secret" type="password">
      <label>Spotify refresh token</label>
      <input id="spotify_refresh_token" type="password">
      <label>Spotify playlist ID (optional fallback target)</label>
      <input id="spotify_playlist_id">
      <label>Spotify market</label>
      <input id="spotify_market" value="GB">
      <label>YouTube Music auth JSON (headers_auth.json or oauth token JSON)</label>
      <textarea id="ytmusic_auth_json"></textarea>
      <label>YouTube Music OAuth client credentials JSON (required when using oauth token JSON)</label>
      <textarea id="ytmusic_oauth_credentials_json"></textarea>
      <label>Poll every X minutes</label>
      <input id="poll_minutes" type="number" min="1" max="1440" value="15">
      <label>Match mode</label>
      <select id="match_mode">
        <option value="simple">simple</option>
      </select>
      <label><input id="dry_run" type="checkbox" style="width:auto"> Dry run only</label>
      <button onclick="saveSettings()">Save settings</button>
    </div>
  </div>

  <div class="grid" style="margin-top:16px;">
    <div class="card">
      <h2>Recent like events</h2>
      <div id="events"></div>
    </div>
    <div class="card">
      <h2>Recent sync attempts</h2>
      <div id="attempts"></div>
    </div>
  </div>

  <div class="card" style="margin-top:16px;">
    <h2>Verbose activity log</h2>
    <p class="muted small">Detailed timeline of what the addon is doing right now (startup, scheduled checks, sync actions, dry-run behavior, and errors).</p>
    <div id="logs"></div>
  </div>
</div>
<script>
async function fetchJSON(url, options) {
  const res = await fetch(url, options || {});
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

async function loadAll() {
  const [status, settings, events, attempts, logs] = await Promise.all([
    fetchJSON('./api/status'),
    fetchJSON('./api/settings'),
    fetchJSON('./api/events?limit=25'),
    fetchJSON('./api/attempts?limit=25'),
    fetchJSON('./api/logs?limit=200')
  ]);

  document.getElementById('status').innerHTML = `
    <div class="row"><span class="pill">Spotify: ${status.settings_present.spotify ? 'configured' : 'missing'}</span><span class="pill">YT Music: ${status.settings_present.ytmusic ? 'configured' : 'missing'}</span></div>
    <div class="row">events: ${status.counts.like_events} | attempts: ${status.counts.sync_attempts} | pending: ${status.counts.pending_events}</div>
    <div class="row small muted">last poll started: ${esc(status.last_runs.last_poll_started_at || 'never')}</div>
    <div class="row small muted">last poll finished: ${esc(status.last_runs.last_poll_finished_at || 'never')}</div>
    <div class="row small muted">running: ${status.engine_state.running ? 'yes' : 'no'} | background loop: ${status.engine_state.background_task ? 'active' : 'idle'}</div>
  `;

  for (const key of ['spotify_client_id','spotify_client_secret','spotify_refresh_token','spotify_playlist_id','spotify_market','ytmusic_auth_json','ytmusic_oauth_credentials_json','poll_minutes','match_mode']) {
    const el = document.getElementById(key);
    if (!el) continue;
    if (el.type === 'checkbox') continue;
    el.value = settings[key] ?? el.value ?? '';
  }
  document.getElementById('dry_run').checked = !!settings.dry_run;

  document.getElementById('events').innerHTML = renderTable(events.items, ['source_service','title','artist','liked_at','processed_at']);
  document.getElementById('attempts').innerHTML = renderTable(attempts.items, ['target_service','search_query','status','error_text','attempted_at']);
  document.getElementById('logs').innerHTML = renderLogs(logs.items || []);
}

let lastLogSignature = '';
async function refreshLogs() {
  try {
    const logs = await fetchJSON('./api/logs?limit=200');
    const items = logs.items || [];
    const signature = JSON.stringify(items[items.length - 1] || {});
    if (signature !== lastLogSignature) {
      document.getElementById('logs').innerHTML = renderLogs(items);
      lastLogSignature = signature;
    }
  } catch (err) {
    document.getElementById('status').innerHTML = '<span class="bad">' + esc(err.message) + '</span>';
  }
}

function renderTable(items, keys) {
  const head = '<tr>' + keys.map(k => `<th>${esc(k)}</th>`).join('') + '</tr>';
  const rows = items.map(item => '<tr>' + keys.map(k => `<td>${esc(item[k] || '')}</td>`).join('') + '</tr>').join('');
  return `<table>${head}${rows}</table>`;
}

function renderLogs(items) {
  if (!items.length) return '<div class="muted">No log entries yet.</div>';
  const rows = items.slice().reverse().map(item => {
    const ctx = JSON.stringify(item.context || {});
    return `<tr>
      <td>${esc(item.ts || '')}</td>
      <td>${esc(item.level || '')}</td>
      <td>${esc(item.message || '')}</td>
      <td><code class="small">${esc(ctx)}</code></td>
    </tr>`;
  }).join('');
  return `<table>
    <tr><th>timestamp</th><th>level</th><th>message</th><th>context</th></tr>
    ${rows}
  </table>`;
}

async function saveSettings() {
  const payload = {
    spotify_client_id: document.getElementById('spotify_client_id').value.trim(),
    spotify_client_secret: document.getElementById('spotify_client_secret').value.trim(),
    spotify_refresh_token: document.getElementById('spotify_refresh_token').value.trim(),
    spotify_playlist_id: document.getElementById('spotify_playlist_id').value.trim(),
    spotify_market: document.getElementById('spotify_market').value.trim() || 'GB',
    ytmusic_auth_json: document.getElementById('ytmusic_auth_json').value.trim(),
    ytmusic_oauth_credentials_json: document.getElementById('ytmusic_oauth_credentials_json').value.trim(),
    poll_minutes: parseInt(document.getElementById('poll_minutes').value || '15', 10),
    match_mode: document.getElementById('match_mode').value,
    dry_run: document.getElementById('dry_run').checked,
  };
  await fetchJSON('./api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  await loadAll();
  alert('Saved.');
}

async function runSync() {
  await fetchJSON('./api/sync', { method: 'POST' });
  await loadAll();
}

async function testConnections() {
  const result = await fetchJSON('./api/test-connections', { method: 'POST' });
  const spotify = result.spotify || {};
  const ytmusic = result.ytmusic || {};
  document.getElementById('connection_test_result').innerHTML = `
    <div>Spotify: <span class="${spotify.ok ? 'ok' : 'bad'}">${spotify.ok ? 'ok' : 'failed'}</span> - ${esc(spotify.message || '')}</div>
    <div>YouTube Music: <span class="${ytmusic.ok ? 'ok' : 'bad'}">${ytmusic.ok ? 'ok' : 'failed'}</span> - ${esc(ytmusic.message || '')}</div>
  `;
}

loadAll().catch(err => {
  document.getElementById('status').innerHTML = '<span class="bad">' + esc(err.message) + '</span>';
});
setInterval(refreshLogs, 2000);
</script>
</body>
</html>
"""
