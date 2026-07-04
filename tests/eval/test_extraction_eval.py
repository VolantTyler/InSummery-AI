"""
Live evaluation test: exercises the real Gemini-backed extraction pipeline
end to end (full ADK workflow) against the curated test cases and asserts a
minimum pass rate.

This is the pytest entry point for the unified eval harness's "workflow"
suite (equivalent to `insummery-eval run --suites workflow`). It only runs
when a Gemini credential is available (GEMINI_API_KEY or GOOGLE_API_KEY),
since it makes real calls to the Gemini API. It is skipped automatically
otherwise (e.g. in environments without the secret configured).
"""
import asyncio
import os

import pytest

from app.evaluation.runner import EvalHarness

pytestmark = pytest.mark.skipif(
    not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
    reason="Requires GEMINI_API_KEY (or GOOGLE_API_KEY) to exercise the live Gemini extraction pipeline.",
)

MIN_PASS_RATE = 0.8


@pytest.fixture(autouse=True)
def _force_cloud_llm(monkeypatch):
    monkeypatch.setenv("FORCE_CLOUD_LLM", "true")


def test_gemini_extraction_accuracy_meets_bar():
    harness = EvalHarness()
    result = asyncio.run(harness.eval_workflow_registration())

    failures = [c["id"] for c in result["cases"] if not c["passed"]]
    assert result["pass_rate"] >= MIN_PASS_RATE, (
        f"Gemini end-to-end extraction pass rate {result['pass_rate'] * 100:.1f}% is below "
        f"the {MIN_PASS_RATE * 100:.0f}% bar. Failing cases: {failures}"
    )
