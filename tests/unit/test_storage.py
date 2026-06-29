import os
import shutil
import tempfile
import pytest
from app.storage import LocalStorageProvider

@pytest.fixture
def temp_dir():
    # Create a temporary directory for local storage testing
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)

def test_local_storage_profile(temp_dir):
    provider = LocalStorageProvider(base_dir=temp_dir)
    
    # Verify profile is initially None
    assert provider.get_profile("user_1") is None
    
    # Save a profile
    sample_profile = {
        "parents": [{"name": "Sarah"}],
        "children": [{"name": "Emily"}]
    }
    provider.save_profile("user_1", sample_profile)
    
    # Retrieve and verify
    retrieved = provider.get_profile("user_1")
    assert retrieved == sample_profile

def test_local_storage_matrix(temp_dir):
    provider = LocalStorageProvider(base_dir=temp_dir)
    
    # Verify default matrix is empty
    default_matrix = provider.get_matrix("user_1")
    assert default_matrix == {"activities": [], "gaps": []}
    
    # Save a matrix
    sample_matrix = {
        "activities": [{"child": "Emily", "title": "Soccer Camp"}],
        "gaps": []
    }
    provider.save_matrix("user_1", sample_matrix)
    
    # Retrieve and verify
    retrieved = provider.get_matrix("user_1")
    assert retrieved == sample_matrix

def test_local_storage_pending_workflow(temp_dir):
    provider = LocalStorageProvider(base_dir=temp_dir)
    
    # Verify pending workflow is initially None
    assert provider.get_pending_workflow("user_1", "wf_123") is None
    
    # Save a pending workflow state
    sample_state = {"step": "hitl", "reason": "low_confidence", "data": {"email": "hello"}}
    provider.save_pending_workflow("user_1", "wf_123", sample_state)
    
    # Retrieve and verify
    retrieved = provider.get_pending_workflow("user_1", "wf_123")
    assert retrieved == sample_state
