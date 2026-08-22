# Matchly API image.
# Deliberately does NOT include ffmpeg, OpenCV or torch: the API never touches
# video bytes, it only enqueues work by task name.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency manifests first so the layer cache survives source edits.
COPY packages/shared/pyproject.toml /app/packages/shared/
COPY apps/api/pyproject.toml /app/apps/api/
RUN mkdir -p /app/packages/shared/matchly_shared /app/apps/api/app \
 && touch /app/packages/shared/matchly_shared/__init__.py /app/apps/api/app/__init__.py \
 && pip install -e /app/packages/shared[s3,postgres] \
 && pip install -e "/app/apps/api[dev]"

COPY packages/shared /app/packages/shared
COPY apps/api /app/apps/api
COPY infra/scripts /app/infra/scripts
RUN chmod +x /app/infra/scripts/*.sh

# Run as a non-root user.
RUN useradd --create-home --uid 1000 matchly && chown -R matchly:matchly /app
USER matchly

WORKDIR /app/apps/api
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
