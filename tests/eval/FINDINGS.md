# Intelligence Diagnosis — Findings

Baseline investigation of the InSummery agents. Scope was **diagnosis**: build
the instruments, measure, and rank what to fix. No extraction behavior was
changed — `app/pii_masker.py` and the prompts in `app/agent_factories.py` are
untouched by this work.

**Status: measured.** Full live run against `gemini/gemini-2.5-flash`,
2026-08-28 (`prompt_hash dcb095528058`, `dataset_hash 22ddfdf374df`). Numbers
below are observed, not projected. Regenerate with `insummery-eval run
--json-out output/eval_report.json`, then `insummery-eval diagnose
--from-report output/eval_report.json` (free — no model calls).

---

## Headline: the extraction is strong. The identity layer and the confidence signal are not.

The hard suite was built to have headroom on three axes. Two of them came back
essentially solved:

| Axis | Score | Verdict |
|---|---|---|
| `hard_multi_score` | **0.9992** | Solved |
| `hard_temporal_score` | **0.9902** | Solved |
| `hard_identity_score` | **0.9088** | The real gap |
| `hard_activity_f1` | **1.0000** | Every expected activity found, none invented |

**`activity_f1 = 1.0000` across all 9 cases.** The model correctly split a
two-sibling email into two activities, a two-block enrollment into two, a split
weekly schedule into two, and a camp with a holiday week off into two
non-contiguous ranges — while correctly *not* extracting the three advertised
programs surrounding the one real booking in a newsletter. It also resolved a
year-less date range to the right season.

I expected these axes to show weakness. They did not. **That prediction was
wrong, and it is worth saying plainly: the multi-activity and temporal
reasoning is genuinely good.** The scorer blind spot documented in Finding 3
was real — the old instrument *could not have detected* a failure there — but
the model does not actually fail there.

What is left after that is narrow and specific, and it is the thing you
suspected from the start: **names**.

---

## Why the models felt "adequate but not impressive"

Two separate reasons, and neither is "the model is weak".

### The 0.95 ceiling was a scoring bug

`registration_field_score` sat at ~0.95 because **`notes` scores exactly 0.0 on
every single case** — and `notes` carries weight 0.05. The headline number
literally could not exceed 0.95.

It scores 0 because free text is scored by `SequenceMatcher` ratio against one
hand-written ground-truth phrasing, gated at 0.55. Measured on `case_02`:

```
EXPECTED: Pack peanut-free lunch/snacks, closed-toe shoes required, apply
          sunscreen. Order ID: ST-2026-990812.

MODEL:    Drop-off opens at 8:50 AM. Authorized Pick-up List: Jamie Smith,
          Dana Smith, Avery (Nanny). Pre-camp checklist: Pack a peanut-free
          sack lunch and two snacks. Comfortable, closed-toe shoes are
          required for lab work. Apply sunscreen before arrival, as some
          rocket launches will occur outdoors.

similarity ratio: 0.1279  ->  gated to 0.0
```

The model's notes contain **everything** in the ground truth plus the drop-off
time and the authorized pick-up list. It is the better answer and it scores
zero. The independent LLM-judge tier rates the same field
**`judge_notes_completeness` 0.978**.

This is an instrument defect, not a model defect. It is also the single largest
line in the ranked findings (10.0 points lost in each of two suites) — and it
was invisible because the aggregate never moved.

### The suite had no headroom

The pre-existing baseline reads:

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

## Finding 0 — the confidence score is a constant, so the HITL gate is decorative

**Severity: highest. This outranks every field-level finding below.**
**Status: FIXED** — see "The deterministic gate" below.

Across **29 scored cases** spanning the easy curated set and the deliberately
hard set, the model emitted exactly three distinct confidence values:

```
distinct confidence values ever emitted:  95, 98, 100
cases clearing the production gate (>=80):  29 / 29  (100%)
```

There is one populated confidence band. The gate threshold is 80. **The gate has
never fired.** `confidence_gate_rate` is 1.0000 on both suites, and it is 1.0000
not because the extractions are all good but because the signal has no
discriminative power.

The consequence is concrete. On `hard_id_02_nickname_and_adult` the model got
the child's name **wrong** — `child_name` scored 0.0, every other field 1.0 —
and reported:

```
confidence_score: 100
evaluation_trace: "All essential details (child's name, activity title,
                   start/end dates, start/end times, and location) were
                   clearly provided in the email."
```

Maximum confidence, and a trace that specifically names the child's name as
clearly provided. That activity lands on the wrong child's calendar — or on no
child's — with **no human ever asked**. For a product whose job is knowing which
kid needs care when, silent wrong-child attribution is the worst available
failure mode, and the mechanism designed to catch it is inert.

`INTERPRETER_REGISTRATION_INSTRUCTION` (`app/agent_factories.py:52-58`) orders
the model to drop below 80 when details are missing or ambiguous. It does not
comply, and nothing checked.

This is now tracked: `hard_confidence_gate_rate` and
`registration_confidence_gate_rate` are baseline-gated, and
`insummery-eval diagnose` prints the calibration table and a
**confident-and-wrong** list on every run.

### The deterministic gate

`app/extraction_risk.py` escalates on the **extraction**, not on the model's
opinion of itself, so it cannot be talked out of firing. It runs alongside the
`confidence_score >= 80` test in `confidence_gate_node`; either can escalate.

Signals, each tied to a specific way the schedule ends up wrong:

| Code | Consequence it prevents |
|---|---|
| `unresolved_child_name` | activity lands on nobody's schedule column |
| `missing_required_field` | activity cannot be placed at all |
| `placeholder_leak` | `[CHILD_A]` written into the family's saved data |
| `inverted_date_range` | end before start |
| `date_range_implausibly_far` | year-inference error, >18 months out |
| `guardrail_failed` | already computed and traced, but nothing acted on it |
| `no_activities` | registration classified but nothing extracted |

Measured end to end:

- `hard_id_02` — the case the model rated **confidence 100** while attaching
  the camp to a name matching no child — now returns `INTERRUPTED`, with the
  prompt naming the actual problem: *"'Amy' does not match a child in the
  profile (Pat, Sam, Alex, …)"*.
- `workflow_pass_rate` stays at **1.0000** on the 10 clean fixtures. Zero
  false escalations.

Two design notes worth keeping:

- **The message names the problem, not a percentage.** "I am 62% sure" is not
  something a parent can act on; "this says Sammy and your children are Sam
  and Pat" is.
- **One signal was built and then removed.** "Date range already ended" was
  meant to catch year-inference errors, but it fires on any legitimately old
  email while the consequence is mild. Poor precision, modest consequence —
  the exact combination the module's own design rule excludes. A year error
  landing in the *future* is still caught by `date_range_implausibly_far`.

The gate corrects the *routing*. It does not make `confidence_score` itself
meaningful — that number is still effectively a constant, and is now best read
as unreliable rather than as a safety signal.

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

This is not only a theoretical corruption — it is the measured cause of the one
hard-suite failure. `hard_id_02` refers to the child as `Sammy`; the masker
emits `[CHILD_B]my`, which is neither the placeholder nor a name, so the model
cannot recover `Sam`. That single defect is what holds `hard_identity_score` to
0.9088 while the other two axes sit at 0.99+.

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

## LLM-judge tier (report-only)

Ran over the 9 hard cases with `gemini/gemini-2.5-flash`:

| Dimension | Score |
|---|---|
| `judge_notes_completeness` | 0.978 |
| `judge_confidence_justification` | 1.000 |
| `judge_trace_honesty` | 0.822 |

Two things to take from this.

**It cross-confirms the notes finding.** The deterministic scorer says 0.0; an
independent read of the same field says 0.978. When two instruments disagree
that hard, the instrument is what's broken.

**It failed to catch the calibration problem — and that is the useful lesson.**
It scored `confidence_justification` a perfect 1.0 on `hard_id_02`, the case
where the model claimed confidence 100 and got the child's name wrong. It is
currently the *same model family* grading its own output, so the scores carry
self-preference bias. Point `JUDGE_MODEL` at a different provider to remove it.

This is precisely why the tier is structurally non-gating. That contract was
also verified under real failure: the first judge run errored on all 9 cases (I
had pinned it to a Vertex model spec that needs a GCP project). It reported
`graded 0/9` with `null` metrics — **not zeros** — the eval gates still passed,
and no `judge_*` key reached `report["metrics"]`. An unavailable judge did not
look like a quality drop.

---

## Recommended fixes, ranked by impact ÷ effort

Re-ranked against measured data. The ordering changed once the live numbers
came in: multi-activity and temporal work needs nothing.

1. ~~**Make the confidence score mean something** (Finding 0).~~ **Done** —
   built as a deterministic gate (`app/extraction_risk.py`) rather than as a
   prompt change, because the prompt already orders the model to lower its
   confidence and it demonstrably ignores that. See Finding 0.
2. **Word-boundary matching in `PIIMasker`.** Wrap each name in `\b...\b`.
   Small and local; moves `mask_precision` and `mask_token_integrity` most, and
   fixes the corrupted text every live metric is computed on top of.
3. **Fix `notes` scoring.** Stop using `SequenceMatcher` on free text. Score
   *key-fact coverage* — does the extraction contain the allergy policy, the
   gear list, the drop-off window — rather than string overlap. This unlocks
   the artificial 0.95 ceiling so the suite can show improvement at all.
4. **Restore original casing on unmask** — fixes `mask_roundtrip_fidelity`,
   nearly free once (2) lands.
5. **Teach the identity layer about full names and nicknames.** Add an optional
   `last_name` to the profile schema, or run a Presidio `PERSON` pass over the
   residual text (`presidio-analyzer` is already a dependency and already wired
   as an opt-in guardrail). Closes the surname leak — the one with privacy
   consequences — and the `Sammy` case. Share the nickname map with
   `resolve_child_name` so both sides agree, and handle possessives there.
6. **Adopt `score_activity_set` in the registration and workflow suites.** Not
   urgent: the model scores `activity_f1` 1.0, so this closes a blind spot
   rather than a failure. Worth doing before anyone changes the prompts.

## Open questions

- **`triage_gen_02`** is classified `registration` when it should be `general`
  — the only triager miss, present in the pre-existing baseline too. Worth one
  look at whether the case or the prompt is wrong.
- **The hard suite is now nearly saturated too** (0.9661). It did its job of
  locating the identity gap, but a follow-up round should add cases in the
  areas that actually broke: nicknames, ambiguous sibling references
  ("both boys"), and emails that supersede an earlier registration.
