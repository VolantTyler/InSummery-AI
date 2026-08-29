# InSummery Agent Evaluation Loop

This directory contains the configuration and datasets for the unified
evaluation harness (`app/evaluation/`) covering the LLM-backed agents in the
InSummery workflow: the **triager** (registration / disruption / general
classification) and the **interpreter** (structured schedule extraction). It
implements the "Strict Evaluation & Tracing" requirement from Day 4 of the
Kaggle 5-Day AI Agents course using fully **deterministic scoring** — no
LLM-as-a-judge — so scores are reproducible for a given set of model outputs.

See [FINDINGS.md](./FINDINGS.md) for the baseline diagnosis of what these
suites actually measured on first run.

The harness runs six suites:

- **`triager`**, **`registration`**, **`disruption`** evaluate each agent *in
  isolation*, built from the same shared factories (`app/agent_factories.py`)
  used by `app/nodes.py`, with inputs going through the same PII
  mask → model → unmask round-trip as real traffic.
- **`workflow`** runs the same curated registration emails through the *full
  production ADK workflow* (PII mask → triager → interpreter → confidence
  gate), so the graph wiring itself — routing, state passing, the HITL
  confidence gate — is exercised end to end, not just the agents.
- **`identity`** scores `PIIMasker` and `resolve_child_name` directly against
  span expectations. It makes **no model calls**, so it needs no credential and
  gates every pull request. It exists because a masking defect corrupts the
  text every other metric is computed from — a bad mask does not look like a
  masking bug in the aggregate scores, it looks like a mediocre model.
- **`hard`** runs registration emails built to have *headroom* across three
  axes — identity (full names, nicknames, an unknown child), multi-activity
  (two siblings, two sessions, a booking buried in a newsletter), and temporal
  (year-less ranges, split weekly schedules, a holiday gap). Ground truth is a
  *list* scored as a set, so a missed sibling and an invented activity both
  cost score.

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

# Offline only — no API key, no cost. This is what gates every PR.
insummery-eval run --suites identity

# Ranked findings + confidence calibration, written to output/diagnosis.md.
# Never gates; answers "which capability is costing the score" rather than
# "did anything regress".
insummery-eval diagnose

# Add the LLM-judge tier (report-only, see below)
insummery-eval run --judge
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
| `registration_field_score` | Weighted field-level score of extracted activities vs. the ground-truth manifest (`tests/test_cases/test_cases_manifest.json`). Dates and times are exact-match; the child name accepts fuller forms ("Emily Smith" for "Emily"); title/location/notes use gated string similarity. |
| `registration_confidence_gate_rate` | Share of registration cases whose self-reported confidence clears the production HITL gate (≥ 80). |
| `disruption_field_score` | Weighted field-level score for disruption extraction (child, date, type, description). |
| `workflow_pass_rate` | End-to-end: share of registration emails that complete the full workflow with correct routing, confidence ≥ 80, correct critical fields (child, dates, times), and a matching activity title. |
| `workflow_field_score` | End-to-end: same weighted field score as `registration_field_score`, but computed on the extraction the full workflow actually produced. Reported and baseline-tracked, not gated by an absolute threshold. |
| `mask_precision` | Offline. Share of ordinary words and third-party names the masker leaves intact. Catches `"same"` → `"[CHILD_B]e"`. |
| `mask_recall` | Offline. Share of true PII spans actually removed. Catches an unmasked surname. |
| `mask_token_integrity` | Offline. Share of cases where no placeholder is welded to adjacent word characters. Catches the whole substring-collision class structurally, without anyone having to enumerate the colliding word. |
| `mask_roundtrip_fidelity` | Offline. Share of cases where `unmask(mask(text)) == text`. |
| `name_resolution_accuracy` | Offline. `resolve_child_name` over full names, nicknames, possessives, and children *not* in the profile (which must stay unmatched, not be coerced onto a sibling). |
| `hard_score` | Live. `activity_f1 × matched_field_score` over the hard suite. |
| `hard_identity_score` / `hard_multi_score` / `hard_temporal_score` | Live. The same score split by capability axis, so a drop points at a capability rather than at one number. |

## Where the gates run

| | Suites | Credential | Gate |
|---|---|---|---|
| `ci.yml`, every PR | `identity` | none needed | thresholds |
| `eval-nightly.yml`, nightly + manual | all | `GCP_SA_KEY` + `GCP_PROJECT` (Vertex), or `GEMINI_API_KEY` | thresholds + baseline regression |

The nightly picks Vertex AI when `GCP_SA_KEY` and `GCP_PROJECT` are configured
and falls back to the API key otherwise, warning in the log when it does. With
neither, it fails the job rather than passing while measuring nothing.

Before this split, `insummery-eval` ran in no workflow at all: the thresholds
and the committed baseline were never enforced automatically.

### If the nightly hangs to its 45-minute timeout

This happened three times while first wiring the nightly up, with two
different confirmed causes — both fixed, both worth knowing if a future
change reintroduces either shape of problem:

1. **Cloud Trace export lacking IAM permission.** `setup_telemetry()`
   configures a `CloudTraceSpanExporter` whenever `GOOGLE_CLOUD_PROJECT` is
   set. A credential scoped to just `roles/aiplatform.user` (correct,
   least-privilege) lacks `cloudtrace.traces.patch`, so the exporter retries
   and logs a full traceback every 5s for the run's entire duration. Fixed by
   `INSUMMERY_DISABLE_CLOUD_TRACE=true` in both live steps.
2. **Weave's PII redaction hitting a broken `pip`-less venv.** `WANDB_API_KEY`
   was wired into `Run Full Eval Suite` but the command never passed
   `--weave-publish`, so it was activating live Weave tracing
   (`redact_pii=True`) for no benefit. Weave's redaction lazily builds a
   Presidio `AnalyzerEngine`, which tries to self-install its spaCy model via
   `pip` on first use — and `uv venv` does not include `pip`. The install
   fails inside a background thread pool, gets silently swallowed, and the
   run goes dead silent until the timeout kills it — this was the actual
   cause, confirmed by direct A/B: the sibling `Write Diagnosis Report` step,
   which never had `WANDB_API_KEY` set, never hung, even running strictly
   more suites. Fixed by not setting `WANDB_API_KEY` on a step that doesn't
   publish to Weave.

If you deliberately want Weave tracing during a live eval run (e.g. via
`--weave-publish`), install `pip` into the venv first
(`uv pip install pip` or `python -m ensurepip`) so Presidio's lazy model
download can actually succeed instead of hanging.

The identity thresholds in `eval_config.yaml` are pinned to the **current
measured (defective) values** on purpose — a ratchet that prevents the identity
layer getting worse without blocking every unrelated PR on a known-broken
component. See the comment block in that file for the target values.

## The LLM-judge tier (`--judge`)

Deterministic scoring cannot tell whether the model's *self-report* is honest —
whether `evaluation_trace` names the real ambiguity or just says "extraction
successful", and whether `confidence_score` is defensible. `--judge` grades
those, plus whether the parent-actionable content survived into `notes`.

It is **structurally non-gating**: judge results are written to `report["judge"]`,
never to `report["metrics"]`, and both `check_thresholds` and
`compare_to_baseline` read only `metrics`. The judge model and judge prompt
hash are stamped on every result so judge drift is itself attributable, and a
judge failure degrades to `None` rather than to a zero — an unavailable judge
must never look like a quality drop.

## Drift attribution

Every report and baseline carries a `prompt_hash` (over the static instruction
constants, excluding the interpolated date) and a `dataset_hash`. When a
nightly number moves:

- `prompt_hash` changed → you changed the instructions.
- `dataset_hash` changed → you changed ground truth; scores are not comparable
  across that boundary.
- neither changed → the **model** moved. That is drift.

Absolute thresholds and the regression tolerance live in
[eval_config.yaml](./eval_config.yaml). `insummery-eval run` exits non-zero if
any metric falls below its threshold **or** drops more than
`regression_tolerance` below the stored baseline for the active model.

## Baseline policy (read before regenerating)

Eval scores are **model-dependent**: a baseline generated against a local
Ollama model is not comparable to one generated against Gemini.

**Decision: Vertex AI is the project's provider** (`vertex_ai/gemini-2.5-flash`,
which is what `app/model_client.py` defaults to). Baselines are per-model, so
the file name follows the resolved spec:
`baseline_vertex_ai_gemini-2.5-flash.json`.

A `baseline_gemini_gemini-2.5-flash.json` is also committed, from a run made
through the API-key path. It is valid for that path but is **not** the Vertex
reference — generate the Vertex baseline once Vertex credentials are wired.

> **`GEMINI_API_KEY` alone does not select Gemini.** `resolve_model_spec()`
> returns `vertex_ai/gemini-2.5-flash` by default, which needs a GCP project
> and ADC, not an API key. To run through the API-key path you must set
> **both** `GEMINI_API_KEY` and `GEMINI_MODEL=gemini/gemini-2.5-flash`.
> Setting only the key gives you a Vertex call that fails, and a lookup for a
> baseline file that does not exist — so the regression check silently skips.

Concretely:

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
# Vertex AI (the project's provider)
export GOOGLE_CLOUD_PROJECT=your-project      # or VERTEXAI_PROJECT
gcloud auth application-default login          # ADC
FORCE_CLOUD_LLM=true insummery-eval baseline

# Or the API-key path -- note BOTH variables are required
FORCE_CLOUD_LLM=true \
  GEMINI_API_KEY=... \
  GEMINI_MODEL=gemini/gemini-2.5-flash \
  insummery-eval baseline
```

To promote an existing run instead of paying for a second full suite:

```bash
insummery-eval baseline --from-report output/eval_report.json
```

`baseline` refuses to save a run that fails the absolute thresholds unless you
pass `--force`, so a broken prompt can't silently become the new reference.
