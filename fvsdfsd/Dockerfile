ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.22
FROM ${BUILD_FROM}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/app \
    APP_DATA_DIR=/data/music_like_mirror

WORKDIR /app

COPY rootfs/app/requirements.txt /tmp/requirements.txt
RUN apk add --no-cache gcc musl-dev linux-headers libffi-dev && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    apk del gcc musl-dev linux-headers

COPY rootfs/app /app
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
