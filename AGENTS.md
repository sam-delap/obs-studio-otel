# AGENTS.md

Python service that scrapes OBS Studio WebSocket (v5) metrics and emits them as
OpenTelemetry log events (canonical wide events) over OTLP/gRPC. Single-package,
no test suite.

## Toolchain / commands

- Requires **Python 3.14** (`requires-python = ">=3.14"`, `target-version = "py314"`). Older interpreters will not work.
- Managed with **uv**. Use `uv run ...`; do not invoke `pip`/`python` directly.
- Verification = lint only (there are **no tests**). CI runs exactly:
  - `uv run ruff check .`
  - `uv run ruff format --check .` (use `uv run ruff format .` to apply)
- Run the service: `uv run obs-otel` (console script -> `obs_otel.main:run`).

## Architecture

Entrypoint `src/obs_otel/main.py` runs a scrape loop. Each cycle calls
`OBSScraper.scrape()` (`scraper.py`, two OBS requests: `get_stream_status` +
`get_stats`) and emits one `obs.scrape` log event (`telemetry.py` sets up the
logger provider) with the results as event attributes. Config is env-only via
`Config.from_env()` (`config.py`). On scrape failure the event is emitted at
ERROR severity (with the exception recorded) and the OBS client reconnects next
cycle.

## Versioning / releases (do not edit version by hand)

- Version is derived from **git tags** via `setuptools-scm` -> generated
  `src/obs_otel/_version.py` (ruff-excluded; never edit). When running from a source
  tree without an install, `__version__` falls back to `"0.0.0"`.
- Releases are automated: **Conventional Commits** drive semantic-release
  (`fix:` -> patch, `feat:` -> minor, `feat!:`/`BREAKING CHANGE:` -> major). Push to
  `main` -> tag `vX.Y.Z` -> `publish.yml` builds & pushes the GHCR image (version tags
  only, no `:latest`).

## Gotchas

- The **Docker image version does NOT come from git**. It is passed via the
  `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL` build-arg, which is **required**
  (builds without it fail with "unable to detect version"). `publish.yml` derives it
  from the pushed tag with the leading `v` stripped (`vX.Y.Z` -> `X.Y.Z`). For local
  builds pass it yourself (see `docs/SETUP.md`).
- The OTLP exporter also honors standard `OTEL_EXPORTER_OTLP_*` env vars (headers/TLS)
  beyond the documented ones.
- Full local integration test setup (OBS -> scraper -> SigNoz, dashboard provisioning,
  teardown) lives in `docs/SETUP.md` + `scripts/`. Reference it rather than reinventing.
