"""Tests for the optional Weave observability setup.

The critical property under test: when Weave is enabled, ``setup_weave`` must
disable Weave's implicit integration patching. The production workflow receives
the *raw* email as ``new_message`` and only masks it inside ``pii_mask_node``,
so auto-tracing the Google ADK / GenAI SDKs would export unmasked PII.
"""
import sys
import types

import pytest

import app.weave_observability as wo


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
