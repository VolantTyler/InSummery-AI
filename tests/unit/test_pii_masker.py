import pytest
from app.pii_masker import PIIMasker

@pytest.fixture
def sample_profile():
    return {
        "parents": [
            {
                "name": "Sarah",
                "email": "sarah.parent@example.com",
                "phone": "555-123-4567"
            }
        ],
        "children": [
            {"name": "Emily"},
            {"name": "Jack"}
        ],
        "address": "123 Elm Street, Springville"
    }

def test_profile_based_masking(sample_profile):
    masker = PIIMasker(sample_profile)
    
    text = "Emily is going to soccer camp. Sarah will pick her up at 123 Elm Street, Springville."
    masked = masker.mask(text)
    
    # Verify profile names and address are masked
    assert "Emily" not in masked
    assert "Sarah" not in masked
    assert "123 Elm Street, Springville" not in masked
    assert "[CHILD_A]" in masked
    assert "[PARENT_A]" in masked
    assert "[ADDRESS_1]" in masked

def test_case_insensitive_masking(sample_profile):
    masker = PIIMasker(sample_profile)
    
    text = "EMILY and jack are registered. Contact sarah."
    masked = masker.mask(text)
    
    assert "EMILY" not in masked
    assert "jack" not in masked
    assert "sarah" not in masked
    assert "[CHILD_A]" in masked
    assert "[CHILD_B]" in masked
    assert "[PARENT_A]" in masked

def test_dynamic_pii_masking(sample_profile):
    masker = PIIMasker(sample_profile)
    
    text = "Please contact the coach at coach.dave@camp.com or call 555-999-8888."
    masked = masker.mask(text)
    
    # Dynamic email and phone should be masked
    assert "coach.dave@camp.com" not in masked
    assert "555-999-8888" not in masked
    assert "[DYNAMIC_EMAIL_1]" in masked or "[DYNAMIC_EMAIL" in masked
    assert "[DYNAMIC_PHONE_1]" in masked or "[DYNAMIC_PHONE" in masked

def test_unmasking(sample_profile):
    masker = PIIMasker(sample_profile)
    
    text = "Emily is registered. Email her at sarah.parent@example.com."
    masked = masker.mask(text)
    
    # Unmask
    unmasked = masker.unmask(masked)
    
    # Should restore original text (may differ slightly in case if case-insensitive was applied,
    # but exact match should be restored)
    assert "Emily" in unmasked
    assert "sarah.parent@example.com" in unmasked
    assert "[CHILD_A]" not in unmasked
    assert "[EMAIL_1]" not in unmasked

def test_caregiver_masking():
    profile = {
        "parents": [{"name": "Sarah"}],
        "children": [{"name": "Emily"}],
        "caregivers": [
            {
                "name": "Jessica",
                "email": "jessica.nanny@example.com",
                "phone": "555-222-3333"
            }
        ]
    }
    masker = PIIMasker(profile)
    text = "Nanny Jessica will watch Emily. Reach Jessica at jessica.nanny@example.com or 555-222-3333."
    masked = masker.mask(text)
    
    assert "Jessica" not in masked
    assert "jessica.nanny@example.com" not in masked
    assert "555-222-3333" not in masked
    assert "[CAREGIVER_A]" in masked
    assert "[CAREGIVER_EMAIL_1]" in masked
    assert "[CAREGIVER_PHONE_1]" in masked
    
    unmasked = masker.unmask(masked)
    assert "Jessica" in unmasked
    assert "jessica.nanny@example.com" in unmasked
    assert "555-222-3333" in unmasked
