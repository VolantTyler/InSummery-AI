"""Shared LlmAgent definitions.

The production workflow (app/nodes.py) and the evaluation harness
(app/evaluation/) both build agents through these factories so that the eval
loop always scores the exact instructions and schemas used in production.
"""
from datetime import datetime
from typing import Optional

from google.adk.agents.llm_agent import LlmAgent

from app.model_client import get_model_client
from app.schemas import InterpretationResult, DisruptionDetail


def _today_context() -> str:
    """Ground the LLM in the current date so relative or year-less dates
    (e.g. 'next week', 'August 5th') resolve to the correct upcoming dates
    instead of defaulting to a past year from the model's training data."""
    now = datetime.now()
    return (
        f"Today's date is {now.strftime('%A')}, {now.strftime('%Y-%m-%d')}. "
        "When a date in the message has no year, resolve it to the nearest "
        "occurrence on or after today; never output a date in a past year."
    )


TRIAGER_INSTRUCTION = (
    "You are an email triager for a family schedule concierge. "
    "Classify the incoming email/message into one of the following categories:\n"
    "1. 'registration': For new camp, class, school, or activity registrations, "
    "registration confirmations, or requests to schedule an activity or care for "
    "a child - even vague or incomplete ones (e.g. 'Camp next week for [CHILD_A]').\n"
    "2. 'disruption': For cancellations, nanny sick leave, schedule changes, or delays.\n"
    "3. 'general': For other messages or general inquiries (e.g. newsletters, "
    "invoices, social messages).\n"
    "Respond with exactly one word: 'registration', 'disruption', or 'general'."
)

INTERPRETER_REGISTRATION_INSTRUCTION = (
    "Extract all camp, class, school, or activity registrations from the email. "
    "For each activity, extract the child's name, activity title, start/end dates (YYYY-MM-DD), "
    "daily start/end times (HH:MM), location, and notes. "
    "Assign a confidence score (0-100) on how confident you are in this extraction, "
    "along with a brief evaluation trace explaining the score. "
    "If essential details are missing or ambiguous (e.g. no specific dates, no daily "
    "times, or an unclear activity), you MUST assign a confidence score below 80 and "
    "state exactly which details are missing in the evaluation trace."
)

INTERPRETER_DISRUPTION_INSTRUCTION = (
    "Extract the disruption details from the message. "
    "Extract the affected child's name, the affected activity title (if one is mentioned), "
    "the date of the disruption (YYYY-MM-DD), start/end times (HH:MM), "
    "description, and the disruption type (CANCELLATION, DELAY, SICK_LEAVE). "
    "If the message does not identify a specific child, set child_name to an empty "
    "string; never invent a name or use 'N/A'. If the family's current schedule is "
    "provided below, use it to resolve which child, activity, and exact dates are affected."
)

INTERPRETER_HITL_INSTRUCTION = (
    "Extract all camp, class, school, or activity registrations from the email using the parent's clarification. "
    "For each activity, extract the child's name, activity title, start/end dates (YYYY-MM-DD), "
    "daily start/end times (HH:MM), location, and notes."
)


def build_triager_agent(model: Optional[object] = None) -> LlmAgent:
    return LlmAgent(
        name="triager_agent",
        model=model or get_model_client(),
        instruction=TRIAGER_INSTRUCTION,
    )


def build_interpreter_registration_agent(model: Optional[object] = None) -> LlmAgent:
    return LlmAgent(
        name="interpreter_agent_registration",
        model=model or get_model_client(),
        instruction=f"{INTERPRETER_REGISTRATION_INSTRUCTION}\n\n{_today_context()}",
        output_schema=InterpretationResult,
    )


def build_interpreter_disruption_agent(
    model: Optional[object] = None, schedule_context: str = ""
) -> LlmAgent:
    instruction = f"{INTERPRETER_DISRUPTION_INSTRUCTION}\n\n{_today_context()}"
    if schedule_context:
        instruction += f"\n\nFamily's current schedule (PII-masked):\n{schedule_context}"
    return LlmAgent(
        name="interpreter_agent_disruption",
        model=model or get_model_client(),
        instruction=instruction,
        output_schema=DisruptionDetail,
    )


def build_interpreter_hitl_agent(model: Optional[object] = None) -> LlmAgent:
    return LlmAgent(
        name="interpreter_agent_hitl",
        model=model or get_model_client(),
        instruction=f"{INTERPRETER_HITL_INSTRUCTION}\n\n{_today_context()}",
        output_schema=InterpretationResult,
    )
