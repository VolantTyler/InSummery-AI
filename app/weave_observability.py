"""Optional Weights & Biases Weave observability helpers.

The app's primary privacy boundary is still ``PIIMasker``. This module only
initializes Weave when explicitly configured and exposes helpers that record
masked/summarized metadata rather than raw family emails or Firebase tokens.
"""
import os
from typing import Any, Callable, Dict, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_INITIALIZED = False
_DISABLED_VALUES = {"1", "true", "yes", "on"}

def weave_enabled() -> bool:
    """Return whether Weave should be active for this process."""
    if os.getenv("WEAVE_DISABLED", "").lower() in _DISABLED_VALUES:
        return False
    return bool(os.getenv("WANDB_API_KEY"))


def setup_weave() -> bool:
    """Initialize Weave with PII redaction when WANDB_API_KEY is configured.

    Returns True when initialization happened in this process. The function is a
    no-op when ``WANDB_API_KEY`` is absent or ``WEAVE_DISABLED`` is true, so local
    development and tests do not need a W&B credential.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return True
    if not weave_enabled():
        return False

    import weave

    project = os.getenv("WEAVE_PROJECT", "insummery-ai")
    weave.init(project, settings={"redact_pii": True})
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


async def trace_agent_call(agent_name: str, masked_text: str, response: Any) -> Dict[str, Any]:
    """Record a masked agent call summary without raw PII-bearing input."""
    async def _record() -> Dict[str, Any]:
        return {
            "agent_name": agent_name,
            "masked_input_chars": len(masked_text or ""),
            "response_type": type(response).__name__,
        }

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


async def trace_confidence_gate(category: Optional[str], score: float, route: str) -> Dict[str, Any]:
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
