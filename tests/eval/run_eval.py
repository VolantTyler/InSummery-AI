#!/usr/bin/env python3
"""
InSummery Gemini Extraction Evaluation Harness.

Runs the real ADK workflow (Triager + Interpreter LlmAgents, backed by
GEMINI_API_KEY) against the curated test cases in `tests/test_cases/` and
scores the extracted structured output against the ground-truth manifest.

This is the concrete implementation of the evaluation plan described in
`implementation_plan.md` ("Strict Evaluation & Tracing" / "LLM-as-a-Judge"):
it exercises the Triager -> Interpreter -> Confidence Gate pipeline end to
end with live Gemini calls and reports per-case and aggregate accuracy.

Usage:
    python -m tests.eval.run_eval
    python -m tests.eval.run_eval --cases case_01 case_05
    python -m tests.eval.run_eval --json-report output/eval_report.json
    python -m tests.eval.run_eval --allow-local-llm   # don't force Gemini
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_CASES_DIR = Path(__file__).resolve().parent.parent / "test_cases"
MANIFEST_PATH = TEST_CASES_DIR / "test_cases_manifest.json"
PROFILE_PATH = TEST_CASES_DIR / "profile_10_kids.json"

CRITICAL_FIELDS = ["start_date", "end_date", "start_time", "end_time"]
FUZZY_FIELDS = ["child_name", "activity_title"]
CONFIDENCE_THRESHOLD = 80


def load_manifest() -> List[Dict[str, Any]]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_profile() -> Dict[str, Any]:
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def isolated_workdir(profile: Dict[str, Any]):
    """Runs the workflow from a scratch temp directory so eval runs never
    touch the real config/profile.json or data/matrix.json, and so each
    case starts from a clean (empty) schedule matrix."""
    tmp_dir = tempfile.mkdtemp(prefix="insummery_eval_")
    old_cwd = os.getcwd()
    try:
        config_dir = os.path.join(tmp_dir, "config")
        data_dir = os.path.join(tmp_dir, "data")
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(config_dir, "profile.json"), "w", encoding="utf-8") as f:
            json.dump(profile, f)
        os.chdir(tmp_dir)
        yield tmp_dir
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _normalize(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


_WORD_RE = re.compile(r"[a-z0-9]+")


def _token_overlap_ratio(a: str, b: str) -> float:
    """Overlap coefficient between word sets: |A∩B| / min(|A|, |B|).

    More forgiving than Jaccard for titles where one string is a superset of
    the other (e.g. "Brand Camp - Session Name" vs. just "Session Name").
    """
    tokens_a, tokens_b = set(_WORD_RE.findall(a)), set(_WORD_RE.findall(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def _fuzzy_contains(extracted: Optional[str], expected: Optional[str], token_overlap_threshold: float = 0.5) -> bool:
    e, x = _normalize(extracted), _normalize(expected)
    if not e or not x:
        return False
    if e == x or e in x or x in e:
        return True
    return _token_overlap_ratio(e, x) >= token_overlap_threshold


def _extraction_to_dict(extraction: Any) -> Dict[str, Any]:
    if extraction is None:
        return {}
    if hasattr(extraction, "model_dump"):
        return extraction.model_dump()
    if isinstance(extraction, dict):
        return extraction
    return {}


async def run_case(case: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Run a single test case's raw email text through the live ADK/Gemini
    workflow (Triager -> Interpreter -> Confidence Gate) and return the
    raw extraction result alongside routing metadata."""
    # Imported lazily so PROJECT_ROOT is on sys.path (and env overrides like
    # FORCE_CLOUD_LLM are applied) before app.* modules are imported.
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part

    from app.agent import insummery_workflow
    from app.pii_masker import PIIMasker

    case_path = TEST_CASES_DIR / case["filename"]
    email_text = case_path.read_text(encoding="utf-8")

    result: Dict[str, Any] = {"id": case["id"], "filename": case["filename"]}

    with isolated_workdir(profile):
        user_id = "eval_user"
        session_id = f"eval_{case['id']}_{int(datetime.now().timestamp() * 1000)}"

        session_service = InMemorySessionService()
        runner = Runner(
            agent=insummery_workflow,
            app_name="insummery_eval",
            session_service=session_service,
            auto_create_session=True,
        )

        msg = Content(parts=[Part(text=email_text)])
        state_delta = {"mode": "local"}

        started_at = datetime.now()
        try:
            events = list(runner.run(
                user_id=user_id,
                session_id=session_id,
                new_message=msg,
                state_delta=state_delta,
            ))
        except Exception as exc:  # noqa: BLE001 - surface any failure as a result row
            result["status"] = "ERROR"
            result["error"] = str(exc)
            return result
        result["latency_s"] = round((datetime.now() - started_at).total_seconds(), 2)

        for event in events:
            if getattr(event, "error_code", None):
                result["status"] = "ERROR"
                result["error"] = f"[{event.error_code}] {event.error_message}"
                return result

        pending_interrupt = None
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and fc.name == "adk_request_input":
                        pending_interrupt = fc
                        break

        session = await session_service.get_session(
            user_id=user_id, session_id=session_id, app_name="insummery_eval"
        )

        if pending_interrupt:
            result["status"] = "INTERRUPTED"
            result["category"] = session.state.get("category")
            result["message"] = pending_interrupt.args.get("message")
            return result

        category = session.state.get("category")
        extraction = _extraction_to_dict(session.state.get("extraction_result"))
        result["status"] = "COMPLETED"
        result["category"] = category
        result["confidence_score"] = extraction.get("confidence_score")
        result["evaluation_trace"] = extraction.get("evaluation_trace")

        # `extraction_result` is captured before matrix_analyzer_node unmasks
        # it (unmasking normally happens further down the real pipeline), so
        # PII placeholders like "[CHILD_A]" are still present here. Unmask
        # using the same mappings the pipeline itself produced, so scoring
        # compares against the same values a real run would persist.
        pii_mappings = session.state.get("pii_mappings", {})
        masker = PIIMasker(profile)
        masker.mask_to_original = pii_mappings

        activities = extraction.get("activities") or []
        activity = dict(activities[0]) if activities else {}
        for field in ("child_name", "activity_title", "location", "notes"):
            if field in activity:
                activity[field] = masker.unmask(activity[field])
        result["extracted"] = activity
        result["activity_count"] = len(activities)
        return result


def score_case(result: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    """Compares a run_case() result against its manifest ground truth."""
    if result.get("status") != "COMPLETED":
        result["pass"] = False
        result["field_matches"] = {}
        return result

    extracted = result.get("extracted", {})
    field_matches = {}
    for field in CRITICAL_FIELDS:
        field_matches[field] = _normalize(extracted.get(field)) == _normalize(expected.get(field))
    for field in FUZZY_FIELDS:
        field_matches[field] = _fuzzy_contains(extracted.get(field), expected.get(field))

    correct_category = result.get("category") == "registration"
    confidence = result.get("confidence_score") or 0
    confident_enough = confidence >= CONFIDENCE_THRESHOLD

    result["field_matches"] = field_matches
    result["correct_category"] = correct_category
    result["pass"] = (
        correct_category
        and confident_enough
        and all(field_matches[f] for f in CRITICAL_FIELDS)
        and all(field_matches[f] for f in FUZZY_FIELDS)
    )
    return result


async def run_all(case_filter: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    manifest = load_manifest()
    profile = load_profile()
    by_id = {c["id"]: c for c in manifest}

    if case_filter:
        selected = [by_id[c] for c in case_filter if c in by_id]
        missing = [c for c in case_filter if c not in by_id]
        if missing:
            print(f"Warning: unknown case id(s) ignored: {', '.join(missing)}", file=sys.stderr)
    else:
        selected = manifest

    results = []
    for case in selected:
        raw_result = await run_case(case, profile)
        scored = score_case(raw_result, case)
        scored["expected"] = case
        results.append(scored)
    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    completed = [r for r in results if r.get("status") == "COMPLETED"]
    avg_confidence = (
        round(sum(r.get("confidence_score") or 0 for r in completed) / len(completed), 1)
        if completed else 0.0
    )
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": round(passed / total, 4) if total else 0.0,
        "avg_confidence": avg_confidence,
    }


def print_report(results: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    print("\n=== InSummery Gemini Extraction Evaluation ===\n")
    header = f"{'ID':<9}{'STATUS':<13}{'CONF':<6}{'CHILD':<7}{'TITLE':<7}{'DATES':<7}{'TIMES':<7}RESULT"
    print(header)
    print("-" * len(header))
    for r in results:
        status = r.get("status", "?")
        conf = r.get("confidence_score")
        conf_str = f"{conf}%" if conf is not None else "-"
        fm = r.get("field_matches", {})
        child_ok = "OK" if fm.get("child_name") else "--"
        title_ok = "OK" if fm.get("activity_title") else "--"
        dates_ok = "OK" if (fm.get("start_date") and fm.get("end_date")) else "--"
        times_ok = "OK" if (fm.get("start_time") and fm.get("end_time")) else "--"
        outcome = "PASS" if r.get("pass") else ("N/A" if status != "COMPLETED" else "FAIL")
        print(f"{r['id']:<9}{status:<13}{conf_str:<6}{child_ok:<7}{title_ok:<7}{dates_ok:<7}{times_ok:<7}{outcome}")
        if status == "ERROR":
            print(f"          error: {r.get('error')}")
        if status == "INTERRUPTED":
            print(f"          clarification requested: {r.get('message')}")

    print("\n--- Summary ---")
    print(f"Total cases:      {summary['total']}")
    print(f"Passed:           {summary['passed']}")
    print(f"Failed:           {summary['failed']}")
    print(f"Accuracy:         {summary['accuracy'] * 100:.1f}%")
    print(f"Avg. confidence:  {summary['avg_confidence']}%")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate InSummery's Gemini-backed extraction pipeline.")
    parser.add_argument("--cases", nargs="*", help="Specific case IDs to run (e.g. case_01 case_05). Default: all.")
    parser.add_argument("--json-report", type=str, help="Path to write a JSON results report to.")
    parser.add_argument(
        "--allow-local-llm",
        action="store_true",
        help="Do not force cloud Gemini; allow falling back to a local Ollama model if available.",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.8,
        help="Minimum required pass rate (0-1) for a zero exit code. Default: 0.8.",
    )
    args = parser.parse_args()

    if not args.allow_local_llm:
        os.environ["FORCE_CLOUD_LLM"] = "true"

    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        print(
            "Error: GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. "
            "Add it in Cursor Settings > Secrets or export it before running this evaluation.",
            file=sys.stderr,
        )
        return 2

    results = asyncio.run(run_all(args.cases))
    summary = summarize(results)
    print_report(results, summary)

    if args.json_report:
        report_path = Path(args.json_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({"results": results, "summary": summary}, f, indent=2, default=str)
        print(f"JSON report written to: {report_path}")

    return 0 if summary["accuracy"] >= args.min_accuracy else 1


if __name__ == "__main__":
    sys.exit(main())
