"""Baseline storage and regression comparison for eval runs.

Baselines are stored one file per model. Per the project decision, the
committed reference baseline is generated against Gemini (the model used for
the capstone submission). Baselines produced against local Ollama models are
written to a gitignored ``local/`` subdirectory: they are useful for
day-to-day iteration but must never overwrite or masquerade as the committed
Gemini baseline, because scores are model-dependent.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def is_gemini_model(model_spec: str) -> bool:
    return model_spec.startswith("gemini/") or model_spec.startswith("vertex_ai/")


def sanitize_model_spec(model_spec: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_spec)


def baseline_path(config: Dict[str, Any], root: Path, model_spec: str) -> Path:
    cfg = config.get("baselines", {})
    if is_gemini_model(model_spec):
        base_dir = root / cfg.get("dir", "tests/eval/baselines")
    else:
        base_dir = root / cfg.get("local_dir", "tests/eval/baselines/local")
    return base_dir / f"baseline_{sanitize_model_spec(model_spec)}.json"


def save_baseline(report: Dict[str, Any], config: Dict[str, Any], root: Path) -> Path:
    path = baseline_path(config, root, report["model"])
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline = {
        "model": report["model"],
        "timestamp": report["timestamp"],
        "metrics": report["metrics"],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)
        f.write("\n")
    return path


def load_baseline(config: Dict[str, Any], root: Path, model_spec: str) -> Optional[Dict[str, Any]]:
    path = baseline_path(config, root, model_spec)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_to_baseline(
    report: Dict[str, Any],
    baseline: Dict[str, Any],
    tolerance: float,
) -> List[str]:
    """Return regression messages for metrics that dropped more than
    ``tolerance`` below the baseline."""
    regressions = []
    for metric, base_value in baseline.get("metrics", {}).items():
        actual = report["metrics"].get(metric)
        if actual is None:
            regressions.append(f"{metric}: missing from current run (baseline {base_value:.4f})")
            continue
        if actual < base_value - tolerance:
            regressions.append(
                f"{metric}: {actual:.4f} regressed more than {tolerance:.2f} below baseline {base_value:.4f}"
            )
    return regressions
