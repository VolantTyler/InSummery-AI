import os
import sys
import time

# Add project root to python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

# Set up telemetry (this will configure the ConsoleSpanExporter)
from app.telemetry import setup_telemetry
setup_telemetry()

# Get the tracer
from opentelemetry import trace
tracer = trace.get_tracer("summify.demo")

print("\n=== STARTING SIMULATED GENAI INFERENCE SPAN ===\n")

# Simulate a GenAI inference operation span
with tracer.start_as_current_span("gen_ai.client.inference") as span:
    # Set the model name
    span.set_attribute("gen_ai.request.model", "gemini-2.5-flash")
    
    # Set the OTel GenAI references to the uploaded prompt and response files
    span.set_attribute("gen_ai.input.messages_ref", "gs://summify-telemetry-bucket/2026-06-30/input_abc123.jsonl")
    span.set_attribute("gen_ai.output.messages_ref", "gs://summify-telemetry-bucket/2026-06-30/output_abc123.jsonl")
    span.set_attribute("gen_ai.system_instructions_ref", "gs://summify-telemetry-bucket/2026-06-30/system_instruction_abc123.jsonl")
    
    # Simulate some latency
    print("Processing GenAI request...")
    time.sleep(0.5)
    
    # Set execution status
    span.set_status(trace.Status(trace.StatusCode.OK))

print("\n=== SPAN COMPLETED & EXPORTED TO CONSOLE ===\n")
