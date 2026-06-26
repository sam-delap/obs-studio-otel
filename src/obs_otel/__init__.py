"""OBS Studio WebSocket -> OpenTelemetry span scraper."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("obs-studio-otel")
except PackageNotFoundError:  # pragma: no cover - not installed (e.g. running from source tree)
    __version__ = "0.0.0"

__all__ = ["__version__"]
