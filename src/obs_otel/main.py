"""Entry point: scrape OBS metrics on an interval and emit OTel spans."""

from __future__ import annotations

import logging
import signal
import threading
from types import FrameType

from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from .config import Config
from .scraper import OBSScraper
from .telemetry import setup_tracing

logger = logging.getLogger(__name__)

SCRAPE_SPAN_NAME = "obs.scrape"


class _Shutdown:
    """Threading event flipped on SIGINT/SIGTERM for graceful shutdown."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def install(self) -> None:
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)

    def _handle(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, shutting down...", signum)
        self._event.set()

    def wait(self, timeout: float) -> bool:
        """Block up to ``timeout`` seconds. Returns True if shutdown requested."""
        return self._event.wait(timeout)

    @property
    def requested(self) -> bool:
        return self._event.is_set()


def _scrape_once(tracer: Tracer, scraper: OBSScraper) -> None:
    with tracer.start_as_current_span(SCRAPE_SPAN_NAME, kind=SpanKind.CLIENT) as span:
        try:
            attributes = scraper.scrape()
        except Exception as exc:  # noqa: BLE001 - record any failure on the span
            span.set_attribute("obs.connected", False)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.warning("Scrape failed: %s", exc)
            return
        span.set_attributes(attributes)
        span.set_status(Status(StatusCode.OK))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config.from_env()
    logger.info(
        "Starting obs-studio-otel: OBS=%s:%s interval=%.1fs OTLP=%s",
        config.obs_host,
        config.obs_port,
        config.scrape_interval_seconds,
        config.otlp_endpoint,
    )

    provider, tracer = setup_tracing(config)
    scraper = OBSScraper(config)

    shutdown = _Shutdown()
    shutdown.install()

    try:
        while not shutdown.requested:
            _scrape_once(tracer, scraper)
            if shutdown.wait(config.scrape_interval_seconds):
                break
    finally:
        logger.info("Flushing telemetry and closing connections...")
        scraper.close()
        provider.shutdown()

    return 0


def run() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
