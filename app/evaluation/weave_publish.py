"""Publish local ``insummery-eval`` reports into Weave Evaluations.

Keeps deterministic scoring in ``app.evaluation.scoring``; this module only
mirrors already-computed metrics into Weave's EvaluationLogger UI so model
runs can be compared without re-invoking agents.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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


def publish_eval_report(
    report: Dict[str, Any],
    *,
    evaluation_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Log a finished eval report into Weave via EvaluationLogger.

    Returns ``{"ok": True, "ui_url": ...}`` on success, or a reason dict when
    Weave is disabled / unavailable.
    """
    if not weave_enabled():
        return {"ok": False, "reason": "weave_disabled"}

    setup_weave()
    import weave

    name = evaluation_name or f"insummery-eval/{report.get('model', 'unknown')}"
    ev = weave.EvaluationLogger(
        name=name,
        model=report.get("model") or "unknown",
        dataset="insummery-eval-suites",
        eval_attributes={
            "timestamp": report.get("timestamp"),
            "suites": report.get("suites") or [],
        },
        scorers=["score", "passed"],
    )

    details = report.get("details") or {}
    for section_name, section in details.items():
        cases: List[Dict[str, Any]] = section.get("cases") or []
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

    summary = dict(report.get("metrics") or {})
    ev.log_summary(summary)

    ui_url = getattr(ev, "ui_url", None)
    return {"ok": True, "ui_url": ui_url, "name": name}
