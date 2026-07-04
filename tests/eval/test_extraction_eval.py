"""
Live evaluation test: exercises the real Gemini-backed extraction pipeline
against the curated test cases and asserts a minimum accuracy bar.

This test only runs when a Gemini credential is available (GEMINI_API_KEY or
GOOGLE_API_KEY), since it makes real calls to the Gemini API. It is skipped
automatically otherwise (e.g. in environments without the secret configured).
"""
import asyncio
import os

import pytest

from tests.eval.run_eval import run_all, summarize

pytestmark = pytest.mark.skipif(
    not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
    reason="Requires GEMINI_API_KEY (or GOOGLE_API_KEY) to exercise the live Gemini extraction pipeline.",
)


@pytest.fixture(autouse=True)
def _force_cloud_llm(monkeypatch):
    monkeypatch.setenv("FORCE_CLOUD_LLM", "true")


def test_gemini_extraction_accuracy_meets_bar():
    results = asyncio.run(run_all())
    summary = summarize(results)

    failures = [r["id"] for r in results if not r.get("pass")]
    assert summary["accuracy"] >= 0.8, (
        f"Gemini extraction accuracy {summary['accuracy'] * 100:.1f}% is below the 80% bar. "
        f"Failing cases: {failures}"
    )
