import pytest
import sys
import os

# Add the project root to the python path for testing
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from app.telemetry import setup_telemetry

@pytest.fixture(scope="session", autouse=True)
def initialize_telemetry():
    """Session-wide fixture to automatically initialize telemetry before any tests run."""
    setup_telemetry()
