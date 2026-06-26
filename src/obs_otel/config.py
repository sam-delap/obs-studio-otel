"""Environment-driven configuration for the OBS OTel scraper."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid integer for {name!r}: {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid number for {name!r}: {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class Config:
    """Runtime configuration resolved from environment variables."""

    # OBS WebSocket connection.
    obs_host: str
    obs_port: int
    obs_password: str
    obs_timeout: float

    # Scrape loop.
    scrape_interval_seconds: float

    # OpenTelemetry. The OTLP exporter additionally honours the standard
    # OTEL_EXPORTER_OTLP_* environment variables natively.
    otlp_endpoint: str
    otlp_insecure: bool
    service_name: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            obs_host=os.environ.get("OBS_HOST", "localhost"),
            obs_port=_get_int("OBS_PORT", 4455),
            obs_password=os.environ.get("OBS_PASSWORD", ""),
            obs_timeout=_get_float("OBS_TIMEOUT_SECONDS", 5.0),
            scrape_interval_seconds=_get_float("SCRAPE_INTERVAL_SECONDS", 10.0),
            otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            otlp_insecure=_get_bool("OTEL_EXPORTER_OTLP_INSECURE", True),
            service_name=os.environ.get("OTEL_SERVICE_NAME", "obs-studio-scraper"),
        )
