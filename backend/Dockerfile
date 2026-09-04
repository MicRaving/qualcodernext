# QualCoder v4 server image (SERVER_PLAN.md §10.1).
# Multi-stage: build wheels with toolchains, ship a slim runtime.

FROM python:3.11.12-slim-bookworm AS builder

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
# README needed by setuptools long_description if configured; tolerate absence.
RUN pip wheel --no-cache-dir --wheel-dir /wheels .


FROM python:3.11.12-slim-bookworm

# libgomp1: ctranslate2/faster-whisper runtime; ffmpeg: audio transcription.
# rclone: cloud backup mirror (Phase 4 sidecar also uses it). Pinned to a
# versioned release (never `rclone-current`) so builds are reproducible; the
# official SHA256SUMS is verified before extraction (supply-chain guard).
ARG RCLONE_VERSION=v1.69.0
RUN apt-get update \
  && apt-get install -y --no-install-recommends libgomp1 ffmpeg curl unzip ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && curl -fsSL -o /tmp/rclone.zip https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip \
  && curl -fsSL -o /tmp/rclone.sha256 https://downloads.rclone.org/${RCLONE_VERSION}/SHA256SUMS \
  && cd /tmp && grep "rclone-${RCLONE_VERSION}-linux-amd64.zip" rclone.sha256 | sha256sum -c - \
  && unzip -j /tmp/rclone.zip "*/rclone" -d /usr/local/bin/ \
  && chmod +x /usr/local/bin/rclone \
  && rm /tmp/rclone.zip /tmp/rclone.sha256 \
  && useradd --uid 1000 --create-home qualcoder

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY scripts/docker-entrypoint.sh /app/scripts/docker-entrypoint.sh
COPY deploy/Caddyfile /app/deploy/Caddyfile
RUN chmod +x /app/scripts/docker-entrypoint.sh \
 && mkdir -p /data/qualcoder /var/log/qualcoder \
 && chown -R qualcoder:qualcoder /data /var/log/qualcoder /app

USER qualcoder
WORKDIR /app

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
