import os
from datetime import datetime, timedelta
from typing import Any, Dict, List
from google.adk import Context
from google.adk.workflow import node
from google.adk.events import RequestInput

from app.agent_factories import (
    build_triager_agent,
    build_interpreter_registration_agent,
    build_interpreter_disruption_agent,
    build_interpreter_hitl_agent,
)
from app.pii_masker import PIIMasker
from app.storage import LocalStorageProvider, FirestoreStorageProvider
from app.schemas import InterpretationResult, DisruptionDetail
from app.matrix_logic import calculate_gaps, merge_activities, apply_disruption, parse_date

def _get_storage_provider(ctx: Context) -> Any:
    mode = ctx.state.get("mode", "local")
    if mode == "firebase":
        return FirestoreStorageProvider()
    return LocalStorageProvider()

async def pii_mask_node(ctx: Context, node_input: str) -> str:
    """Mask PII in the raw input text using the user's family profile."""
    storage = _get_storage_provider(ctx)
    user_id = ctx.user_id or "default_user"
    
    # Load profile
    profile = storage.get_profile(user_id)
    if not profile:
        # Fallback if no profile is set up yet
        profile = {"children": [], "parents": [], "address": ""}
        
    masker = PIIMasker(profile)
    masked_text = masker.mask(node_input)
    
    # Save masker mappings to session state for unmasking later
    ctx.state["pii_mappings"] = masker.mask_to_original
    ctx.state["original_text"] = node_input
    
    return masked_text

@node(rerun_on_resume=True)
async def triager_node(ctx: Context, node_input: str) -> str:
    """Classify the input text as registration, disruption, or general."""
    agent = build_triager_agent()
    
    res = await ctx.run_node(agent, node_input)
    category = res.strip().lower()
    if category not in ["registration", "disruption", "general"]:
        category = "general"
        
    ctx.state["category"] = category
    ctx.route = category
    return category

@node(rerun_on_resume=True)
async def interpreter_registration_node(ctx: Context, node_input: str) -> Any:
    """Extract structured registration data from the masked text."""
    agent = build_interpreter_registration_agent()
    res = await ctx.run_node(agent, node_input)
    return res

@node(rerun_on_resume=True)
async def interpreter_disruption_node(ctx: Context, node_input: str) -> Any:
    """Extract structured disruption data from the masked text."""
    agent = build_interpreter_disruption_agent()
    res = await ctx.run_node(agent, node_input)
    return res

async def confidence_gate_node(ctx: Context, node_input: Any) -> str:
    """Check the extraction confidence score and decide whether to route to HITL."""
    category = ctx.state.get("category")
    if category != "registration":
        # Disruptions and general inquiries bypass the confidence gate
        ctx.state["extraction_result"] = node_input
        ctx.route = "CONFIDENCE_HIGH"
        return "CONFIDENCE_HIGH"
        
    score = 100
    if isinstance(node_input, InterpretationResult):
        score = node_input.confidence_score
    elif isinstance(node_input, dict):
        score = node_input.get("confidence_score", 100)
        
    ctx.state["extraction_result"] = node_input
    
    if score >= 80:
        ctx.route = "CONFIDENCE_HIGH"
        return "CONFIDENCE_HIGH"
    else:
        ctx.state["hitl_question"] = (
            f"The extraction confidence was low ({score}%). "
            f"Reason: {getattr(node_input, 'evaluation_trace', 'Low extraction confidence')}. "
            f"Please clarify the schedule details."
        )
        ctx.route = "CONFIDENCE_LOW"
        return "CONFIDENCE_LOW"

@node(rerun_on_resume=True)
async def hitl_node(ctx: Context, node_input: Any) -> Any:
    """Pause the workflow and wait for human clarification if confidence is low."""
    interrupt_id = "clarification_prompt"
    
    if ctx.resume_inputs and interrupt_id in ctx.resume_inputs:
        val = ctx.resume_inputs[interrupt_id]
        # Since we are in HITL, the user's response contains the corrected schedule details.
        # We run the interpreter agent again, this time forcing high confidence or combining the inputs.
        original_text = ctx.state.get("original_text", "")
        combined_prompt = f"Original email:\n{original_text}\n\nParent clarification: {val}"
        
        # Re-run masking on combined prompt (reusing the same PII mappings)
        storage = _get_storage_provider(ctx)
        profile = storage.get_profile(ctx.user_id or "default_user") or {}
        masker = PIIMasker(profile)
        masker.mask_to_original = ctx.state.get("pii_mappings", {})
        masked_combined = masker.mask(combined_prompt)
        
        agent = build_interpreter_hitl_agent()
        res = await ctx.run_node(agent, masked_combined)
        yield res
        return
        
    yield RequestInput(
        interrupt_id=interrupt_id,
        message=ctx.state.get("hitl_question", "Please clarify the schedule details.")
    )

async def matrix_analyzer_node(ctx: Context, node_input: Any) -> Dict[str, Any]:
    """Merge activities, handle disruptions, run gap analysis, and save the matrix."""
    storage = _get_storage_provider(ctx)
    user_id = ctx.user_id or "default_user"
    category = ctx.state.get("category")
    
    # 1. Unmask the extracted data using the stored PII mappings
    pii_mappings = ctx.state.get("pii_mappings", {})
    profile = storage.get_profile(user_id) or {"children": [], "parents": [], "address": ""}
    
    masker = PIIMasker(profile)
    masker.mask_to_original = pii_mappings
    
    # Load current matrix
    current_matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    
    # 2. Merge or apply disruptions
    extraction_result = ctx.state.get("extraction_result")
    if extraction_result is None or isinstance(extraction_result, str):
        extraction_result = node_input
        
    if category == "registration":
        # Unmask activities
        raw_activities = []
        activities_list = []
        if isinstance(extraction_result, InterpretationResult):
            activities_list = extraction_result.activities
        elif isinstance(extraction_result, dict):
            activities_list = extraction_result.get("activities", [])
            
        for act in activities_list:
            act_dict = act.model_dump() if hasattr(act, "model_dump") else dict(act)
            # Unmask child name and other fields
            act_dict["child_name"] = masker.unmask(act_dict["child_name"])
            act_dict["activity_title"] = masker.unmask(act_dict["activity_title"])
            act_dict["location"] = masker.unmask(act_dict.get("location") or "")
            act_dict["notes"] = masker.unmask(act_dict.get("notes") or "")
            raw_activities.append(act_dict)
            
        updated_matrix = merge_activities(current_matrix, raw_activities)
    elif category == "disruption":
        dis_dict = extraction_result.model_dump() if hasattr(extraction_result, "model_dump") else dict(extraction_result)
        dis_dict["child_name"] = masker.unmask(dis_dict["child_name"])
        dis_dict["description"] = masker.unmask(dis_dict["description"])
        
        updated_matrix = apply_disruption(current_matrix, dis_dict)
    else:
        # General inquiry, no matrix changes
        updated_matrix = current_matrix

    # 3. Perform Gap Analysis
    # Determine the date range for gap analysis: from today to 4 weeks out,
    # or based on the min/max dates in the matrix.
    all_activities = updated_matrix.get("activities", [])
    if all_activities:
        active_dates = [parse_date(a["start_date"]) for a in all_activities if a.get("status") == "ACTIVE"]
        active_dates += [parse_date(a["end_date"]) for a in all_activities if a.get("status") == "ACTIVE"]
        if active_dates:
            start_date = min(active_dates)
            end_date = max(active_dates)
        else:
            start_date = datetime.now().date()
            end_date = start_date + timedelta(weeks=4)
    else:
        start_date = datetime.now().date()
        end_date = start_date + timedelta(weeks=4)
        
    # Cap the gap analysis window to a maximum of 3 months to prevent infinite loops
    if (end_date - start_date).days > 90:
        end_date = start_date + timedelta(days=90)
        
    gaps = calculate_gaps(all_activities, profile, start_date, end_date)
    updated_matrix["gaps"] = gaps
    
    # Save the updated matrix
    storage.save_matrix(user_id, updated_matrix)
    
    return updated_matrix
