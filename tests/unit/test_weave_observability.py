"""Tests for optional Weave observability helpers and guardrails."""
import asyncio
import sys
import types

import pytest

import app.weave_observability as wo
from app.schemas import ActivityDetail, DisruptionDetail, InterpretationResult
from app.evaluation.weave_publish import publish_eval_report, _safe_case
from app.weave_monitors import ensure_production_monitors, build_monitors


@pytest.fixture(autouse=True)
def reset_initialized_flag(monkeypatch):
    monkeypatch.setattr(wo, "_INITIALIZED", False)


@pytest.fixture
def fake_weave(monkeypatch):
    """Stub the weave module so tests need no W&B credential or network."""
    calls = []
    module = types.ModuleType("weave")
    module.init = lambda project, **kwargs: calls.append((project, kwargs))
    monkeypatch.setitem(sys.modules, "weave", module)
    return calls


def test_setup_weave_noop_without_api_key(monkeypatch, fake_weave):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.delenv("WEAVE_DISABLED", raising=False)
    assert wo.setup_weave() is False
    assert fake_weave == []


def test_setup_weave_noop_when_disabled(monkeypatch, fake_weave):
    monkeypatch.setenv("WANDB_API_KEY", "test-key")
    monkeypatch.setenv("WEAVE_DISABLED", "true")
    assert wo.setup_weave() is False
    assert fake_weave == []


def test_setup_weave_disables_implicit_patching(monkeypatch, fake_weave):
    """Weave must not auto-trace ADK/GenAI: raw emails reach the workflow
    before pii_mask_node runs, so automatic input capture would leak PII."""
    monkeypatch.setenv("WANDB_API_KEY", "test-key")
    monkeypatch.delenv("WEAVE_DISABLED", raising=False)
    monkeypatch.setenv("WEAVE_PROJECT", "test-project")

    assert wo.setup_weave() is True

    assert len(fake_weave) == 1
    project, kwargs = fake_weave[0]
    assert project == "test-project"
    settings = kwargs["settings"]
    assert settings["redact_pii"] is True
    assert settings["implicitly_patch_integrations"] is False


def test_setup_weave_init_failure_is_noop(monkeypatch, fake_weave):
    """A bad API key / network error must not crash the app."""
    monkeypatch.setenv("WANDB_API_KEY", "bad-key")
    monkeypatch.delenv("WEAVE_DISABLED", raising=False)

    def boom(project, **kwargs):
        raise RuntimeError("401 Unauthorized")

    fake_weave  # keep fixture for sys.modules stub
    import weave

    monkeypatch.setattr(weave, "init", boom)
    assert wo.setup_weave() is False
    assert wo._INITIALIZED is False


def test_setup_weave_settings_disable_real_autopatching(monkeypatch):
    """Against the real weave library: the settings dict setup_weave passes
    must actually turn off implicit_patch() and the import hook, even with
    google.adk / google.genai already imported (as in production)."""
    weave = pytest.importorskip("weave")
    pytest.importorskip("google.adk")

    from weave.integrations import patch as weave_patch
    from weave.trace.settings import (
        replace_settings,
        should_implicitly_patch_integrations,
    )

    monkeypatch.delenv("WEAVE_IMPLICITLY_PATCH_INTEGRATIONS", raising=False)

    weave_patch.reset_patched_integrations()
    try:
        # The same settings dict setup_weave passes to weave.init.
        replace_settings({"redact_pii": True, "implicitly_patch_integrations": False})
        assert should_implicitly_patch_integrations() is False

        # These are the two calls weave.init makes to enable automatic tracing.
        weave_patch.implicit_patch()
        weave_patch.register_import_hook()

        assert weave_patch._PATCHED_INTEGRATIONS == set()
        assert weave_patch._IMPORT_HOOK is None
    finally:
        weave_patch.reset_patched_integrations()
        weave_patch.unregister_import_hook()
        replace_settings(None)


def test_response_summary_registration_omits_names():
    result = InterpretationResult(
        activities=[
            ActivityDetail(
                child_name="Emily",
                activity_title="Soccer",
                start_date="2026-07-06",
                end_date="2026-07-10",
                start_time="09:00",
                end_time="12:00",
            )
        ],
        confidence_score=88,
        evaluation_trace="solid dates",
    )
    summary = wo._response_summary(result)
    assert summary["confidence_score"] == 88
    assert summary["activity_count"] == 1
    assert "Emily" not in str(summary)
    assert "Soccer" not in str(summary)


def test_guardrail_passes_valid_disruption():
    detail = DisruptionDetail(
        child_name="Emily",
        date="2026-07-07",
        description="Camp cancelled",
        disruption_type="CANCELLATION",
    )
    result = wo.check_extraction_guardrails("disruption", detail)
    assert result["passed"] is True
    assert result["violations"] == []


def test_guardrail_flags_invalid_disruption_type():
    detail = DisruptionDetail(
        child_name="Emily",
        date="2026-07-07",
        description="Something odd",
        disruption_type="WEATHER",
    )
    result = wo.check_extraction_guardrails("disruption", detail)
    assert result["passed"] is False
    assert "invalid_disruption_type" in result["violations"]


def test_guardrail_flags_email_leak_in_notes():
    result = InterpretationResult(
        activities=[
            ActivityDetail(
                child_name="Emily",
                activity_title="Soccer",
                start_date="2026-07-06",
                end_date="2026-07-10",
                start_time="09:00",
                end_time="12:00",
                notes="email parent@example.com if late",
            )
        ],
        confidence_score=90,
        evaluation_trace="ok",
    )
    gated = wo.check_extraction_guardrails("registration", result)
    assert gated["passed"] is False
    assert "possible_email_leak" in gated["violations"]


def test_trace_workflow_run_noop_without_weave():
    payload = asyncio.run(
        wo.trace_workflow_run(
            status="COMPLETED",
            category="registration",
            confidence_score=90,
            warning_count=0,
            latency_ms=120.5,
        )
    )
    assert payload["status"] == "COMPLETED"
    assert payload["healthy"] is True
    assert payload["latency_ms"] == 120.5


def test_publish_eval_report_skipped_without_weave(monkeypatch):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    result = publish_eval_report({"model": "test", "metrics": {}, "details": {}})
    assert result == {"ok": False, "reason": "weave_disabled"}


def test_safe_case_strips_unknown_keys():
    safe = _safe_case({"id": "c1", "score": 1.0, "raw_email": "secret", "passed": True})
    assert safe == {"id": "c1", "score": 1.0, "passed": True}
    assert "raw_email" not in safe


def test_ensure_monitors_skipped_without_weave(monkeypatch):
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    result = ensure_production_monitors(dry_run=True)
    assert result["ok"] is False
    assert result["reason"] == "weave_disabled"


def test_build_monitors_when_weave_available(monkeypatch):
    pytest.importorskip("weave")
    monkeypatch.setenv("WANDB_API_KEY", "test-key")
    monkeypatch.delenv("WEAVE_DISABLED", raising=False)
    # Dry-run path still needs weave imported for Scorer subclasses.
    monitors = build_monitors()
    names = {m.name for m in monitors}
    assert "insummery-workflow-health" in names
    assert "insummery-guardrail-pass" in names
    assert "insummery-confidence-gate" in names
