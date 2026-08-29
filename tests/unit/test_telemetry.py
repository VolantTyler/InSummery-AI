"""Tests for app/telemetry.py's Cloud Trace opt-out.

Regression test for a real incident: a nightly eval run authenticated with a
service account deliberately scoped to only roles/aiplatform.user (least
privilege) hit the eval job's 45-minute CI timeout. The confirmed, concrete
finding in the logs was that setup_telemetry() unconditionally tries to
export spans to Cloud Trace whenever GOOGLE_CLOUD_PROJECT is set, and that
credential lacks cloudtrace.traces.patch -- so the BatchSpanProcessor retried
and logged a full traceback on its 5-second export interval for the entire
run. INSUMMERY_DISABLE_CLOUD_TRACE lets a caller skip configuring the
exporter instead of widening the credential's IAM grant just to keep an eval
run quiet.
"""
import logging

import pytest

from app.telemetry import _cloud_trace_export_disabled, setup_telemetry


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("false", False),
        ("0", False),
        ("", False),
    ],
)
def test_cloud_trace_export_disabled_parses_common_truthy_values(monkeypatch, value, expected):
    monkeypatch.setenv("INSUMMERY_DISABLE_CLOUD_TRACE", value)
    assert _cloud_trace_export_disabled() is expected


def test_cloud_trace_export_disabled_defaults_to_false(monkeypatch):
    monkeypatch.delenv("INSUMMERY_DISABLE_CLOUD_TRACE", raising=False)
    assert _cloud_trace_export_disabled() is False


def test_setup_telemetry_skips_cloud_trace_exporter_when_disabled(monkeypatch, caplog):
    """The regression case: a GCP project is configured (as it is for any
    Vertex AI run) but the opt-out is set -- CloudTraceSpanExporter must never
    be constructed, since constructing it is what starts the retry loop."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fake-project")
    monkeypatch.setenv("INSUMMERY_DISABLE_CLOUD_TRACE", "true")
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.setenv("WEAVE_DISABLED", "true")

    with caplog.at_level(logging.INFO):
        setup_telemetry()

    assert "Cloud Trace exporter skipped" in caplog.text
    assert "Cloud Trace exporter configured" not in caplog.text


def test_setup_telemetry_does_not_crash_without_gcp_project(monkeypatch):
    """Local/CLI runs (no GOOGLE_CLOUD_PROJECT) must keep working regardless
    of the opt-out -- there was never an exporter to skip."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("INSUMMERY_DISABLE_CLOUD_TRACE", raising=False)
    monkeypatch.setenv("WEAVE_DISABLED", "true")
    setup_telemetry()
