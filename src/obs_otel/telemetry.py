"""OpenTelemetry tracer setup with an OTLP/gRPC span exporter."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

from . import __version__
from .config import Config

INSTRUMENTATION_NAME = "obs-studio-otel"


def setup_tracing(config: Config) -> tuple[TracerProvider, Tracer]:
    """Configure the global tracer provider and return it with a tracer.

    The exporter targets the configured OTLP/gRPC endpoint. Standard
    ``OTEL_EXPORTER_OTLP_*`` environment variables are also honoured by the
    underlying exporter, so headers/TLS can be tuned without code changes.
    """
    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": __version__,
            "obs.host": config.obs_host,
            "obs.port": config.obs_port,
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=config.otlp_endpoint,
        insecure=config.otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = provider.get_tracer(INSTRUMENTATION_NAME, __version__)
    return provider, tracer
