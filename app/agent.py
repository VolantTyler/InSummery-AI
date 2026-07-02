<<<<<<< HEAD
# Summify agent workflow skeleton
from google.adk.workflow import Workflow

# Define a simple workflow placeholder
workflow = Workflow(name="summify_workflow")
=======
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

# Define the root Workflow for Summify
summify_workflow = Workflow(
    name="summify_workflow",
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
>>>>>>> 06422c5fe6db78fdf6f89312d28fd1b410973ed1
