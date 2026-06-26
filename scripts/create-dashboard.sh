#!/usr/bin/env bash
#
# create-dashboard.sh — provision the "OBS Studio — Stream Health & Network"
# dashboard in a SigNoz instance via its REST API.
#
# This records, as code, the dashboard used to visualize the network/stream
# health metrics emitted by obs-studio-otel (the obs.scrape spans) so it can be
# recreated without clicking through the UI.
#
# Usage:
#   SIGNOZ_API_KEY=<key> ./scripts/create-dashboard.sh
#   SIGNOZ_API_KEY=<key> SIGNOZ_URL=http://localhost:18080 ./scripts/create-dashboard.sh
#
# Environment:
#   SIGNOZ_API_KEY  (required) SigNoz API key (Settings -> API Keys, Admin role).
#   SIGNOZ_URL      (optional) Base URL of the SigNoz UI/API.
#                              Default: http://localhost:18080
#   DASHBOARD_JSON  (optional) Path to the dashboard definition.
#                              Default: <this script dir>/obs-network-dashboard.json
#
# Requires: curl, and either jq (preferred) or python3 for JSON handling.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIGNOZ_URL="${SIGNOZ_URL:-http://localhost:18080}"
DASHBOARD_JSON="${DASHBOARD_JSON:-$SCRIPT_DIR/obs-network-dashboard.json}"

if [[ -z "${SIGNOZ_API_KEY:-}" ]]; then
  echo "error: SIGNOZ_API_KEY is required (create one in SigNoz: Settings -> API Keys)." >&2
  exit 1
fi

if [[ ! -f "$DASHBOARD_JSON" ]]; then
  echo "error: dashboard definition not found: $DASHBOARD_JSON" >&2
  exit 1
fi

# The /api/v1/dashboards endpoint expects the dashboard fields (title, widgets,
# layout, ...) at the top level of the request body. We validate the JSON and
# send it as-is.
if command -v jq >/dev/null 2>&1; then
  payload="$(jq -c '.' "$DASHBOARD_JSON")"
else
  payload="$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$DASHBOARD_JSON")"
fi

echo "Creating dashboard from $DASHBOARD_JSON at $SIGNOZ_URL ..."

http_code="$(
  curl -sS -o /tmp/obs-dashboard-resp.json -w '%{http_code}' \
    -X POST "$SIGNOZ_URL/api/v1/dashboards" \
    -H "SIGNOZ-API-KEY: $SIGNOZ_API_KEY" \
    -H 'Content-Type: application/json' \
    --data-binary "$payload"
)"

body="$(cat /tmp/obs-dashboard-resp.json)"

if [[ "$http_code" =~ ^2 ]]; then
  if command -v jq >/dev/null 2>&1; then
    uuid="$(printf '%s' "$body" | jq -r '.data.uuid // .data.id // empty')"
  else
    uuid="$(printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data",{}); print(d.get("uuid") or d.get("id") or "")' 2>/dev/null || true)"
  fi
  echo "Dashboard created (HTTP $http_code)."
  if [[ -n "$uuid" ]]; then
    echo "View it at: $SIGNOZ_URL/dashboard/$uuid"
  fi
else
  echo "error: dashboard creation failed (HTTP $http_code):" >&2
  echo "$body" >&2
  exit 1
fi
