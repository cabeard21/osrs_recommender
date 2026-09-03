FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY tracker ./tracker
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRACKER_BIND_ADDRESS=0.0.0.0 \
    TRACKER_ALLOW_ALL_INTERFACES=true \
    TRACKER_PORT=8502 \
    TRACKER_DATABASE_URL=sqlite:////data/tracker.db \
    TRACKER_CONFIG_FILE=/config/config.yaml \
    NICEGUI_STORAGE_PATH=/data/nicegui

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels \
    && groupadd --gid 10001 tracker \
    && useradd --uid 10001 --gid tracker --no-create-home --shell /usr/sbin/nologin tracker \
    && mkdir -p /data /config \
    && chown tracker:tracker /data

COPY alembic.ini ./
COPY tracker/migrations ./tracker/migrations
COPY content ./content
COPY docker-entrypoint.sh ./docker-entrypoint.sh

USER tracker
EXPOSE 8502
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8502/healthz', timeout=3).read()"]

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
