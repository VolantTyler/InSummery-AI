"""Evaluation runner for the InSummery agents.

Two kinds of suites live here:

- **Per-agent suites** (triager, registration interpreter, disruption
  interpreter) build each agent in isolation from the shared factories and
  mirror the production data path: inputs are PII-masked with the family
  profile before reaching the model, and extracted fields are unmasked before
  being scored against ground truth, so the mask/unmask round-trip is part of
  what gets evaluated.
- **The end-to-end workflow suite** runs the full production ADK workflow
  (PII mask → triager → interpreter → confidence gate), so the graph wiring
  itself is exercised, not just the agents.

Model/workflow invocations are injected (``agent_invoker`` /
``workflow_invoker``) so unit tests can run the full harness offline against
canned responses.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import yaml

from app.agent_factories import (
    build_triager_agent,
    build_interpreter_registration_agent,
    build_interpreter_disruption_agent,
)
from app.pii_masker import PIIMasker
from app.schemas import InterpretationResult, DisruptionDetail
from app.evaluation.scoring import (
    score_triager_case,
    score_registration_activity,
    score_disruption,
    pick_best_activity,
    score_activity_set,
    aggregate,
)
from app.evaluation.hard_manifest import load_cases as load_hard_cases
from app.evaluation.provenance import build_provenance
from app.evaluation.identity_scoring import (
    aggregate_mask_results,
    aggregate_name_resolution,
    score_mask_case,
    score_name_resolution_case,
)
from app.matrix_logic import resolve_child_name
from app.weave_observability import trace_eval_case
from app.evaluation.workflow import WorkflowInvoker, adk_workflow_invoker

AgentInvoker = Callable[[Any, str], Awaitable[str]]

CONFIDENCE_GATE = 80  # must match confidence_gate_node in app/nodes.py

# Exact-match fields that must all be correct for a workflow case to pass.
WORKFLOW_CRITICAL_FIELDS = ("child_name", "start_date", "end_date", "start_time", "end_time")

SUITES = ("identity", "triager", "registration", "disruption", "workflow", "hard")

# Axes probed by the "hard" suite (tests/test_cases/hard/hard_manifest.json).
HARD_AXES = ("identity", "multi", "temporal")

# The config key each suite needs. A suite whose key is absent is skipped
# rather than crashing, so a config that predates a suite still runs -- but
# the skip is recorded in the report and printed, never silent. A nightly eval
# that quietly measures nothing is worse than one that fails, because it looks
# like passing.
SUITE_DATASET_KEYS = {
    "identity": "identity",
    "triager": "triager",
    "registration": "interpreter_registration",
    "disruption": "interpreter_disruption",
    "workflow": "workflow_registration",
    "hard": "hard_registration",
}

# Suites that make no model calls. These are safe (and free) to run on every
# pull request with no API credential configured.
OFFLINE_SUITES = ("identity",)


async def adk_agent_invoker(agent: Any, text: str) -> str:
    """Run a single-turn ADK agent and return its final text response."""
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="insummery_eval",
        session_service=session_service,
        auto_create_session=True,
    )
    msg = Content(parts=[Part(text=text)])
    session_id = f"eval_{uuid.uuid4().hex[:12]}"

    final_text = ""
    for event in runner.run(user_id="eval_user", session_id=session_id, new_message=msg):
        if event.error_code:
            raise RuntimeError(f"Agent run failed: [{event.error_code}] {event.error_message}")
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text = part.text
    return final_text


def extract_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object out of a model response, tolerating code fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))
    raise ValueError(f"No JSON object found in model response: {text[:200]!r}")


class EvalHarness:
    def __init__(
        self,
        config_path: str = "tests/eval/eval_config.yaml",
        agent_invoker: Optional[AgentInvoker] = None,
        workflow_invoker: Optional[WorkflowInvoker] = None,
        model_spec: Optional[str] = None,
    ):
        self.config_path = Path(config_path)
        self.root = self.config_path.parent.parent.parent  # repo root
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.agent_invoker = agent_invoker or adk_agent_invoker
        self.workflow_invoker = workflow_invoker or adk_workflow_invoker

        if model_spec is None:
            from app.model_client import resolve_model_spec
            model_spec = resolve_model_spec()
        self.model_spec = model_spec

        with open(self.root / self.config["profile"], "r", encoding="utf-8") as f:
            self.profile = json.load(f)

    def _load_json(self, rel_path: str) -> Any:
        with open(self.root / rel_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _read_case_text(self, case: Dict[str, Any]) -> str:
        if "text" in case:
            return case["text"]
        with open(self.root / case["file"], "r", encoding="utf-8") as f:
            return f.read()

    # ------------------------------------------------------------------
    # Identity (offline: no model calls)
    # ------------------------------------------------------------------
    def _resolve_case_profile(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """A case's profile is either a repo-relative path or an inline object.

        Inline profiles let a case exercise a profile *shape* the shared
        fixture does not have -- a stored surname, a formal given name -- which
        is exactly where the masker's assumptions break.
        """
        profile = case.get("profile")
        if isinstance(profile, dict):
            return profile
        if isinstance(profile, str):
            return self._load_json(profile)
        return self.profile

    async def eval_identity(self) -> Dict[str, Any]:
        """Score PIIMasker and resolve_child_name against span expectations.

        Runs entirely offline. A masking defect corrupts the text every other
        suite's score is computed from, so this suite is the first thing to
        read when the live numbers look mediocre for no obvious reason.
        """
        dataset = self._load_json(self.config["datasets"]["identity"])

        mask_results = []
        for case in dataset.get("mask_cases", []):
            masker = PIIMasker(self._resolve_case_profile(case))
            scored = score_mask_case(masker, case)
            # masked_text can contain real names from inline profiles; keep it
            # out of the persisted report and out of Weave.
            scored.pop("masked_text", None)
            trace_eval_case(
                "identity_mask",
                case["id"],
                1.0 if scored["passed"] else 0.0,
                {
                    "family": case.get("family"),
                    "leak_count": len(scored["leaks"]),
                    "over_mask_count": len(scored["over_masked"]),
                    "glued_count": len(scored["glued_placeholders"]),
                },
            )
            mask_results.append(scored)

        name_results = []
        for case in dataset.get("name_resolution_cases", []):
            children = self._resolve_case_profile(case).get("children", [])
            scored = score_name_resolution_case(resolve_child_name, case, children)
            trace_eval_case(
                "identity_name_resolution",
                case["id"],
                1.0 if scored["passed"] else 0.0,
                {"family": case.get("family"), "method": scored["method"]},
            )
            name_results.append(scored)

        metrics = aggregate_mask_results(mask_results)
        metrics.update(aggregate_name_resolution(name_results))
        return {
            "metrics": metrics,
            "mask_cases": mask_results,
            "name_resolution_cases": name_results,
        }

    # ------------------------------------------------------------------
    # Triager
    # ------------------------------------------------------------------
    async def eval_triager(self) -> Dict[str, Any]:
        cases = self._load_json(self.config["datasets"]["triager"])
        agent = build_triager_agent()
        results = []
        for case in cases:
            raw_text = self._read_case_text(case)
            masked = PIIMasker(self.profile).mask(raw_text)
            response = await self.agent_invoker(agent, masked)
            predicted = response.strip().lower().strip(".'\"")
            if predicted not in ("registration", "disruption", "general"):
                predicted = "general"
            score = score_triager_case(case["expected_category"], predicted)
            result = {
                "id": case["id"],
                "expected": case["expected_category"],
                "predicted": predicted,
                "score": score,
            }
            trace_eval_case(
                "triager",
                case["id"],
                score,
                {"expected": case["expected_category"], "predicted": predicted},
            )
            results.append(result)
        return {
            "accuracy": aggregate([r["score"] for r in results]),
            "cases": results,
        }

    # ------------------------------------------------------------------
    # Interpreter: registrations
    # ------------------------------------------------------------------
    async def eval_interpreter_registration(self) -> Dict[str, Any]:
        ds_cfg = self.config["datasets"]["interpreter_registration"]
        manifest = self._load_json(ds_cfg["manifest"])
        cases_dir = self.root / ds_cfg["cases_dir"]
        agent = build_interpreter_registration_agent()

        results = []
        for expected in manifest:
            with open(cases_dir / expected["filename"], "r", encoding="utf-8") as f:
                raw_text = f.read()

            masker = PIIMasker(self.profile)
            masked = masker.mask(raw_text)
            response = await self.agent_invoker(agent, masked)
            parsed = InterpretationResult.model_validate(extract_json(response))

            activities = []
            for act in parsed.activities:
                act_dict = act.model_dump()
                for field in ("child_name", "activity_title", "location", "notes"):
                    act_dict[field] = masker.unmask(act_dict.get(field) or "")
                activities.append(act_dict)

            best = pick_best_activity(expected, activities)
            if best is None:
                scored = {"field_scores": {}, "score": 0.0}
            else:
                scored = score_registration_activity(expected, best)

            result = {
                "id": expected["id"],
                "score": scored["score"],
                "field_scores": scored["field_scores"],
                "confidence_score": parsed.confidence_score,
                "passes_confidence_gate": parsed.confidence_score >= CONFIDENCE_GATE,
                "extracted_activities": len(activities),
            }
            trace_eval_case(
                "registration",
                expected["id"],
                scored["score"],
                {
                    "confidence_score": parsed.confidence_score,
                    "passes_confidence_gate": parsed.confidence_score >= CONFIDENCE_GATE,
                    "extracted_activities": len(activities),
                },
            )
            results.append(result)

        return {
            "field_score": aggregate([r["score"] for r in results]),
            "confidence_gate_rate": aggregate(
                [1.0 if r["passes_confidence_gate"] else 0.0 for r in results]
            ),
            "cases": results,
        }

    # ------------------------------------------------------------------
    # Interpreter: disruptions
    # ------------------------------------------------------------------
    async def eval_interpreter_disruption(self) -> Dict[str, Any]:
        cases = self._load_json(self.config["datasets"]["interpreter_disruption"])
        agent = build_interpreter_disruption_agent()
        results = []
        for case in cases:
            masker = PIIMasker(self.profile)
            masked = masker.mask(case["text"])
            response = await self.agent_invoker(agent, masked)
            parsed = DisruptionDetail.model_validate(extract_json(response))

            predicted = parsed.model_dump()
            predicted["child_name"] = masker.unmask(predicted.get("child_name") or "")
            predicted["description"] = masker.unmask(predicted.get("description") or "")

            scored = score_disruption(case["expected"], predicted)
            result = {
                "id": case["id"],
                "score": scored["score"],
                "field_scores": scored["field_scores"],
            }
            trace_eval_case("disruption", case["id"], scored["score"])
            results.append(result)
        return {
            "field_score": aggregate([r["score"] for r in results]),
            "cases": results,
        }

    # ------------------------------------------------------------------
    # Hard suite: identity / multi-activity / temporal stress cases
    # ------------------------------------------------------------------
    async def eval_hard_registration(
        self, axes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Score the interpreter on cases built to have headroom.

        Two differences from ``eval_interpreter_registration``:

        1. Ground truth is a *list* of activities scored as a set
           (``score_activity_set``), so a missed sibling and an invented
           activity both cost score. The existing suite's
           ``pick_best_activity`` cannot express either.
        2. Every case declares an ``axis``, and metrics are reported per axis
           as well as overall, so a drop points at a capability rather than at
           a single number.
        """
        ds_cfg = self.config["datasets"]["hard_registration"]
        manifest = self._load_json(ds_cfg["manifest"])
        cases_dir = self.root / ds_cfg["cases_dir"]
        cases = load_hard_cases(manifest, axes=axes)
        agent = build_interpreter_registration_agent()

        results = []
        judge_inputs: List[Dict[str, Any]] = []
        for case in cases:
            with open(cases_dir / case["filename"], "r", encoding="utf-8") as f:
                raw_text = f.read()

            masker = PIIMasker(self.profile)
            masked = masker.mask(raw_text)
            response = await self.agent_invoker(agent, masked)
            parsed = InterpretationResult.model_validate(extract_json(response))

            predicted = []
            for act in parsed.activities:
                act_dict = act.model_dump()
                for field in ("child_name", "activity_title", "location", "notes"):
                    act_dict[field] = masker.unmask(act_dict.get(field) or "")
                predicted.append(act_dict)

            scored = score_activity_set(case["expected_activities"], predicted)
            row = {
                "id": case["id"],
                "axis": case["axis"],
                "intent": case.get("intent"),
                "score": scored["score"],
                "activity_f1": scored["activity_f1"],
                "activity_precision": scored["activity_precision"],
                "activity_recall": scored["activity_recall"],
                "matched_field_score": scored["matched_field_score"],
                "expected_count": scored["expected_count"],
                "predicted_count": scored["predicted_count"],
                "missed_expected": scored["missed_expected"],
                "spurious_predicted": scored["spurious_predicted"],
                "confidence_score": parsed.confidence_score,
                "passes_confidence_gate": parsed.confidence_score >= CONFIDENCE_GATE,
                "evaluation_trace": parsed.evaluation_trace,
                # Per-field scores of the matched pairs, so `diagnose` can rank
                # which field is actually costing the most across the suite.
                "field_scores": [
                    score_registration_activity(
                        case["expected_activities"][p["expected_index"]],
                        predicted[p["predicted_index"]],
                    )["field_scores"]
                    for p in scored["pairs"]
                ],
            }
            judge_inputs.append(
                {
                    "id": case["id"],
                    "masked_email": masked,
                    "confidence_score": parsed.confidence_score,
                    "evaluation_trace": parsed.evaluation_trace,
                    "extracted_notes": [a.get("notes") or "" for a in predicted],
                }
            )
            trace_eval_case(
                "hard",
                case["id"],
                scored["score"],
                {
                    "axis": case["axis"],
                    "activity_f1": scored["activity_f1"],
                    "expected_count": scored["expected_count"],
                    "predicted_count": scored["predicted_count"],
                    "confidence_score": parsed.confidence_score,
                },
            )
            results.append(row)

        by_axis = {}
        for axis in HARD_AXES:
            rows = [r for r in results if r["axis"] == axis]
            if rows:
                by_axis[axis] = aggregate([r["score"] for r in rows])

        return {
            "score": aggregate([r["score"] for r in results]),
            "activity_f1": aggregate([r["activity_f1"] for r in results]),
            "confidence_gate_rate": aggregate(
                [1.0 if r["passes_confidence_gate"] else 0.0 for r in results]
            ),
            "by_axis": by_axis,
            "cases": results,
            # Consumed by the --judge tier and stripped before the report is
            # written: masked_email is bulky and belongs in no artifact.
            "judge_inputs": judge_inputs,
        }

    # ------------------------------------------------------------------
    # End-to-end workflow (full ADK graph, registration cases)
    # ------------------------------------------------------------------
    async def eval_workflow_registration(
        self, case_filter: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Run raw registration emails through the complete production
        workflow and score the persisted extraction against ground truth.

        A case passes when the workflow completed without interruption, the
        triager routed it to "registration", the self-reported confidence
        cleared the production HITL gate, every critical field matched
        exactly, and the activity title cleared the fuzzy-match gate.
        """
        ds_cfg = self.config["datasets"]["workflow_registration"]
        manifest = self._load_json(ds_cfg["manifest"])
        cases_dir = self.root / ds_cfg["cases_dir"]

        if case_filter:
            manifest = [c for c in manifest if c["id"] in set(case_filter)]

        results = []
        for expected in manifest:
            with open(cases_dir / expected["filename"], "r", encoding="utf-8") as f:
                email_text = f.read()

            outcome = await self.workflow_invoker(email_text, self.profile)
            row: Dict[str, Any] = {"id": expected["id"], "status": outcome["status"]}

            if outcome["status"] != "COMPLETED":
                row.update({
                    "passed": False,
                    "score": 0.0,
                    "field_scores": {},
                    "error": outcome.get("error"),
                    "message": outcome.get("message"),
                })
                trace_eval_case(
                    "workflow",
                    expected["id"],
                    0.0,
                    {"status": outcome["status"], "passed": False},
                )
                results.append(row)
                continue

            best = pick_best_activity(expected, outcome.get("activities") or [])
            scored = (
                score_registration_activity(expected, best)
                if best is not None
                else {"field_scores": {}, "score": 0.0}
            )

            confidence = outcome.get("confidence_score") or 0
            correct_category = outcome.get("category") == "registration"
            field_scores = scored["field_scores"]
            passed = (
                correct_category
                and confidence >= CONFIDENCE_GATE
                and all(field_scores.get(f) == 1.0 for f in WORKFLOW_CRITICAL_FIELDS)
                and field_scores.get("activity_title", 0.0) > 0.0
            )

            row.update({
                "passed": passed,
                "score": scored["score"],
                "field_scores": field_scores,
                "category": outcome.get("category"),
                "confidence_score": confidence,
                "extracted_activities": len(outcome.get("activities") or []),
            })
            trace_eval_case(
                "workflow",
                expected["id"],
                scored["score"],
                {
                    "status": outcome["status"],
                    "passed": passed,
                    "category": outcome.get("category"),
                    "confidence_score": confidence,
                    "extracted_activities": len(outcome.get("activities") or []),
                },
            )
            results.append(row)

        return {
            "pass_rate": aggregate([1.0 if r["passed"] else 0.0 for r in results]),
            "field_score": aggregate([r["score"] for r in results]),
            "cases": results,
        }

    # ------------------------------------------------------------------
    async def run_all(self, suites: Optional[List[str]] = None) -> Dict[str, Any]:
        selected = list(suites) if suites else list(SUITES)
        unknown = [s for s in selected if s not in SUITES]
        if unknown:
            raise ValueError(f"Unknown eval suite(s): {unknown}. Valid suites: {list(SUITES)}")

        configured = self.config.get("datasets") or {}
        skipped = [
            suite
            for suite in selected
            if SUITE_DATASET_KEYS.get(suite) not in configured
        ]
        selected = [s for s in selected if s not in skipped]

        metrics: Dict[str, float] = {}
        details: Dict[str, Any] = {}

        if "identity" in selected:
            identity = await self.eval_identity()
            metrics.update(identity["metrics"])
            details["identity"] = identity

        if "triager" in selected:
            triager = await self.eval_triager()
            metrics["triager_accuracy"] = triager["accuracy"]
            details["triager"] = triager

        if "registration" in selected:
            registration = await self.eval_interpreter_registration()
            metrics["registration_field_score"] = registration["field_score"]
            metrics["registration_confidence_gate_rate"] = registration["confidence_gate_rate"]
            details["interpreter_registration"] = registration

        if "disruption" in selected:
            disruption = await self.eval_interpreter_disruption()
            metrics["disruption_field_score"] = disruption["field_score"]
            details["interpreter_disruption"] = disruption

        if "workflow" in selected:
            workflow = await self.eval_workflow_registration()
            metrics["workflow_pass_rate"] = workflow["pass_rate"]
            metrics["workflow_field_score"] = workflow["field_score"]
            details["workflow_registration"] = workflow

        if "hard" in selected:
            hard = await self.eval_hard_registration()
            metrics["hard_score"] = hard["score"]
            metrics["hard_activity_f1"] = hard["activity_f1"]
            metrics["hard_confidence_gate_rate"] = hard["confidence_gate_rate"]
            for axis, value in hard["by_axis"].items():
                metrics[f"hard_{axis}_score"] = value
            details["hard"] = hard

        report = {
            "model": self.model_spec,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "suites": selected,
            "skipped_suites": skipped,
            "metrics": metrics,
            "details": details,
        }
        # Stamp what produced these numbers, so a future score change can be
        # attributed to a prompt edit, a fixture edit, or genuine model drift.
        report.update(build_provenance(self.root, self.config))
        return report

    def check_thresholds(self, report: Dict[str, Any]) -> List[str]:
        """Return failure messages for metrics below their absolute thresholds."""
        failures = []
        thresholds = self.config.get("thresholds", {})
        for metric, minimum in thresholds.items():
            actual = report["metrics"].get(metric)
            if actual is None:
                continue
            if actual < minimum:
                failures.append(
                    f"{metric}: {actual:.4f} is below the required threshold {minimum:.4f}"
                )
        return failures
