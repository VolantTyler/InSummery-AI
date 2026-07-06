import os
import json
import sys
from dotenv import load_dotenv

# Load the project-root .env regardless of the current working directory
# the MCP server is invoked from (e.g. `insummery-mcp` console script).
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import FastMCP

from app.storage import LocalStorageProvider

# Create the FastMCP server
mcp = FastMCP("InSummery Local Server")
provider = LocalStorageProvider()

@mcp.tool()
def get_schedule_matrix() -> str:
    """Get the local schedule matrix showing all activities and gaps.
    
    Returns:
        JSON string representing the schedule matrix.
    """
    matrix = provider.get_matrix("local_user")
    return json.dumps(matrix, indent=2)

@mcp.tool()
def get_family_profile() -> str:
    """Get the local family profile containing parents, children, address, and baseline coverage.
    
    Returns:
        JSON string representing the family profile.
    """
    profile = provider.get_profile("local_user")
    if not profile:
        return json.dumps({"error": "No family profile found."})
    return json.dumps(profile, indent=2)

@mcp.tool()
def list_childcare_gaps() -> str:
    """List all identified childcare gaps from the local schedule matrix.
    
    Returns:
        JSON string representing the list of childcare gaps.
    """
    matrix = provider.get_matrix("local_user")
    gaps = matrix.get("gaps", [])
    return json.dumps(gaps, indent=2)

@mcp.tool()
def sync_google_calendar() -> str:
    """Sync the local schedule matrix activities to Google Calendar.
    
    Uses a local tokens.json OAuth flow. Runs local InstalledAppFlow if tokens are missing or expired.
    
    Returns:
        JSON string with status details.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return json.dumps({"error": "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables must be set."})

    scopes = ["https://www.googleapis.com/auth/calendar.events"]
    creds = None
    token_path = "tokens.json"

    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, scopes=scopes)
        except Exception:
            pass

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        
        if not creds:
            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            try:
                flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                return json.dumps({"error": f"Failed to run InstalledAppFlow: {str(e)}"})

        # Save the credentials to tokens.json
        try:
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())
        except Exception as e:
            return json.dumps({"error": f"Failed to save tokens.json: {str(e)}"})

    # Load schedule matrix and profile
    matrix = provider.get_matrix("local_user") or {"activities": [], "gaps": []}
    activities = matrix.get("activities", [])
    profile = provider.get_profile("local_user") or {}

    synced_count = 0
    errors = []

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
                try:
                    service.events().update(calendarId='primary', eventId=event_id, body=event_body).execute()
                    synced_count += 1
                except HttpError as e:
                    if e.resp.status == 404:
                        # Recreate if deleted from calendar
                        try:
                            event = service.events().insert(calendarId='primary', body=event_body).execute()
                            act["google_event_id"] = event['id']
                            synced_count += 1
                        except Exception as insert_err:
                            errors.append(f"Failed to recreate event for {title}: {str(insert_err)}")
                    else:
                        errors.append(f"Failed to update event for {title}: {str(e)}")
                except Exception as update_err:
                    errors.append(f"Failed to update event for {title}: {str(update_err)}")
            else:
                try:
                    event = service.events().insert(calendarId='primary', body=event_body).execute()
                    act["google_event_id"] = event['id']
                    synced_count += 1
                except Exception as insert_err:
                    errors.append(f"Failed to create event for {title}: {str(insert_err)}")

        provider.save_matrix("local_user", matrix)
        
        return json.dumps({
            "status": "SUCCESS",
            "synced_events": synced_count,
            "errors": errors
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to sync calendar: {str(e)}"})

def main():
    mcp.run()

if __name__ == "__main__":
    main()
