# obs-studio-otel

A small Python service that scrapes stream **health** and **network** metrics
from an [OBS Studio](https://obsproject.com/) WebSocket (v5) endpoint and emits
them as **OpenTelemetry log events** over OTLP/gRPC to a collector of your choice.

Each scrape cycle issues two OBS WebSocket requests — `GetStreamStatus` and
`GetStats` — and records the results as attributes on a single `obs.scrape`
log event. The service is designed to run as a container.

## Metrics collected

Each `obs.scrape` log event carries:

| Attribute | Source | Description |
| --- | --- | --- |
| `obs.connected` | — | Whether the scrape connected successfully |
| `obs.stream.output_active` | GetStreamStatus | Stream output is active |
| `obs.stream.output_reconnecting` | GetStreamStatus | Output is reconnecting |
| `obs.stream.output_timecode` | GetStreamStatus | Current output timecode |
| `obs.stream.output_duration_ms` | GetStreamStatus | Output duration (ms) |
| `obs.stream.output_congestion` | GetStreamStatus | Network congestion (0.0–1.0) |
| `obs.stream.output_bytes` | GetStreamStatus | Bytes sent by the output |
| `obs.stream.output_skipped_frames` | GetStreamStatus | Frames skipped by the output |
| `obs.stream.output_total_frames` | GetStreamStatus | Total frames delivered |
| `obs.stream.output_dropped_frames_pct` | derived | skipped / total × 100 |
| `obs.stats.cpu_usage` | GetStats | CPU usage (%) |
| `obs.stats.memory_usage_mb` | GetStats | Memory used by OBS (MB) |
| `obs.stats.available_disk_space_mb` | GetStats | Free recording disk space (MB) |
| `obs.stats.active_fps` | GetStats | Rendered FPS |
| `obs.stats.average_frame_render_time_ms` | GetStats | Avg frame render time (ms) |
| `obs.stats.render_skipped_frames` | GetStats | Render-thread skipped frames |
| `obs.stats.render_total_frames` | GetStats | Render-thread total frames |
| `obs.stats.output_skipped_frames` | GetStats | Output-thread skipped frames |
| `obs.stats.output_total_frames` | GetStats | Output-thread total frames |

On a connection or protocol error the scrape emits an `obs.scrape` log event at
`ERROR` severity with `obs.connected=false`, the exception is recorded as
`exception.*` attributes, and the client reconnects on the next cycle.

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `OBS_HOST` | `localhost` | OBS WebSocket host |
| `OBS_PORT` | `4455` | OBS WebSocket port |
| `OBS_PASSWORD` | _(empty)_ | OBS WebSocket password (if auth enabled) |
| `OBS_TIMEOUT_SECONDS` | `5` | OBS request timeout |
| `SCRAPE_INTERVAL_SECONDS` | `10` | Time between scrapes |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP/gRPC collector endpoint |
| `OTEL_EXPORTER_OTLP_INSECURE` | `true` | Disable TLS for the OTLP exporter |
| `OTEL_SERVICE_NAME` | `obs-studio-scraper` | `service.name` resource attribute |

The OTLP exporter also honours the standard `OTEL_EXPORTER_OTLP_*` environment
variables (e.g. `OTEL_EXPORTER_OTLP_HEADERS`).

## Running with Docker

```bash
docker run --rm \
  -e OBS_HOST=192.168.1.10 \
  -e OBS_PASSWORD=mystrongpass \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
  ghcr.io/sam-delap/obs-studio-otel:0.1.0
```

## Local development

This project uses [uv](https://docs.astral.sh/uv/) and is built with
`setuptools` + `setuptools-scm` (the version is derived from git tags).

```bash
# Install dependencies (including dev tools)
uv sync

# Run the service against a local OBS
uv run obs-otel

# Lint and format
uv run ruff check .
uv run ruff format .          # apply
uv run ruff format --check .  # validate (used in CI)
```

## Versioning & releases

- **Versions are derived from git tags** via `setuptools-scm`. The container
  build does not read git; `publish.yml` passes the release version into the
  image via the `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL` build-arg
  (the tag with its leading `v` stripped) so the in-image `__version__` matches
  the release.
- Releases are automated with
  [semantic-release](https://semantic-release.org/) driven by
  [Conventional Commits](https://www.conventionalcommits.org/):
  - `fix:` → patch, `feat:` → minor, `feat!:`/`BREAKING CHANGE:` → major.
- The project starts in the **0.x** line. Create the baseline tag once before
  the first automated release:

  ```bash
  git tag v0.1.0
  git push origin v0.1.0
  ```

  semantic-release computes subsequent versions relative to this tag.

### CI/CD workflows

- **`lint.yml`** — runs `ruff check` and `ruff format --check` on PRs and on
  pushes to `main`.
- **`release.yml`** — on push to `main`, runs semantic-release to compute the
  next version and create the `vX.Y.Z` git tag + GitHub release.
- **`publish.yml`** — triggered by the new `v*` tag; builds the container and
  pushes version tags (`X.Y.Z`, `X.Y`, `X`) to
  `ghcr.io/sam-delap/obs-studio-otel`. No rolling `:latest` tag is published.
