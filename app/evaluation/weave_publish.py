"""Publish local ``insummery-eval`` reports into Weave Evaluations.

Keeps deterministic scoring in ``app.evaluation.scoring`` as the source of
truth. This module:

1. Publishes sanitized suite rows as versioned ``weave.Dataset`` objects.
2. Mirrors already-computed metrics into Weave via ``EvaluationLogger`` so
   model runs are comparable in the UI without re-invoking agents.
3. Exposes Weave Scorer wrappers around the local exact/fuzzy scorers for
   reuse in future ``weave.Evaluation`` runs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.evaluation.scoring import (
    exact_score,
    score_disruption,
    score_registration_activity,
    score_triager_case,
)
from app.weave_observability import setup_weave, weave_enabled

# Case fields safe to ship to Weave (no raw email bodies).
_SAFE_CASE_KEYS = frozenset(
    {
        "id",
        "score",
        "passed",
        "status",
        "expected",
        "predicted",
        "field_scores",
        "confidence_score",
        "passes_confidence_gate",
        "extracted_activities",
        "category",
        "error",
        "message",
    }
)


def _safe_case(case: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in case.items() if k in _SAFE_CASE_KEYS}


def build_eval_scorers():
    """Wrap local deterministic scorers as Weave Scorer classes.

    These mirror ``app.evaluation.scoring`` so Weave Evaluations and Monitors
    can reuse the same metrics without LLM-as-judge.
    """
    import weave

    class TriagerAccuracyScorer(weave.Scorer):
        @weave.op
        def score(self, output: dict, expected: str = "", predicted: str = "") -> dict:  # type: ignore[override]
            if isinstance(output, dict):
                expected = output.get("expected") or expected
                predicted = output.get("predicted") or predicted
            return {"score": score_triager_case(str(expected), str(predicted))}

    class RegistrationFieldScorer(weave.Scorer):
        @weave.op
        def score(self, output: dict, expected: dict | None = None, predicted: dict | None = None) -> dict:  # type: ignore[override]
            # Prefer precomputed field scores from the local harness.
            if isinstance(output, dict) and "score" in output:
                return {
                    "score": float(output.get("score") or 0.0),
                    "field_scores": output.get("field_scores") or {},
                }
            expected = expected or {}
            predicted = predicted or {}
            return score_registration_activity(expected, predicted)

    class DisruptionFieldScorer(weave.Scorer):
        @weave.op
        def score(self, output: dict, expected: dict | None = None, predicted: dict | None = None) -> dict:  # type: ignore[override]
            if isinstance(output, dict) and "score" in output:
                return {
                    "score": float(output.get("score") or 0.0),
                    "field_scores": output.get("field_scores") or {},
                }
            expected = expected or {}
            predicted = predicted or {}
            return score_disruption(expected, predicted)

    class WorkflowPassScorer(weave.Scorer):
        @weave.op
        def score(self, output: dict) -> dict:  # type: ignore[override]
            if not isinstance(output, dict):
                return {"passed": 0.0, "score": 0.0}
            passed = 1.0 if output.get("passed") else 0.0
            return {
                "passed": passed,
                "score": float(output.get("score") or 0.0),
                "status_ok": exact_score(output.get("status"), "COMPLETED"),
            }

    return {
        "triager": TriagerAccuracyScorer(),
        "registration": RegistrationFieldScorer(),
        "disruption": DisruptionFieldScorer(),
        "workflow": WorkflowPassScorer(),
    }


def publish_eval_datasets(report: Dict[str, Any]) -> Dict[str, Any]:
    """Publish sanitized per-suite rows as Weave Datasets (versioned)."""
    import weave

    details = report.get("details") or {}
    published: Dict[str, int] = {}
    for section_name, section in details.items():
        rows = []
        for case in section.get("cases") or []:
            row = _safe_case(case)
            row["suite"] = section_name
            rows.append(row)
        if not rows:
            continue
        dataset = weave.Dataset(
            name=f"insummery-eval-{section_name}",
            rows=rows,
        )
        weave.publish(dataset)
        published[section_name] = len(rows)
    return published


def publish_eval_report(
    report: Dict[str, Any],
    *,
    evaluation_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish Datasets + EvaluationLogger mirror of a finished eval report.

    Returns ``{"ok": True, "ui_url": ...}`` on success, or a reason dict when
    Weave is disabled / unavailable.
    """
    if not weave_enabled():
        return {"ok": False, "reason": "weave_disabled"}

    if not setup_weave():
        return {"ok": False, "reason": "weave_init_failed"}

    import weave

    datasets_published = publish_eval_datasets(report)
    scorers = build_eval_scorers()

    name = evaluation_name or f"insummery-eval/{report.get('model', 'unknown')}"
    ev = weave.EvaluationLogger(
        name=name,
        model=report.get("model") or "unknown",
        dataset="insummery-eval-suites",
        eval_attributes={
            "timestamp": report.get("timestamp"),
            "suites": report.get("suites") or [],
            "datasets_published": datasets_published,
            "scorer_names": list(scorers.keys()),
        },
        scorers=["score", "passed"],
    )

    details = report.get("details") or {}
    for section_name, section in details.items():
        cases: List[Dict[str, Any]] = section.get("cases") or []
        suite_scorer = scorers.get(
            "triager" if section_name == "triager"
            else "registration" if "registration" in section_name
            else "disruption" if "disruption" in section_name
            else "workflow"
        )
        for case in cases:
            safe = _safe_case(case)
            pred = ev.log_prediction(
                inputs={
                    "suite": section_name,
                    "case_id": case.get("id"),
                },
                output=safe,
            )
            pred.log_score("score", float(case.get("score") or 0.0))
            if "passed" in case:
                pred.log_score("passed", 1.0 if case["passed"] else 0.0)
            # Attach the matching Weave Scorer result for UI drill-down.
            if suite_scorer is not None:
                try:
                    scored = suite_scorer.score(output=safe)
                    for key, value in scored.items():
                        if key in ("score", "passed"):
                            continue
                        if isinstance(value, (int, float, bool)):
                            pred.log_score(f"scorer_{key}", float(value))
                except Exception:  # noqa: BLE001 - publishing must not fail the eval CLI
                    pass

    summary = dict(report.get("metrics") or {})
    ev.log_summary(summary)

    ui_url = getattr(ev, "ui_url", None)
    return {
        "ok": True,
        "ui_url": ui_url,
        "name": name,
        "datasets_published": datasets_published,
    }
