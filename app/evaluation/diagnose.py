"""Turn an eval report into a ranked diagnosis.

``insummery-eval run`` answers "did anything regress". This module answers the
different question you need when the numbers are merely *mediocre*: which
capability is costing the score, and is the model's own confidence worth
trusting.

Everything here is a pure function over a finished report dict, so it is
unit-testable offline and can be re-run against a saved report without
spending another API call.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Confidence bands for the calibration table. The 80 boundary is the
# production HITL gate (CONFIDENCE_GATE in app/evaluation/runner.py, mirroring
# confidence_gate_node in app/nodes.py).
CONFIDENCE_BANDS = ((0, 50), (50, 80), (80, 95), (95, 101))


def _iter_scored_cases(report: Dict[str, Any]):
    """Yield ``(suite_name, case)`` for every case that carries a score."""
    for suite_name, section in (report.get("details") or {}).items():
        for case in section.get("cases", []) or []:
            yield suite_name, case


def _field_score_dicts(case: Dict[str, Any]) -> List[Dict[str, float]]:
    """Normalize the two field_scores shapes into a list of dicts.

    Single-activity suites store one dict; the hard suite stores one dict per
    matched activity pair.
    """
    fs = case.get("field_scores")
    if isinstance(fs, dict):
        return [fs]
    if isinstance(fs, list):
        return [d for d in fs if isinstance(d, dict)]
    return []


def field_breakdown(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Mean score per extracted field, per suite.

    This is the table that turns "registration_field_score is 0.87" into
    "start_time is at 0.45 and everything else is near 1.0".
    """
    out: Dict[str, Dict[str, Any]] = {}
    for suite_name, case in _iter_scored_cases(report):
        for fs in _field_score_dicts(case):
            for field, value in fs.items():
                bucket = out.setdefault(suite_name, {}).setdefault(
                    field, {"total": 0.0, "n": 0}
                )
                bucket["total"] += float(value)
                bucket["n"] += 1
    return {
        suite: {
            field: {"mean": round(b["total"] / b["n"], 4), "n": b["n"]}
            for field, b in fields.items()
        }
        for suite, fields in out.items()
    }


def axis_breakdown(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Mean score and worst case per hard-suite axis."""
    axes: Dict[str, List[Dict[str, Any]]] = {}
    for _, case in _iter_scored_cases(report):
        axis = case.get("axis")
        if axis:
            axes.setdefault(axis, []).append(case)

    out = {}
    for axis, cases in axes.items():
        scores = [c.get("score", 0.0) for c in cases]
        worst = min(cases, key=lambda c: c.get("score", 0.0))
        out[axis] = {
            "mean": round(sum(scores) / len(scores), 4),
            "n": len(cases),
            "worst_case": worst.get("id"),
            "worst_score": worst.get("score"),
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["mean"]))


def confidence_calibration(report: Dict[str, Any]) -> Dict[str, Any]:
    """Is self-reported confidence predictive of being right?

    The production HITL gate pauses for a human below 80. That gate is only
    worth anything if extractions above 80 are actually more accurate than
    those below. A flat table -- high confidence everywhere, correctness
    uncorrelated -- means the gate never fires and never protects anyone,
    which is a far more serious finding than any single field score.
    """
    rows = [
        case
        for _, case in _iter_scored_cases(report)
        if isinstance(case.get("confidence_score"), (int, float))
        and isinstance(case.get("score"), (int, float))
    ]
    if not rows:
        return {"bands": [], "n": 0, "gate_precision": None, "overconfident_cases": []}

    bands = []
    for low, high in CONFIDENCE_BANDS:
        in_band = [r for r in rows if low <= r["confidence_score"] < high]
        if not in_band:
            continue
        bands.append(
            {
                "band": f"{low}-{high - 1}",
                "n": len(in_band),
                "mean_score": round(
                    sum(r["score"] for r in in_band) / len(in_band), 4
                ),
            }
        )

    above = [r for r in rows if r["confidence_score"] >= 80]
    # Of the extractions the gate waves through, how many were actually right?
    gate_precision = (
        round(sum(1 for r in above if r["score"] >= 0.9) / len(above), 4)
        if above
        else None
    )
    # The dangerous quadrant: confident and wrong. These reach the family's
    # calendar with no human ever being asked.
    overconfident = sorted(
        (
            {
                "id": r.get("id"),
                "confidence_score": r["confidence_score"],
                "score": r["score"],
            }
            for r in above
            if r["score"] < 0.75
        ),
        key=lambda r: r["score"],
    )
    return {
        "bands": bands,
        "n": len(rows),
        "n_above_gate": len(above),
        "gate_precision": gate_precision,
        "overconfident_cases": overconfident,
    }


def rank_findings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rank (suite, field) pairs by how much score they are costing.

    Cost is ``(1 - mean) * n`` -- total points lost, not just the lowest mean,
    so a field that is slightly wrong everywhere ranks above one that is badly
    wrong in a single case.
    """
    findings = []
    for suite, fields in field_breakdown(report).items():
        for field, stats in fields.items():
            lost = round((1.0 - stats["mean"]) * stats["n"], 4)
            if lost > 0:
                findings.append(
                    {
                        "suite": suite,
                        "field": field,
                        "mean": stats["mean"],
                        "n": stats["n"],
                        "points_lost": lost,
                    }
                )

    # Field scores only exist for activities that were MATCHED. An activity the
    # model never produced contributes no field rows at all, so a run that
    # misses everything would otherwise show an empty findings table and read
    # as "nothing wrong". Surface coverage as its own finding so a miss is
    # never quieter than a wrong field.
    for suite, counts in _coverage_gaps(report).items():
        for kind, stats in counts.items():
            if stats["lost"] > 0:
                findings.append(
                    {
                        "suite": suite,
                        "field": kind,
                        "mean": stats["rate"],
                        "n": stats["n"],
                        "points_lost": stats["lost"],
                    }
                )

    return sorted(findings, key=lambda f: -f["points_lost"])


def _coverage_gaps(report: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Count activities the model failed to produce, and ones it invented."""
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for suite_name, case in _iter_scored_cases(report):
        if "missed_expected" not in case and "spurious_predicted" not in case:
            continue
        bucket = out.setdefault(
            suite_name,
            {
                "<activities missed>": {"lost": 0.0, "n": 0, "rate": 1.0},
                "<activities invented>": {"lost": 0.0, "n": 0, "rate": 1.0},
            },
        )
        expected = case.get("expected_count") or 0
        predicted = case.get("predicted_count") or 0
        bucket["<activities missed>"]["lost"] += len(case.get("missed_expected") or [])
        bucket["<activities missed>"]["n"] += expected
        bucket["<activities invented>"]["lost"] += len(case.get("spurious_predicted") or [])
        bucket["<activities invented>"]["n"] += predicted

    for suite, kinds in out.items():
        for kind, stats in kinds.items():
            stats["rate"] = (
                round(1.0 - stats["lost"] / stats["n"], 4) if stats["n"] else 1.0
            )
            stats["lost"] = round(stats["lost"], 4)
    return out


def identity_findings(report: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize the offline identity suite by failure family."""
    section = (report.get("details") or {}).get("identity")
    if not section:
        return {}

    families: Dict[str, Dict[str, Any]] = {}
    for case in section.get("mask_cases", []):
        fam = families.setdefault(
            case.get("family") or "unspecified",
            {"n": 0, "failed": 0, "leaks": [], "over_masked": [], "glued": 0},
        )
        fam["n"] += 1
        if not case["passed"]:
            fam["failed"] += 1
            fam["leaks"].extend(case.get("leaks") or [])
            fam["over_masked"].extend(case.get("over_masked") or [])
            fam["glued"] += len(case.get("glued_placeholders") or [])

    name_families: Dict[str, Dict[str, int]] = {}
    for case in section.get("name_resolution_cases", []):
        fam = name_families.setdefault(
            case.get("family") or "unspecified", {"n": 0, "failed": 0}
        )
        fam["n"] += 1
        if not case["passed"]:
            fam["failed"] += 1

    return {
        "mask_families": dict(
            sorted(families.items(), key=lambda kv: -kv[1]["failed"])
        ),
        "name_families": dict(
            sorted(name_families.items(), key=lambda kv: -kv[1]["failed"])
        ),
    }


def build_diagnosis(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "model": report.get("model"),
        "timestamp": report.get("timestamp"),
        "prompt_hash": report.get("prompt_hash"),
        "metrics": report.get("metrics", {}),
        "field_breakdown": field_breakdown(report),
        "axis_breakdown": axis_breakdown(report),
        "calibration": confidence_calibration(report),
        "ranked_findings": rank_findings(report),
        "identity": identity_findings(report),
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def _table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "_(no data)_\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out) + "\n"


def render_markdown(diagnosis: Dict[str, Any]) -> str:
    d = diagnosis
    parts: List[str] = ["# InSummery Intelligence Diagnosis\n"]
    parts.append(f"- **Model:** `{d.get('model')}`")
    parts.append(f"- **Run:** {d.get('timestamp')}")
    if d.get("prompt_hash"):
        parts.append(f"- **Prompt hash:** `{d['prompt_hash']}`")
    parts.append("")

    parts.append("## Scorecard\n")
    parts.append(
        _table(
            ["Metric", "Score"],
            [[k, f"{v:.4f}"] for k, v in sorted(d["metrics"].items())],
        )
    )

    if d["axis_breakdown"]:
        parts.append("## By capability axis\n")
        parts.append(
            _table(
                ["Axis", "Mean", "Cases", "Worst case", "Worst"],
                [
                    [a, f"{s['mean']:.4f}", s["n"], f"`{s['worst_case']}`",
                     f"{s['worst_score']:.2f}"]
                    for a, s in d["axis_breakdown"].items()
                ],
            )
        )

    cal = d["calibration"]
    if cal.get("bands"):
        parts.append("## Confidence calibration\n")
        parts.append(
            "Does self-reported confidence predict correctness? The production "
            "HITL gate pauses below 80, so it only protects anyone if these "
            "bands separate.\n"
        )
        parts.append(
            _table(
                ["Confidence band", "Cases", "Mean score"],
                [[b["band"], b["n"], f"{b['mean_score']:.4f}"] for b in cal["bands"]],
            )
        )
        if cal.get("gate_precision") is not None:
            parts.append(
                f"\n**Gate precision:** {cal['gate_precision']:.1%} of the "
                f"{cal['n_above_gate']} extractions the gate waved through "
                f"(confidence >= 80) scored >= 0.90.\n"
            )
        if cal.get("overconfident_cases"):
            parts.append(
                "\n**Confident and wrong** — these reach the calendar with no "
                "human ever asked:\n"
            )
            parts.append(
                _table(
                    ["Case", "Confidence", "Score"],
                    [
                        [f"`{c['id']}`", c["confidence_score"], f"{c['score']:.2f}"]
                        for c in cal["overconfident_cases"]
                    ],
                )
            )

    if d["ranked_findings"]:
        parts.append("## Ranked findings (by score lost)\n")
        parts.append(
            _table(
                ["#", "Suite", "Field", "Mean", "N", "Points lost"],
                [
                    [i, f["suite"], f"`{f['field']}`", f"{f['mean']:.4f}",
                     f["n"], f"{f['points_lost']:.2f}"]
                    for i, f in enumerate(d["ranked_findings"][:15], 1)
                ],
            )
        )

    judge = d.get("judge")
    if judge:
        parts.append("## LLM judge (report-only — never gates)\n")
        parts.append(
            f"Model `{judge.get('judge_model')}`, prompt hash "
            f"`{judge.get('judge_prompt_hash')}`, graded "
            f"{judge.get('graded')}/{judge.get('attempted')} cases.\n"
        )
        parts.append(
            _table(
                ["Dimension", "Score"],
                [
                    [k, f"{v:.4f}" if isinstance(v, float) else "n/a"]
                    for k, v in (judge.get("metrics") or {}).items()
                ],
            )
        )
        parts.append(
            "\nThese never enter `report[\"metrics\"]`, so they cannot fail a "
            "threshold or a baseline comparison.\n"
        )

    ident = d.get("identity") or {}
    if ident.get("mask_families"):
        parts.append("## Identity layer (offline)\n")
        parts.append("### PII masking, by failure family\n")
        parts.append(
            _table(
                ["Family", "Cases", "Failed", "Leaked spans", "Over-masked spans"],
                [
                    [
                        fam,
                        s["n"],
                        s["failed"],
                        ", ".join(f"`{x}`" for x in sorted(set(s["leaks"]))) or "—",
                        ", ".join(f"`{x}`" for x in sorted(set(s["over_masked"]))) or "—",
                    ]
                    for fam, s in ident["mask_families"].items()
                ],
            )
        )
    if ident.get("name_families"):
        parts.append("### Child-name resolution, by family\n")
        parts.append(
            _table(
                ["Family", "Cases", "Failed"],
                [[fam, s["n"], s["failed"]] for fam, s in ident["name_families"].items()],
            )
        )

    return "\n".join(parts) + "\n"
