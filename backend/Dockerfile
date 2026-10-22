# Subh AI backend.
#
# Multi-stage so the runtime image carries no build toolchain. The app runs as a
# non-root user, because the terminal tool executes subprocesses - if that
# sandbox is ever bypassed, the blast radius should not include root.

FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# git is on the sandbox allowlist, so it has to exist for that tool to work.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 subh

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=subh:subh app ./app

# The agent workspace is the only path the filesystem tool can reach.
RUN mkdir -p /app/workspace && chown -R subh:subh /app

USER subh
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# One worker: the permission gate, confirmation store and scheduler are
# per-process, so multiple workers would disagree about state. Scale out only
# after moving that state into the database.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
