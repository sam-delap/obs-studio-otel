#!/usr/bin/env bash
#
# teardown.sh — spin down the local OBS → obs-studio-otel → SigNoz test stack.
#
# By default this removes the SigNoz volumes too (stored spans, the Postgres
# metastore, dashboards, and accounts), giving a clean slate on the next bring-up.
# Pass --keep-volumes to preserve them.
#
# Usage:
#   ./scripts/teardown.sh                 # remove scraper + SigNoz + volumes
#   ./scripts/teardown.sh --keep-volumes  # remove containers but keep data
#
# Environment:
#   COMPOSE_FILE     (optional) Path to the rendered SigNoz compose file.
#                              Default: /tmp/opencode/signoz/pours/deployment/compose.yaml
#   SCRAPER_NAME     (optional) Name of the scraper container.
#                              Default: obs-otel-test
#   DOCKER           (optional) Docker command to use (e.g. "sudo docker").
#                              Default: docker
#
# Requires: docker (with the compose v2 plugin).
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/tmp/opencode/signoz/pours/deployment/compose.yaml}"
SCRAPER_NAME="${SCRAPER_NAME:-obs-otel-test}"
DOCKER="${DOCKER:-docker}"

REMOVE_VOLUMES=1
for arg in "$@"; do
  case "$arg" in
    --keep-volumes) REMOVE_VOLUMES=0 ;;
    --remove-volumes) REMOVE_VOLUMES=1 ;;
    -h|--help)
      sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "error: unknown argument: $arg (try --help)" >&2
      exit 1
      ;;
  esac
done

# 1. Remove the scraper container (best effort; it isn't part of the compose stack).
if $DOCKER ps -a --format '{{.Names}}' | grep -qx "$SCRAPER_NAME"; then
  echo "Removing scraper container '$SCRAPER_NAME'..."
  $DOCKER rm -f "$SCRAPER_NAME" >/dev/null
else
  echo "Scraper container '$SCRAPER_NAME' not found; skipping."
fi

# 2. Tear down the SigNoz stack via compose.
down_args=(down --remove-orphans)
if [[ "$REMOVE_VOLUMES" -eq 1 ]]; then
  down_args+=(--volumes)
fi

if [[ -f "$COMPOSE_FILE" ]]; then
  echo "Tearing down SigNoz stack from $COMPOSE_FILE (remove volumes: $([[ $REMOVE_VOLUMES -eq 1 ]] && echo yes || echo no))..."
  $DOCKER compose -f "$COMPOSE_FILE" "${down_args[@]}"
else
  # Compose file is gone (e.g. /tmp was cleared). Fall back to removing the
  # SigNoz containers (and optionally volumes) directly by project label.
  echo "Compose file not found at $COMPOSE_FILE; falling back to direct removal."
  ids="$($DOCKER ps -aq --filter 'label=com.docker.compose.project=signoz' || true)"
  if [[ -n "$ids" ]]; then
    echo "Removing SigNoz containers..."
    $DOCKER rm -f $ids >/dev/null
  else
    echo "No SigNoz containers found."
  fi
  if [[ "$REMOVE_VOLUMES" -eq 1 ]]; then
    vols="$($DOCKER volume ls -q --filter 'label=com.docker.compose.project=signoz' || true)"
    # Fall back to the well-known SigNoz volume names if the label filter misses any.
    vols="$vols $($DOCKER volume ls -q | grep -E '^signoz-' || true)"
    vols="$(echo "$vols" | tr ' ' '\n' | sort -u | grep -v '^$' || true)"
    if [[ -n "$vols" ]]; then
      echo "Removing SigNoz volumes..."
      echo "$vols" | xargs -r $DOCKER volume rm >/dev/null
    fi
  fi
fi

echo "Teardown complete."
