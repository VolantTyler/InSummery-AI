"""CLI for the InSummery agent evaluation loop.

Usage:
    insummery-eval run                # run all suites, gate on thresholds + baseline
    insummery-eval run --suites workflow      # end-to-end workflow suite only
    insummery-eval run --json-out report.json
    insummery-eval run --weave-publish        # also mirror report into Weave Evaluations
    insummery-eval run --suites identity       # offline only: no API key needed
    insummery-eval run --judge                # add the non-gating LLM-judge tier
    insummery-eval diagnose           # ranked findings + calibration -> Markdown
    insummery-eval baseline           # run all suites and (re)write the baseline
    insummery-eval weave-monitors     # publish/activate production Weave monitors
"""
import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

from app.telemetry import setup_telemetry

# Load repo-root .env regardless of cwd (same pattern as app/cli.py).
# override=True so a stale empty WANDB_API_KEY in the shell cannot mask .env.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_REPO_ROOT, ".env"), override=True)
setup_telemetry()

from app.evaluation.runner import EvalHarness, SUITES, OFFLINE_SUITES
from app.evaluation.baseline import (
    is_gemini_model,
    save_baseline,
    load_baseline,
    compare_to_baseline,
)
from app.evaluation.diagnose import build_diagnosis, render_markdown
from app.evaluation.judge import judge_cases
from app.evaluation.provenance import explain_change
from app.evaluation.weave_publish import publish_eval_report
from app.weave_monitors import ensure_production_monitors


def _print_report(report: dict) -> None:
    ran = report.get("suites") or []
    offline_only = bool(ran) and set(ran) <= set(OFFLINE_SUITES)
    # Naming a model on a run that never called one is how a suite gets
    # mistaken for a live measurement.
    model_line = (
        "(none — offline suites only)" if offline_only else report["model"]
    )
    print(f"\nModel:     {model_line}")
    print(f"Timestamp: {report['timestamp']}\n")
    if report.get("skipped_suites"):
        print(
            "WARNING: these suites were SKIPPED because the eval config does "
            "not define their dataset: " + ", ".join(report["skipped_suites"])
        )
        print("They contributed no metrics. Add them to eval_config.yaml.\n")
    print(f"{'Metric':<40} {'Score':>8}")
    print("-" * 49)
    for metric, value in report["metrics"].items():
        print(f"{metric:<40} {value:>8.4f}")
    print()

    def _is_failing(case: dict) -> bool:
        if "passed" in case:
            return not case["passed"]
        score = case.get("score")
        return isinstance(score, (int, float)) and score < 1.0

    for section_name, section in report["details"].items():
        # Most suites report a flat "cases" list; the identity suite reports
        # two lists (mask_cases / name_resolution_cases) because its two halves
        # are scored differently.
        case_lists = {
            key: value
            for key, value in section.items()
            if key.endswith("cases") and isinstance(value, list)
        }
        for key, cases in sorted(case_lists.items()):
            failing = [c for c in cases if _is_failing(c)]
            if not failing:
                continue
            label = section_name if key == "cases" else f"{section_name}.{key}"
            print(f"[{label}] cases below a perfect score:")
            for case in failing:
                extra = ""
                if case.get("status") and case["status"] != "COMPLETED":
                    extra = f" ({case['status']}: {case.get('error') or case.get('message')})"
                elif case.get("leaks") or case.get("over_masked") or case.get("glued_placeholders"):
                    bits = []
                    if case.get("leaks"):
                        bits.append(f"leaked {case['leaks']}")
                    if case.get("over_masked"):
                        bits.append(f"over-masked {case['over_masked']}")
                    if case.get("glued_placeholders"):
                        bits.append(f"{len(case['glued_placeholders'])} glued placeholder(s)")
                    extra = " (" + "; ".join(bits) + ")"
                score = case.get("score")
                score_str = f"{score:.4f}" if isinstance(score, (int, float)) else "FAIL"
                print(f"  - {case['id']}: {score_str}{extra}")
            print()


def _run_report(harness: EvalHarness, suites=None) -> dict:
    try:
        return asyncio.run(harness.run_all(suites=suites))
    except Exception as exc:
        exc_str = str(exc)
        if "GEMINI_API_KEY" in exc_str or "GOOGLE_API_KEY" in exc_str:
            print(
                "\nEVAL ABORTED: the active model is Gemini but no API key is set.\n"
                "Set GEMINI_API_KEY (Cloud Agents: add it as a secret in the Cursor "
                "Dashboard) or start a local Ollama instance.",
                file=sys.stderr,
            )
            sys.exit(2)
        elif "vertex_ai" in exc_str.lower() or "aiplatform" in exc_str.lower() or "billing" in exc_str.lower() or "quota" in exc_str.lower():
            print(
                f"\nEVAL ABORTED: Vertex AI API call failed.\n"
                f"Error: {exc}\n"
                f"Please ensure Google Cloud SDK is authenticated, the Vertex AI API (aiplatform.googleapis.com) "
                f"is enabled, billing is enabled, and GOOGLE_CLOUD_PROJECT/VERTEXAI_PROJECT is set properly.",
                file=sys.stderr,
            )
            sys.exit(2)
        raise


def _maybe_publish_weave(report: dict, enabled: bool) -> None:
    if not enabled:
        return
    result = publish_eval_report(report)
    if not result.get("ok"):
        print(
            f"NOTE: Weave publish skipped ({result.get('reason', 'unknown')}). "
            "Set WANDB_API_KEY and WEAVE_DISABLED=false to enable."
        )
        return
    url = result.get("ui_url")
    if url:
        print(f"Weave evaluation published: {url}")
    else:
        print(f"Weave evaluation published: {result.get('name')}")


def _pop_judge_inputs(report: dict) -> list:
    """Remove the bulky judge payloads from the report and return them.

    They carry the full masked email body, which has no business in a saved
    artifact or in Weave. Always called before the report is written.
    """
    hard = (report.get("details") or {}).get("hard") or {}
    return hard.pop("judge_inputs", []) or []


def _maybe_judge(report: dict, enabled: bool, judge_inputs: list) -> None:
    """Attach the LLM-judge block. Never touches report["metrics"].

    Keeping judge results out of "metrics" is what makes the tier structurally
    non-gating: check_thresholds and compare_to_baseline both read only that
    key, so a judge score can never fail a build.
    """
    if not enabled:
        return
    if not judge_inputs:
        print("NOTE: --judge had nothing to grade (the 'hard' suite did not run).")
        return
    from app.evaluation.runner import adk_agent_invoker

    result = asyncio.run(judge_cases(judge_inputs, adk_agent_invoker))
    report["judge"] = result
    print(f"\nLLM judge (report-only, non-gating) — model {result['judge_model']}")
    print(f"  graded {result['graded']}/{result['attempted']} cases")
    for metric, value in result["metrics"].items():
        shown = f"{value:.4f}" if isinstance(value, float) else "n/a"
        print(f"  {metric:<38} {shown:>8}")
    print()


def cmd_run(args: argparse.Namespace) -> int:
    harness = EvalHarness(config_path=args.config)
    suites = args.suites or None
    if suites and set(suites) <= set(OFFLINE_SUITES):
        # No model is contacted, so don't imply one was: printing a model spec
        # here previously suggested a Gemini call that never happens.
        print(f"Running offline eval suites (no model calls): {', '.join(suites)}")
    else:
        print(f"Running InSummery agent evals against model: {harness.model_spec}")
    report = _run_report(harness, suites=suites)
    judge_inputs = _pop_judge_inputs(report)
    _print_report(report)
    _maybe_judge(report, getattr(args, "judge", False), judge_inputs)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Full report written to {args.json_out}")

    _maybe_publish_weave(report, args.weave_publish)

    failures = harness.check_thresholds(report)

    partial_run = suites is not None and set(suites) != set(SUITES)
    if partial_run and not args.no_baseline_check:
        print(
            "NOTE: only a subset of suites ran; skipping the baseline regression "
            "check (baselines cover the full suite set)."
        )
    elif not args.no_baseline_check:
        baseline = load_baseline(harness.config, harness.root, harness.model_spec)
        if baseline is None:
            print(
                f"NOTE: no baseline found for model '{harness.model_spec}'. "
                "Run 'insummery-eval baseline' to create one. Skipping regression check."
            )
        else:
            tolerance = harness.config.get("regression_tolerance", 0.05)
            failures += compare_to_baseline(report, baseline, tolerance)

    if failures:
        print("\nEVAL FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("All eval gates passed.")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    harness = EvalHarness(config_path=args.config)

    if args.from_report:
        # Promote an existing run rather than paying for the whole suite a
        # second time. The thresholds are re-checked below either way, so a
        # saved run cannot become a baseline it never qualified for.
        with open(args.from_report, "r", encoding="utf-8") as f:
            report = json.load(f)
        _pop_judge_inputs(report)
        print(f"Promoting saved report to baseline: {args.from_report}")
        print(f"  model {report.get('model')}, run {report.get('timestamp')}")
        _print_report(report)
        failures = harness.check_thresholds(report)
        if failures and not args.force:
            print("\nRefusing to save a baseline that does not meet the absolute "
                  "thresholds (use --force to override):")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        path = save_baseline(report, harness.config, harness.root)
        print(f"Baseline saved to {path}")
        return 0

    print(f"Generating eval baseline against model: {harness.model_spec}")

    if not is_gemini_model(harness.model_spec):
        print(
            "NOTE: the active model is a local Ollama model. This baseline will be "
            "written to the gitignored local baselines directory. The committed "
            "reference baseline must be generated against Gemini "
            "(set FORCE_CLOUD_LLM=true with a GEMINI_API_KEY)."
        )

    report = _run_report(harness)
    _pop_judge_inputs(report)
    _print_report(report)
    _maybe_publish_weave(report, args.weave_publish)

    failures = harness.check_thresholds(report)
    if failures and not args.force:
        print("\nRefusing to save a baseline that does not meet the absolute thresholds")
        print("(use --force to override):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    path = save_baseline(report, harness.config, harness.root)
    print(f"Baseline saved to {path}")
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    """Run the suites and emit a ranked diagnosis instead of a pass/fail gate.

    `run` answers "did anything regress". `diagnose` answers "which capability
    is costing the score, and is the model's confidence worth trusting" -- the
    question you actually have when the numbers are merely mediocre. It never
    gates, so it always exits 0 unless the run itself failed.
    """
    harness = EvalHarness(config_path=args.config)
    suites = args.suites or None

    if args.from_report:
        # Diagnosis is a pure function over a finished report, so re-deriving
        # it from a saved run costs nothing. Without this, asking a second
        # question about the same numbers means paying for the whole suite
        # again.
        with open(args.from_report, "r", encoding="utf-8") as f:
            report = json.load(f)
        print(f"Diagnosing saved report: {args.from_report}")
        print(f"  model {report.get('model')}, run {report.get('timestamp')}")
        if args.judge:
            print(
                "NOTE: --judge needs live model output and cannot run against a "
                "saved report; skipping the judge tier."
            )
        judge_inputs = []
    else:
        print(f"Diagnosing InSummery agents against model: {harness.model_spec}")
        report = _run_report(harness, suites=suites)
        judge_inputs = _pop_judge_inputs(report)
        _maybe_judge(report, args.judge, judge_inputs)

    diagnosis = build_diagnosis(report)
    if report.get("judge"):
        diagnosis["judge"] = report["judge"]

    baseline = load_baseline(harness.config, harness.root, harness.model_spec)
    if baseline:
        print(f"\n{explain_change(report, baseline)}")

    markdown = render_markdown(diagnosis)
    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"\nDiagnosis written to {out_path}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"report": report, "diagnosis": diagnosis}, f, indent=2)
        print(f"Full report + diagnosis written to {args.json_out}")

    findings = diagnosis["ranked_findings"][:5]
    if findings:
        print("\nTop findings by score lost:")
        for i, f in enumerate(findings, 1):
            print(f"  {i}. [{f['suite']}] {f['field']}: mean {f['mean']:.3f} "
                  f"over {f['n']} activities ({f['points_lost']:.2f} points lost)")
    return 0


def cmd_weave_monitors(args: argparse.Namespace) -> int:
    """Publish/activate Weave Monitors for production soft-failure signals."""
    result = ensure_production_monitors(
        activate=not args.deactivate,
        dry_run=args.dry_run,
    )
    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        print(f"Weave monitors failed ({reason}).")
        if result.get("error"):
            print(f"  error: {result['error']}")
        if result.get("hint"):
            print(f"  hint: {result['hint']}")
        elif reason == "weave_disabled":
            print(
                "  Set WANDB_API_KEY and WEAVE_DISABLED=false in the repo-root .env "
                "(and re-run from any directory — .env is loaded by absolute path)."
            )
        return 2

    mode = "dry-run" if result.get("dry_run") else (
        "activated" if result.get("activate") else "published"
    )
    print(f"Weave monitors ({mode}):")
    for name in result.get("monitors") or []:
        print(f"  - {name}")
    print(
        "\nNote: Weave Monitors score LLM/workflow soft failures. "
        "Use GCP Cloud Monitoring for HTTP 5xx / function uptime."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="insummery-eval",
        description="Evaluation loop for the InSummery triager and interpreter agents.",
    )
    parser.add_argument(
        "--config", default="tests/eval/eval_config.yaml", help="Path to eval config YAML"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run evals and gate on thresholds + baseline")
    run_p.add_argument("--json-out", help="Write the full JSON report to this path")
    run_p.add_argument(
        "--suites",
        nargs="+",
        choices=SUITES,
        help=(
            "Only run the given suites (default: all). "
            "'workflow' runs the full end-to-end ADK graph on the registration cases; "
            "the others evaluate each agent in isolation."
        ),
    )
    run_p.add_argument(
        "--no-baseline-check",
        action="store_true",
        help="Skip the regression comparison against the stored baseline",
    )
    run_p.add_argument(
        "--weave-publish",
        action="store_true",
        help="Mirror the finished report into a Weave Evaluation (requires WANDB_API_KEY)",
    )
    run_p.add_argument(
        "--judge",
        action="store_true",
        help=(
            "Also run the LLM-judge tier over the 'hard' suite. Reported only: "
            "judge scores never enter report['metrics'], so they can never fail "
            "a threshold or a baseline comparison."
        ),
    )
    run_p.set_defaults(func=cmd_run)

    base_p = sub.add_parser("baseline", help="Run evals and save the result as the baseline")
    base_p.add_argument(
        "--force",
        action="store_true",
        help="Save the baseline even if absolute thresholds are not met",
    )
    base_p.add_argument(
        "--weave-publish",
        action="store_true",
        help="Also mirror the baseline report into a Weave Evaluation",
    )
    base_p.add_argument(
        "--from-report",
        help=(
            "Promote a saved JSON report (from `run --json-out`) to the "
            "baseline instead of re-running every suite. Thresholds are still "
            "enforced. Free — no model calls."
        ),
    )
    base_p.set_defaults(func=cmd_baseline)

    diag_p = sub.add_parser(
        "diagnose",
        help="Run evals and write a ranked findings + calibration report (never gates)",
    )
    diag_p.add_argument(
        "--suites", nargs="+", choices=SUITES,
        help="Only diagnose the given suites (default: all)",
    )
    diag_p.add_argument(
        "--out", default="output/diagnosis.md",
        help="Path for the Markdown diagnosis (default: output/diagnosis.md)",
    )
    diag_p.add_argument("--json-out", help="Also write report + diagnosis as JSON")
    diag_p.add_argument(
        "--from-report",
        help=(
            "Diagnose a saved JSON report (from `run --json-out`) instead of "
            "running the suites again. Free — no model calls."
        ),
    )
    diag_p.add_argument(
        "--judge", action="store_true",
        help="Include the non-gating LLM-judge tier in the diagnosis",
    )
    diag_p.set_defaults(func=cmd_diagnose)

    mon_p = sub.add_parser(
        "weave-monitors",
        help="Publish/activate Weave Monitors for production soft-failure scoring",
    )
    mon_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print monitor names without publishing or activating",
    )
    mon_p.add_argument(
        "--deactivate",
        action="store_true",
        help="Publish monitor definitions without activating them",
    )
    mon_p.set_defaults(func=cmd_weave_monitors)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
