"""Grow eval datasets from sanitized HITL clarifications.

Never stores raw clarification text or email bodies — only structural
metadata useful for future registration/HITL suites.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.weave_observability import setup_weave, weave_enabled

logger = logging.getLogger(__name__)

# Default local path (gitignored via data/*.json patterns when present; otherwise
# under a dedicated hitl file). Override with INSUMMERY_HITL_DATASET_PATH.
_DEFAULT_PATH = Path("data/hitl_feedback_cases.json")


def hitl_dataset_path() -> Optional[Path]:
    """Return the local append path, or None when append is disabled.

    Append is on by default for local mode when the path's parent is writable.
    Set ``INSUMMERY_HITL_DATASET_APPEND=false`` to disable. Firebase/production
    can point ``INSUMMERY_HITL_DATASET_PATH`` at a writable volume or leave
    unset and rely on Weave Dataset publish only.
    """
    flag = os.getenv("INSUMMERY_HITL_DATASET_APPEND", "true").lower()
    if flag in {"0", "false", "no", "off"}:
        return None
    raw = os.getenv("INSUMMERY_HITL_DATASET_PATH")
    return Path(raw) if raw else _DEFAULT_PATH


def build_sanitized_hitl_case(
    *,
    workflow_id: str,
    status: str,
    clarification_chars: int,
    category: Optional[str] = None,
    confidence_before: Optional[float] = None,
    confidence_after: Optional[float] = None,
    activity_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a PII-safe HITL case row (no clarification text)."""
    return {
        "id": f"hitl_{workflow_id}",
        "source": "hitl_clarification",
        "workflow_id": workflow_id,
        "status": status,
        "category": category,
        "clarification_chars": clarification_chars,
        "confidence_before": confidence_before,
        "confidence_after": confidence_after,
        "activity_count": activity_count,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def append_hitl_case_local(case: Dict[str, Any]) -> Optional[Path]:
    """Append a sanitized HITL case to the local JSON dataset. Returns path."""
    path = hitl_dataset_path()
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows: List[Dict[str, Any]] = []
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                rows = loaded
        rows.append(case)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        return path
    except Exception as exc:  # noqa: BLE001 - dataset growth is best-effort
        logger.warning("Failed to append HITL eval case locally: %s", exc)
        return None


def publish_hitl_case_to_weave(case: Dict[str, Any]) -> bool:
    """Publish/append the sanitized HITL case to a Weave Dataset."""
    if not weave_enabled():
        return False
    if not setup_weave():
        return False
    try:
        import weave

        # Publish as a single-row dataset version snapshot. Weave Datasets are
        # immutable versions; each HITL event creates a small versioned object
        # that can later be merged into a curated eval suite.
        dataset = weave.Dataset(
            name="insummery-hitl-feedback",
            rows=[case],
        )
        weave.publish(dataset)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to publish HITL case to Weave: %s", exc)
        return False


def record_hitl_eval_case(
    *,
    workflow_id: str,
    status: str,
    clarification_chars: int,
    category: Optional[str] = None,
    confidence_before: Optional[float] = None,
    confidence_after: Optional[float] = None,
    activity_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Sanitize, append locally (optional), and publish to Weave Dataset."""
    case = build_sanitized_hitl_case(
        workflow_id=workflow_id,
        status=status,
        clarification_chars=clarification_chars,
        category=category,
        confidence_before=confidence_before,
        confidence_after=confidence_after,
        activity_count=activity_count,
    )
    local_path = append_hitl_case_local(case)
    weave_ok = publish_hitl_case_to_weave(case)
    return {
        "case": case,
        "local_path": str(local_path) if local_path else None,
        "weave_published": weave_ok,
    }
