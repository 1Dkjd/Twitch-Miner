# Dropwatch: the page is built with Node, the miner runs on Python 3.12. One container, one miner.
#   docker build --build-arg DROPWATCH_COMMIT=main@$(git rev-parse --short HEAD) -t dropwatch .
#   docker run -d -p 5800:5800 -v /path/to/appdata:/data dropwatch

FROM node:24.16.0-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.7-slim-bookworm
# tzdata: TZ sets the server's local time (the weekly summary's default zone); util-linux for setpriv.
# chromium + xvfb + x11vnc: the in-page Twitch sign-in (2026-10-18). Twitch only issues the token that lists
# campaigns and account links on its real login page, so Settings opens it in this Chromium on a virtual
# screen the page shows live. They run only during a sign-in.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata util-linux \
      chromium xvfb x11vnc fonts-liberation fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p -m 1777 /tmp/.X11-unix
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra browser --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra browser
COPY --from=web /web/dist ./web/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

ARG DROPWATCH_COMMIT=""
# required: without it every build looks the same (no update notice, no copy before upgrades)
RUN test -n "$DROPWATCH_COMMIT" || (echo "build with --build-arg DROPWATCH_COMMIT=<branch>@<sha>" && exit 1)
ENV DROPWATCH_COMMIT=$DROPWATCH_COMMIT \
    DROPWATCH_DATA=/data \
    DROPWATCH_WEB=/app/web/dist \
    PATH=/app/.venv/bin:$PATH \
    PUID=99 PGID=100 TZ=UTC \
    DROPWATCH_EXIT_WHEN_STUCK=1 \
    DROPWATCH_BROWSER=/usr/bin/chromium
# Unraid's user 99 (nobody) and group 100 (users) by default, so the host can read /data without sudo

EXPOSE 5800
VOLUME /data
# fails when mining crashed or stopped ticking (not just when the page is down). Unraid shows it; the
# in-app watchdog (DROPWATCH_EXIT_WHEN_STUCK) exits and the container's restart policy brings it back
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5800/api/health/miner', timeout=8).status == 200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["dropwatch", "serve", "--host", "0.0.0.0", "--port", "5800"]
