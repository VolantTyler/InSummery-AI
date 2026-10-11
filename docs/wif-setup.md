# GitHub Actions Workload Identity Federation

GitHub Actions for this repo authenticates to Google Cloud with
[Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
(`google-github-actions/auth` v3). Service-account JSON keys stay in place
only until a workflow log shows `Google auth path: workload identity federation`.

Do not merge this until you have run the steps below. This file does not
create the pool, bind IAM, or change GitHub secrets.

## Which project

The workflows deploy and call Vertex in **`in-summery`**. That id is hardcoded
in `.github/workflows/deploy.yml` and
`.github/workflows/firebase-hosting-pull-request.yml`, and it is the project
in the Vertex section of `README.md`.

`.firebaserc` `projects.default` is `insummery-ai`. That alias is the local
emulator placeholder. Do not create the pool there.

`firebase.json` deploys three things, and only these:

- `hosting` → `frontend/dist`
- `functions` → Python Cloud Functions (2nd gen). `functions/main.py` declares
  secrets `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `WANDB_API_KEY`
- `firestore` → `firestore.rules` only (no indexes file)

## What the workflows read

| Variable | Used by |
|---|---|
| `GCP_WIF_PROVIDER` | eval, Hosting preview, and deploy when the deploy-specific provider is unset |
| `GCP_WIF_PROVIDER_DEPLOY` | deploy only, if you create the main-branch provider |
| `GCP_EVAL_SERVICE_ACCOUNT` | nightly eval (falls back to `GCP_SERVICE_ACCOUNT`) |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `firebase deploy` (falls back to `GCP_SERVICE_ACCOUNT`) |
| `GCP_PREVIEW_SERVICE_ACCOUNT` | Hosting preview (falls back to the deploy account, then `GCP_SERVICE_ACCOUNT`) |
| `GCP_PROJECT` | optional; workflows default to `in-summery` |
| `GCP_LOCATION` | optional; eval defaults to `us-central1` |

`GCP_SERVICE_ACCOUNT` is a single-account shortcut. One account cannot both
deploy production only from `main` and publish pull-request previews. Use the
three accounts below if you want that split.

JSON keys, still secrets, used only when the matching WIF variables are
missing or the auth action fails:

- `GCP_SA_KEY` — eval
- `FIREBASE_SERVICE_ACCOUNT_KEY` — deploy, and only when the ref is `refs/heads/main`
- `FIREBASE_SERVICE_ACCOUNT_IN_SUMMERY` — Hosting preview

Account ids created below:

- `github-eval@in-summery.iam.gserviceaccount.com`
- `github-deploy@in-summery.iam.gserviceaccount.com`
- `github-preview@in-summery.iam.gserviceaccount.com`

Checked on 2026-10-11 against `VolantTyler/InSummery-AI`: `repository_id`
`1284164591`, `repository_owner_id` `33227593`. Re-read them before creating
the provider. If either number differs, put the new value in the attribute
condition.

## 1. Confirm the repo ids

```bash
gh api repos/VolantTyler/InSummery-AI --jq '{repository_id: .id, repository_owner_id: .owner.id}'
```

## 2. Read the project number

The provider resource name uses the project **number**, not `in-summery`.

```bash
gcloud projects describe in-summery --format='value(projectNumber)'
```

Replace `<PROJECT_NUMBER>` below with that number.

## 3. Enable APIs

```bash
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com aiplatform.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com firestore.googleapis.com firebaserules.googleapis.com cloudfunctions.googleapis.com run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com --project=in-summery
```

## 4. Create the service accounts

```bash
gcloud iam service-accounts create github-eval --project=in-summery --display-name="GitHub Actions eval"
```

```bash
gcloud iam service-accounts create github-deploy --project=in-summery --display-name="GitHub Actions deploy"
```

```bash
gcloud iam service-accounts create github-preview --project=in-summery --display-name="GitHub Actions hosting preview"
```

## 5. Create the pool and the repo provider

Issuer: `https://token.actions.githubusercontent.com`.

Attribute condition (this repo only; ids are immutable if the repo is renamed):

```text
assertion.repository=='VolantTyler/InSummery-AI' && assertion.repository_owner_id=='33227593' && assertion.repository_id=='1284164591'
```

```bash
gcloud iam workload-identity-pools create github --project=in-summery --location=global --display-name="GitHub Actions"
```

```bash
gcloud iam workload-identity-pools providers create-oidc github --project=in-summery --location=global --workload-identity-pool=github --display-name="VolantTyler/InSummery-AI" --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.repository_owner_id=assertion.repository_owner_id,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" --attribute-condition="assertion.repository=='VolantTyler/InSummery-AI' && assertion.repository_owner_id=='33227593' && assertion.repository_id=='1284164591'"
```

```bash
gcloud iam workload-identity-pools providers describe github --project=in-summery --location=global --workload-identity-pool=github --format='value(name)'
```

The describe output is `<WIF_PROVIDER_RESOURCE>`. It looks like
`projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/providers/github`.

If `create-oidc` is denied by organization policy, an org admin must allow the
issuer, then rerun step 5:

```bash
gcloud resource-manager org-policies allow constraints/iam.workloadIdentityPoolProviders https://token.actions.githubusercontent.com --project=in-summery
```

## 6. Restrict deploy to main

Pull-request previews run with ref `refs/pull/<n>/merge`. Nightly eval and
`workflow_dispatch` of the eval can run on other branches. A provider
condition that requires `assertion.ref=='refs/heads/main'` would reject those
tokens. Deploy is the workflow that should be limited to main.

Two controls, and what each one actually stops:

- **Provider attribute condition** (optional second provider `github-main`).
  The token is rejected before any service account can be impersonated
  through that provider. This is the stronger door. It does not by itself
  stop the general `github` provider. Deploy uses
  `GCP_WIF_PROVIDER_DEPLOY` when that variable is set, and
  `GCP_WIF_PROVIDER` otherwise. A too-broad IAM binding on the deploy
  account would still allow a non-main token from the general provider.
- **IAM principal on the deploy account** (do this either way). Bind
  `roles/iam.workloadIdentityUser` to the exact subject
  `repo:VolantTyler/InSummery-AI:ref:refs/heads/main`, not to the whole
  repository. `principalSet` members match one attribute, so a binding on
  `attribute.ref` / `refs/heads/main` is not repo-scoped unless the provider
  condition already requires this repository. The subject string contains
  the repository, so it stays repo-specific. Pull-request tokens use subject
  `repo:VolantTyler/InSummery-AI:pull_request` and will not match.
  `workflow_dispatch` of deploy from a branch other than main will not match
  either. The JSON key fallback is also withheld unless
  `github.ref` is `refs/heads/main`.

Eval and preview stay on the repository `principalSet`, so manual evals and
same-repo pull requests can impersonate their own accounts. Fork pull
requests never run the preview job, so they never get an OIDC token.

Create the optional main-only provider:

```bash
gcloud iam workload-identity-pools providers create-oidc github-main --project=in-summery --location=global --workload-identity-pool=github --display-name="VolantTyler/InSummery-AI main" --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.repository_owner_id=assertion.repository_owner_id,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" --attribute-condition="assertion.repository=='VolantTyler/InSummery-AI' && assertion.repository_owner_id=='33227593' && assertion.repository_id=='1284164591' && assertion.ref=='refs/heads/main'"
```

```bash
gcloud iam workload-identity-pools providers describe github-main --project=in-summery --location=global --workload-identity-pool=github --format='value(name)'
```

That output is `<DEPLOY_PROVIDER_RESOURCE>`.

## 7. Let GitHub impersonate the service accounts

Eval and preview, any workflow in this repo that the provider admits:

```bash
gcloud iam service-accounts add-iam-policy-binding github-eval@in-summery.iam.gserviceaccount.com --project=in-summery --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/attribute.repository/VolantTyler/InSummery-AI"
```

```bash
gcloud iam service-accounts add-iam-policy-binding github-preview@in-summery.iam.gserviceaccount.com --project=in-summery --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/attribute.repository/VolantTyler/InSummery-AI"
```

Deploy, main only:

```bash
gcloud iam service-accounts add-iam-policy-binding github-deploy@in-summery.iam.gserviceaccount.com --project=in-summery --role=roles/iam.workloadIdentityUser --member="principal://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github/subject/repo:VolantTyler/InSummery-AI:ref:refs/heads/main"
```

## 8. Grant product roles

Eval only needs Vertex AI User. Do not add Cloud Trace; the nightly workflow
sets `INSUMMERY_DISABLE_CLOUD_TRACE=true` because this role lacks
`cloudtrace.traces.patch`.

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-eval@in-summery.iam.gserviceaccount.com --role=roles/aiplatform.user
```

Deploy, from `firebase.json` (`hosting`, `functions`, `firestore` rules):

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/firebasehosting.admin
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/firebaserules.admin
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/firebase.viewer
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/cloudfunctions.admin
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/run.admin
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/artifactregistry.writer
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/cloudbuild.builds.editor
```

`firebase.json` does not set a function runtime service account, so deploy
acts as the default compute account. Replace `<PROJECT_NUMBER>` first.

```bash
gcloud iam service-accounts add-iam-policy-binding <PROJECT_NUMBER>-compute@developer.gserviceaccount.com --project=in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/iam.serviceAccountUser
```

The function's secret list is `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and
`WANDB_API_KEY`. Deploy reads the latest version and grants the runtime
account accessor, which needs `roles/secretmanager.admin` on each secret.

```bash
gcloud secrets add-iam-policy-binding GOOGLE_CLIENT_ID --project=in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/secretmanager.admin
```

```bash
gcloud secrets add-iam-policy-binding GOOGLE_CLIENT_SECRET --project=in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/secretmanager.admin
```

```bash
gcloud secrets add-iam-policy-binding WANDB_API_KEY --project=in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/secretmanager.admin
```

Preview only deploys a Hosting channel:

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-preview@in-summery.iam.gserviceaccount.com --role=roles/firebasehosting.admin
```

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-preview@in-summery.iam.gserviceaccount.com --role=roles/firebase.viewer
```

If function deploy then fails with `iam.serviceAccounts.actAs` on the Cloud
Build account, grant the deploy account `roles/iam.serviceAccountUser` there
too:

```bash
gcloud iam service-accounts add-iam-policy-binding <PROJECT_NUMBER>@cloudbuild.gserviceaccount.com --project=in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/iam.serviceAccountUser
```

If it fails with `storage.objects.create`, grant object admin on the project
and rerun deploy. Do not grant `roles/firebase.admin` to skip past the error.

```bash
gcloud projects add-iam-policy-binding in-summery --member=serviceAccount:github-deploy@in-summery.iam.gserviceaccount.com --role=roles/storage.objectAdmin
```

## 9. Set repository variables

These are variables, not secrets. The provider resource name and the service
account email are not credentials.

```bash
gh variable set GCP_WIF_PROVIDER --repo VolantTyler/InSummery-AI --body "<WIF_PROVIDER_RESOURCE>"
```

```bash
gh variable set GCP_WIF_PROVIDER_DEPLOY --repo VolantTyler/InSummery-AI --body "<DEPLOY_PROVIDER_RESOURCE>"
```

```bash
gh variable set GCP_EVAL_SERVICE_ACCOUNT --repo VolantTyler/InSummery-AI --body "github-eval@in-summery.iam.gserviceaccount.com"
```

```bash
gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo VolantTyler/InSummery-AI --body "github-deploy@in-summery.iam.gserviceaccount.com"
```

```bash
gh variable set GCP_PREVIEW_SERVICE_ACCOUNT --repo VolantTyler/InSummery-AI --body "github-preview@in-summery.iam.gserviceaccount.com"
```

```bash
gh variable set GCP_PROJECT --repo VolantTyler/InSummery-AI --body "in-summery"
```

```bash
gh variable set GCP_LOCATION --repo VolantTyler/InSummery-AI --body "us-central1"
```

Leave the JSON key secrets in place for the next run. IAM can take a few
minutes to propagate.

## 10. Delete the JSON keys only after a WIF run succeeds

Run the nightly eval with `workflow_dispatch` (or wait for the schedule) and
read the log. You want `Google auth path: workload identity federation` and
`Using Vertex AI`. A line that says `service account JSON key` means the
fallback ran; do not delete keys yet.

Then delete the key secrets:

```bash
gh secret delete GCP_SA_KEY --repo VolantTyler/InSummery-AI
```

```bash
gh secret delete FIREBASE_SERVICE_ACCOUNT_KEY --repo VolantTyler/InSummery-AI
```

```bash
gh secret delete FIREBASE_SERVICE_ACCOUNT_IN_SUMMERY --repo VolantTyler/InSummery-AI
```

Disable or delete the key material on the old service accounts in GCP as
well. Deleting the GitHub secret does not delete the key in Google Cloud.

## Gemini API key

`GEMINI_API_KEY` is an AI Studio key. Workload Identity Federation cannot
mint it.

The eval harness already runs on Vertex without that key. `resolve_model_spec()`
in `app/model_client.py` defaults to `vertex_ai/gemini-2.5-flash`, which uses
ADC plus `GOOGLE_CLOUD_PROJECT` / `VERTEXAI_PROJECT`. `eval-nightly.yml` sets
those, and `GEMINI_MODEL`, when the auth action succeeds. No new repository
variable is required.

The API key is used only when Google auth does not succeed. The workflow then
sets `GEMINI_MODEL=gemini/gemini-2.5-flash` and warns. After a nightly run
actually takes the Vertex path, delete the key:

```bash
gh secret delete GEMINI_API_KEY --repo VolantTyler/InSummery-AI
```

Until that run is green, leave the secret. The job is supposed to keep
scoring rather than go dark while WIF is still being wired.
