import asyncio
import json

import pytest
import yaml

from app.evaluation.runner import EvalHarness, extract_json
from app.evaluation.baseline import (
    is_gemini_model,
    baseline_path,
    save_baseline,
    load_baseline,
    compare_to_baseline,
)

PROFILE = {
    "parents": [{"name": "Sarah", "email": "sarah@example.com", "phone": "555-010-0001"}],
    "children": [{"name": "Emily", "age": 10}],
    "caregivers": [{"name": "Jessica", "email": "jess@example.com", "phone": "555-010-0003"}],
    "address": "555 Pine Lane, Springville",
}

REGISTRATION_EMAIL = (
    "Dear Sarah,\n"
    "Emily is registered for Junior Striker Soccer Camp.\n"
    "Dates: July 6, 2026 to July 10, 2026\n"
    "Times: 09:00 AM - 12:00 PM daily\n"
    "Location: Green Valley Sports Complex\n"
)

DISRUPTION_TEXT = (
    "Hi Sarah, Jessica here - I'm sick and can't watch Emily on Tuesday July 7th 2026."
)

MANIFEST_ENTRY = {
    "id": "case_01",
    "filename": "reg_case.txt",
    "child_name": "Emily",
    "activity_title": "Junior Striker Soccer Camp",
    "start_date": "2026-07-06",
    "end_date": "2026-07-10",
    "start_time": "09:00",
    "end_time": "12:00",
    "location": "Green Valley Sports Complex",
    "notes": None,
}


@pytest.fixture
def eval_root(tmp_path):
    """Build a miniature repo layout with a config, datasets, and one case."""
    eval_dir = tmp_path / "tests" / "eval"
    datasets_dir = eval_dir / "datasets"
    datasets_dir.mkdir(parents=True)

    (tmp_path / "profile.json").write_text(json.dumps(PROFILE))
    (tmp_path / "reg_case.txt").write_text(REGISTRATION_EMAIL)

    (datasets_dir / "triager_cases.json").write_text(json.dumps([
        {"id": "t_reg", "file": "reg_case.txt", "expected_category": "registration"},
        {"id": "t_dis", "text": DISRUPTION_TEXT, "expected_category": "disruption"},
    ]))
    (tmp_path / "manifest.json").write_text(json.dumps([MANIFEST_ENTRY]))
    (datasets_dir / "disruption_cases.json").write_text(json.dumps([
        {
            "id": "d_01",
            "text": DISRUPTION_TEXT,
            "expected": {
                "child_name": "Emily",
                "date": "2026-07-07",
                "disruption_type": "SICK_LEAVE",
                "description": "Jessica is sick and cannot watch Emily",
            },
        }
    ]))

    config = {
        "profile": "profile.json",
        "datasets": {
            "triager": "tests/eval/datasets/triager_cases.json",
            "interpreter_registration": {"manifest": "manifest.json", "cases_dir": "."},
            "interpreter_disruption": "tests/eval/datasets/disruption_cases.json",
        },
        "thresholds": {
            "triager_accuracy": 0.90,
            "registration_field_score": 0.85,
            "disruption_field_score": 0.85,
            "registration_confidence_gate_rate": 0.90,
        },
        "regression_tolerance": 0.05,
        "baselines": {
            "dir": "tests/eval/baselines",
            "local_dir": "tests/eval/baselines/local",
        },
    }
    (eval_dir / "eval_config.yaml").write_text(yaml.safe_dump(config))
    return tmp_path


async def fake_invoker(agent, text):
    """Emulate a model that answers correctly using masked placeholders.

    Asserts that the harness masked PII before the text reached the 'model'.
    """
    assert "Emily" not in text, "child name leaked to the model unmasked"
    assert "Jessica" not in text, "caregiver name leaked to the model unmasked"

    if agent.name == "triager_agent":
        return "disruption" if "sick" in text.lower() else "registration"

    if agent.name == "interpreter_agent_registration":
        return json.dumps({
            "activities": [{
                "child_name": "[CHILD_A]",
                "activity_title": "Junior Striker Soccer Camp",
                "start_date": "2026-07-06",
                "end_date": "2026-07-10",
                "start_time": "09:00",
                "end_time": "12:00",
                "location": "Green Valley Sports Complex",
                "notes": None,
            }],
            "confidence_score": 93,
            "evaluation_trace": "All fields explicit in the email.",
        })

    if agent.name == "interpreter_agent_disruption":
        return json.dumps({
            "child_name": "[CHILD_A]",
            "date": "2026-07-07",
            "start_time": None,
            "end_time": None,
            "description": "[CAREGIVER_A] is sick and cannot watch [CHILD_A]",
            "disruption_type": "SICK_LEAVE",
        })

    raise AssertionError(f"Unexpected agent: {agent.name}")


def make_harness(eval_root, model_spec="gemini/gemini-2.5-flash"):
    return EvalHarness(
        config_path=str(eval_root / "tests" / "eval" / "eval_config.yaml"),
        agent_invoker=fake_invoker,
        model_spec=model_spec,
    )


def test_full_eval_run_with_fake_model(eval_root):
    harness = make_harness(eval_root)
    report = asyncio.run(harness.run_all())

    assert report["model"] == "gemini/gemini-2.5-flash"
    assert report["metrics"]["triager_accuracy"] == 1.0
    assert report["metrics"]["registration_field_score"] == 1.0
    assert report["metrics"]["registration_confidence_gate_rate"] == 1.0
    assert report["metrics"]["disruption_field_score"] == 1.0
    assert harness.check_thresholds(report) == []


def test_thresholds_fail_on_low_scores(eval_root):
    harness = make_harness(eval_root)
    report = asyncio.run(harness.run_all())
    report["metrics"]["triager_accuracy"] = 0.5
    failures = harness.check_thresholds(report)
    assert len(failures) == 1
    assert "triager_accuracy" in failures[0]


def test_baseline_round_trip_and_regression(eval_root):
    harness = make_harness(eval_root)
    report = asyncio.run(harness.run_all())

    path = save_baseline(report, harness.config, harness.root)
    assert path.exists()
    # Gemini baselines go to the committed directory, not local/
    assert "local" not in path.parts

    baseline = load_baseline(harness.config, harness.root, harness.model_spec)
    assert baseline["metrics"] == report["metrics"]

    assert compare_to_baseline(report, baseline, tolerance=0.05) == []

    degraded = json.loads(json.dumps(report))
    degraded["metrics"]["registration_field_score"] = 0.7
    regressions = compare_to_baseline(degraded, baseline, tolerance=0.05)
    assert len(regressions) == 1
    assert "registration_field_score" in regressions[0]


def test_local_model_baseline_routed_to_gitignored_dir(eval_root):
    harness = make_harness(eval_root, model_spec="ollama_chat/gemma4:25b")
    assert not is_gemini_model(harness.model_spec)
    path = baseline_path(harness.config, harness.root, harness.model_spec)
    assert "local" in path.parts
    assert path.name == "baseline_ollama_chat_gemma4_25b.json"


def test_extract_json_variants():
    obj = {"a": 1}
    assert extract_json(json.dumps(obj)) == obj
    assert extract_json(f"```json\n{json.dumps(obj)}\n```") == obj
    assert extract_json(f"Here you go:\n{json.dumps(obj)}\nDone.") == obj
    with pytest.raises(ValueError):
        extract_json("no json here")
