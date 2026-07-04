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

## Running Unit Tests

Run the pytest suite to verify all logic (matrix merging, gap analysis, PII masking):

```bash
python -m pytest
```

---

## Agent Evaluation Loop

The LLM-backed agents (triager and interpreter) have a dedicated evaluation
harness with deterministic scoring, absolute quality gates, and per-model
baseline regression tracking:

```bash
insummery-eval run        # run evals and gate on thresholds + baseline
insummery-eval baseline   # regenerate the baseline after intentional changes
```

Executing the evals requires a `GEMINI_API_KEY` (or a running Ollama
instance). The committed reference baseline is generated against Gemini. See
[tests/eval/README.md](tests/eval/README.md) for metrics, thresholds, and the
baseline policy.

There is also a standalone live smoke-test script, `tests/eval/run_eval.py`,
which runs the real Triager + Interpreter agents through the full ADK
workflow (not just the agents in isolation) against the same curated emails
and reports pass/fail per case. It's a quick way to sanity-check that
`GEMINI_API_KEY` is working end to end and that the workflow's graph wiring
delivers the right input to each node:

```bash
# Requires GEMINI_API_KEY (or GOOGLE_API_KEY) to be set
python -m tests.eval.run_eval

# Run a subset of cases and write a JSON report
python -m tests.eval.run_eval --cases case_01 case_05 --json-report output/eval_report.json
```

The same check also runs automatically as part of `python -m pytest`
(`tests/eval/test_extraction_eval.py`), and is skipped automatically when no
Gemini credential is configured.
