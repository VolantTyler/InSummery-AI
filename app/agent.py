from google.adk import Workflow
from app.nodes import (
    pii_mask_node,
    triager_node,
    interpreter_registration_node,
    interpreter_disruption_node,
    confidence_gate_node,
    hitl_node,
    matrix_analyzer_node
)

# Define the root Workflow for InSummery
insummery_workflow = Workflow(
    name="insummery_workflow",
    description="Concierge agent to ingest, mask, interpret schedule emails, and run gap analysis.",
    edges=[
        ("START", pii_mask_node),
        (pii_mask_node, triager_node),
        (triager_node, {
            "registration": interpreter_registration_node,
            "disruption": interpreter_disruption_node,
            "general": matrix_analyzer_node
        }),
        (interpreter_registration_node, confidence_gate_node),
        (interpreter_disruption_node, confidence_gate_node),
        (confidence_gate_node, {
            "CONFIDENCE_HIGH": matrix_analyzer_node,
            "CONFIDENCE_LOW": hitl_node
        }),
        (hitl_node, matrix_analyzer_node)
    ]
)
