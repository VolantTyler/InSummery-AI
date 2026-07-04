"""End-to-end workflow evaluation support.

Unlike the per-agent suites in ``runner.py`` (which build each agent in
isolation), this module runs the full production ADK workflow
(``app.agent.insummery_workflow``) — PII mask → triager → interpreter →
confidence gate — so the graph wiring itself is part of what gets evaluated.

The workflow invocation is injected (``workflow_invoker``) so unit tests can
exercise the suite offline against canned outcomes. The default invoker makes
live model calls and runs each case from an isolated temp working directory,
so eval runs never touch the real ``config/profile.json`` or
``data/matrix.json``.
"""
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Dict, Optional

# A workflow invoker takes (raw_email_text, profile) and returns an outcome:
#   status:          "COMPLETED" | "INTERRUPTED" | "ERROR"
#   category:        triager routing decision (when available)
#   confidence_score: interpreter self-reported confidence (when available)
#   activities:      extracted activity dicts, already unmasked
#   error / message: diagnostics for ERROR / INTERRUPTED outcomes
WorkflowInvoker = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]


@contextmanager
def isolated_workdir(profile: Dict[str, Any]):
    """Run the workflow from a scratch temp directory so each case starts
    from a clean (empty) schedule matrix and never touches real local data."""
    tmp_dir = tempfile.mkdtemp(prefix="insummery_eval_")
    old_cwd = os.getcwd()
    try:
        config_dir = os.path.join(tmp_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(os.path.join(tmp_dir, "data"), exist_ok=True)
        with open(os.path.join(config_dir, "profile.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f)
        os.chdir(tmp_dir)
        yield tmp_dir
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extraction_to_dict(extraction: Any) -> Dict[str, Any]:
    if extraction is None:
        return {}
    if hasattr(extraction, "model_dump"):
        return extraction.model_dump()
    if isinstance(extraction, dict):
        return extraction
    return {}


async def adk_workflow_invoker(email_text: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Run one raw email through the live ADK workflow and return the outcome."""
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService

    from google.genai.types import Content, Part

    from app.agent import insummery_workflow
    from app.pii_masker import PIIMasker

    with isolated_workdir(profile):
        user_id = "eval_user"
        session_id = f"eval_wf_{uuid.uuid4().hex[:12]}"
        session_service = InMemorySessionService()
        runner = Runner(
            agent=insummery_workflow,
            app_name="insummery_eval",
            session_service=session_service,
            auto_create_session=True,
        )
        msg = Content(parts=[Part(text=email_text)])

        try:
            events = list(runner.run(
                user_id=user_id,
                session_id=session_id,
                new_message=msg,
                state_delta={"mode": "local"},
            ))
        except Exception as exc:  # noqa: BLE001 - surface any failure as an outcome row
            return {"status": "ERROR", "error": str(exc)}

        for event in events:
            if getattr(event, "error_code", None):
                return {
                    "status": "ERROR",
                    "error": f"[{event.error_code}] {event.error_message}",
                }

        pending_interrupt = None
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and fc.name == "adk_request_input":
                        pending_interrupt = fc
                        break

        session = await session_service.get_session(
            user_id=user_id, session_id=session_id, app_name="insummery_eval"
        )

        if pending_interrupt:
            return {
                "status": "INTERRUPTED",
                "category": session.state.get("category"),
                "message": pending_interrupt.args.get("message"),
            }

        extraction = _extraction_to_dict(session.state.get("extraction_result"))

        # `extraction_result` is captured before matrix_analyzer_node unmasks
        # it (unmasking normally happens further down the real pipeline), so
        # PII placeholders like "[CHILD_A]" are still present here. Unmask
        # using the same mappings the pipeline itself produced, so scoring
        # compares against the same values a real run would persist.
        masker = PIIMasker(profile)
        masker.mask_to_original = session.state.get("pii_mappings", {})

        activities = []
        for act in extraction.get("activities") or []:
            act_dict = dict(act)
            for field in ("child_name", "activity_title", "location", "notes"):
                if field in act_dict:
                    act_dict[field] = masker.unmask(act_dict.get(field) or "")
            activities.append(act_dict)

        return {
            "status": "COMPLETED",
            "category": session.state.get("category"),
            "confidence_score": extraction.get("confidence_score"),
            "activities": activities,
        }
