"""Guard the GitHub Actions Google auth shape without running the workflows."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
AUTH_ACTION = ROOT / ".github" / "actions" / "google-cloud-auth" / "action.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_auth_action_uses_current_major_and_key_fallback():
    action = _load(AUTH_ACTION)
    text = AUTH_ACTION.read_text()
    steps = action["runs"]["steps"]
    uses = [step.get("uses") for step in steps]
    assert uses.count("google-github-actions/auth@v3") == 2
    assert "google-github-actions/setup-gcloud@v3" in uses
    assert "workload_identity_provider" in text
    assert "credentials_json" in text
    assert "service-account.json" not in text
    assert 'echo "$CREDENTIALS_JSON"' not in text
    assert "echo ${CREDENTIALS_JSON}" not in text


def test_eval_job_requests_oidc_and_keeps_key_fallback():
    workflow = _load(WORKFLOWS / "eval-nightly.yml")
    job = workflow["jobs"]["live-eval"]
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["contents"] == "read"
    text = (WORKFLOWS / "eval-nightly.yml").read_text()
    assert "google-github-actions/auth@v2" not in text
    assert "./.github/actions/google-cloud-auth" in text
    assert "secrets.GCP_SA_KEY" in text
    assert "vars.GCP_WIF_PROVIDER" in text
    assert "service-account.json" not in text


def test_deploy_job_does_not_write_a_key_file():
    workflow = _load(WORKFLOWS / "deploy.yml")
    job = workflow["jobs"]["deploy"]
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["contents"] == "read"
    text = (WORKFLOWS / "deploy.yml").read_text()
    assert "service-account.json" not in text
    assert "echo '${{ secrets" not in text
    assert "FIREBASE_SERVICE_ACCOUNT_KEY" in text
    assert "refs/heads/main" in text
    assert "firebase deploy --only hosting,functions,firestore" in text
    assert "GOOGLE_APPLICATION_CREDENTIALS" in text


def test_preview_workflow_skips_forks_and_does_not_use_hosting_action():
    path = WORKFLOWS / "firebase-hosting-pull-request.yml"
    workflow = _load(path)
    # PyYAML 1.1 parses the key "on" as boolean true.
    assert workflow[True] == "pull_request"
    job = workflow["jobs"]["build_and_preview"]
    assert "head.repo.full_name" in job["if"]
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["contents"] == "read"
    assert job["permissions"]["pull-requests"] == "write"
    text = path.read_text()
    assert "uses: FirebaseExtended/action-hosting-deploy" not in text
    assert "hosting:channel:deploy" in text
    assert "secrets.FIREBASE_SERVICE_ACCOUNT_IN_SUMMERY" in text
    assert "vars.GCP_WIF_PROVIDER" in text
    assert "GCP_WIF_PROVIDER_DEPLOY" not in text
