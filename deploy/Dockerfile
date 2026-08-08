# syntax=docker/dockerfile:1
#
# Shared Dockerfile for BOTH Django backends (generic-backend & backend).
# It is specialized entirely through build args so the two services in
# docker-compose.yml can build from the same file:
#
#   APP_DIR          sub-folder (inside the build context) holding one repo
#   PYTHON_VERSION   python:3.13 (generic-backend) / python:3.14 (backend)
#
# The cloned private repos live on the host under deploy/services/<repo> and
# are COPYed in here -- nothing is cloned during the build.

ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# gcc: a few wheels still need a compiler; small safety net.
# git: generic-backend imports gitpython at startup (handlers/rlib).
RUN apt-get update && apt-get install -y --no-install-recommends gcc git \
    && rm -rf /var/lib/apt/lists/*

# Install uv (matches the repos' own tooling).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# --- Dependency layer (cached unless pyproject/lock/README change) ---
ARG APP_DIR=.
COPY ${APP_DIR}/pyproject.toml ${APP_DIR}/uv.lock ${APP_DIR}/README.md ./
# Install only third-party deps; the project itself runs straight from source.
RUN uv sync --frozen --no-install-project

# --- Application source ---
COPY ${APP_DIR}/ ./

# Entrypoint: migrate + collectstatic, then hand off to the service command.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN chmod +x /usr/local/bin/docker-entrypoint

ENTRYPOINT ["docker-entrypoint"]
