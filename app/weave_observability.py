"""Optional Weights & Biases Weave observability helpers.

The app's primary privacy boundary is still ``PIIMasker``. This module only
initializes Weave when explicitly configured and exposes helpers that record
masked/summarized metadata rather than raw family emails or Firebase tokens.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_INITIALIZED = False
_DISABLED_VALUES = {"1", "true", "yes", "on"}

# Keep in sync with DisruptionDetail prompt / schemas.
ALLOWED_DISRUPTION_TYPES = frozenset({"CANCELLATION", "DELAY", "SICK_LEAVE"})

# Defense-in-depth patterns for values that should never appear in LLM output
# after PII masking (emails/phones). Names are intentionally omitted — family
# names can appear as placeholders like [CHILD_1] and real first names are
# sometimes schedule titles; Presidio PERSON checks are too noisy here.
_LEAK_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_LEAK_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Opt-in Presidio pass over masked interpreter field text.
# Set WEAVE_PRESIDIO_GUARDRAIL=true to enable (requires presidio-analyzer).
_PRESIDIO_ENABLED_VALUES = {"1", "true", "yes", "on"}
_PRESIDIO_ENTITIES = ("EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD")


def weave_enabled() -> bool:
    """Return whether Weave should be active for this process."""
    if os.getenv("WEAVE_DISABLED", "").lower() in _DISABLED_VALUES:
        return False
    return bool(os.getenv("WANDB_API_KEY"))


def setup_weave() -> bool:
    """Initialize Weave with PII redaction when WANDB_API_KEY is configured.

    Returns True when initialization happened in this process. The function is a
    no-op when ``WANDB_API_KEY`` is absent or ``WEAVE_DISABLED`` is true, so local
    development and tests do not need a W&B credential. Init failures (bad key,
    network) also become a no-op so the app keeps running without Weave.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return True
    if not weave_enabled():
        return False

    import logging

    import weave

    project = os.getenv("WEAVE_PROJECT", "insummery-ai")
    # implicitly_patch_integrations=False keeps Weave from auto-tracing the
    # Google ADK / GenAI SDKs. The workflow receives the *raw* email as
    # `new_message` and only masks it inside pii_mask_node, so automatic ADK
    # input capture would export unmasked PII. With autopatching off, the only
    # data Weave receives is what the explicit helpers below record, all of
    # which is masked or summarized metadata.
    try:
        weave.init(
            project,
            settings={
                "redact_pii": True,
                "implicitly_patch_integrations": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 - observability must not break the app
        logging.getLogger(__name__).warning(
            "Weave init failed (%s); continuing without Weave tracing.", exc
        )
        return False
    _INITIALIZED = True
    return True


def weave_op(name: Optional[str] = None) -> Callable[[F], F]:
    """Decorate a function as a Weave op only when Weave is active."""

    def decorator(func: F) -> F:
        if not _INITIALIZED:
            return func
        import weave

        return weave.op(name=name)(func)  # type: ignore[return-value]

    return decorator


def _response_summary(response: Any) -> Dict[str, Any]:
    """Build a PII-safe summary of an agent response for tracing."""
    summary: Dict[str, Any] = {"response_type": type(response).__name__}

    if isinstance(response, str):
        text = response.strip()
        summary["response_chars"] = len(text)
        # Triager returns a short category label — safe to record.
        if len(text) <= 32 and "\n" not in text:
            summary["predicted_label"] = text.lower()
        return summary

    # Pydantic models (InterpretationResult / DisruptionDetail) or dicts.
    data = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(data, dict):
        return summary

    if "confidence_score" in data:
        summary["confidence_score"] = data.get("confidence_score")
        activities = data.get("activities") or []
        summary["activity_count"] = len(activities) if isinstance(activities, list) else 0
        summary["has_evaluation_trace"] = bool(data.get("evaluation_trace"))

    if "disruption_type" in data:
        summary["disruption_type"] = data.get("disruption_type")
        summary["has_child_name"] = bool(data.get("child_name"))
        summary["has_activity_title"] = bool(data.get("activity_title"))
        summary["has_date"] = bool(data.get("date"))

    return summary


def _presidio_guardrail_enabled() -> bool:
    return os.getenv("WEAVE_PRESIDIO_GUARDRAIL", "").lower() in _PRESIDIO_ENABLED_VALUES


def _collect_text_fields(data: Dict[str, Any], category: Optional[str]) -> str:
    """Concatenate interpreter text fields for leak scanning (still masked)."""
    chunks: List[str] = []
    if category == "registration":
        for act in data.get("activities") or []:
            act_dict = act.model_dump() if hasattr(act, "model_dump") else act
            if not isinstance(act_dict, dict):
                continue
            for field in ("child_name", "activity_title", "location", "notes"):
                val = act_dict.get(field)
                if isinstance(val, str) and val:
                    chunks.append(val)
    elif category == "disruption":
        for field in ("child_name", "activity_title", "description"):
            val = data.get(field)
            if isinstance(val, str) and val:
                chunks.append(val)
    return "\n".join(chunks)


def _presidio_leak_violations(text: str) -> List[str]:
    """Run Presidio on masked field text; return violation codes (no spans)."""
    if not text.strip():
        return []
    try:
        from presidio_analyzer import AnalyzerEngine
    except ImportError:
        return []

    try:
        analyzer = AnalyzerEngine()
        results = analyzer.analyze(
            text=text,
            language="en",
            entities=list(_PRESIDIO_ENTITIES),
        )
    except SystemExit:
        # Presidio may attempt to download a spaCy model via sys.exit on failure.
        return []
    except Exception:  # noqa: BLE001 - guardrails must never break extraction
        return []

    codes = []
    for entity in {r.entity_type for r in results}:
        codes.append(f"presidio_{entity.lower()}")
    return codes


def check_extraction_guardrails(category: Optional[str], response: Any) -> Dict[str, Any]:
    """Validate interpreter output before it reaches the schedule matrix.

    Returns a dict with ``passed``, ``violations`` (list of codes), and
    ``details``. Does not include raw field values — only structural flags.

    When ``WEAVE_PRESIDIO_GUARDRAIL=true``, also runs Presidio over masked
    text fields for email/phone/SSN/credit-card entities.
    """
    violations: List[str] = []
    details: Dict[str, Any] = {"category": category}

    data = response.model_dump() if hasattr(response, "model_dump") else response
    if not isinstance(data, dict):
        violations.append("unstructured_output")
        return {"passed": False, "violations": violations, "details": details}

    if category == "registration":
        score = data.get("confidence_score")
        if not isinstance(score, int) or not (0 <= score <= 100):
            violations.append("confidence_out_of_range")
        activities = data.get("activities")
        if not isinstance(activities, list) or len(activities) == 0:
            violations.append("empty_activities")
        else:
            for i, act in enumerate(activities):
                act_dict = act.model_dump() if hasattr(act, "model_dump") else act
                if not isinstance(act_dict, dict):
                    violations.append(f"activity_{i}_invalid")
                    continue
                for field in ("child_name", "activity_title", "start_date", "end_date"):
                    if not act_dict.get(field):
                        violations.append(f"activity_{i}_missing_{field}")
                for field in ("child_name", "activity_title", "location", "notes"):
                    val = act_dict.get(field) or ""
                    if isinstance(val, str) and _LEAK_EMAIL.search(val):
                        violations.append("possible_email_leak")
                    if isinstance(val, str) and _LEAK_PHONE.search(val):
                        violations.append("possible_phone_leak")

    elif category == "disruption":
        dtype = (data.get("disruption_type") or "").upper()
        details["disruption_type"] = dtype or None
        if dtype not in ALLOWED_DISRUPTION_TYPES:
            violations.append("invalid_disruption_type")
        if not data.get("date"):
            violations.append("missing_disruption_date")
        if not data.get("description"):
            violations.append("missing_disruption_description")
        for field in ("child_name", "activity_title", "description"):
            val = data.get(field) or ""
            if isinstance(val, str) and _LEAK_EMAIL.search(val):
                violations.append("possible_email_leak")
            if isinstance(val, str) and _LEAK_PHONE.search(val):
                violations.append("possible_phone_leak")

    if _presidio_guardrail_enabled() and isinstance(data, dict):
        details["presidio"] = True
        violations.extend(_presidio_leak_violations(_collect_text_fields(data, category)))

    # Dedupe while preserving order
    seen = set()
    unique = []
    for v in violations:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    return {
        "passed": len(unique) == 0,
        "violations": unique,
        "details": details,
    }


async def trace_agent_call(agent_name: str, masked_text: str, response: Any) -> Dict[str, Any]:
    """Record a masked agent call summary without raw PII-bearing input."""

    async def _record() -> Dict[str, Any]:
        payload = {
            "agent_name": agent_name,
            "masked_input_chars": len(masked_text or ""),
        }
        payload.update(_response_summary(response))
        return payload

    if not _INITIALIZED:
        return await _record()
    return await weave_op("insummery.workflow.agent_call")(_record)()


async def trace_pii_mask(masked_text: str, mapping_count: int) -> Dict[str, Any]:
    """Record PII masking metadata after placeholders have been applied."""

    async def _record() -> Dict[str, Any]:
        return {
            "masked_input_chars": len(masked_text or ""),
            "mapping_count": mapping_count,
        }

    if not _INITIALIZED:
        return await _record()
    return await weave_op("insummery.workflow.pii_mask")(_record)()


async def trace_confidence_gate(
    category: Optional[str], score: float, route: str
) -> Dict[str, Any]:
    """Record the confidence-gate routing decision."""

    async def _record() -> Dict[str, Any]:
        return {
            "category": category,
            "confidence_score": score,
            "route": route,
        }

    if not _INITIALIZED:
        return await _record()
    return await weave_op("insummery.workflow.confidence_gate")(_record)()


async def trace_guardrail(result: Dict[str, Any]) -> Dict[str, Any]:
    """Record a guardrail check result (structural flags only)."""

    async def _record() -> Dict[str, Any]:
        return {
            "passed": bool(result.get("passed")),
            "violations": list(result.get("violations") or []),
            "category": (result.get("details") or {}).get("category"),
            "disruption_type": (result.get("details") or {}).get("disruption_type"),
        }

    if not _INITIALIZED:
        return await _record()
    return await weave_op("insummery.workflow.guardrail")(_record)()


async def trace_workflow_run(
    *,
    status: str,
    category: Optional[str] = None,
    confidence_score: Optional[float] = None,
    hitl: bool = False,
    warning_count: int = 0,
    latency_ms: Optional[float] = None,
    model_id: Optional[str] = None,
    error_code: Optional[str] = None,
    guardrail_passed: Optional[bool] = None,
    disruption_matched: Optional[bool] = None,
    activity_count: Optional[int] = None,
    gap_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Record an end-of-run workflow summary for ops dashboards and monitors."""

    async def _record() -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "status": status,
            "category": category,
            "hitl": hitl,
            "warning_count": warning_count,
            "healthy": status == "COMPLETED" and warning_count == 0 and not error_code,
        }
        if confidence_score is not None:
            payload["confidence_score"] = confidence_score
        if latency_ms is not None:
            payload["latency_ms"] = round(latency_ms, 1)
        if model_id:
            payload["model_id"] = model_id
        if error_code:
            payload["error_code"] = error_code
        if guardrail_passed is not None:
            payload["guardrail_passed"] = guardrail_passed
        if disruption_matched is not None:
            payload["disruption_matched"] = disruption_matched
        if activity_count is not None:
            payload["activity_count"] = activity_count
        if gap_count is not None:
            payload["gap_count"] = gap_count
        return payload

    if not _INITIALIZED:
        return await _record()
    return await weave_op("insummery.workflow.run")(_record)()


async def trace_hitl_feedback(
    *,
    workflow_id: str,
    clarification_chars: int,
    status: str,
    confidence_after: Optional[float] = None,
    confidence_before: Optional[float] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Record that a parent clarified a low-confidence extraction (no raw text).

    When Weave is active, also attaches structured Call feedback so the
    clarification shows up on the Trace feedback panel.
    """
    import inspect

    async def _record() -> Dict[str, Any]:
        return {
            "workflow_id": workflow_id,
            "clarification_chars": clarification_chars,
            "status": status,
            "confidence_before": confidence_before,
            "confidence_after": confidence_after,
            "category": category,
            "feedback_type": "hitl_clarification",
        }

    payload = await _record()
    if not _INITIALIZED:
        return payload

    import weave

    @weave.op(name="insummery.workflow.hitl_feedback")
    async def _op() -> Dict[str, Any]:
        return payload

    try:
        maybe = _op.call()
        result, call = await maybe if inspect.isawaitable(maybe) else maybe
        try:
            call.feedback.add(
                "hitl_clarification",
                {
                    "status": status,
                    "clarification_chars": clarification_chars,
                    "confidence_before": confidence_before,
                    "confidence_after": confidence_after,
                    "category": category,
                },
            )
            if status == "COMPLETED":
                call.feedback.add_reaction("👍")
            elif status == "ERROR":
                call.feedback.add_reaction("👎")
        except Exception:  # noqa: BLE001 - feedback is best-effort
            pass
        return result if isinstance(result, dict) else payload
    except Exception:  # noqa: BLE001 - fall back to plain op invoke
        return await weave_op("insummery.workflow.hitl_feedback")(_record)()


def trace_eval_case(
    suite: str,
    case_id: str,
    score: float,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record a summarized evaluation result without raw test email content."""

    def _record() -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "suite": suite,
            "case_id": case_id,
            "score": score,
        }
        if extra:
            result.update(extra)
        return result

    if not _INITIALIZED:
        return _record()
    return weave_op("insummery.eval.case")(_record)()
