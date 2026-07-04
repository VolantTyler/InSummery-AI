# InSummery Agent Evaluation Loop

This directory contains the configuration and datasets for the unified
evaluation harness (`app/evaluation/`) covering the LLM-backed agents in the
InSummery workflow: the **triager** (registration / disruption / general
classification) and the **interpreter** (structured schedule extraction). It
implements the "Strict Evaluation & Tracing" requirement from Day 4 of the
Kaggle 5-Day AI Agents course using fully **deterministic scoring** — no
LLM-as-a-judge — so scores are reproducible for a given set of model outputs.

The harness runs four suites:

- **`triager`**, **`registration`**, **`disruption`** evaluate each agent *in
  isolation*, built from the same shared factories (`app/agent_factories.py`)
  used by `app/nodes.py`, with inputs going through the same PII
  mask → model → unmask round-trip as real traffic.
- **`workflow`** runs the same curated registration emails through the *full
  production ADK workflow* (PII mask → triager → interpreter → confidence
  gate), so the graph wiring itself — routing, state passing, the HITL
  confidence gate — is exercised end to end, not just the agents.

## Running the evals

```bash
# Run all suites, gate on absolute thresholds and the stored baseline
insummery-eval run

# Run only the end-to-end workflow suite (quick live sanity check that
# GEMINI_API_KEY works and the workflow graph delivers the right input
# to each node)
insummery-eval run --suites workflow

# Save a full per-case JSON report
insummery-eval run --json-out output/eval_report.json

# Regenerate the baseline after an intentional prompt/model change
insummery-eval baseline
```

(Equivalent: `python -m app.evaluation.cli run`.)

The workflow suite also runs as a live pytest check
(`tests/eval/test_extraction_eval.py`), skipped automatically when no Gemini
credential is configured.

### Model requirements

The harness uses the same model resolution as the production workflow
(`app/model_client.py`): a local **Ollama** instance if one is running with a
matching model, otherwise **Gemini** via LiteLLM. To execute the eval loop end
to end you therefore need one of:

- a `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) environment variable — for Cloud
  Agents, add it as a secret in the Cursor Dashboard (Cloud Agents → Secrets); or
- a running Ollama instance (set `OLLAMA_MODEL` / `OLLAMA_API_BASE` to override
  the defaults).

Force a specific side with `FORCE_CLOUD_LLM=true` or `FORCE_LOCAL_LLM=true`.

Everything else — the harness itself, scoring, and baseline management — is
covered offline by unit tests (`tests/unit/test_eval_scoring.py`,
`tests/unit/test_eval_harness.py`) using an injected fake model.

## What gets measured

| Metric | Description |
|---|---|
| `triager_accuracy` | Exact classification accuracy over 18 cases (10 registrations, 5 disruptions, 3 general). |
| `registration_field_score` | Weighted field-level score of extracted activities vs. the ground-truth manifest (`tests/test_cases/test_cases_manifest.json`). Child name, dates, and times are exact-match; title/location/notes use gated string similarity. |
| `registration_confidence_gate_rate` | Share of registration cases whose self-reported confidence clears the production HITL gate (≥ 80). |
| `disruption_field_score` | Weighted field-level score for disruption extraction (child, date, type, description). |
| `workflow_pass_rate` | End-to-end: share of registration emails that complete the full workflow with correct routing, confidence ≥ 80, exact critical fields (child, dates, times), and a matching activity title. |
| `workflow_field_score` | End-to-end: same weighted field score as `registration_field_score`, but computed on the extraction the full workflow actually produced. |

Absolute thresholds and the regression tolerance live in
[eval_config.yaml](./eval_config.yaml). `insummery-eval run` exits non-zero if
any metric falls below its threshold **or** drops more than
`regression_tolerance` below the stored baseline for the active model.

## Baseline policy (read before regenerating)

Eval scores are **model-dependent**: a baseline generated against a local
Ollama model is not comparable to one generated against Gemini.

**Decision: the committed reference baseline is generated against Gemini**
(`gemini/gemini-2.5-flash`), since Gemini is the model used for the capstone
submission. Concretely:

- `insummery-eval baseline` while Gemini is active writes
  `tests/eval/baselines/baseline_gemini_gemini-2.5-flash.json` — this file is
  committed and is the regression reference for CI and reviews.
- `insummery-eval baseline` while an Ollama model is active writes to
  `tests/eval/baselines/local/`, which is **gitignored**. Local baselines are
  for day-to-day iteration only and must not be committed.

The routing is automatic (`app/evaluation/baseline.py`), so a local run can
never overwrite the committed Gemini baseline. To regenerate the committed
baseline:

```bash
FORCE_CLOUD_LLM=true GEMINI_API_KEY=... insummery-eval baseline
```

`baseline` refuses to save a run that fails the absolute thresholds unless you
pass `--force`, so a broken prompt can't silently become the new reference.
