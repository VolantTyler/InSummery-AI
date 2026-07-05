import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from flask import jsonify

from firebase_functions import https_fn
from firebase_admin import initialize_app, firestore, auth

# Initialize telemetry BEFORE importing anything that uses the GenAI Client,
# so that spans emitted during module import (e.g. agent/workflow construction)
# are captured as well.
from app.telemetry import setup_telemetry
setup_telemetry()

from google.adk import Runner, Context
from google.adk.sessions import InMemorySessionService, Session
from google.adk.events import RequestInput
from google.genai.types import Content, Part, FunctionResponse

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.agent import insummery_workflow
from app.storage import FirestoreStorageProvider

# Initialize Firebase Admin
if os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
    initialize_app(options={"projectId": "insummery-ai"})
else:
    initialize_app()

_db = None
def get_db():
    global _db
    if _db is None:
        _db = firestore.client()
    return _db


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_auth_token(req: https_fn.Request) -> str:
    """Verify the Firebase ID token in the Authorization header and return the uid."""
    auth_header = req.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise ValueError("Missing or invalid Authorization header")
    
    id_token = auth_header.split("Bearer ")[1]
    
    # Bypass verification for local mock authentication
    if id_token == "mock-firebase-id-token":
        return "mock_user"
        
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token["uid"]
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise ValueError("Unauthorized")

def serialize_session_events(session: Session) -> List[Dict[str, Any]]:
    """Serialize session events to a list of dicts for Firestore storage."""
    serialized = []
    for event in session.events:
        try:
            # Pydantic model dump
            serialized.append(event.model_dump(mode="json"))
        except AttributeError:
            # Fallback for older Pydantic
            serialized.append(event.dict())
    return serialized

def deserialize_session_events(events_data: List[Dict[str, Any]]) -> List[Any]:
    """Deserialize list of dicts to ADK event objects."""
    from google.adk.events import Event
    deserialized = []
    for event_dict in events_data:
        deserialized.append(Event(**event_dict))
    return deserialized

@https_fn.on_request()
def api(req: https_fn.Request) -> https_fn.Response:
    """Main API router for Firebase Cloud Functions."""
    try:
        return _route_request(req)
    finally:
        # Cloud Functions instances can have their CPU frozen immediately
        # after the response is sent, before the BatchSpanProcessor's
        # background thread gets scheduled to export queued spans. Force a
        # flush here so traces reliably reach Cloud Trace instead of being
        # silently dropped.
        from opentelemetry import trace
        trace.get_tracer_provider().force_flush(timeout_millis=5000)

def _route_request(req: https_fn.Request) -> https_fn.Response:
    # Enable CORS
    if req.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600"
        }
        return https_fn.Response(status=204, headers=headers)

    headers = {"Access-Control-Allow-Origin": "*"}

    try:
        user_id = verify_auth_token(req)
    except ValueError as e:
        return https_fn.Response(json.dumps({"error": str(e)}), status=401, headers=headers, mimetype="application/json")

    path = req.path.replace("/api", "")
    
    if path == "/process-email" and req.method == "POST":
        return handle_process_email(req, user_id, headers)
    elif path == "/resume-workflow" and req.method == "POST":
        return handle_resume_workflow(req, user_id, headers)
    elif (path == "/get-schedule" or path == "/get-matrix") and req.method == "GET":
        return handle_get_schedule(user_id, headers)
    elif path == "/sync-calendar" and req.method == "POST":
        return handle_sync_calendar(user_id, headers)
    elif path == "/get-profile" and req.method == "GET":
        return handle_get_profile(user_id, headers)
    elif path == "/save-profile" and req.method == "POST":
        return handle_save_profile(req, user_id, headers)
    else:
        return https_fn.Response(json.dumps({"error": "Not Found"}), status=404, headers=headers, mimetype="application/json")

def handle_process_email(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    data = req.get_json() or {}
    email_text = data.get("text", "")
    if not email_text:
        return https_fn.Response(json.dumps({"error": "Missing text parameter"}), status=400, headers=headers, mimetype="application/json")

    session_id = data.get("sessionId") or f"session_{int(datetime.now().timestamp())}"
    
    # Run the workflow
    session_service = InMemorySessionService()
    runner = Runner(
        agent=insummery_workflow,
        app_name="insummery_app",
        session_service=session_service,
        auto_create_session=True
    )
    
    # We pass the mode=firebase to the workflow state
    state_delta = {"mode": "firebase"}
    
    msg = Content(parts=[Part(text=email_text)])
    res_gen = runner.run(user_id=user_id, session_id=session_id, new_message=msg, state_delta=state_delta)
    
    events = list(res_gen)
    
    # Retrieve the session to check if it's interrupted
    loop = asyncio.new_event_loop()
    session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
    loop.close()
    
    # Check for RequestInput
    pending_interrupt = None
    for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call and part.function_call.name == "adk_request_input":
                    pending_interrupt = part.function_call
                    break

    storage = FirestoreStorageProvider()
    
    if pending_interrupt:
        # Save the workflow session events to Firestore so we can resume later
        serialized_events = serialize_session_events(session)
        state_to_save = {
            "sessionId": session_id,
            "events": serialized_events,
            "interrupt_id": pending_interrupt.id,
            "message": pending_interrupt.args.get("message", "Clarification needed.")
        }
        storage.save_pending_workflow(user_id, session_id, state_to_save)
        
        return https_fn.Response(
            json.dumps({
                "status": "INTERRUPTED",
                "workflowId": session_id,
                "message": pending_interrupt.args.get("message")
            }),
            status=200,
            headers=headers,
            mimetype="application/json"
        )
    
    # Successful completion, return updated matrix
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    return https_fn.Response(
        json.dumps({
            "status": "COMPLETED",
            "matrix": matrix
        }),
        status=200,
        headers=headers,
        mimetype="application/json"
    )

def handle_resume_workflow(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    data = req.get_json() or {}
    workflow_id = data.get("workflowId")
    user_response = data.get("response")
    
    if not workflow_id or not user_response:
        return https_fn.Response(json.dumps({"error": "Missing workflowId or response"}), status=400, headers=headers, mimetype="application/json")

    storage = FirestoreStorageProvider()
    saved_state = storage.get_pending_workflow(user_id, workflow_id)
    if not saved_state:
        return https_fn.Response(json.dumps({"error": "Workflow not found or already completed"}), status=404, headers=headers, mimetype="application/json")

    # Recreate the session from saved events
    session_id = saved_state["sessionId"]
    deserialized_events = deserialize_session_events(saved_state["events"])
    
    session_service = InMemorySessionService()
    # Pre-populate the session
    loop = asyncio.new_event_loop()
    loop.run_until_complete(session_service.create_session(
        user_id=user_id,
        session_id=session_id,
        app_name="insummery_app"
    ))
    session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
    session.events = deserialized_events
    loop.close()

    runner = Runner(
        agent=insummery_workflow,
        app_name="insummery_app",
        session_service=session_service,
        auto_create_session=False
    )

    # Resume by sending the FunctionResponse
    msg = Content(parts=[
        Part(function_response=FunctionResponse(
            name='adk_request_input', 
            response={'response': user_response}, 
            id=saved_state["interrupt_id"]
        ))
    ])
    
    res_gen = runner.run(user_id=user_id, session_id=session_id, new_message=msg)
    events = list(res_gen)

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
        loop = asyncio.new_event_loop()
        session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
        loop.close()
        
        serialized_events = serialize_session_events(session)
        saved_state["events"] = serialized_events
        saved_state["interrupt_id"] = pending_interrupt.id
        saved_state["message"] = pending_interrupt.args.get("message")
        storage.save_pending_workflow(user_id, workflow_id, saved_state)
        
        return https_fn.Response(
            json.dumps({
                "status": "INTERRUPTED",
                "workflowId": workflow_id,
                "message": pending_interrupt.args.get("message")
            }),
            status=200,
            headers=headers,
            mimetype="application/json"
        )

    # Completed! Clean up pending workflow
    # Delete the pending workflow document
    get_db().collection("users").document(user_id).collection("pending_workflows").document(workflow_id).delete()
    
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    return https_fn.Response(
        json.dumps({
            "status": "COMPLETED",
            "matrix": matrix
        }),
        status=200,
        headers=headers,
        mimetype="application/json"
    )

def handle_get_schedule(user_id: str, headers: dict) -> https_fn.Response:
    storage = FirestoreStorageProvider()
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    return https_fn.Response(json.dumps(matrix), status=200, headers=headers, mimetype="application/json")

def handle_get_profile(user_id: str, headers: dict) -> https_fn.Response:
    storage = FirestoreStorageProvider()
    profile = storage.get_profile(user_id)
    if not profile:
        return https_fn.Response(json.dumps({"onboarding_required": True}), status=200, headers=headers, mimetype="application/json")
    return https_fn.Response(json.dumps(profile), status=200, headers=headers, mimetype="application/json")

def handle_save_profile(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    data = req.get_json() or {}
    storage = FirestoreStorageProvider()
    storage.save_profile(user_id, data)
    return https_fn.Response(json.dumps({"status": "SUCCESS"}), status=200, headers=headers, mimetype="application/json")

def handle_sync_calendar(user_id: str, headers: dict) -> https_fn.Response:
    # 1. Get Google Calendar OAuth tokens from Firestore
    token_ref = get_db().collection("users").document(user_id).collection("tokens").document("google_calendar")
    token_doc = token_ref.get()
    if not token_doc.exists:
        return https_fn.Response(json.dumps({"error": "Google Calendar not connected"}), status=400, headers=headers, mimetype="application/json")
    
    token_data = token_doc.to_dict()
    
    # 2. Build credentials and refresh if needed
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    creds = Credentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed token
            token_ref.update({
                "access_token": creds.token,
                "expiry": creds.expiry.isoformat() if creds.expiry else None
            })
        except Exception as e:
            logger.error(f"Failed to refresh Google token: {e}")
            return https_fn.Response(json.dumps({"error": "Failed to refresh Google Calendar connection"}), status=401, headers=headers, mimetype="application/json")

    # 3. Load schedule matrix
    storage = FirestoreStorageProvider()
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    activities = matrix.get("activities", [])
    profile = storage.get_profile(user_id) or {}
    
    # 4. Sync each activity
    try:
        service = build('calendar', 'v3', credentials=creds)
        
        for act in activities:
            status = act.get("status", "ACTIVE")
            title = act.get("activity_title", "")
            
            # Prepend status if disrupted/cancelled
            if status in ["DISRUPTED", "CANCELLED"]:
                event_title = f"[{status}] {title}"
            else:
                # Add child prefix for single calendar mode
                event_title = f"[{act.get('child_name')}] {title}"

            event_body = {
                'summary': event_title,
                'location': act.get('location', ''),
                'description': act.get('notes', ''),
                'start': {
                    'dateTime': f"{act['start_date']}T{act['start_time']}:00",
                    'timeZone': profile.get('timezone', 'America/New_York'),
                },
                'end': {
                    'dateTime': f"{act['end_date']}T{act['end_time']}:00",
                    'timeZone': profile.get('timezone', 'America/New_York'),
                }
            }
            
            event_id = act.get("google_event_id")
            if event_id:
                # Update existing event
                try:
                    service.events().update(calendarId='primary', eventId=event_id, body=event_body).execute()
                except HttpError as e:
                    if e.resp.status == 404:
                        # If deleted from calendar, recreate it
                        event = service.events().insert(calendarId='primary', body=event_body).execute()
                        act["google_event_id"] = event['id']
                    else:
                        raise e
            else:
                # Create new event
                event = service.events().insert(calendarId='primary', body=event_body).execute()
                act["google_event_id"] = event['id']

        # Save updated matrix (containing google_event_ids)
        storage.save_matrix(user_id, matrix)
        
        return https_fn.Response(json.dumps({"status": "SUCCESS", "message": "Calendar synced successfully"}), status=200, headers=headers, mimetype="application/json")
        
    except Exception as e:
        logger.error(f"Calendar sync failed: {e}")
        return https_fn.Response(json.dumps({"error": f"Calendar sync failed: {str(e)}"}), status=500, headers=headers, mimetype="application/json")
