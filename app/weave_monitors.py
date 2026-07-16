"""Production Weave Monitors for soft-failure and quality drift.

Weave Monitors passively score live ops (they are not HTTP uptime checks).
Pair these with GCP Cloud Monitoring / Firebase metrics for 5xx and timeouts.

Usage:
    insummery-eval weave-monitors          # publish + activate (requires Weave)
    insummery-eval weave-monitors --dry-run
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.weave_observability import setup_weave, weave_enabled


# Op names emitted by app.weave_observability — keep in sync.
WORKFLOW_RUN_OP = "insummery.workflow.run"
GUARDRAIL_OP = "insummery.workflow.guardrail"
CONFIDENCE_GATE_OP = "insummery.workflow.confidence_gate"


def _build_scorers():
    """Create Weave Scorer subclasses for production soft-failure signals."""
    import weave

    class WorkflowHealthScorer(weave.Scorer):
        """Score end-of-run workflow summaries for soft failures."""

        @weave.op
        def score(self, output: dict) -> dict:  # type: ignore[override]
            if not isinstance(output, dict):
                return {"healthy": False, "reason": "non_dict_output"}
            status = output.get("status")
            warning_count = int(output.get("warning_count") or 0)
            error_code = output.get("error_code")
            healthy = (
                status == "COMPLETED"
                and warning_count == 0
                and not error_code
            )
            return {
                "healthy": healthy,
                "is_completed": status == "COMPLETED",
                "is_interrupted": status == "INTERRUPTED",
                "is_error": status == "ERROR" or bool(error_code),
                "has_warnings": warning_count > 0,
                "disruption_unmatched": output.get("disruption_matched") is False,
                "guardrail_failed": output.get("guardrail_passed") is False,
            }

    class GuardrailPassScorer(weave.Scorer):
        """Score guardrail ops — expect passed=True."""

        @weave.op
        def score(self, output: dict) -> dict:  # type: ignore[override]
            if not isinstance(output, dict):
                return {"passed": False}
            return {
                "passed": bool(output.get("passed")),
                "violation_count": len(output.get("violations") or []),
            }

    class ConfidenceGateScorer(weave.Scorer):
        """Track HITL interrupt rate from confidence-gate routes."""

        @weave.op
        def score(self, output: dict) -> dict:  # type: ignore[override]
            if not isinstance(output, dict):
                return {"route_high": False}
            route = output.get("route")
            return {
                "route_high": route == "CONFIDENCE_HIGH",
                "route_low": route == "CONFIDENCE_LOW",
                "confidence_score": output.get("confidence_score"),
            }

    return WorkflowHealthScorer(), GuardrailPassScorer(), ConfidenceGateScorer()


def build_monitors() -> List[Any]:
    """Construct (inactive) Monitor objects for InSummery production ops."""
    import weave

    health, guardrail, confidence = _build_scorers()
    return [
        weave.Monitor(
            name="insummery-workflow-health",
            description=(
                "Soft-failure monitor on workflow.run: ERROR/INTERRUPTED, "
                "warnings, unmatched disruptions, guardrail failures."
            ),
            sampling_rate=1.0,
            op_names=[WORKFLOW_RUN_OP],
            scorers=[health],
            active=False,
        ),
        weave.Monitor(
            name="insummery-guardrail-pass",
            description="Tracks interpreter guardrail pass rate on production traffic.",
            sampling_rate=1.0,
            op_names=[GUARDRAIL_OP],
            scorers=[guardrail],
            active=False,
        ),
        weave.Monitor(
            name="insummery-confidence-gate",
            description="Tracks confidence-gate HIGH vs LOW (HITL) route rates.",
            sampling_rate=1.0,
            op_names=[CONFIDENCE_GATE_OP],
            scorers=[confidence],
            active=False,
        ),
    ]


def ensure_production_monitors(*, activate: bool = True, dry_run: bool = False) -> Dict[str, Any]:
    """Publish (and optionally activate) production monitors.

    Returns a summary dict. No-ops when Weave is disabled.
    ``dry_run`` only constructs monitor definitions locally (no ``weave.init``).
    """
    if not weave_enabled():
        return {
            "ok": False,
            "reason": "weave_disabled",
            "monitors": [],
        }

    # Dry-run builds Monitor objects without contacting W&B.
    if dry_run:
        monitors = build_monitors()
        return {
            "ok": True,
            "dry_run": True,
            "activate": activate,
            "monitors": [m.name for m in monitors],
        }

    setup_weave()
    monitors = build_monitors()
    names = [m.name for m in monitors]

    activated: List[str] = []
    for monitor in monitors:
        if activate:
            # activate() publishes the monitor definition to the Weave project.
            monitor.activate()
            activated.append(monitor.name)
        else:
            import weave

            weave.publish(monitor)

    return {
        "ok": True,
        "dry_run": False,
        "activate": activate,
        "monitors": activated or names,
    }
