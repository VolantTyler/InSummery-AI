import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor

logger = logging.getLogger(__name__)


def _console_export_enabled() -> bool:
    """Opt-in console span export for local debugging.

    Local CLI runs instrument the GenAI SDK but stay quiet by default so demo
    output is not drowned in JSON spans. Set INSUMMERY_OTEL_CONSOLE=true to
    print spans to stderr.
    """
    return os.getenv("INSUMMERY_OTEL_CONSOLE", "").lower() in ("1", "true", "yes")


def _cloud_trace_export_disabled() -> bool:
    """Opt-out for the Cloud Trace exporter.

    Cloud Trace export needs the `roles/cloudtrace.agent` grant (specifically
    `cloudtrace.traces.patch`) on top of whatever the caller actually needs to
    talk to the model. A credential scoped tightly to just Vertex AI access --
    exactly what you want for a CI service account -- doesn't have it, and the
    BatchSpanProcessor doesn't fail quietly: it retries on its export interval
    (every 5s by default) for the life of the process, each attempt logging a
    full traceback. Measured impact: a nightly eval run against a
    Vertex-AI-only-scoped service account produced dozens of these per minute
    for the run's entire duration.

    Set INSUMMERY_DISABLE_CLOUD_TRACE=true to skip configuring the exporter
    rather than widening the credential's IAM grant just to keep an eval run
    quiet -- the eval harness doesn't need to feed production trace tooling.
    """
    return os.getenv("INSUMMERY_DISABLE_CLOUD_TRACE", "").lower() in ("1", "true", "yes")


def _maybe_add_console_exporter(provider: TracerProvider) -> None:
    if _console_export_enabled():
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        logger.info("OpenTelemetry console span exporter enabled (INSUMMERY_OTEL_CONSOLE).")


def setup_telemetry():
    """Initializes OpenTelemetry tracing and instruments the Google GenAI SDK.
    
    This function should be called at the very beginning of the application startup,
    before any GenAI Client instances are created.
    """

    from app.weave_observability import setup_weave

    setup_weave()

    # 1. Initialize the Tracer Provider
    provider = TracerProvider()
    
    # 2. Configure the Span Exporter
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id and _cloud_trace_export_disabled():
        logger.info(
            "Cloud Trace exporter skipped (INSUMMERY_DISABLE_CLOUD_TRACE)."
        )
        _maybe_add_console_exporter(provider)
    elif project_id:
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            exporter = CloudTraceSpanExporter(project_id=project_id)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OpenTelemetry Cloud Trace exporter configured for project: {project_id}")
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-gcp-trace is not installed. Cloud Trace export disabled."
            )
            _maybe_add_console_exporter(provider)
    else:
        # Local / CLI: instrument the SDK but stay quiet unless console export is requested.
        _maybe_add_console_exporter(provider)
        
    trace.set_tracer_provider(provider)
    
    # 3. Instrument the Google GenAI SDK
    # This automatically hooks into the SDK to emit spans following the GenAI semantic conventions
    GoogleGenAiSdkInstrumentor().instrument()
    logger.info("Google GenAI SDK successfully instrumented with OpenTelemetry.")
