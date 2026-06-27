"""OpenTelemetry logs setup: emit OBS scrapes as canonical log events."""

from __future__ import annotations

from opentelemetry._logs import Logger, set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from . import __version__
from .config import Config

INSTRUMENTATION_NAME = "obs-studio-otel"


def setup_logging(config: Config) -> tuple[LoggerProvider, Logger]:
    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": __version__,
            "obs.host": config.obs_host,
            "obs.port": config.obs_port,
        }
    )
    provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(
        endpoint=config.otlp_endpoint,
        insecure=config.otlp_insecure,
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)
    otel_logger = provider.get_logger(INSTRUMENTATION_NAME, __version__)
    return provider, otel_logger
