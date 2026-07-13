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


## Optional Weave Observability

InSummery can send masked agent traces and summarized eval results to
Weights & Biases Weave. Keep Weave credentials server-side only; do not add
these values to `frontend/.env*` files.

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
masked agent inputs plus summarized workflow/evaluation metadata. The
existing `PIIMasker` remains the primary privacy boundary before LLM calls. For
deployed Firebase Cloud Functions, configure `WANDB_API_KEY` and `WEAVE_PROJECT`
as backend secrets/environment variables rather than frontend build variables.

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
insummery-eval baseline               # regenerate the baseline after intentional changes
```

Executing the evals requires a `GEMINI_API_KEY` (or a running Ollama
instance). The committed reference baseline is generated against Gemini. See
[tests/eval/README.md](tests/eval/README.md) for suites, metrics, thresholds,
and the baseline policy.

The end-to-end workflow suite also runs automatically as part of
`python -m pytest` (`tests/eval/test_extraction_eval.py`), and is skipped
automatically when no Gemini credential is configured.
