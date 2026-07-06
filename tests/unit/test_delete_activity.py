import json
from unittest.mock import MagicMock, patch
import pytest
from datetime import datetime

class MockRequest:
    def __init__(self, json_data):
        self._json_data = json_data
    def get_json(self):
        return self._json_data

@patch("functions.main.FirestoreStorageProvider")
def test_delete_activity_series(mock_storage_class):
    # Setup mocks
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    initial_matrix = {
        "activities": [
            {
                "id": "act_1",
                "child_name": "Emily",
                "activity_title": "Soccer Camp",
                "start_date": "2026-07-06",
                "end_date": "2026-07-10",
                "start_time": "09:00",
                "end_time": "12:00",
                "status": "ACTIVE",
                "google_event_id": "g_123"
            }
        ],
        "gaps": []
    }
    mock_storage.get_profile.return_value = {
        "children": [{"name": "Emily"}]
    }
    mock_storage.get_matrix.return_value = initial_matrix

    from functions.main import handle_delete_activity

    req = MockRequest({
        "activity_id": "act_1",
        "delete_type": "series"
    })
    
    response = handle_delete_activity(req, "user_1", {})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data["status"] == "SUCCESS"
    assert len(data["matrix"]["activities"]) == 0
    assert "g_123" in data["matrix"]["deleted_google_event_ids"]
    mock_storage.save_matrix.assert_called_once()

@patch("functions.main.FirestoreStorageProvider")
def test_delete_activity_single_edge_start(mock_storage_class):
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    initial_matrix = {
        "activities": [
            {
                "id": "act_1",
                "child_name": "Emily",
                "activity_title": "Soccer Camp",
                "start_date": "2026-07-06",
                "end_date": "2026-07-10",
                "start_time": "09:00",
                "end_time": "12:00",
                "status": "ACTIVE"
            }
        ],
        "gaps": []
    }
    mock_storage.get_profile.return_value = {
        "children": [{"name": "Emily"}]
    }
    mock_storage.get_matrix.return_value = initial_matrix

    from functions.main import handle_delete_activity

    req = MockRequest({
        "activity_id": "act_1",
        "delete_type": "single",
        "date": "2026-07-06"
    })
    
    response = handle_delete_activity(req, "user_1", {})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data["status"] == "SUCCESS"
    activities = data["matrix"]["activities"]
    assert len(activities) == 1
    assert activities[0]["start_date"] == "2026-07-07"
    assert activities[0]["end_date"] == "2026-07-10"

@patch("functions.main.FirestoreStorageProvider")
def test_delete_activity_single_edge_end(mock_storage_class):
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    initial_matrix = {
        "activities": [
            {
                "id": "act_1",
                "child_name": "Emily",
                "activity_title": "Soccer Camp",
                "start_date": "2026-07-06",
                "end_date": "2026-07-10",
                "start_time": "09:00",
                "end_time": "12:00",
                "status": "ACTIVE"
            }
        ],
        "gaps": []
    }
    mock_storage.get_profile.return_value = {
        "children": [{"name": "Emily"}]
    }
    mock_storage.get_matrix.return_value = initial_matrix

    from functions.main import handle_delete_activity

    req = MockRequest({
        "activity_id": "act_1",
        "delete_type": "single",
        "date": "2026-07-10"
    })
    
    response = handle_delete_activity(req, "user_1", {})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data["status"] == "SUCCESS"
    activities = data["matrix"]["activities"]
    assert len(activities) == 1
    assert activities[0]["start_date"] == "2026-07-06"
    assert activities[0]["end_date"] == "2026-07-09"

@patch("functions.main.FirestoreStorageProvider")
def test_delete_activity_single_split(mock_storage_class):
    mock_storage = MagicMock()
    mock_storage_class.return_value = mock_storage
    
    initial_matrix = {
        "activities": [
            {
                "id": "act_1",
                "child_name": "Emily",
                "activity_title": "Soccer Camp",
                "start_date": "2026-07-06",
                "end_date": "2026-07-10",
                "start_time": "09:00",
                "end_time": "12:00",
                "status": "ACTIVE",
                "google_event_id": "g_123"
            }
        ],
        "gaps": []
    }
    mock_storage.get_profile.return_value = {
        "children": [{"name": "Emily"}]
    }
    mock_storage.get_matrix.return_value = initial_matrix

    from functions.main import handle_delete_activity

    req = MockRequest({
        "activity_id": "act_1",
        "delete_type": "single",
        "date": "2026-07-08"
    })
    
    response = handle_delete_activity(req, "user_1", {})
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert data["status"] == "SUCCESS"
    
    activities = data["matrix"]["activities"]
    assert len(activities) == 2
    
    assert activities[0]["id"] == "act_1"
    assert activities[0]["start_date"] == "2026-07-06"
    assert activities[0]["end_date"] == "2026-07-07"
    assert activities[0]["google_event_id"] == "g_123"
    
    assert activities[1]["id"] != "act_1"
    assert activities[1]["start_date"] == "2026-07-09"
    assert activities[1]["end_date"] == "2026-07-10"
    assert "google_event_id" not in activities[1]
