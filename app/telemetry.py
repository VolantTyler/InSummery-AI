import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.google_genai import GoogleGenAiSdkInstrumentor

logger = logging.getLogger(__name__)

def setup_telemetry():
    """Initializes OpenTelemetry tracing and instruments the Google GenAI SDK.
    
    This function should be called at the very beginning of the application startup,
    before any GenAI Client instances are created.
    """
    # 1. Initialize the Tracer Provider
    provider = TracerProvider()
    
    # 2. Configure the Span Exporter
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            exporter = CloudTraceSpanExporter(project_id=project_id)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OpenTelemetry Cloud Trace exporter configured for project: {project_id}")
        except ImportError:
            logger.warning(
                "opentelemetry-exporter-gcp-trace is not installed. Falling back to console exporter."
            )
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        # Fallback to Console exporter for local development if GOOGLE_CLOUD_PROJECT is not set
        logger.info("GOOGLE_CLOUD_PROJECT not set. Telemetry spans will be output to the console.")
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        
    trace.set_tracer_provider(provider)
    
    # 3. Instrument the Google GenAI SDK
    # This automatically hooks into the SDK to emit spans following the GenAI semantic conventions
    GoogleGenAiSdkInstrumentor().instrument()
    logger.info("Google GenAI SDK successfully instrumented with OpenTelemetry.")
