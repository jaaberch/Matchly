# Matchly worker image — serves both the video and the AI worker.
# One image, two queues: the process is chosen by the compose command, which keeps
# the build simple while allowing the AI queue to move to a GPU node later.
FROM python:3.11-slim AS base

# The computer-vision stack (torch, ultralytics, opencv) is by far the largest
# thing in the deployment. It is opt-in so the media worker stays small, and
# every step that needs it degrades cleanly when it is absent.
ARG INSTALL_CV=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg is pinned by the base image tag, never installed from `latest`, so a
# transcode that works today still works after a rebuild.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/shared/pyproject.toml /app/packages/shared/
COPY services/video-worker/pyproject.toml /app/services/video-worker/
COPY services/ai-worker/pyproject.toml /app/services/ai-worker/
RUN mkdir -p /app/packages/shared/matchly_shared \
             /app/services/video-worker/video_worker \
             /app/services/ai-worker/ai_worker \
 && touch /app/packages/shared/matchly_shared/__init__.py \
          /app/services/video-worker/video_worker/__init__.py \
          /app/services/ai-worker/ai_worker/__init__.py \
 && pip install -e /app/packages/shared[s3,postgres] \
 && pip install -e /app/services/video-worker \
 && if [ "$INSTALL_CV" = "true" ]; then \
        pip install -e "/app/services/ai-worker[cv]"; \
    else \
        pip install -e /app/services/ai-worker; \
    fi

COPY packages/shared /app/packages/shared
COPY services /app/services

RUN useradd --create-home --uid 1000 matchly && chown -R matchly:matchly /app
USER matchly

# Overridden per service in docker-compose.
CMD ["celery", "-A", "video_worker.worker:app", "worker", "-Q", "video", "-c", "2", "-l", "info"]
