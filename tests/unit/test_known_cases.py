import os
import json
import pytest
from app.pii_masker import PIIMasker

@pytest.fixture
def test_cases_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_cases")

@pytest.fixture
def profile_10_kids(test_cases_dir):
    profile_path = os.path.join(test_cases_dir, "profile_10_kids.json")
    with open(profile_path, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def manifest(test_cases_dir):
    manifest_path = os.path.join(test_cases_dir, "test_cases_manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)

def test_pii_masking_on_all_known_cases(profile_10_kids, manifest, test_cases_dir):
    masker = PIIMasker(profile_10_kids)
    
    # Extract names and other PII to verify masking
    child_names = [child["name"] for child in profile_10_kids["children"]]
    parent_names = [parent["name"] for parent in profile_10_kids["parents"]]
    caregiver_names = [cg["name"] for cg in profile_10_kids["caregivers"]]
    address = profile_10_kids["address"]
    
    all_pii_names = child_names + parent_names + caregiver_names
    
    for case in manifest:
        filename = case["filename"]
        child_name = case["child_name"]
        
        filepath = os.path.join(test_cases_dir, filename)
        assert os.path.exists(filepath), f"Test case file {filename} does not exist"
        
        with open(filepath, "r", encoding="utf-8") as f:
            original_text = f.read()
        
        # Mask text
        masked_text = masker.mask(original_text)
        
        # 1. Verify specific child associated with this case is masked
        assert child_name not in masked_text, f"Child name '{child_name}' was not masked in {filename}"
        
        # 2. Verify parent names are masked if they appear in the original text
        for parent in parent_names:
            if parent in original_text:
                assert parent not in masked_text, f"Parent name '{parent}' was not masked in {filename}"
                
        # 3. Verify caregiver names are masked if they appear in the original text
        for caregiver in caregiver_names:
            if caregiver in original_text:
                assert caregiver not in masked_text, f"Caregiver name '{caregiver}' was not masked in {filename}"
                
        # 4. Verify home address is masked if it appears in the original text
        if address in original_text:
            assert address not in masked_text, f"Address '{address}' was not masked in {filename}"
            
        # 5. Verify unmasking restores the child's name
        unmasked_text = masker.unmask(masked_text)
        assert child_name in unmasked_text, f"Unmasking failed to restore child name '{child_name}' in {filename}"
        
        # 6. Verify unmasking restores parent names if they were present
        for parent in parent_names:
            if parent in original_text:
                assert parent in unmasked_text, f"Unmasking failed to restore parent name '{parent}' in {filename}"
