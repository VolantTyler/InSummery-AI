# InSummery - Family Schedule Concierge

InSummery is an AI-powered family schedule assistant designed to ingest chaotic, unstructured scheduling emails (such as camp registrations, school calendars, or nanny updates), parse them into a structured family schedule, detect childcare gaps, and handle real-time disruptions.

It features a multi-agent network built using the **Google Agent Development Kit (ADK 2.0)**, a custom **PII Data-Masking Framework** to protect family privacy, and supports both a local command-line interface (CLI) and a web application integrated with **Firebase** and **Google Calendar**.

---

## Key Features

- **Chaotic Email Ingestion**: Paste registrations, emails, or texts, and the AI will extract the child's name, activity, dates, times, location, and notes.
- **PII Data-Masking**: Automatically replaces family names, contact details, and addresses with placeholders (e.g., `[CHILD_A]`, `[PARENT_A]`, `[CAREGIVER_A]`) before sending data to the LLM, restoring them afterwards to ensure total privacy.
- **Childcare Gap Analysis**: Automatically flags:
  - *Absolute Gaps*: Weekday hours (9 AM - 5 PM) where a child has no scheduled activity and is not covered by the baseline school hours.
  - *Relative Gaps*: Sibling care mismatches (e.g., Sibling A has camp but Sibling B has no scheduled care).
- **Disruption & Conflict Handling**: Processes alerts (e.g., "Nanny called out sick") by marking the affected slots as `DISRUPTED`, recalculating gaps, and updating Google Calendar events.
- **Human-in-the-Loop (HITL)**: Pauses the workflow and prompts the user for clarification when the AI's extraction confidence is low (< 80%), resuming seamlessly once clarified.
- **Google Calendar Sync**: Syncs activities to Google Calendar, using child-name prefixes (e.g., `[Emily] Soccer Camp`) and marking disruptions with `[DISRUPTED]`.

---

## Tech Stack & Architecture

- **Backend**: Python 3.10+, Google ADK 2.0, Pydantic, Firebase Cloud Functions (Python), Firestore.
- **Frontend**: Vite + React with vanilla CSS (responsive layouts, dark/light modes, and micro-animations).
- **Authentication**: Firebase Auth (supports Email/Password and Google SSO).
- **CLI**: Click/Argparse Python-based terminal runner.

---

## Local Development Setup

### 1. Prerequisites & Installing Firebase
Ensure you have the following installed:
- **Python 3.10+**
- **Node.js** (Required to install the Firebase CLI)
- **Firebase CLI**:
  To install the Firebase CLI globally on your system, run:
  ```bash
  npm install -g firebase-tools
  ```
  *Note: If you encounter permission errors on Windows, run your terminal as Administrator. On macOS/Linux, run with `sudo npm install -g firebase-tools`.*

  After installation, log in to your Firebase account to authorize the CLI:
  ```bash
  firebase login
  ```

### 2. Python Environment Setup
Clone the repository, then set up your virtual environment and dependencies:

```bash
# 1. Create virtual environment
python -m venv .venv

# 2. Activate virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# 3. Install project and dependencies in editable mode
pip install -e .
```

> **Always use the venv's Python explicitly, or activate it first.** On
> Windows, a bare `python` on `PATH` can resolve to a different, global
> Python install that doesn't have this project's dependencies — you'll see
> errors like `ModuleNotFoundError: No module named 'opentelemetry.instrumentation'`
> or `No module named 'weave'`. Either run
> `.\.venv\Scripts\Activate.ps1` once per terminal session, or invoke
> `.\.venv\Scripts\python.exe bin\insummery ...` directly.

### 3. Local Credentials (`.env`)

Copy `.env.example` to a root-level `.env` file and fill in the values you
need (Google Calendar OAuth, Vertex AI/Gemini, Weave — see the sections
below for each). This file is gitignored and is loaded automatically by
`app/cli.py` and `app/mcp_server.py` via `python-dotenv`, regardless of the
directory you run commands from — no manual `$env:` exports or shell
sourcing required.

---

## How to Run the Project

### Option A: Local CLI Mode (Zero Cloud Dependencies)
In local mode, the CLI uses local JSON files for storage (`config/profile.json` and `data/matrix.json`) and renders a static HTML dashboard.

1. **Configure your family profile**:
   Create or edit [config/profile.json](file:///c:/Users/tyler/Git/InSummery-AI/config/profile.json) with your family details, children, caregivers, and baseline school hours.

2. **Ingest a scheduling email**:
   ```bash
   python bin/insummery --mode local --input "Emily is registered for Soccer Camp from July 6 to July 10, daily 9:00 to 12:00."
   ```

3. **Ingest a schedule disruption**:
   ```bash
   python bin/insummery --mode local --disruption "Nanny Jessica called out sick for Tuesday July 7th."
   ```

4. **Review the local dashboard**:
   The CLI will automatically generate a static HTML page at `output/schedule.html` and open it in your default web browser.

---

### Option B: Web App Mode (With Firebase Emulator)
In web mode, the application runs a local Firebase emulator suite (Auth, Firestore, Hosting, and Cloud Functions). The frontend is a Vite + React app located in `frontend/`.

1. **Build the frontend**:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```
   Firebase Hosting serves the built app from `frontend/dist`.

   *For frontend development with hot reload, run `npm run dev` inside `frontend/` instead (the dev server runs at `http://localhost:5173` and talks to the Cloud Functions emulator directly; override the API endpoint with a `VITE_API_URL` env var if needed).*

2. **Start the Firebase Emulators**:
   From the project root, run:
   ```bash
   firebase emulators:start
   ```
   This will start:
   - **Hosting** at `http://localhost:5000` (Serving the frontend)
   - **Cloud Functions** at `http://localhost:5001`
   - **Firestore** at `http://localhost:8080` / Emulator UI at `http://localhost:4000`

   > **Note:** the Functions emulator uses a **separate virtualenv** at
   > `functions/venv` (distinct from the root `.venv`), created from
   > `functions/requirements.txt`. If it's stale (e.g. after adding a new
   > dependency there) you'll see the emulator fail to load any function with
   > errors like `ModuleNotFoundError: No module named 'opentelemetry.instrumentation'`.
   > Fix it with:
   > ```bash
   > .\functions\venv\Scripts\python.exe -m pip install -r functions\requirements.txt
   > ```

3. **Access the Web Dashboard**:
   Open your browser and navigate to `http://localhost:5000/`.

4. **Verify the Onboarding Flow**:
   - Sign up with any email and password.
   - You will be prompted with the **Welcome / Onboarding** screen.
   - Enter your family details (parents, children, and nannies).
   - Once completed, the dashboard will render your children's schedule columns.
   - Use the **Family Profile** button in the header to add children or nannies at any time.

---

## Firebase Authentication Setup (Production)

The deployed app signs in against the real Firebase project (configured via
`frontend/.env.production`). If sign-in fails with
`Firebase: Error (auth/configuration-not-found)`, Firebase Authentication has
not been initialized for the project yet. To fix it:

1. Open the [Firebase console](https://console.firebase.google.com/), select
   the project (`in-summery`), and go to **Build > Authentication**.
2. Click **Get started** to initialize Authentication for the project.
3. On the **Sign-in method** tab, enable the **Email/Password** provider and
   the **Google** provider (for Google, set the public-facing app name and a
   support email).
4. On the **Settings > Authorized domains** tab, confirm the domains the app
   is served from are listed (the project's `*.firebaseapp.com` and
   `*.web.app` domains are added automatically; add any custom domain).

No code or config changes are needed after this — the error is entirely a
project-console setting.

---

## Google Calendar OAuth Testing (Local)

Google Calendar sync uses **two different OAuth flows locally**, and each
needs its own OAuth client configured in
[Google Cloud Console](https://console.cloud.google.com/apis/credentials)
(project `in-summery`) with a matching `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
pair:

| Path | Client type | Where credentials go | Redirect URI |
|---|---|---|---|
| CLI / MCP (`app/mcp_server.py`, `InstalledAppFlow`) | **Desktop app** | root `.env` | none to register — loopback `http://localhost:<random-port>/` is allowed automatically for Desktop clients |
| Web app via Firebase emulator (`functions/main.py`) | **Web application** | `functions/.env.local` | `http://localhost:5000/api/oauth/google-calendar/callback` (add under **Authorized redirect URIs** on that client) |

Both `.env` and `functions/.env.local` are gitignored. If you see
`Error 400: redirect_uri_mismatch` in the browser during the web flow, the
redirect URI above hasn't been added to the Web application client yet;
changes can take a few minutes to propagate.

## Vertex AI Setup (Local)

The default local model is `vertex_ai/gemini-2.5-flash` (see
`GEMINI_MODEL`/`resolve_model_spec()` in `app/model_client.py`). Unlike the
Gemini Developer API (AI Studio), **Vertex AI does not use a simple
`GEMINI_API_KEY` string** — it authenticates via Application Default
Credentials (ADC) against a real GCP project.

1. Log in and select a quota project (use your real GCP project ID, e.g.
   `in-summery` — check with `gcloud projects list` if unsure; this is **not**
   necessarily the same as the Firebase alias in `.firebaserc`, which may be a
   local-only placeholder):
   ```bash
   gcloud auth application-default login
   gcloud auth application-default set-quota-project in-summery
   ```
2. Ensure the Vertex AI API is enabled on that project:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=in-summery
   ```
3. Set in your root `.env`:
   ```bash
   GOOGLE_CLOUD_PROJECT=in-summery
   GOOGLE_CLOUD_LOCATION=us-central1
   ```

If instead you want to use the Gemini Developer API (AI Studio) rather than
Vertex AI, set `GEMINI_MODEL=gemini/gemini-2.5-flash` and `GEMINI_API_KEY`
(from [Google AI Studio](https://aistudio.google.com/apikey), **not** a
Google Cloud Console API key like a Firebase browser key — those are for
client-side Firebase SDK calls, not LLM inference) instead of steps 1-3
above.

---

## Google Calendar OAuth Secrets (Production)

The `api` Cloud Function declares two secrets in its decorator
(`functions/main.py`): `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. These
live in **Google Cloud Secret Manager** — Firebase functions secrets *are*
Secret Manager secrets; `firebase functions:secrets:set` is just a wrapper
that writes a new secret version there.

### One-time setup

1. Create the secrets (as a project owner/editor):
   ```bash
   firebase functions:secrets:set GOOGLE_CLIENT_ID --project in-summery
   firebase functions:secrets:set GOOGLE_CLIENT_SECRET --project in-summery
   ```
   Verify they exist in the **`in-summery`** project (not another project —
   the 403 deploy error also fires when the secret simply isn't there):
   ```bash
   gcloud secrets list --project=in-summery
   ```

2. Grant the **CI deploy service account** access to the secrets. During
   `firebase deploy`, the CLI resolves the `latest` secret version and grants
   the function's runtime service account access to it — both require Secret
   Manager permissions on the deploying identity. The deploy service account
   is the `client_email` inside the JSON stored in the
   `FIREBASE_SERVICE_ACCOUNT_KEY` GitHub Actions secret. Grant it
   `roles/secretmanager.admin` scoped to just these two secrets:
   ```bash
   DEPLOY_SA="<client_email from FIREBASE_SERVICE_ACCOUNT_KEY>"
   for s in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET; do
     gcloud secrets add-iam-policy-binding "$s" \
       --project=in-summery \
       --member="serviceAccount:${DEPLOY_SA}" \
       --role="roles/secretmanager.admin"
   done
   ```
   Without this, deploys fail with
   `Permission 'secretmanager.versions.get' denied on resource (or it may not exist)`.

3. Deploy. The CLI automatically grants the function's runtime service
   account `roles/secretmanager.secretAccessor` on the secrets, and the
   values are exposed to the function as environment variables at runtime.

### Rotating a secret

Set a new version, then redeploy functions so they pick it up:
```bash
firebase functions:secrets:set GOOGLE_CLIENT_ID --project in-summery
firebase deploy --only functions --project in-summery
```


## Optional Weave Observability

InSummery can send masked agent traces, guardrail checks, HITL feedback, and
summarized eval results to Weights & Biases Weave. Keep Weave credentials
server-side only; do not add these values to `frontend/.env*` files.

For local CLI and eval runs, copy `.env.example` to `.env` and set:

```bash
WANDB_API_KEY=your_wandb_api_key
WEAVE_PROJECT=your-wandb-entity/insummery-ai
WEAVE_DISABLED=false
```

`WANDB_API_KEY` is optional. When it is absent, or when
`WEAVE_DISABLED=true`, the app skips Weave initialization and runs normally.
When enabled, Weave is initialized with PII redaction and with automatic
integration patching disabled (`implicitly_patch_integrations=False`), so it
does not auto-trace the Google ADK / GenAI SDKs — auto-tracing would capture
the raw email before `pii_mask_node` masks it. The application only records
masked/summarized metadata (status, category, confidence, latency, warnings,
guardrail codes). The existing `PIIMasker` remains the primary privacy
boundary before LLM calls. For deployed Firebase Cloud Functions, configure
`WANDB_API_KEY` and `WEAVE_PROJECT` as backend secrets/environment variables
rather than frontend build variables.

Note that `WEAVE_PROJECT` must include your W&B entity/team (e.g.
`your-entity/insummery-ai`), not just the project name.

### What gets traced

| Op | When |
|----|------|
| `insummery.workflow.pii_mask` | After PII masking |
| `insummery.workflow.agent_call` | After each LLM agent (summary only) |
| `insummery.workflow.confidence_gate` | HIGH vs LOW (HITL) route |
| `insummery.workflow.guardrail` | Post-interpreter structural checks |
| `insummery.workflow.run` | End-of-run status / soft-failure summary |
| `insummery.workflow.hitl_feedback` | Parent clarification + Call feedback |
| `insummery.eval.case` | Per-case eval breadcrumbs |

Optional Presidio defense-in-depth on masked interpreter fields:

```bash
WEAVE_PRESIDIO_GUARDRAIL=true
```

HITL clarifications also grow a sanitized local dataset (no clarification text)
at `data/hitl_feedback_cases.json` and publish to the Weave Dataset
`insummery-hitl-feedback`. Disable with `INSUMMERY_HITL_DATASET_APPEND=false`.

### Publish evals and activate monitors

```bash
insummery-eval run --weave-publish       # Datasets + EvaluationLogger mirror
insummery-eval weave-monitors --dry-run  # preview production monitors
insummery-eval weave-monitors            # activate soft-failure monitors
```

Weave Monitors score agent soft failures (unmatched disruptions, guardrail
fails, HITL rate). Use GCP Cloud Monitoring for HTTP 5xx / function uptime.

Note that `WEAVE_PROJECT` must include your W&B entity/team, not just the
project name (`your-entity/insummery-ai`, not just `insummery-ai`) — find
your entity at [wandb.ai](https://wandb.ai) under your account/team name. You
don't need to pre-create the project in the W&B UI: `weave.init()` creates it
automatically under that entity on the first successful run.

---

## Running Unit Tests

Run the pytest suite to verify all logic (matrix merging, gap analysis, PII masking):

```bash
python -m pytest
```

---

## Agent Evaluation Loop

The LLM-backed agents (triager and interpreter) have a single, unified
evaluation harness with deterministic scoring, absolute quality gates, and
per-model baseline regression tracking. It covers both the agents in
isolation and the full end-to-end ADK workflow (PII mask → triager →
interpreter → confidence gate):

```bash
insummery-eval run                    # run all suites, gate on thresholds + baseline
insummery-eval run --suites workflow  # end-to-end workflow suite only (quick live sanity check)
insummery-eval run --weave-publish    # also mirror scores into Weave Evaluations
insummery-eval baseline               # regenerate the baseline after intentional changes
insummery-eval weave-monitors         # activate Weave soft-failure monitors (requires Weave)
```

Executing the evals requires a `GEMINI_API_KEY` (or a running Ollama
instance). The committed reference baseline is generated against Gemini. See
[tests/eval/README.md](tests/eval/README.md) for suites, metrics, thresholds,
and the baseline policy.

The end-to-end workflow suite also runs automatically as part of
`python -m pytest` (`tests/eval/test_extraction_eval.py`), and is skipped
automatically when no Gemini credential is configured.
