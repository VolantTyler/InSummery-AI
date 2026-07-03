import re
from typing import Dict, Any, List

class PIIMasker:
    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile
        self.mask_to_original: Dict[str, str] = {}
        self.original_to_mask: Dict[str, str] = {}
        self._initialize_profile_mappings()

    def _initialize_profile_mappings(self) -> None:
        """Initialize mappings from the profile data."""
        # 1. Map children
        children = self.profile.get("children", [])
        for i, child in enumerate(children):
            name = child.get("name")
            if name:
                placeholder = f"[CHILD_{chr(65 + i)}]" # [CHILD_A], [CHILD_B], etc.
                self._add_mapping(name, placeholder)

        # 2. Map parents
        parents = self.profile.get("parents", [])
        for i, parent in enumerate(parents):
            name = parent.get("name")
            if name:
                placeholder = f"[PARENT_{chr(65 + i)}]" # [PARENT_A], [PARENT_B], etc.
                self._add_mapping(name, placeholder)
            
            email = parent.get("email")
            if email:
                placeholder = f"[EMAIL_{i + 1}]"
                self._add_mapping(email, placeholder)
            
            phone = parent.get("phone")
            if phone:
                placeholder = f"[PHONE_{i + 1}]"
                self._add_mapping(phone, placeholder)

        # 3. Map home address
        address = self.profile.get("address")
        if address:
            self._add_mapping(address, "[ADDRESS_1]")

        # 4. Map caregivers/nannies
        caregivers = self.profile.get("caregivers", [])
        for i, caregiver in enumerate(caregivers):
            name = caregiver.get("name")
            if name:
                placeholder = f"[CAREGIVER_{chr(65 + i)}]" # [CAREGIVER_A], [CAREGIVER_B], etc.
                self._add_mapping(name, placeholder)
            
            email = caregiver.get("email")
            if email:
                placeholder = f"[CAREGIVER_EMAIL_{i + 1}]"
                self._add_mapping(email, placeholder)
            
            phone = caregiver.get("phone")
            if phone:
                placeholder = f"[CAREGIVER_PHONE_{i + 1}]"
                self._add_mapping(phone, placeholder)

    def _add_mapping(self, original: str, placeholder: str) -> None:
        if not original:
            return
        # Store mapping both ways
        self.mask_to_original[placeholder] = original
        self.original_to_mask[original] = placeholder

    def mask(self, text: str) -> str:
        """
        Masks PII in the input text.
        First applies profile-based exact-match masking, then applies regex-based masking
        for any remaining email addresses, phone numbers, and addresses.
        """
        if not text:
            return ""

        masked_text = text

        # 1. Profile-based exact matches (sorted by length descending to prevent partial matches)
        sorted_originals = sorted(self.original_to_mask.keys(), key=len, reverse=True)
        for orig in sorted_originals:
            placeholder = self.original_to_mask[orig]
            # Case-insensitive replacement
            pattern = re.compile(re.escape(orig), re.IGNORECASE)
            masked_text = pattern.sub(placeholder, masked_text)

        # 2. Regex-based masking for emails
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, masked_text)
        for i, email in enumerate(emails):
            if email not in self.original_to_mask:
                placeholder = f"[DYNAMIC_EMAIL_{len(self.mask_to_original) + 1}]"
                self._add_mapping(email, placeholder)
                masked_text = masked_text.replace(email, placeholder)

        # 3. Regex-based masking for phone numbers (e.g. 123-456-7890, (123) 456-7890)
        phone_pattern = r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
        phones = re.findall(phone_pattern, masked_text)
        for i, phone in enumerate(phones):
            if phone not in self.original_to_mask:
                placeholder = f"[DYNAMIC_PHONE_{len(self.mask_to_original) + 1}]"
                self._add_mapping(phone, placeholder)
                masked_text = masked_text.replace(phone, placeholder)

        return masked_text

    def unmask(self, text: str) -> str:
        """Restores the original PII from the masked placeholders."""
        if not text:
            return ""

        unmasked_text = text
        # Sort placeholders by length descending to prevent partial replacement issues
        sorted_placeholders = sorted(self.mask_to_original.keys(), key=len, reverse=True)
        for placeholder in sorted_placeholders:
            original = self.mask_to_original[placeholder]
            unmasked_text = unmasked_text.replace(placeholder, original)

        return unmasked_text
