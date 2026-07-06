import os
import sys
import argparse
import asyncio
import json
import webbrowser
from datetime import datetime
from dotenv import load_dotenv

# Load the project-root .env regardless of the current working directory
# the CLI is invoked from (e.g. `insummery` console script vs `python bin/insummery`).
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.events import RequestInput
from google.genai.types import Content, Part, FunctionResponse

from app.agent import insummery_workflow
from app.storage import LocalStorageProvider
from app.ui_generator import generate_html_grid

def get_session_events_serialized(session) -> list:
    serialized = []
    for event in session.events:
        try:
            serialized.append(event.model_dump(mode="json"))
        except AttributeError:
            serialized.append(event.dict())
    return serialized

def deserialize_session_events(events_data: list) -> list:
    from google.adk.events import Event
    deserialized = []
    for event_dict in events_data:
        deserialized.append(Event(**event_dict))
    return deserialized

async def run_local_workflow(text: str, is_disruption: bool) -> None:
    storage = LocalStorageProvider()
    user_id = "local_user"
    session_id = f"session_{int(datetime.now().timestamp())}"
    
    session_service = InMemorySessionService()
    runner = Runner(
        agent=insummery_workflow,
        app_name="insummery_app",
        session_service=session_service,
        auto_create_session=True
    )
    
    # We pass the category in state if it's a disruption
    state_delta = {"mode": "local"}
    if is_disruption:
        state_delta["category"] = "disruption"
        
    msg = Content(parts=[Part(text=text)])
    res_gen = runner.run(user_id=user_id, session_id=session_id, new_message=msg, state_delta=state_delta)
    
    events = list(res_gen)
    
    # Check for errors in the events
    for event in events:
        if event.error_code:
            print(f"\nError: Workflow execution failed: [{event.error_code}] {event.error_message}")
            return

    session = await session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app")
    
    # Check for RequestInput
    pending_interrupt = None
    for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name == "adk_request_input":
                    pending_interrupt = part.function_call
                    break

    if pending_interrupt:
        # Save state to local pending workflows
        serialized_events = get_session_events_serialized(session)
        state_to_save = {
            "sessionId": session_id,
            "events": serialized_events,
            "interrupt_id": pending_interrupt.id,
            "message": pending_interrupt.args.get("message")
        }
        storage.save_pending_workflow(user_id, session_id, state_to_save)
        
        print("\n=== CLARIFICATION REQUIRED (PAUSED) ===")
        print(f"Workflow ID: {session_id}")
        print(f"Question: {pending_interrupt.args.get('message')}")
        print(f"\nTo resume, run:\ninsummery --mode local --resume \"<your answer>\" --workflow-id {session_id}")
        return

    # Success! Generate and open UI
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    profile = storage.get_profile(user_id) or {}
    output_path = os.path.abspath(os.path.join(".", "output", "schedule.html"))
    
    generate_html_grid(matrix, profile, output_path)
    _print_run_outcome(matrix)
    print(f"HTML Dashboard generated at: file:///{output_path.replace(os.sep, '/')}")
    webbrowser.open(f"file:///{output_path}")

def _print_run_outcome(matrix: dict) -> None:
    warnings = matrix.get("warnings") or []
    if warnings:
        print("\nSchedule processed with warnings:")
        for warning in warnings:
            print(f"  Warning: {warning}")
    else:
        print("\nSchedule updated successfully!")

async def resume_local_workflow(workflow_id: str, response: str) -> None:
    storage = LocalStorageProvider()
    user_id = "local_user"
    
    saved_state = storage.get_pending_workflow(user_id, workflow_id)
    if not saved_state:
        print(f"Error: Workflow {workflow_id} not found.")
        sys.exit(1)
        
    session_id = saved_state["sessionId"]
    deserialized_events = deserialize_session_events(saved_state["events"])
    
    session_service = InMemorySessionService()
    await session_service.create_session(user_id=user_id, session_id=session_id, app_name="insummery_app")
    session = await session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app")
    for event in deserialized_events:
        await session_service.append_event(session, event)
    
    runner = Runner(
        agent=insummery_workflow,
        app_name="insummery_app",
        session_service=session_service,
        auto_create_session=False
    )
    
    msg = Content(parts=[
        Part(function_response=FunctionResponse(
            name='adk_request_input', 
            response={'response': response}, 
            id=saved_state["interrupt_id"]
        ))
    ])
    
    res_gen = runner.run(user_id=user_id, session_id=session_id, new_message=msg)
    events = list(res_gen)
    
    # Check for errors in the events
    for event in events:
        if event.error_code:
            print(f"\nError: Workflow resumption failed: [{event.error_code}] {event.error_message}")
            return
            
    # Check if still interrupted
    pending_interrupt = None
    for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name == "adk_request_input":
                    pending_interrupt = part.function_call
                    break

    if pending_interrupt:
        # Save updated events
        updated_session = await session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app")
        serialized_events = get_session_events_serialized(updated_session)
        saved_state["events"] = serialized_events
        saved_state["interrupt_id"] = pending_interrupt.id
        saved_state["message"] = pending_interrupt.args.get("message")
        storage.save_pending_workflow(user_id, workflow_id, saved_state)
        
        print("\n=== CLARIFICATION REQUIRED (PAUSED) ===")
        print(f"Workflow ID: {workflow_id}")
        print(f"Question: {pending_interrupt.args.get('message')}")
        print(f"\nTo resume, run:\ninsummery --mode local --resume \"<your answer>\" --workflow-id {workflow_id}")
        return

    # Completed! Clean up pending workflow
    # Delete from local file
    path = storage._get_pending_workflows_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            workflows = json.load(f)
        workflows.pop(f"{user_id}#{workflow_id}", None)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(workflows, f, indent=2, ensure_ascii=False)
            
    # Generate and open UI
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    profile = storage.get_profile(user_id) or {}
    output_path = os.path.abspath(os.path.join(".", "output", "schedule.html"))
    
    generate_html_grid(matrix, profile, output_path)
    _print_run_outcome(matrix)
    print(f"HTML Dashboard generated at: file:///{output_path.replace(os.sep, '/')}")
    webbrowser.open(f"file:///{output_path}")

def run_firebase_request(action: str, payload: dict) -> dict:
    """Helper to send request to Firebase Cloud Function API."""
    import requests
    # Retrieve Firebase Auth token or ask user (we'll look for FIREBASE_ID_TOKEN env var,
    # or fallback to mock token if in local test)
    token = os.getenv("FIREBASE_ID_TOKEN", "mock_token")
    api_url = os.getenv("INSUMMERY_API_URL", "http://localhost:5001/insummery-ai/us-central1/api")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    url = f"{api_url}/{action}"
    try:
        if payload:
            response = requests.post(url, json=payload, headers=headers)
        else:
            response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"API Error ({url}): {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="InSummery CLI - Ingest emails, manage schedules and detect gaps.")
    parser.add_argument("--mode", choices=["local", "firebase"], default="local", help="Execution mode (default: local)")
    parser.add_argument("--input", type=str, help="Raw email text of a registration or schedule update")
    parser.add_argument("--disruption", type=str, help="Raw text describing a schedule disruption (e.g., nanny sick)")
    parser.add_argument("--resume", type=str, help="Clarification text to resume a paused workflow")
    parser.add_argument("--workflow-id", type=str, help="Workflow ID required for resumption")
    
    args = parser.parse_args()

    if args.resume:
        if not args.workflow_id:
            parser.error("--workflow-id is required when resuming a workflow")
            
        if args.mode == "local":
            asyncio.run(resume_local_workflow(args.workflow_id, args.resume))
        else:
            print(f"Resuming workflow {args.workflow_id} on Firebase...")
            res = run_firebase_request("resume-workflow", {"workflowId": args.workflow_id, "response": args.resume})
            print("Status:", res.get("status"))
            if res.get("status") == "INTERRUPTED":
                print("Question:", res.get("message"))
            else:
                print("Successfully completed!")
    elif args.input or args.disruption:
        text = args.input or args.disruption
        is_dis = args.disruption is not None
        
        if args.mode == "local":
            asyncio.run(run_local_workflow(text, is_dis))
        else:
            print("Processing via Firebase Cloud Functions...")
            res = run_firebase_request("process-email", {"text": text, "isDisruption": is_dis})
            print("Status:", res.get("status"))
            if res.get("status") == "INTERRUPTED":
                print("Workflow ID:", res.get("workflowId"))
                print("Question:", res.get("message"))
            else:
                print("Successfully processed! Run with --mode firebase to sync or view on dashboard.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
