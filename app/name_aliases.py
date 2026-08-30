"""Small, explicit nickname/diminutive table shared by ``PIIMasker`` (input
masking) and ``resolve_child_name`` (output resolution), so both sides agree
on which name forms refer to the same person.

Deliberately a short, curated list rather than a generated one: an
over-eager nickname table creates false positives (e.g. "Alex" must NOT be
treated as equivalent to "Alexandra" -- they are tested as distinct people
in tests/eval/datasets/identity_cases.json's collide_alex_alexandra case).
Add entries only for pairs that are unambiguously the same name.
"""
from __future__ import annotations

from typing import FrozenSet, List

_NICKNAME_GROUPS: List[FrozenSet[str]] = [
    frozenset({"sam", "sammy", "sammie"}),
    frozenset({"mike", "michael", "mikey"}),
    frozenset({"katie", "katherine", "kathy", "kate", "cathy"}),
]

_GROUP_BY_NAME = {
    name: group for group in _NICKNAME_GROUPS for name in group
}


def name_variants(name: str) -> FrozenSet[str]:
    """Return every known equivalent spelling of ``name`` (casefolded), including itself."""
    key = (name or "").strip().casefold()
    return _GROUP_BY_NAME.get(key, frozenset({key} if key else frozenset()))


def names_equivalent(a: str, b: str) -> bool:
    """True if ``a`` and ``b`` are the same name or known nicknames of each other."""
    a_key = (a or "").strip().casefold()
    b_key = (b or "").strip().casefold()
    if not a_key or not b_key:
        return False
    if a_key == b_key:
        return True
    return b_key in name_variants(a_key)
