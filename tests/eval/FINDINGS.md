# Intelligence Diagnosis — Findings

Baseline investigation of the InSummery agents. Scope was **diagnosis**: build
the instruments, measure, and rank what to fix. No extraction behavior was
changed — `app/pii_masker.py` and the prompts in `app/agent_factories.py` are
untouched by this work.

Regenerate the live half with `insummery-eval diagnose` (see
[README.md](./README.md)).

---

## Why the models felt "adequate but not impressive"

The existing suite could not have told you otherwise. The committed baseline
(`baselines/baseline_gemini_gemini-2.5-flash.json`) reads:

| Metric | Baseline |
|---|---|
| `triager_accuracy` | 0.9444 |
| `registration_field_score` | 0.9515 |
| `registration_confidence_gate_rate` | 1.0000 |
| `disruption_field_score` | 0.9500 |
| `workflow_pass_rate` | 1.0000 |

Those come from 10 curated emails, each one child, one activity, a clean
confirmation receipt, with the child's name spelled exactly as the profile
stores it. **A benchmark scoring 0.95+ on its easy path has no headroom and no
teeth** — it cannot show an improvement and it cannot catch a regression.

Three structural gaps sat underneath that number.

---

## Finding 1 — `PIIMasker` does naive substring replacement

**Severity: high. `app/pii_masker.py:80-87`.**

Profile names are masked with `re.compile(re.escape(orig), re.IGNORECASE)` and
no word boundaries, so any name that appears *inside* an ordinary word rewrites
that word. Measured against the project's own eval profile
(`tests/test_cases/profile_10_kids.json`, whose children include Sam, Pat and
Alex):

```
IN : Camp runs at the same time each day.
OUT: Camp runs at the [CHILD_B]e time each day.

IN : Please pay the balance; participation is required.
OUT: Please pay the balance; partici[CHILD_A]ion is required.

IN : Alexandra will be the lead counselor.
OUT: [CHILD_C]andra will be the lead counselor.

IN : Two families withdrew last week.
OUT: Two families with[CAREGIVER_B] last week.
```

The model is handed corrupted English. This is a mechanical cause of mediocre
extraction that **does not look like a masking bug in the aggregate scores — it
looks like a mediocre model.** It was invisible to the old suite only because
the 10 curated fixtures happen to contain none of these words.

Measured on the new offline suite (22 cases):

| Metric | Today | Target |
|---|---|---|
| `mask_precision` (non-PII left intact) | **0.1667** | 1.00 |
| `mask_recall` (PII actually removed) | **0.3750** | 1.00 |
| `mask_token_integrity` (no placeholder welded mid-word) | **0.5000** | 1.00 |
| `mask_roundtrip_fidelity` (`unmask(mask(t)) == t`) | **0.7727** | 1.00 |

Round-trip fails because a case-insensitive match is restored with the
profile's casing: `"at the same time"` returns as `"at the Same time"`.

## Finding 2 — surnames are never masked, on the project's own fixtures

**Severity: high (privacy). Same file.**

The profile schema stores first names only. `tests/test_cases/case_02_sam_robotics.txt`
contains `Name: Sam Smith`, `Jamie Smith`, `Dana Smith` — masking yields
`[CHILD_B] Smith`, so the family surname reaches the LLM verbatim on every one
of these cases. PII masking is the product's headline privacy guarantee.

The inverse fails too: a profile storing `"Emily Carter"` against an email
saying just `Emily` produces **no mask at all**.

Nicknames are a third variant — `Sammy`, `Michael` for a profile `Mike`,
`Katie` for `Katherine` — all leak or mangle.

Note the asymmetry, because it shapes the fix: the **output** side is fine.
`resolve_child_name` (`app/matrix_logic.py:96-180`) already does exact →
first-name → token-containment matching and handles `"Sam Smith" → "Sam"`
correctly. It is the **input** side that is broken. It fails only on nicknames
(`Sammy`, `Michael`) and possessives (`Riley's`) —
`name_resolution_accuracy 0.75`.

## Finding 3 — the scorer could not see missing or invented activities

**Severity: medium. `app/evaluation/scoring.py`, used at `runner.py:190` and `:301`.**

`pick_best_activity` selects the single best-matching predicted activity and
scores only that one. So:

- expected 2 activities, model extracts 1 → scored **1.0**
- expected 1 activity, model invents 4 more → scored **1.0**

`extracted_activities` was recorded on each row but never entered a metric.
Since every existing fixture is exactly one child × one activity, splitting a
multi-child email had **never been scored at all**.

Fixed in the instrument (not in the model): `match_activities` /
`score_activity_set` do one-to-one assignment and report precision, recall and
F1, so a miss and a hallucination both cost score.

## Finding 4 — the regression gate never ran

**Severity: high (process). `.github/workflows/ci.yml`.**

`insummery-eval` appeared nowhere in CI. The live pytest entry point
(`tests/eval/test_extraction_eval.py`) auto-skips without a Gemini credential,
and none was configured. The thresholds, the committed baseline and
`regression_tolerance: 0.05` were all real, well-built, and **never enforced**.

---

## What was built

| Instrument | What it answers |
|---|---|
| `identity` suite (offline, 34 cases) | Is the masker corrupting the text the model reads? Does name resolution handle real-world name forms? |
| `hard` suite (live, 9 cases / 13 activities) | Identity, multi-activity and temporal reasoning, on cases built to have headroom |
| `score_activity_set` | Do misses and hallucinations cost score? |
| `insummery-eval diagnose` | Which field is costing the most, and is confidence calibrated? |
| `provenance.py` | Did the score move because of the prompt, the data, or the model? |
| `judge.py` | Is the model's self-report honest? (report-only, never gates) |
| `ci.yml` + `eval-nightly.yml` | Offline gate every PR; full live gate nightly |

### Threshold policy

The identity thresholds in `eval_config.yaml` are pinned to **today's measured
(broken) values**, deliberately. That makes them a ratchet — the identity layer
can never get *worse* without failing a PR — while a known-broken component
does not block every unrelated change. The target column is in the config
comment. Raise them when the masker fix lands.

---

## Recommended fixes, ranked by impact ÷ effort

1. **Word-boundary matching in `PIIMasker`.** Wrap each name pattern in
   `\b...\b`. Small, local change; moves `mask_precision` and
   `mask_token_integrity` most, and fixes the corrupted text every live metric
   is computed on top of. Start here.
2. **Restore original casing on unmask**, or match case-preservingly — fixes
   `mask_roundtrip_fidelity` and is nearly free once (1) is in.
3. **Teach the identity layer about full names.** Either add an optional
   `last_name` to the profile schema and mask `first`, `last` and
   `"first last"` independently, or run a Presidio `PERSON` pass over the
   residual text. `presidio-analyzer` is already a dependency and already
   wired as an opt-in guardrail in `weave_observability.py`. Closes the
   surname leak, which is the one with privacy consequences.
4. **Nickname/diminutive mapping**, shared by the masker and
   `resolve_child_name` so both sides agree. Also handle possessives
   (`Riley's`) in `resolve_child_name`.
5. **Adopt `score_activity_set` in the existing registration and workflow
   suites** once (1)-(4) land, so multi-activity emails are scored honestly
   everywhere rather than only in the `hard` suite.

## Still to measure

The live suites need a model credential and did not run in the environment
this investigation was performed in. The first run of
`.github/workflows/eval-nightly.yml` (or a local
`FORCE_CLOUD_LLM=true GEMINI_API_KEY=... insummery-eval diagnose`) will produce:

- `hard_score` and the per-axis breakdown (`hard_identity_score`,
  `hard_multi_score`, `hard_temporal_score`)
- the **confidence calibration table** — the open question flagged by
  `registration_confidence_gate_rate: 1.00`. The model currently reports
  itself confident on 100% of cases. If that holds on the hard suite, the
  production HITL gate never fires and protects no one, which would outrank
  every field-level finding above.

Once those land, commit the hard-suite baseline and add a `hard_score`
threshold to `eval_config.yaml`.
