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


# ---------------------------------------------------------------------------
# Characterization tests: CURRENT (defective) masker behavior
# ---------------------------------------------------------------------------
# These assert what PIIMasker does today, not what it should do. They exist so
# the substring-matching defects are pinned in the test suite rather than
# living only in a report, and so the fix has to flip them *deliberately*
# instead of silently changing behavior.
#
# When the masker is fixed to match on word boundaries and to understand
# first/last names, every test in this section should be rewritten to assert
# the correct behavior named in its docstring. A failure here after such a fix
# is the fix working.
#
# Measured impact of these defects (insummery-eval run --suites identity):
#   mask_precision 0.17 | mask_recall 0.38 | mask_token_integrity 0.50
# ---------------------------------------------------------------------------

@pytest.fixture
def collision_profile():
    """A profile whose names collide with ordinary English words.

    Not contrived: "Sam", "Pat" and "Alex" are all in the project's own eval
    fixture, tests/test_cases/profile_10_kids.json.
    """
    return {
        "parents": [{"name": "Dana"}],
        "children": [{"name": "Sam"}, {"name": "Pat"}, {"name": "Alex"}],
        "address": "1 Main St",
    }


def test_current_masker_corrupts_ordinary_words_containing_a_child_name(collision_profile):
    """SHOULD: leave "same" alone. DOES: rewrites it to "[CHILD_A]e"."""
    masker = PIIMasker(collision_profile)
    masked = masker.mask("Camp runs at the same time each day.")
    assert "same" not in masked
    assert "[CHILD_A]e time" in masked


def test_current_masker_corrupts_words_with_an_interior_match(collision_profile):
    """SHOULD: leave "participation" alone. DOES: splits it mid-word."""
    masker = PIIMasker(collision_profile)
    masked = masker.mask("Participation is required.")
    assert "[CHILD_B]" in masked
    assert "Participation" not in masked


def test_current_masker_truncates_a_longer_name_sharing_a_prefix(collision_profile):
    """SHOULD: leave the unrelated adult "Alexandra" intact.
    DOES: turns her into "[CHILD_C]andra"."""
    masker = PIIMasker(collision_profile)
    assert masker.mask("Alexandra Reyes will lead.").startswith("[CHILD_C]andra")


def test_current_masker_does_not_mask_a_surname_it_was_never_given():
    """SHOULD: keep the family surname off the wire. DOES: passes it through.

    The profile schema stores first names only, so "Smith" reaches the model
    verbatim -- on the project's own fixtures (case_02_sam_robotics.txt).
    """
    masker = PIIMasker({"children": [{"name": "Sam"}], "parents": [], "address": ""})
    masked = masker.mask("Attendee: Sam Smith")
    assert "[CHILD_A]" in masked
    assert "Smith" in masked


def test_current_masker_misses_a_first_name_when_profile_stores_a_full_name():
    """SHOULD: mask "Emily". DOES: nothing, because it only matches the whole
    stored string "Emily Carter"."""
    masker = PIIMasker({"children": [{"name": "Emily Carter"}], "parents": [], "address": ""})
    assert masker.mask("Emily starts camp Monday.") == "Emily starts camp Monday."


def test_current_masker_does_not_understand_nicknames():
    """SHOULD: mask "Sammy" as the child Sam. DOES: produces "[CHILD_A]my"."""
    masker = PIIMasker({"children": [{"name": "Sam"}], "parents": [], "address": ""})
    assert masker.mask("Sammy had a great day.") == "[CHILD_A]my had a great day."


def test_current_masker_roundtrip_is_lossy_on_a_collision(collision_profile):
    """SHOULD: unmask(mask(text)) == text. DOES: corrupts casing.

    "same" is masked case-insensitively, then restored with the profile's
    casing, so the sentence comes back with a capital S mid-word.
    """
    masker = PIIMasker(collision_profile)
    text = "Camp runs at the same time."
    assert masker.unmask(masker.mask(text)) != text
    assert masker.unmask(masker.mask(text)) == "Camp runs at the Same time."


def test_masking_is_correct_when_the_name_stands_alone(collision_profile):
    """The happy path the existing eval fixtures exercise -- and the reason
    the aggregate scores looked fine while the above were all broken."""
    masker = PIIMasker(collision_profile)
    masked = masker.mask("Sam and Pat are registered for camp.")
    assert masked == "[CHILD_A] and [CHILD_B] are registered for camp."
    assert masker.unmask(masked) == "Sam and Pat are registered for camp."
