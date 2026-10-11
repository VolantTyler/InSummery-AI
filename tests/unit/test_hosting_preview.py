"""Parser for firebase hosting:channel:deploy --json preview comments."""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "hosting_preview.py"
_spec = importlib.util.spec_from_file_location("hosting_preview", _SCRIPT)
assert _spec is not None and _spec.loader is not None
hosting_preview = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hosting_preview)


def test_parse_channel_deploy_reads_site_url():
    payload = {
        "status": "success",
        "result": {
            "in-summery": {
                "site": "in-summery",
                "url": "https://in-summery--pr12-abc.web.app",
                "expireTime": "2026-10-18T00:00:00.000Z",
            }
        },
    }
    parsed = hosting_preview.parse_channel_deploy(json.dumps(payload))
    assert parsed["url"] == "https://in-summery--pr12-abc.web.app"
    assert parsed["site"] == "in-summery"
    assert parsed["expire_time"] == "2026-10-18T00:00:00.000Z"


def test_parse_channel_deploy_uses_last_json_object():
    noise = 'i  hosting: deploying channel\n{"status":"error","error":"stale"}\n'
    payload = {
        "status": "success",
        "result": {
            "in-summery": {
                "site": "in-summery",
                "url": "https://example.web.app",
                "expireTime": "2026-10-18T00:00:00Z",
            }
        },
    }
    parsed = hosting_preview.parse_channel_deploy(noise + json.dumps(payload))
    assert parsed["url"] == "https://example.web.app"


def test_parse_channel_deploy_rejects_error_status():
    payload = {"status": "error", "error": "Failed to authenticate, have you run firebase login?"}
    with pytest.raises(hosting_preview.PreviewDeployError, match="Failed to authenticate"):
        hosting_preview.parse_channel_deploy(json.dumps(payload))


def test_parse_channel_deploy_rejects_missing_url():
    with pytest.raises(hosting_preview.PreviewDeployError, match="https url"):
        hosting_preview.parse_channel_deploy('{"status":"success","result":{}}')


def test_success_comment_includes_marker_url_and_short_sha():
    body = hosting_preview.success_comment(
        project="in-summery",
        sha="abcdef1234567890",
        url="https://in-summery--pr1.web.app",
        expire_time="2026-10-18T00:00:00Z",
    )
    assert hosting_preview.COMMENT_MARKER in body
    assert "https://in-summery--pr1.web.app" in body
    assert "`abcdef1`" in body
    assert "in-summery" in body
    assert "private_key" not in body


def test_failure_comment_points_at_the_run_and_not_a_credential():
    body = hosting_preview.failure_comment(
        run_url="https://github.com/VolantTyler/InSummery-AI/actions/runs/1"
    )
    assert hosting_preview.COMMENT_MARKER in body
    assert "actions/runs/1" in body
    assert "BEGIN PRIVATE KEY" not in body
