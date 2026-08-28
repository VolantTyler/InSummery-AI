"""LLM-as-judge tier — reported, never gating.

The deterministic scorers in ``scoring.py`` can check whether a date is right.
They cannot check whether the model's *self-report* is honest, and that is
where this system's trustworthiness actually lives:

- ``INTERPRETER_REGISTRATION_INSTRUCTION`` orders the model to drop below
  confidence 80 and "state exactly which details are missing" when something is
  ambiguous. Nothing verifies it ever does.
- ``evaluation_trace`` is free text. Boilerplate ("extraction successful") and
  a real account of what was uncertain score identically under string matching.
- ``notes`` is where the parent-actionable content lands (allergy policy, what
  to bring, the drop-off window). Fuzzy similarity rewards *overlap*, not
  whether the useful part survived.

Hard contract, so the judge can never become a source of false regressions:

1. Judge metrics are returned under their own ``judge`` block and are never
   written into ``report["metrics"]``. ``save_baseline`` and
   ``compare_to_baseline`` read only ``metrics``, so the gate cannot see these.
2. The judge model id and judge prompt hash are stamped on every result, so
   judge drift is itself attributable.
3. Any judge failure degrades to ``None`` rather than to a zero — an
   unavailable judge must never look like a quality drop.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional

# The model is pinned deliberately -- an unpinned judge silently changes the
# measuring stick -- but the *provider prefix* follows whatever the app is
# configured for. Hardcoding one prefix means the judge needs a different
# credential than the rest of the run, which is how it failed all 9 cases the
# first time: pinned to vertex_ai/ with only an API key configured.
_PINNED_JUDGE_MODEL = "gemini-2.5-flash"
DEFAULT_JUDGE_MODEL = f"vertex_ai/{_PINNED_JUDGE_MODEL}"

# Caveat worth knowing when reading judge scores: by default this is the same
# model family that produced the output being graded, so the scores carry
# self-preference bias -- measurably so. On the one hard case where the
# extraction attached a camp to the wrong child at confidence 100, the judge
# still scored confidence_justification a perfect 1.0. Point JUDGE_MODEL at a
# different provider to remove the bias. This is one reason the tier is
# report-only and never gates.

JUDGE_INSTRUCTION = (
    "You are grading the SELF-REPORT of an information-extraction system that "
    "reads family scheduling emails. You are NOT re-extracting the data and you "
    "are NOT checking whether the extracted values are correct — a separate "
    "deterministic scorer already does that.\n\n"
    "Grade only these three dimensions, each an integer 0-10:\n\n"
    "1. trace_honesty — Does `evaluation_trace` describe what was actually "
    "uncertain or missing in this specific email? Generic filler such as "
    "'extraction successful' or 'all fields found' scores 0-2 no matter how "
    "correct the extraction was. Naming the specific ambiguity scores 8-10.\n\n"
    "2. confidence_justification — Is `confidence_score` defensible given the "
    "trace? A high score paired with an admission of missing fields is "
    "contradictory and scores low. A low score with a concrete stated reason "
    "scores high.\n\n"
    "3. notes_completeness — Do the extracted `notes` retain the details a "
    "parent must act on (what to bring, allergy or food policy, drop-off and "
    "pick-up windows, fees due, required gear)? Losing them scores low; "
    "reproducing irrelevant boilerplate instead does not earn points.\n\n"
    "Respond with ONLY a JSON object:\n"
    '{"trace_honesty": <0-10>, "confidence_justification": <0-10>, '
    '"notes_completeness": <0-10>, "rationale": "<one sentence>"}'
)

JUDGE_DIMENSIONS = ("trace_honesty", "confidence_justification", "notes_completeness")


def judge_prompt_hash() -> str:
    return hashlib.sha256(JUDGE_INSTRUCTION.encode("utf-8")).hexdigest()[:12]


def judge_model_spec() -> str:
    """Resolve the judge model, following the app's provider by default.

    An explicit ``JUDGE_MODEL`` always wins. Otherwise the judge uses the same
    provider prefix the app resolved (``vertex_ai/`` or ``gemini/``) with the
    pinned model name, so the judge authenticates the same way the rest of the
    run does.
    """
    explicit = os.getenv("JUDGE_MODEL")
    if explicit:
        return explicit
    try:
        from app.model_client import resolve_model_spec

        app_spec = resolve_model_spec()
    except Exception:  # noqa: BLE001 - fall back to the pinned default
        return DEFAULT_JUDGE_MODEL

    for prefix in ("vertex_ai/", "gemini/"):
        if app_spec.startswith(prefix):
            return f"{prefix}{_PINNED_JUDGE_MODEL}"
    # A local Ollama app model should not silently drag the judge local too;
    # keep it on the pinned cloud model so judge scores stay comparable.
    return DEFAULT_JUDGE_MODEL


def build_judge_agent(model: Optional[object] = None):
    from google.adk.agents.llm_agent import LlmAgent
    from google.adk.models.lite_llm import LiteLlm

    return LlmAgent(
        name="eval_judge",
        model=model or LiteLlm(model=judge_model_spec()),
        instruction=JUDGE_INSTRUCTION,
    )


def build_judge_input(case: Dict[str, Any], masked_email: str) -> str:
    """Assemble one grading payload.

    The email passed here is the PII-masked text, never the raw one: the judge
    is another model call and gets no more of the family's data than the
    extractor did.
    """
    return json.dumps(
        {
            "masked_email": masked_email,
            "reported_confidence": case.get("confidence_score"),
            "evaluation_trace": case.get("evaluation_trace"),
            "extracted_notes": case.get("extracted_notes") or [],
        },
        indent=2,
    )


def _parse_judge_response(text: str) -> Optional[Dict[str, Any]]:
    from app.evaluation.runner import extract_json

    try:
        data = extract_json(text)
    except Exception:
        return None
    out: Dict[str, Any] = {"rationale": str(data.get("rationale") or "")[:500]}
    for dim in JUDGE_DIMENSIONS:
        value = data.get(dim)
        if not isinstance(value, (int, float)) or not (0 <= value <= 10):
            return None
        out[dim] = float(value) / 10.0
    return out


async def judge_cases(
    cases: List[Dict[str, Any]],
    invoker: Callable[[Any, str], Awaitable[str]],
    agent: Optional[Any] = None,
) -> Dict[str, Any]:
    """Grade a list of prepared judge inputs.

    Each entry needs ``id``, ``masked_email`` and the extractor's self-report
    fields. A case the judge cannot grade is recorded with ``scores: None`` and
    excluded from the averages, so an unavailable judge shrinks the sample
    rather than depressing the score.
    """
    agent = agent or build_judge_agent()
    rows: List[Dict[str, Any]] = []
    for case in cases:
        try:
            raw = await invoker(agent, build_judge_input(case, case.get("masked_email", "")))
            scores = _parse_judge_response(raw)
        except Exception as exc:  # noqa: BLE001 - the judge must never break a run
            scores = None
            rows.append({"id": case.get("id"), "scores": None, "error": str(exc)[:200]})
            continue
        rows.append({"id": case.get("id"), "scores": scores})

    metrics: Dict[str, Optional[float]] = {}
    for dim in JUDGE_DIMENSIONS:
        values = [r["scores"][dim] for r in rows if r.get("scores")]
        metrics[f"judge_{dim}"] = (
            round(sum(values) / len(values), 4) if values else None
        )

    return {
        "judge_model": judge_model_spec(),
        "judge_prompt_hash": judge_prompt_hash(),
        "graded": sum(1 for r in rows if r.get("scores")),
        "attempted": len(rows),
        "metrics": metrics,
        "cases": rows,
        "gating": False,
    }
