# Local test setup: OBS → obs-studio-otel → SigNoz

This guide walks through running `obs-studio-otel` against a local OBS Studio
instance and visualizing the scraped stream-health / network metrics in
[SigNoz](https://signoz.io/). It also covers provisioning the bundled
**"OBS Studio — Stream Health & Network"** dashboard from
[`scripts/`](../scripts).

## What gets stood up

| Component | Role | Where |
| --- | --- | --- |
| **OBS Studio** | Source of metrics; WebSocket v5 server (auth on) | host, `:4455` |
| **SigNoz stack** | OTel collector + ClickHouse + ClickHouse Keeper + Postgres + UI | Docker (via Foundry) |
| **obs-studio-otel** | Scrapes OBS, emits `obs.scrape` log events over OTLP/gRPC | Docker container |

SigNoz's stack already includes an OpenTelemetry collector that accepts OTLP on
`4317` (gRPC) and `4318` (HTTP), so **no separate collector is required** — the
scraper exports directly to SigNoz's collector.

## Prerequisites

- Docker Engine 20.10+ with the Compose v2 plugin, and **≥4 GB** memory
  available to Docker (SigNoz requirement).
- OBS Studio running with **Tools → WebSocket Server Settings → Enable
  WebSocket server** (note the port and password).
- `curl` and `python3` (or `jq`) on the host for the dashboard script.

> **Port note:** This guide maps the SigNoz UI to host port **`18080`** because
> `8080` was already in use on the test machine. If `8080` is free for you, you
> can leave the default and substitute `8080` for `18080` throughout.

## 1. Stand up SigNoz

SigNoz is installed with [Foundry](https://github.com/SigNoz/foundry), its
deployment CLI.

```bash
# Install foundryctl (installs to ~/.local/bin)
curl -fsSL https://signoz.io/foundry.sh | bash

# Create a working directory and a minimal casting file
mkdir -p ~/signoz && cd ~/signoz
cat > casting.yaml <<'YAML'
apiVersion: v1alpha1
kind: Installation
metadata:
  name: signoz
spec:
  deployment:
    flavor: compose
    mode: docker
YAML

# Render the Compose files (does not start anything yet)
foundryctl forge -f casting.yaml
```

If you need to change the UI port (e.g. `8080` is taken), edit the rendered
`pours/deployment/compose.yaml` and change the `signoz-signoz-0` service port
mapping from `8080:8080` to `18080:8080`. Then bring the stack up:

```bash
docker compose -f pours/deployment/compose.yaml up -d
```

Verify all containers are healthy and note the collector + UI:

```bash
docker compose -f pours/deployment/compose.yaml ps
```

You should see `signoz-ingester-1` publishing `4317-4318` and `signoz-signoz-0`
publishing `18080->8080`. Open the UI at <http://localhost:18080> and complete
the first-run account setup if prompted.

## 2. Build the scraper image

The image version is supplied at build time via the
`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL` build-arg (the build does
not read git). The arg is **required** — a build without it fails with
`setuptools-scm was unable to detect version`.

```bash
# From the repo root. Pass the version you want baked into the image:
docker build \
  --build-arg SETUPTOOLS_SCM_PRETEND_VERSION_FOR_OBS_STUDIO_OTEL=0.1.0 \
  -t obs-studio-otel:test .
```

## 3. Run the scraper against OBS

Attach the scraper to SigNoz's Compose network so it can reach the collector by
service name, and use `host.docker.internal` to reach OBS on the host:

```bash
docker run -d --name obs-otel-test \
  --network signoz-network \
  --add-host=host.docker.internal:host-gateway \
  -e OBS_HOST=host.docker.internal \
  -e OBS_PORT=4455 \
  -e OBS_PASSWORD='<your-obs-websocket-password>' \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://signoz-ingester:4317 \
  -e OTEL_EXPORTER_OTLP_INSECURE=true \
  -e SCRAPE_INTERVAL_SECONDS=5 \
  -e OTEL_SERVICE_NAME=obs-studio-scraper \
  obs-studio-otel:test

# Confirm it connected and is scraping cleanly:
docker logs -f obs-otel-test
```

Look for `Successfully identified ReqClient with the server` and the absence of
`Scrape failed` warnings. Within a few seconds, `obs-studio-scraper` will appear
as a source under **Logs** in the SigNoz UI, emitting `obs.scrape` log events.

## 4. Create the dashboard

Dashboard provisioning uses the SigNoz REST API, which authenticates with an API
key. **In current SigNoz, API keys belong to service accounts, not human
users.**

1. In the SigNoz UI, go to **Settings → Service Accounts** and create a service
   account (e.g. `dashboard-provisioner`) with the **Admin** role. Creating an
   API key requires an Admin user, and provisioning a dashboard is a *write*
   operation, so the service account must be **Admin** (or at least Editor) — a
   Viewer-role key will be rejected with `403`.
2. Open the service account's **Keys** tab and generate an API key. Copy it.
3. Run the provisioning script, passing the key via the environment:

   ```bash
   SIGNOZ_API_KEY='<your-service-account-api-key>' \
     ./scripts/create-dashboard.sh
   ```

   To target a non-default URL:

   ```bash
   SIGNOZ_API_KEY='<key>' SIGNOZ_URL=http://localhost:18080 \
     ./scripts/create-dashboard.sh
   ```

On success the script prints the dashboard URL, e.g.
`http://localhost:18080/dashboard/<uuid>`.

> **Keep the key out of version control.** The script only reads
> `SIGNOZ_API_KEY` from the environment; it never writes it to disk. Do not
> commit the key or paste it into tracked files.

### The dashboard

[`scripts/obs-network-dashboard.json`](../scripts/obs-network-dashboard.json)
defines 7 panels, all filtered to `service.name = obs-studio-scraper`. It is
scoped to the three ways an OBS→YouTube stream drops frames; general health /
built-in-editor metrics (render-thread frames, FPS, render time, memory, bytes)
are intentionally excluded. Derived views (percentages) are computed at query
time via SigNoz query formulas rather than baked into the scraper, so new views
can be added as panels without changing the emitter:

| Panel | Failure mode / signal |
| --- | --- |
| Frames Dropped on the Wire (%) | Shared overview: `obs.stream.output_skipped_frames` / `obs.stream.output_total_frames` × 100 |
| Mode 1: Network Congestion / Buffer Saturation | `obs.stream.output_congestion` × 100 vs `obs.stream.output_reconnecting` — congestion saturating with no reconnect = internal network can't drain OBS's buffer |
| Mode 1: Congestion (current) | `obs.stream.output_congestion` × 100 (query-time %, last value) |
| Mode 2: YouTube Endpoint Disconnects (sampled) | `obs.stream.output_reconnecting` vs wire-dropped % — periodic sample of upstream RTMPS drops |
| Mode 2: Stream State Transitions (events) | `count()` of `obs.stream_state_changed` grouped by `obs.stream.output_state` — event-driven, catches reconnects between scrapes |
| Mode 3: OBS Output Send Failures (%) | `obs.stats.output_skipped_frames` / `obs.stats.output_total_frames` × 100 (output/encoder thread, not render) |
| Mode 3: OBS Send Drop % (current) | same as above, last value |

> **String vs bool in SigNoz.** Booleans (`output_active`, `output_reconnecting`)
> are emitted as 0/1 integers so they can be aggregated (`max`/`avg`) — a raw
> bool renders as NaN. The `obs.stream.output_state` string is handled the
> opposite way: it is used only as a **group-by dimension** (one series per
> state) via `count()`, never aggregated as a number. Follow this convention for
> any new panels: numbers for metrics, strings for dimensions/filters.

To re-create or update the dashboard, edit the JSON and re-run the script (it
creates a new dashboard each run).

## 5. Verify

- **UI:** open the dashboard URL printed by the script. While OBS is idle the
  panels read `0`; start streaming in OBS to see congestion, dropped-frame %, and
  the frame counters move.
- **Mode 2 events:** start/stop streaming (or briefly drop the network) to see
  `obs.stream_state_changed` events appear in the "Stream State Transitions"
  panel, grouped by state (e.g. `OBS_WEBSOCKET_OUTPUT_STARTED`,
  `..._RECONNECTING`, `..._STOPPED`).
- **Distinguishing the modes:** sustained congestion approaching 100% with no
  reconnect = Mode 1; reconnect spikes / state transitions = Mode 2; output-thread
  send drops while congestion is low and no reconnect = Mode 3.

## 6. Teardown

The quickest way is the teardown script, which removes the scraper container and
the SigNoz stack. **It removes the SigNoz volumes by default** (stored logs,
metastore, dashboards, accounts) for a clean slate:

```bash
./scripts/teardown.sh                 # remove scraper + SigNoz + volumes (default)
./scripts/teardown.sh --keep-volumes  # remove containers but keep stored data
```

If your Docker socket needs `sudo`, pass the command in:

```bash
DOCKER='sudo docker' ./scripts/teardown.sh
```

Or do it manually:

```bash
# Stop the scraper
sudo docker rm -f obs-otel-test

# Tear down SigNoz (drop -v to keep stored telemetry)
sudo docker compose -f /tmp/opencode/signoz/pours/deployment/compose.yaml down -v
```

## Troubleshooting

- **Scraper logs `Connection refused`:** OBS isn't reachable at
  `host.docker.internal:4455`. Confirm the OBS WebSocket server is enabled and
  the port matches.
- **Scraper logs an auth error:** check `OBS_PASSWORD`.
- **Dashboard script returns HTTP 403:** the service account lacks a
  write-capable role — recreate it (or its key) with the **Admin** role.
- **Panels show "no data":** confirm log events are arriving (Logs explorer,
  filter `service.name = obs-studio-scraper`) and that the dashboard time range
  covers the period the scraper has been running.
