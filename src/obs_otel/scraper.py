"""OBS WebSocket client wrapper that scrapes stream health/network stats."""

from __future__ import annotations

import logging
from typing import Any

import obsws_python as obs
from obsws_python.error import OBSSDKError

from .config import Config

logger = logging.getLogger(__name__)


def _safe(value: float | int | None) -> float | int:
    """Coerce a possibly-missing numeric field to an event-friendly value."""
    return value if value is not None else 0


class OBSScraper:
    """Manages a single OBS WebSocket connection and metric retrieval.

    The client is connected lazily and reconnected on demand so that the
    scrape loop keeps running across OBS restarts.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client: obs.ReqClient | None = None

    def _connect(self) -> obs.ReqClient:
        if self._client is not None:
            return self._client
        logger.info(
            "Connecting to OBS WebSocket at %s:%s",
            self._config.obs_host,
            self._config.obs_port,
        )
        self._client = obs.ReqClient(
            host=self._config.obs_host,
            port=self._config.obs_port,
            password=self._config.obs_password,
            timeout=self._config.obs_timeout,
        )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except OBSSDKError:  # pragma: no cover - best effort cleanup
                logger.debug("Error while disconnecting from OBS", exc_info=True)
            finally:
                self._client = None

    def _reset(self) -> None:
        """Drop the current client so the next scrape reconnects."""
        self.close()

    def scrape(self) -> dict[str, Any]:
        """Fetch stream status and stats from OBS.

        Returns a flat dict of log-event attributes. Raises on
        connection/protocol errors so the caller can emit a failure event and
        trigger a reconnect on the next cycle.
        """
        try:
            client = self._connect()
            stream = client.get_stream_status()
            stats = client.get_stats()
        except Exception:
            # Force a fresh connection on the next attempt.
            self._reset()
            raise

        attributes: dict[str, Any] = {
            "obs.connected": True,
            # --- Stream health / network (GetStreamStatus) ---
            # output_active / output_reconnecting are emitted as 0/1 integers
            # (not bools) so SigNoz can aggregate them; the raw boolean type
            # cannot be averaged/maxed and renders as NaN in panels.
            "obs.stream.output_active": int(bool(stream.output_active)),
            "obs.stream.output_reconnecting": int(bool(stream.output_reconnecting)),
            "obs.stream.output_timecode": str(stream.output_timecode),
            "obs.stream.output_duration_ms": _safe(stream.output_duration),
            "obs.stream.output_congestion": _safe(stream.output_congestion),
            "obs.stream.output_bytes": _safe(stream.output_bytes),
            "obs.stream.output_skipped_frames": _safe(stream.output_skipped_frames),
            "obs.stream.output_total_frames": _safe(stream.output_total_frames),
            # --- OBS / session stats (GetStats) ---
            "obs.stats.cpu_usage": _safe(stats.cpu_usage),
            "obs.stats.memory_usage_mb": _safe(stats.memory_usage),
            "obs.stats.available_disk_space_mb": _safe(stats.available_disk_space),
            "obs.stats.active_fps": _safe(stats.active_fps),
            "obs.stats.average_frame_render_time_ms": _safe(stats.average_frame_render_time),
            "obs.stats.render_skipped_frames": _safe(stats.render_skipped_frames),
            "obs.stats.render_total_frames": _safe(stats.render_total_frames),
            "obs.stats.output_skipped_frames": _safe(stats.output_skipped_frames),
            "obs.stats.output_total_frames": _safe(stats.output_total_frames),
        }
        return attributes
