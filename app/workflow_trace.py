"""Helpers that emit end-of-run Weave workflow summaries from CLI / Firebase."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.evaluation.hitl_dataset import record_hitl_eval_case
from app.weave_observability import trace_hitl_feedback, trace_workflow_run


def _model_id() -> Optional[str]:
    try:
        from app.model_client import resolve_model_spec

        return resolve_model_spec()
    except Exception:  # noqa: BLE001 - tracing must never break the request path
        return None


def _confidence_from_state(state: Dict[str, Any]) -> Optional[float]:
    extraction = state.get("extraction_result")
    if extraction is None:
        return None
    if hasattr(extraction, "confidence_score"):
        return float(extraction.confidence_score)
    if isinstance(extraction, dict) and "confidence_score" in extraction:
        return float(extraction["confidence_score"])
    return None


def _activity_count_from_state(state: Dict[str, Any]) -> Optional[int]:
    extraction = state.get("extraction_result")
    if extraction is None:
        return None
    if hasattr(extraction, "activities"):
        return len(extraction.activities or [])
    if isinstance(extraction, dict):
        acts = extraction.get("activities") or []
        return len(acts) if isinstance(acts, list) else None
    return None


async def emit_workflow_trace(
    *,
    status: str,
    state: Optional[Dict[str, Any]] = None,
    matrix: Optional[Dict[str, Any]] = None,
    started_at: Optional[float] = None,
    error_code: Optional[str] = None,
    hitl: bool = False,
) -> Dict[str, Any]:
    """Emit a PII-safe ``insummery.workflow.run`` summary."""
    state = state or {}
    matrix = matrix or {}
    warnings = matrix.get("warnings") or []
    guard = state.get("guardrail") or {}
    latency_ms = None
    if started_at is not None:
        latency_ms = (time.monotonic() - started_at) * 1000.0

    disruption_matched = state.get("disruption_matched")
    category = state.get("category")

    return await trace_workflow_run(
        status=status,
        category=category,
        confidence_score=_confidence_from_state(state),
        hitl=hitl,
        warning_count=len(warnings),
        latency_ms=latency_ms,
        model_id=_model_id(),
        error_code=error_code,
        guardrail_passed=guard.get("passed") if guard else None,
        disruption_matched=disruption_matched,
        activity_count=len(matrix.get("activities") or []),
        gap_count=len(matrix.get("gaps") or []),
    )


async def emit_hitl_feedback(
    *,
    workflow_id: str,
    clarification: str,
    status: str,
    state: Optional[Dict[str, Any]] = None,
    confidence_before: Optional[float] = None,
) -> Dict[str, Any]:
    """Record HITL clarification as Weave feedback + optional eval dataset row.

    Never records the clarification text itself — only its length and
    structural outcomes.
    """
    state = state or {}
    confidence_after = _confidence_from_state(state)
    category = state.get("category")
    clarification_chars = len(clarification or "")

    traced = await trace_hitl_feedback(
        workflow_id=workflow_id,
        clarification_chars=clarification_chars,
        status=status,
        confidence_after=confidence_after,
        confidence_before=confidence_before,
        category=category,
    )

    record_hitl_eval_case(
        workflow_id=workflow_id,
        status=status,
        clarification_chars=clarification_chars,
        category=category,
        confidence_before=confidence_before,
        confidence_after=confidence_after,
        activity_count=_activity_count_from_state(state),
    )
    return traced
