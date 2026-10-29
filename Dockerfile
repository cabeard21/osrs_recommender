FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS frontend

WORKDIR /build/frontend/gear
COPY frontend/gear/package.json frontend/gear/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/gear ./
RUN npm run build

FROM --platform=$BUILDPLATFORM python:3.12-slim-bookworm AS icons

WORKDIR /build
RUN python -m pip install --no-cache-dir httpx pydantic PyYAML
COPY tracker ./tracker
COPY content ./content
COPY tools/capture_gear_icons.py ./tools/capture_gear_icons.py
# Capture before wheel creation so CI images include every authored physical form.
# A failed download fails the build; the runtime never needs network icon access.
RUN python -u -m tools.capture_gear_icons

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY tracker ./tracker
COPY contracts ./contracts
COPY --from=icons /build/tracker/ui/assets/items ./tracker/ui/assets/items
COPY --from=frontend /build/tracker/ui/gear_static ./tracker/ui/gear_static
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
