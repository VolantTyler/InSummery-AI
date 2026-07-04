"""Shared LlmAgent definitions.

The production workflow (app/nodes.py) and the evaluation harness
(app/evaluation/) both build agents through these factories so that the eval
loop always scores the exact instructions and schemas used in production.
"""
from typing import Optional

from google.adk.agents.llm_agent import LlmAgent

from app.model_client import get_model_client
from app.schemas import InterpretationResult, DisruptionDetail

TRIAGER_INSTRUCTION = (
    "You are an email triager for a family schedule concierge. "
    "Classify the incoming email/message into one of the following categories:\n"
    "1. 'registration': For new camp, class, school, or activity registrations.\n"
    "2. 'disruption': For cancellations, nanny sick leave, schedule changes, or delays.\n"
    "3. 'general': For other messages or general inquiries.\n"
    "Respond with exactly one word: 'registration', 'disruption', or 'general'."
)

INTERPRETER_REGISTRATION_INSTRUCTION = (
    "Extract all camp, class, school, or activity registrations from the email. "
    "For each activity, extract the child's name, activity title, start/end dates (YYYY-MM-DD), "
    "daily start/end times (HH:MM), location, and notes. "
    "Assign a confidence score (0-100) on how confident you are in this extraction, "
    "along with a brief evaluation trace explaining the score."
)

INTERPRETER_DISRUPTION_INSTRUCTION = (
    "Extract the disruption details from the message. "
    "Extract the child's name, the date of the disruption (YYYY-MM-DD), start/end times (HH:MM), "
    "description, and the disruption type (CANCELLATION, DELAY, SICK_LEAVE)."
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
        instruction=INTERPRETER_REGISTRATION_INSTRUCTION,
        output_schema=InterpretationResult,
    )


def build_interpreter_disruption_agent(model: Optional[object] = None) -> LlmAgent:
    return LlmAgent(
        name="interpreter_agent_disruption",
        model=model or get_model_client(),
        instruction=INTERPRETER_DISRUPTION_INSTRUCTION,
        output_schema=DisruptionDetail,
    )


def build_interpreter_hitl_agent(model: Optional[object] = None) -> LlmAgent:
    return LlmAgent(
        name="interpreter_agent_hitl",
        model=model or get_model_client(),
        instruction=INTERPRETER_HITL_INSTRUCTION,
        output_schema=InterpretationResult,
    )
