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
| **obs-studio-otel** | Scrapes OBS, emits `obs.scrape` spans over OTLP/gRPC | Docker container |

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

The Dockerfile derives its version from git via `setuptools-scm`. For a local
build where the bind-mounted `.git` is owned by a different uid than the build
user, pass the version explicitly:

```bash
# From the repo root. Create the baseline tag once if it doesn't exist:
git tag v0.1.0 2>/dev/null || true

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
under **Services** in the SigNoz UI, and `obs.scrape` spans under **Traces**.

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
defines 10 panels, all filtered to `service.name = obs-studio-scraper`:

| Panel | Metric |
| --- | --- |
| Stream Output Active | `obs.stream.output_active` |
| Network Congestion (current / over time) | `obs.stream.output_congestion` |
| Dropped Frames % (current / over time) | `obs.stream.output_dropped_frames_pct` |
| Output Bytes Sent | `obs.stream.output_bytes` |
| Output Frames: total vs skipped | `obs.stream.output_total_frames`, `obs.stream.output_skipped_frames` |
| Active FPS | `obs.stats.active_fps` |
| Avg Frame Render Time | `obs.stats.average_frame_render_time_ms` |
| Scrape Health | `count()` of `obs.scrape` spans grouped by `status_code_string` (Ok/Error) |

To re-create or update the dashboard, edit the JSON and re-run the script (it
creates a new dashboard each run).

## 5. Verify

- **UI:** open the dashboard URL printed by the script. While OBS is idle the
  network panels read `0`; start streaming in OBS to see congestion, bytes, and
  frame counters move. FPS, memory, and render-time panels populate immediately.
- **Scrape Health** should show a steady stream of `Ok` spans. A drop to zero or
  a rise in `Error` indicates the scraper or its OBS connection is failing.

## 6. Teardown

The quickest way is the teardown script, which removes the scraper container and
the SigNoz stack. **It removes the SigNoz volumes by default** (stored spans,
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

# Optional: remove the local baseline tag
git tag -d v0.1.0
```

## Troubleshooting

- **Scraper logs `Connection refused`:** OBS isn't reachable at
  `host.docker.internal:4455`. Confirm the OBS WebSocket server is enabled and
  the port matches.
- **Scraper logs an auth error:** check `OBS_PASSWORD`.
- **Dashboard script returns HTTP 403:** the service account lacks a
  write-capable role — recreate it (or its key) with the **Admin** role.
- **Panels show "no data":** confirm spans are arriving (Services →
  `obs-studio-scraper`) and that the dashboard time range covers the period the
  scraper has been running.
