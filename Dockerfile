# syntax=docker/dockerfile:1
# social-bot: Graph API Page bot (feed dashboard + scheduled refresh), one
# container. Build: docker compose build      Run: docker compose up -d
#
# Rebuilds are fast: pip's downloaded wheels live in a BuildKit cache mount
# (~/.cache/pip) shared across builds, so `docker compose build` only
# re-fetches a dependency when pyproject.toml actually changes.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SOCIAL_BOT_HOME=/app

WORKDIR /app

# Install the package first (layers well): metadata + src only.
COPY pyproject.toml README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ".[server]"

# Runtime config; keep it a thin layer so overriding it is a cheap bind mount.
COPY config.yaml ./
# Docs (voice briefs, design preview) so the image is self-contained;
# compose bind-mounts ./docs over this for live edits.
COPY docs ./docs

# Non-root runtime user. Runs as uid/gid 1000 by default so it matches a typical
# host user and the bind-mounted ./data needs no chown. Override when your host
# uid differs: --build-arg UID=$(id -u) --build-arg GID=$(id -g).
ARG UID=1000
ARG GID=1000
RUN groupadd --gid "$GID" socialbot \
    && useradd --uid "$UID" --gid "$GID" --no-create-home --shell /usr/sbin/nologin socialbot \
    && mkdir -p /app/data \
    && chown -R "$UID:$GID" /app

USER socialbot

# `social-bot serve` = feed dashboard + scheduled refresh in one long-lived
# process. One-shot CLI commands still work:
#   docker compose run --rm social-bot whoami
EXPOSE 8080
ENTRYPOINT ["social-bot"]
CMD ["serve"]
