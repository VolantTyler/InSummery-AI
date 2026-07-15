import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
from flask import jsonify

from firebase_functions import https_fn, options
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
from google_auth_oauthlib.flow import Flow

from app.agent import insummery_workflow
from app.storage import FirestoreStorageProvider
from app.workflow_trace import emit_hitl_feedback, emit_workflow_trace

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

# /process-email and /resume-workflow run a multi-step agentic workflow
# (PII masking -> triage -> interpretation -> gap analysis), each step a
# separate LLM call. On a cold instance this routinely exceeds the 60s
# default Cloud Functions timeout, which the platform surfaces to callers
# as a 503. Raise the timeout/memory well past worst-case workflow latency;
# note Firebase Hosting's `/api/**` rewrite still hard-caps proxied requests
# at 60s regardless of this setting, so slow endpoints must be called via
# the function's direct URL (see frontend/src/firebase.js DIRECT_API_URL).
@https_fn.on_request(
    timeout_sec=300,
    memory=options.MemoryOption.GB_1,
    secrets=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
)
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

    path = req.path.replace("/api", "")

    # Bypass authentication for Google Calendar OAuth Callback
    if path == "/oauth/google-calendar/callback" and req.method == "GET":
        return handle_oauth_callback(req, headers)

    try:
        user_id = verify_auth_token(req)
    except ValueError as e:
        return https_fn.Response(json.dumps({"error": str(e)}), status=401, headers=headers, mimetype="application/json")

    if path == "/process-email" and req.method == "POST":
        return handle_process_email(req, user_id, headers)
    elif path == "/resume-workflow" and req.method == "POST":
        return handle_resume_workflow(req, user_id, headers)
    elif (path == "/get-schedule" or path == "/get-matrix") and req.method == "GET":
        return handle_get_schedule(user_id, headers)
    elif path == "/delete-activity" and req.method == "POST":
        return handle_delete_activity(req, user_id, headers)
    elif path == "/sync-calendar" and req.method == "POST":
        return handle_sync_calendar(user_id, headers)
    elif path == "/get-profile" and req.method == "GET":
        return handle_get_profile(user_id, headers)
    elif path == "/save-profile" and req.method == "POST":
        return handle_save_profile(req, user_id, headers)
    elif path == "/oauth/google-calendar/start" and req.method == "GET":
        return handle_oauth_start(req, user_id, headers)
    else:
        return https_fn.Response(json.dumps({"error": "Not Found"}), status=404, headers=headers, mimetype="application/json")

def handle_process_email(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    import time

    data = req.get_json() or {}
    email_text = data.get("text", "")
    if not email_text:
        return https_fn.Response(json.dumps({"error": "Missing text parameter"}), status=400, headers=headers, mimetype="application/json")

    session_id = data.get("sessionId") or f"session_{int(datetime.now().timestamp())}"
    started_at = time.monotonic()
    
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

    for event in events:
        if getattr(event, "error_code", None):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(emit_workflow_trace(
                    status="ERROR",
                    started_at=started_at,
                    error_code=str(event.error_code),
                ))
            finally:
                loop.close()
            return https_fn.Response(
                json.dumps({
                    "status": "ERROR",
                    "error": f"[{event.error_code}] {event.error_message}",
                }),
                status=500,
                headers=headers,
                mimetype="application/json",
            )
    
    # Retrieve the session to check if it's interrupted
    loop = asyncio.new_event_loop()
    session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
    
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

        try:
            loop.run_until_complete(emit_workflow_trace(
                status="INTERRUPTED",
                state=dict(session.state or {}),
                started_at=started_at,
                hitl=True,
            ))
        finally:
            loop.close()
        
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
    try:
        loop.run_until_complete(emit_workflow_trace(
            status="COMPLETED",
            state=dict(session.state or {}),
            matrix=matrix,
            started_at=started_at,
        ))
    finally:
        loop.close()
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
    import time

    data = req.get_json() or {}
    workflow_id = data.get("workflowId")
    user_response = data.get("response")
    started_at = time.monotonic()
    
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
    # Pre-populate the session. Events must be appended through the session
    # service (get_session returns a copy, so assigning session.events
    # directly leaves the stored session empty and the runner cannot find
    # the original adk_request_input call to resume from).
    loop = asyncio.new_event_loop()
    loop.run_until_complete(session_service.create_session(
        user_id=user_id,
        session_id=session_id,
        app_name="insummery_app"
    ))
    session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
    for event in deserialized_events:
        loop.run_until_complete(session_service.append_event(session, event))

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

    for event in events:
        if getattr(event, "error_code", None):
            try:
                loop.run_until_complete(emit_hitl_feedback(
                    workflow_id=workflow_id,
                    clarification=user_response,
                    status="ERROR",
                ))
                loop.run_until_complete(emit_workflow_trace(
                    status="ERROR",
                    started_at=started_at,
                    error_code=str(event.error_code),
                    hitl=True,
                ))
            finally:
                loop.close()
            return https_fn.Response(
                json.dumps({
                    "status": "ERROR",
                    "error": f"[{event.error_code}] {event.error_message}",
                }),
                status=500,
                headers=headers,
                mimetype="application/json",
            )

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
        session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
        
        serialized_events = serialize_session_events(session)
        saved_state["events"] = serialized_events
        saved_state["interrupt_id"] = pending_interrupt.id
        saved_state["message"] = pending_interrupt.args.get("message")
        storage.save_pending_workflow(user_id, workflow_id, saved_state)

        try:
            loop.run_until_complete(emit_hitl_feedback(
                workflow_id=workflow_id,
                clarification=user_response,
                status="INTERRUPTED",
                state=dict(session.state or {}),
            ))
            loop.run_until_complete(emit_workflow_trace(
                status="INTERRUPTED",
                state=dict(session.state or {}),
                started_at=started_at,
                hitl=True,
            ))
        finally:
            loop.close()
        
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
    
    session = loop.run_until_complete(session_service.get_session(user_id=user_id, session_id=session_id, app_name="insummery_app"))
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}
    try:
        loop.run_until_complete(emit_hitl_feedback(
            workflow_id=workflow_id,
            clarification=user_response,
            status="COMPLETED",
            state=dict(session.state or {}),
        ))
        loop.run_until_complete(emit_workflow_trace(
            status="COMPLETED",
            state=dict(session.state or {}),
            matrix=matrix,
            started_at=started_at,
            hitl=True,
        ))
    finally:
        loop.close()
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
    token_ref = get_db().collection("users").document(user_id).collection("tokens").document("google_calendar")
    profile["google_calendar_connected"] = token_ref.get().exists
    return https_fn.Response(json.dumps(profile), status=200, headers=headers, mimetype="application/json")

def handle_save_profile(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    data = req.get_json() or {}
    data.pop("google_calendar_connected", None)
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
        
        # Delete any calendar events that were marked for removal
        deleted_ids = matrix.get("deleted_google_event_ids", [])
        if deleted_ids:
            for event_id in deleted_ids:
                try:
                    service.events().delete(calendarId='primary', eventId=event_id).execute()
                except HttpError as e:
                    if e.resp.status not in [404, 410]:
                        logger.error(f"Failed to delete Google Calendar event {event_id}: {e}")
            matrix["deleted_google_event_ids"] = []
        
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

def get_oauth_request_host(req: https_fn.Request) -> str:
    """Resolve the externally-visible host for OAuth redirect URIs.

    When requests arrive through a Firebase Hosting rewrite, the Host header
    contains the internal Cloud Run host (e.g. api-xxxx-uc.a.run.app) while
    the original domain the browser used is in X-Forwarded-Host. The OAuth
    redirect URI must be built from the original domain, since that is what
    is registered in the Google Cloud OAuth client.
    """
    forwarded_host = req.headers.get("X-Forwarded-Host", "")
    if forwarded_host:
        # May be a comma-separated list if multiple proxies are involved;
        # the first entry is the original client-facing host.
        return forwarded_host.split(",")[0].strip()
    return req.headers.get("Host", "")

def handle_oauth_start(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return https_fn.Response(
            json.dumps({"error": "Google Calendar OAuth environment variables (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET) are not configured."}),
            status=500,
            headers=headers,
            mimetype="application/json"
        )
    
    # Construct redirect URI dynamically
    is_emulator = os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
    host = get_oauth_request_host(req)
    if is_emulator or "localhost" in host or "127.0.0.1" in host:
        redirect_uri = "http://localhost:5000/api/oauth/google-calendar/callback"
    else:
        clean_host = host.split(":")[0] if host else "in-summery.web.app"
        redirect_uri = f"https://{clean_host}/api/oauth/google-calendar/callback"
        
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    try:
        # PKCE must be disabled: the code_verifier generated here would live
        # only in this invocation's memory, but the token exchange happens in
        # a separate callback invocation that cannot know it. As a
        # confidential client we authenticate the exchange with client_secret
        # instead.
        flow = Flow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/calendar.events"],
            autogenerate_code_verifier=False
        )
        flow.redirect_uri = redirect_uri
        
        authorization_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=user_id
        )
        
        return https_fn.Response(
            json.dumps({"url": authorization_url}),
            status=200,
            headers=headers,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Failed to generate authorization URL: {e}")
        return https_fn.Response(
            json.dumps({"error": f"Failed to generate authorization URL: {str(e)}"}),
            status=500,
            headers=headers,
            mimetype="application/json"
        )

def handle_oauth_callback(req: https_fn.Request, headers: dict) -> https_fn.Response:
    code = req.args.get("code")
    state = req.args.get("state")
    
    if not code or not state:
        return https_fn.Response(
            json.dumps({"error": "Missing code or state parameter."}),
            status=400,
            headers=headers,
            mimetype="application/json"
        )
        
    user_id = state
    
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return https_fn.Response(
            json.dumps({"error": "Google Calendar OAuth environment variables are not configured."}),
            status=500,
            headers=headers,
            mimetype="application/json"
        )
        
    is_emulator = os.getenv("FIRESTORE_EMULATOR_HOST") or os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
    host = get_oauth_request_host(req)
    if is_emulator or "localhost" in host or "127.0.0.1" in host:
        redirect_uri = "http://localhost:5000/api/oauth/google-calendar/callback"
        redirect_url = "http://localhost:5000/"
    else:
        clean_host = host.split(":")[0] if host else "in-summery.web.app"
        redirect_uri = f"https://{clean_host}/api/oauth/google-calendar/callback"
        redirect_url = f"https://{clean_host}/"
        
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    try:
        # PKCE disabled to match the authorization request (see
        # handle_oauth_start); the exchange authenticates with client_secret.
        flow = Flow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/calendar.events"],
            autogenerate_code_verifier=False
        )
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        
        creds = flow.credentials
        
        db = get_db()
        token_ref = db.collection("users").document(user_id).collection("tokens").document("google_calendar")
        token_ref.set({
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "expiry": creds.expiry.isoformat() if creds.expiry else None
        })
        
        return https_fn.Response(status=302, headers={"Location": redirect_url})
        
    except Exception as e:
        logger.error(f"Failed to complete OAuth callback: {e}")
        return https_fn.Response(
            json.dumps({"error": f"Failed to complete OAuth callback: {str(e)}"}),
            status=500,
            headers=headers,
            mimetype="application/json"
        )


def handle_delete_activity(req: https_fn.Request, user_id: str, headers: dict) -> https_fn.Response:
    from app.matrix_logic import delete_activity, parse_date, calculate_gaps

    data = req.get_json() or {}
    activity_id = data.get("activity_id")
    delete_type = data.get("delete_type")  # "single" or "series"
    date_str = data.get("date")  # "YYYY-MM-DD"

    if not activity_id or not delete_type:
        return https_fn.Response(json.dumps({"error": "Missing activity_id or delete_type"}), status=400, headers=headers, mimetype="application/json")

    storage = FirestoreStorageProvider()
    profile = storage.get_profile(user_id) or {}
    matrix = storage.get_matrix(user_id) or {"activities": [], "gaps": []}

    try:
        matrix = delete_activity(matrix, activity_id, delete_type, date_str)
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        return https_fn.Response(json.dumps({"error": str(e)}), status=status, headers=headers, mimetype="application/json")

    # Recalculate gaps
    activities = matrix.get("activities", [])
    if activities:
        active_dates = []
        for a in activities:
            if a.get("status") == "ACTIVE":
                try:
                    active_dates.append(parse_date(a["start_date"]))
                    active_dates.append(parse_date(a["end_date"]))
                except Exception:
                    pass
        if active_dates:
            start_date = min(active_dates)
            end_date = max(active_dates)
        else:
            start_date = datetime.now().date()
            end_date = start_date + timedelta(weeks=4)
    else:
        start_date = datetime.now().date()
        end_date = start_date + timedelta(weeks=4)

    if (end_date - start_date).days > 90:
        end_date = start_date + timedelta(days=90)

    gaps = calculate_gaps(activities, profile, start_date, end_date)
    matrix["gaps"] = gaps

    storage.save_matrix(user_id, matrix)
    return https_fn.Response(json.dumps({"status": "SUCCESS", "matrix": matrix}), status=200, headers=headers, mimetype="application/json")


