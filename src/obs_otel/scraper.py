"""OBS WebSocket client wrapper that scrapes stream health/network stats."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import obsws_python as obs
from obsws_python.error import OBSSDKError

from .config import Config

logger = logging.getLogger(__name__)

# Handler invoked with a flat dict of event attributes whenever OBS reports a
# stream state transition (start/stop/reconnect).
StreamStateHandler = Callable[[dict[str, Any]], None]


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


class OBSEventListener:
    """Subscribes to OBS stream-state events on a background thread.

    Unlike :class:`OBSScraper` (a synchronous request/reconnect client), this
    opens its own ``EventClient`` whose websocket is serviced by a daemon
    listener thread inside ``obsws_python``. Stream state transitions
    (start/stop/reconnect) are pushed to ``on_state_change`` as a flat dict of
    log-event attributes.

    The listener is created lazily and is recoverable: if OBS disconnects, the
    listener thread dies, and :meth:`ensure_running` reconnects on the next
    call (driven by the scrape loop). Connection failures are logged and
    swallowed so they never disrupt the scrape path.
    """

    def __init__(self, config: Config, on_state_change: StreamStateHandler) -> None:
        self._config = config
        self._on_state_change = on_state_change
        self._client: obs.EventClient | None = None

    def _build_event_attributes(self, data: Any) -> dict[str, Any]:
        """Map an obsws StreamStateChanged dataclass to event attributes.

        ``output_active`` is emitted as a 0/1 integer (matching the bool
        convention in :meth:`OBSScraper.scrape`); ``output_state`` is the raw
        OBS state string (e.g. ``OBS_WEBSOCKET_OUTPUT_RECONNECTING``) and is
        consumed by SigNoz only as a group-by dimension, never aggregated.
        """
        return {
            "obs.stream.output_active": int(bool(data.output_active)),
            "obs.stream.output_state": str(data.output_state),
        }

    def on_stream_state_changed(self, data: Any) -> None:
        try:
            attributes = self._build_event_attributes(data)
            self._on_state_change(attributes)
        except Exception:  # noqa: BLE001 - never let a callback kill the thread
            logger.warning("Failed to handle StreamStateChanged event", exc_info=True)

    def is_alive(self) -> bool:
        """Whether the background listener thread is currently running."""
        if self._client is None:
            return False
        worker = getattr(self._client, "worker", None)
        return bool(worker is not None and worker.is_alive())

    def ensure_running(self) -> None:
        """Connect (or reconnect) the event listener if it is not running.

        Safe to call every scrape cycle. Any connection error is logged and
        swallowed; recovery is retried on the next call.
        """
        if self.is_alive():
            return
        # Drop any stale client (e.g. its listener thread died on disconnect).
        if self._client is not None:
            self.close()
        try:
            logger.info(
                "Subscribing to OBS stream-state events at %s:%s",
                self._config.obs_host,
                self._config.obs_port,
            )
            client = obs.EventClient(
                host=self._config.obs_host,
                port=self._config.obs_port,
                password=self._config.obs_password,
                timeout=self._config.obs_timeout,
                subs=obs.Subs.OUTPUTS,
            )
            client.callback.register(self.on_stream_state_changed)
            # obsws_python dispatches events by matching the OBS event name to a
            # callback named ``on_<snake_case_event>`` (see Callback.trigger). If
            # ``on_stream_state_changed`` ever gets renamed, registration succeeds
            # silently but the handler never fires and every stream-state event is
            # dropped. Verify the library actually recognises our handler.
            registered = client.callback.get()
            if "StreamStateChanged" not in registered:
                logger.warning(
                    "OBS event listener did not register a StreamStateChanged "
                    "handler (recognised: %s); stream-state events will be "
                    "dropped. The callback method must be named "
                    "'on_stream_state_changed' to match obsws_python dispatch.",
                    registered,
                )
            self._client = client
        except Exception as exc:  # noqa: BLE001 - listener must not break scrape loop
            self._client = None
            logger.warning("Could not start OBS event listener: %s", exc)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except OBSSDKError, OSError:  # pragma: no cover - best effort cleanup
                logger.debug("Error while disconnecting event listener", exc_info=True)
            finally:
                self._client = None
