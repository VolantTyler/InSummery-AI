"""CLI for the InSummery agent evaluation loop.

Usage:
    insummery-eval run                # run all suites, gate on thresholds + baseline
    insummery-eval run --suites workflow      # end-to-end workflow suite only
    insummery-eval run --json-out report.json
    insummery-eval baseline           # run all suites and (re)write the baseline
"""
import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv

from app.telemetry import setup_telemetry

load_dotenv()
setup_telemetry()

from app.evaluation.runner import EvalHarness, SUITES
from app.evaluation.baseline import (
    is_gemini_model,
    save_baseline,
    load_baseline,
    compare_to_baseline,
)


def _print_report(report: dict) -> None:
    print(f"\nModel:     {report['model']}")
    print(f"Timestamp: {report['timestamp']}\n")
    print(f"{'Metric':<40} {'Score':>8}")
    print("-" * 49)
    for metric, value in report["metrics"].items():
        print(f"{metric:<40} {value:>8.4f}")
    print()

    def _is_failing(case: dict) -> bool:
        if "passed" in case:
            return not case["passed"]
        return case["score"] < 1.0

    for section_name, section in report["details"].items():
        failing = [c for c in section["cases"] if _is_failing(c)]
        if failing:
            print(f"[{section_name}] cases below a perfect score:")
            for case in failing:
                extra = ""
                if case.get("status") and case["status"] != "COMPLETED":
                    extra = f" ({case['status']}: {case.get('error') or case.get('message')})"
                print(f"  - {case['id']}: {case['score']:.4f}{extra}")
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


def cmd_run(args: argparse.Namespace) -> int:
    harness = EvalHarness(config_path=args.config)
    suites = args.suites or None
    print(f"Running InSummery agent evals against model: {harness.model_spec}")
    report = _run_report(harness, suites=suites)
    _print_report(report)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Full report written to {args.json_out}")

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
    print(f"Generating eval baseline against model: {harness.model_spec}")

    if not is_gemini_model(harness.model_spec):
        print(
            "NOTE: the active model is a local Ollama model. This baseline will be "
            "written to the gitignored local baselines directory. The committed "
            "reference baseline must be generated against Gemini "
            "(set FORCE_CLOUD_LLM=true with a GEMINI_API_KEY)."
        )

    report = _run_report(harness)
    _print_report(report)

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
    run_p.set_defaults(func=cmd_run)

    base_p = sub.add_parser("baseline", help="Run evals and save the result as the baseline")
    base_p.add_argument(
        "--force",
        action="store_true",
        help="Save the baseline even if absolute thresholds are not met",
    )
    base_p.set_defaults(func=cmd_baseline)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
