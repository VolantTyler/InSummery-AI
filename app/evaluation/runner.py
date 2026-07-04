"""Evaluation runner for the triager and interpreter agents.

Mirrors the production data path: inputs are PII-masked with the family
profile before reaching the model, and extracted fields are unmasked before
being scored against ground truth, so the mask/unmask round-trip is part of
what gets evaluated.

The model invocation is injected (``agent_invoker``) so unit tests can run
the full harness offline against canned responses.
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
    aggregate,
)

AgentInvoker = Callable[[Any, str], Awaitable[str]]

CONFIDENCE_GATE = 80  # must match confidence_gate_node in app/nodes.py


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
        model_spec: Optional[str] = None,
    ):
        self.config_path = Path(config_path)
        self.root = self.config_path.parent.parent.parent  # repo root
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.agent_invoker = agent_invoker or adk_agent_invoker

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
            results.append({
                "id": case["id"],
                "expected": case["expected_category"],
                "predicted": predicted,
                "score": score,
            })
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

            results.append({
                "id": expected["id"],
                "score": scored["score"],
                "field_scores": scored["field_scores"],
                "confidence_score": parsed.confidence_score,
                "passes_confidence_gate": parsed.confidence_score >= CONFIDENCE_GATE,
                "extracted_activities": len(activities),
            })

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
            results.append({
                "id": case["id"],
                "score": scored["score"],
                "field_scores": scored["field_scores"],
            })
        return {
            "field_score": aggregate([r["score"] for r in results]),
            "cases": results,
        }

    # ------------------------------------------------------------------
    async def run_all(self) -> Dict[str, Any]:
        triager = await self.eval_triager()
        registration = await self.eval_interpreter_registration()
        disruption = await self.eval_interpreter_disruption()

        return {
            "model": self.model_spec,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "metrics": {
                "triager_accuracy": triager["accuracy"],
                "registration_field_score": registration["field_score"],
                "registration_confidence_gate_rate": registration["confidence_gate_rate"],
                "disruption_field_score": disruption["field_score"],
            },
            "details": {
                "triager": triager,
                "interpreter_registration": registration,
                "interpreter_disruption": disruption,
            },
        }

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
