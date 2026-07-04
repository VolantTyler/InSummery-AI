# Project-Scoped Rules & Preferences

## Firebase Setup and Emulators
- **Prerequisite**: The web application relies on the Firebase Emulator Suite (Firestore, Functions, Hosting, Auth) for local development.
- **Global Installation**: Always ensure the Firebase CLI is installed globally. If `firebase` is not recognized, run:
  ```bash
  npm install -g firebase-tools
  firebase login
  ```
- **Starting Emulators**: Use `firebase emulators:start` to run the backend and hosting locally.

## Cursor Cloud specific instructions

The startup update script already installs everything below; do not reinstall. This section captures the non-obvious runtime caveats. Standard commands live in `README.md`.

### Services / how to run
- **Python (root)** is managed by `uv`; the root virtualenv is `.venv`. Run things with `uv run <cmd>` (e.g. `uv run pytest`, `uv run python bin/insummery ...`). `uv` lives at `~/.local/bin/uv` (already on `PATH` via `~/.bashrc`).
- **Tests**: `uv run pytest` (offline; uses an injected fake model for the eval harness).
- **Lint**: `uv run black --check app tests` and `uv run isort --check-only app tests`. Note: the committed code is NOT black/isort-clean, so `--check` reports diffs today — that is expected, not a setup failure. Do not reformat unless asked.
- **CLI app (local mode)**: `uv run python bin/insummery --mode local --input "..."`. Requires `GEMINI_API_KEY`/`GOOGLE_API_KEY` (provided as Cursor secrets). It calls Gemini via LiteLLM unless a local Ollama server is detected. `webbrowser.open()` is a no-op headless; set `BROWSER=true` to silence it. The HTML dashboard is written to `output/schedule.html`.
- **Web app**: `firebase emulators:start --project insummery-ai --only firestore,functions,hosting` (Hosting :5000, Functions :5001, Firestore :8080, UI :4000). Build the frontend first with `npm --prefix frontend run build` (Hosting serves `frontend/dist`); for hot reload use `npm --prefix frontend run dev` (:5173).

### Non-obvious web-app caveats (all already handled, keep them)
- `firebase.json` pins the functions `runtime` to `python312`. Current `firebase-tools` otherwise defaults Python functions to `python314`, which is not installed, and the Functions emulator fails to load. Keep this pin.
- The Cloud Functions emulator uses its OWN virtualenv at `functions/venv`, which must contain both `functions/requirements.txt` AND the repo-root `app` package installed editable (`uv pip install -e .`), because `functions/main.py` does `from app.agent import ...`. The update script maintains this.
- `firebase_admin` needs a constructible credential even against the Firestore emulator. `GOOGLE_APPLICATION_CREDENTIALS` is exported (via `~/.bashrc`) to a fake service-account file at `~/.config/insummery/fake_sa.json`; the emulator transport ignores it, but without it every API call returns HTTP 500 `DefaultCredentialsError`. Ensure this env var is set in whatever shell starts the emulators.
- Frontend auth is mocked client-side (localStorage) because `firebaseConfig.apiKey === "mock-api-key"`; the mock ID token maps every user to backend uid `mock_user`. No Auth emulator is needed. Firestore emulator data is in-memory and cleared on restart.

### Known app-level limitations (NOT environment issues)
- The agent workflow's LLM ingestion may misclassify inputs or fail to persist extracted activities (triager/interpreter node input chaining and HITL state reuse in `app/nodes.py`). This is pre-existing application behavior, independent of the dev environment.

### Harmless noise
- Shells print an nvm warning: "npmrc ... globalconfig/prefix ... incompatible with nvm". This is because `firebase-tools` is installed under `~/.npm-global` (user prefix). It is cosmetic and safe to ignore.
