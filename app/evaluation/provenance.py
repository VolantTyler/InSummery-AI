"""Provenance stamps that make a score change attributable.

When a nightly number moves, the first question is always *why*: did the model
change under us, or did we change the prompt, or did someone edit a fixture?
Without a stamp on every report that question takes an afternoon of git
archaeology. With one it is a diff of two strings.

- ``prompt_hash``  changed => you changed the instructions.
- ``dataset_hash`` changed => you changed the ground truth; scores across the
  boundary are not comparable.
- both unchanged, score moved => the *model* moved. That is drift.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional


def _sha256_short(text: str, length: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def prompt_hash() -> str:
    """Hash the static agent instructions.

    Deliberately excludes ``_today_context()``: it interpolates the current
    date, so including it would produce a new hash every single day and make
    the stamp useless for spotting real prompt edits.
    """
    from app import agent_factories as af

    parts = [
        af.TRIAGER_INSTRUCTION,
        af.INTERPRETER_REGISTRATION_INSTRUCTION,
        af.INTERPRETER_DISRUPTION_INSTRUCTION,
        af.INTERPRETER_HITL_INSTRUCTION,
    ]
    return _sha256_short("\x00".join(parts))


def dataset_hash(root: Path, config: Dict[str, Any]) -> str:
    """Hash every dataset file the config points at, plus the fixture bodies.

    Missing files are folded in by name rather than raising: provenance must
    never be the thing that fails an eval run.
    """
    paths: List[Path] = []
    for entry in (config.get("datasets") or {}).values():
        if isinstance(entry, str):
            paths.append(root / entry)
        elif isinstance(entry, dict):
            if entry.get("manifest"):
                paths.append(root / entry["manifest"])
            if entry.get("cases_dir"):
                cases_dir = root / entry["cases_dir"]
                if cases_dir.is_dir():
                    paths.extend(sorted(cases_dir.glob("*.txt")))

    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda p: str(p)):
        digest.update(str(path.name).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()[:12]


def build_provenance(root: Path, config: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {"prompt_hash": prompt_hash(), "dataset_hash": dataset_hash(root, config)}


def explain_change(current: Dict[str, Any], previous: Dict[str, Any]) -> str:
    """One line explaining what a score change between two reports can mean."""
    if not previous:
        return "No previous report to compare against."

    # A baseline written before provenance stamps existed carries neither hash.
    # Reporting that as "prompt changed; dataset changed" is a false alarm on
    # every first comparison, which is exactly how a drift signal gets ignored.
    if not previous.get("prompt_hash") and not previous.get("dataset_hash"):
        return (
            "The stored baseline predates provenance stamping, so a prompt or "
            "dataset change cannot be ruled out for any movement. Regenerate "
            "the baseline (`insummery-eval baseline`) to make future runs "
            "attributable."
        )

    prompt_changed = current.get("prompt_hash") != previous.get("prompt_hash")
    data_changed = current.get("dataset_hash") != previous.get("dataset_hash")
    model_changed = current.get("model") != previous.get("model")

    causes = []
    if model_changed:
        causes.append(f"model changed ({previous.get('model')} -> {current.get('model')})")
    if prompt_changed:
        causes.append("prompt changed")
    if data_changed:
        causes.append("dataset changed (scores are not comparable across this boundary)")
    if not causes:
        return (
            "Prompt, dataset and model are all unchanged: any score movement is "
            "model drift, not a code change."
        )
    return "Score movement may be explained by: " + "; ".join(causes) + "."
