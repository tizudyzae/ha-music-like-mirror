#!/usr/bin/with-contenv bash
set -euo pipefail
mkdir -p /data/music_like_mirror
exec uvicorn app:app --host 0.0.0.0 --port 8099
