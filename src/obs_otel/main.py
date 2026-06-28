"""Entry point: scrape OBS metrics on an interval and emit OTel log events."""

from __future__ import annotations

import logging
import signal
import threading
from functools import partial
from types import FrameType
from typing import Any

from opentelemetry._logs import Logger, SeverityNumber

from .config import Config
from .scraper import OBSEventListener, OBSScraper
from .telemetry import setup_logging

logger = logging.getLogger(__name__)

SCRAPE_EVENT_NAME = "obs.scrape"
STREAM_STATE_EVENT_NAME = "obs.stream_state_changed"


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


def _scrape_once(otel_logger: Logger, scraper: OBSScraper) -> None:
    try:
        attributes = scraper.scrape()
    except Exception as exc:  # noqa: BLE001 - record any failure as an event
        otel_logger.emit(
            event_name=SCRAPE_EVENT_NAME,
            severity_number=SeverityNumber.ERROR,
            severity_text="ERROR",
            body=SCRAPE_EVENT_NAME,
            attributes={"obs.connected": False},
            exception=exc,
        )
        logger.warning("Scrape failed: %s", exc)
        return
    otel_logger.emit(
        event_name=SCRAPE_EVENT_NAME,
        severity_number=SeverityNumber.INFO,
        severity_text="INFO",
        body=SCRAPE_EVENT_NAME,
        attributes=attributes,
    )


def _emit_stream_state(otel_logger: Logger, attributes: dict[str, Any]) -> None:
    """Emit a stream state transition pushed by the OBS event listener."""
    logger.info(
        "OBS stream state changed: %s",
        attributes.get("obs.stream.output_state"),
    )
    otel_logger.emit(
        event_name=STREAM_STATE_EVENT_NAME,
        severity_number=SeverityNumber.INFO,
        severity_text="INFO",
        body=STREAM_STATE_EVENT_NAME,
        attributes=attributes,
    )


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

    provider, otel_logger = setup_logging(config)
    scraper = OBSScraper(config)
    listener = OBSEventListener(
        config,
        on_state_change=partial(_emit_stream_state, otel_logger),
    )

    shutdown = _Shutdown()
    shutdown.install()

    try:
        listener.ensure_running()
        while not shutdown.requested:
            # Recover the event listener if OBS dropped its websocket.
            listener.ensure_running()
            _scrape_once(otel_logger, scraper)
            if shutdown.wait(config.scrape_interval_seconds):
                break
    finally:
        logger.info("Flushing telemetry and closing connections...")
        listener.close()
        scraper.close()
        provider.shutdown()

    return 0


def run() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
