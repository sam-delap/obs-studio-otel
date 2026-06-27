# syntax=docker/dockerfile:1
# Build stage: resolve dependencies and install the package. The version is
# supplied explicitly via the SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL
# build-arg (CI passes the release tag), so no git history is needed at build time.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies first (cached layer), without the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the source and install the project.
COPY src ./src
COPY README.md ./
# The package version is supplied here (setuptools_scm reads this as the version
# without consulting git). Required: builds without it fail with "unable to
# detect version". CI passes the release tag (with the leading "v" stripped).
ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL=${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL}
RUN --mount=type=cache,target=/root/.cache/uv \
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
