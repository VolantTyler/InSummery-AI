import re
from typing import Dict, Any, List, Match, Pattern

from app.name_aliases import name_variants

class PIIMasker:
    # A capitalized word immediately following a placeholder, e.g. the
    # "Smith" in "[CHILD_B] Smith". Used to detect a shared family surname
    # that the profile schema has no field for (see _mask_shared_surnames).
    _ADJACENT_CAPITALIZED = re.compile(r"\[[A-Z][A-Z0-9_]*\]\s+([A-Z][a-zA-Z]+)")

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
                self._register_person(name, placeholder)

        # 2. Map parents
        parents = self.profile.get("parents", [])
        for i, parent in enumerate(parents):
            name = parent.get("name")
            if name:
                placeholder = f"[PARENT_{chr(65 + i)}]" # [PARENT_A], [PARENT_B], etc.
                self._register_person(name, placeholder)

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
                self._register_person(name, placeholder)

            email = caregiver.get("email")
            if email:
                placeholder = f"[CAREGIVER_EMAIL_{i + 1}]"
                self._add_mapping(email, placeholder)

            phone = caregiver.get("phone")
            if phone:
                placeholder = f"[CAREGIVER_PHONE_{i + 1}]"
                self._add_mapping(phone, placeholder)

    def _register_person(self, name: str, placeholder: str) -> None:
        """Register every text form that should mask onto ``placeholder``.

        The profile schema only stores a single "name" string per person, but
        that string can be a bare first name ("Sam") or a full name ("Emily
        Carter"). Handling both without a schema change:

        - The first token is always registered, plus its known nicknames
          (e.g. "Sam" also registers "Sammy"), so "Emily Carter" still masks
          a lone "Emily" and "Sam" still masks a lone "Sammy".
        - Any remaining tokens (the surname) are registered as their own
          mapping, so "Carter" masks on its own wherever it appears -- e.g.
          "the Carter family" -- not just when glued to the first name.
        - The full stored string is also registered so a literal exact
          mention (and callers that look up ``original_to_mask[name]`` by
          the profile's stored string) keep working.
        """
        tokens = name.split()
        if not tokens:
            return

        first = tokens[0]
        self._add_mapping(first, placeholder)
        for variant in name_variants(first):
            if variant != first.strip().casefold():
                self._add_mapping(variant, placeholder)

        if len(tokens) > 1:
            surname = " ".join(tokens[1:])
            surname_placeholder = placeholder[:-1] + "_SURNAME]"
            self._add_mapping(surname, surname_placeholder)
            self._add_mapping(name, placeholder)

    def _add_mapping(self, original: str, placeholder: str) -> None:
        if not original:
            return
        # Store mapping both ways
        self.mask_to_original[placeholder] = original
        self.original_to_mask[original] = placeholder

    def _mask_pattern(self, text: str, pattern: Pattern, placeholder: str) -> str:
        """Replace every match of ``pattern`` with ``placeholder``.

        Records the *actual matched text* (not the profile's stored casing)
        as the restoration value, so unmask() round-trips ordinary text that
        happens to case-insensitively match a name (e.g. "same" is never
        matched thanks to word boundaries, but "SARAH" vs. stored "Sarah"
        restores as "SARAH", not "Sarah").
        """
        def _sub(m: Match) -> str:
            self.mask_to_original[placeholder] = m.group(0)
            return placeholder

        return pattern.sub(_sub, text)

    def _mask_shared_surnames(self, text: str) -> str:
        """Detect and mask a family surname the profile never stored.

        A profile that stores only first names ("Sam", "Dana", "Jamie") gives
        the masker no way to know the family's surname structurally. But when
        the *same* capitalized word appears directly after two or more
        already-masked family members ("Sam Smith" ... "Jamie Smith" ...
        "Dana Smith"), that repetition is a strong signal it is the shared
        family surname rather than a one-off third party ("Reese
        Witherspoon", mentioned once, is left alone). Single-occurrence
        adjacency is deliberately not enough -- that is what keeps a guest
        speaker's or vendor's name from being swept in.
        """
        counts: Dict[str, int] = {}
        first_seen: Dict[str, str] = {}
        for m in self._ADJACENT_CAPITALIZED.finditer(text):
            word = m.group(1)
            key = word.casefold()
            counts[key] = counts.get(key, 0) + 1
            first_seen.setdefault(key, word)

        masked = text
        next_index = 1
        for key, count in counts.items():
            if count < 2:
                continue
            word = first_seen[key]
            placeholder = f"[SURNAME_{next_index}]"
            next_index += 1
            self._add_mapping(word, placeholder)
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            masked = self._mask_pattern(masked, pattern, placeholder)
        return masked

    def mask(self, text: str) -> str:
        """
        Masks PII in the input text.
        First applies profile-based whole-word matching, then a pass for a
        shared family surname the profile has no field for, then applies
        regex-based masking for any remaining email addresses, phone
        numbers, and addresses.
        """
        if not text:
            return ""

        masked_text = text

        # 1. Profile-based whole-word matches (sorted by length descending so
        # a full "first last" registration is consumed before its shorter
        # first-name/surname parts, and so overlapping candidates never
        # leave a partial match behind).
        sorted_originals = sorted(self.original_to_mask.keys(), key=len, reverse=True)
        for orig in sorted_originals:
            placeholder = self.original_to_mask[orig]
            # Case-insensitive, whole-word replacement -- \b keeps a name
            # from matching inside an unrelated word ("Sam" inside "same").
            pattern = re.compile(rf"\b{re.escape(orig)}\b", re.IGNORECASE)
            masked_text = self._mask_pattern(masked_text, pattern, placeholder)

        # 2. A shared surname the profile schema never captured.
        masked_text = self._mask_shared_surnames(masked_text)

        # 3. Regex-based masking for emails
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, masked_text)
        for i, email in enumerate(emails):
            if email not in self.original_to_mask:
                placeholder = f"[DYNAMIC_EMAIL_{len(self.mask_to_original) + 1}]"
                self._add_mapping(email, placeholder)
                masked_text = masked_text.replace(email, placeholder)

        # 4. Regex-based masking for phone numbers (e.g. 123-456-7890, (123) 456-7890)
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

        # Second pass: LLMs sometimes echo placeholders without the square
        # brackets (e.g. "CHILD_B" instead of "[CHILD_B]"), which would leak
        # the placeholder into saved data. Replace bare whole-word variants too.
        for placeholder in sorted_placeholders:
            bare = placeholder.strip("[]")
            if not bare:
                continue
            original = self.mask_to_original[placeholder]
            unmasked_text = re.sub(rf"\b{re.escape(bare)}\b", original, unmasked_text)

        return unmasked_text
