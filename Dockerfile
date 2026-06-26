# syntax=docker/dockerfile:1
# Build stage: resolve dependencies and install the package with a real
# setuptools_scm-derived version. The .git directory is bind-mounted (not
# copied) so the version is accurate without bloating the image.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first (cached layer), without the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the source and install the project. The bind-mounted .git lets
# setuptools_scm compute the version from the current tag/commit.
COPY src ./src
COPY README.md ./
# Allow overriding the setuptools_scm version (e.g. for local builds where the
# bind-mounted .git is owned by a different uid and git reports "dubious
# ownership"). Empty by default, so the normal git-derived version is used.
ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL=""
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL=${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL}
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=.git,target=.git \
    git config --global --add safe.directory /app/.git 2>/dev/null || true; \
    uv sync --frozen --no-dev --no-editable

# Runtime stage: minimal image containing only the virtualenv.
FROM python:3.14-slim-bookworm AS runtime

# Create an unprivileged user.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    OBS_HOST=localhost \
    OBS_PORT=4455 \
    SCRAPE_INTERVAL_SECONDS=10 \
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
    OTEL_SERVICE_NAME=obs-studio-scraper

USER app

ENTRYPOINT ["obs-otel"]
