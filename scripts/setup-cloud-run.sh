#!/usr/bin/env bash
#
# Sets up a Google Cloud project to accept deploys from GitHub, and prints the
# four settings the workflow needs.
#
# Two of those four are values you look up; the other two do not exist until
# this has run, which is the thing that makes the setup confusing the first
# time. `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` are created here.
#
# Run it in Cloud Shell, or anywhere `gcloud` is logged in:
#
#     ./scripts/setup-cloud-run.sh [project-id] [region]
#
# Safe to run more than once: every step checks for what it would create and
# says so rather than failing. That matters because the interesting failure
# mode is a half-finished setup — a pool with no provider, a service account
# with two of its three roles — which produces an authentication error at
# deploy time with nothing pointing at the missing piece.
#
# Nothing here is secret in the sense of a password. A Workload Identity
# provider is a *rule* — "GitHub may act as this account, but only from this
# repository" — and no key is created, stored or downloaded. That is the whole
# reason to prefer it: a service-account JSON key is a permanent credential
# that cannot be rotated by whoever eventually finds it in a log.

set -euo pipefail

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${2:-us-central1}"

# The repository allowed to deploy. Change this if you fork.
REPO="${REPO:-vpm238/travel-a2ui}"

POOL="github"
PROVIDER="github"
SA_NAME="travel-a2ui-deployer"
ARTIFACT_REPO="travel-a2ui"

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  cat >&2 <<'MISSING'
No project id.

Find it in the Google Cloud console: the project selector at the top of the
page shows the *name*, and underneath it the **ID** — they are often different,
and the ID is the one to use here. Or:

    gcloud projects list

Then:

    ./scripts/setup-cloud-run.sh your-project-id
MISSING
  exit 1
fi

echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo "Repo    : $REPO"
echo

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
say "1. APIs"
# ---------------------------------------------------------------------------
# Cloud Run to host it, Artifact Registry to hold the image, IAM Credentials to
# let GitHub impersonate the deployer. Enabling an already-enabled API is a
# no-op, so this is not guarded.
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  --project "$PROJECT_ID"
echo "   enabled"

# ---------------------------------------------------------------------------
say "2. Somewhere to push the image"
# ---------------------------------------------------------------------------
if gcloud artifacts repositories describe "$ARTIFACT_REPO" \
     --location="$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "   $ARTIFACT_REPO already exists in $REGION"
else
  gcloud artifacts repositories create "$ARTIFACT_REPO" \
    --repository-format=docker --location="$REGION" --project "$PROJECT_ID"
  echo "   created"
fi

# ---------------------------------------------------------------------------
say "3. A pool, and a provider that trusts GitHub"
# ---------------------------------------------------------------------------
if gcloud iam workload-identity-pools describe "$POOL" \
     --location=global --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "   pool '$POOL' already exists"
else
  gcloud iam workload-identity-pools create "$POOL" \
    --location=global --display-name="GitHub Actions" --project "$PROJECT_ID"
  echo "   pool created"
fi

# The attribute-condition is the security boundary and is not optional. Without
# it the provider trusts a token from *any* repository on GitHub, which is one
# stranger's pull request away from deploying to this project.
if gcloud iam workload-identity-pools providers describe "$PROVIDER" \
     --location=global --workload-identity-pool="$POOL" \
     --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "   provider '$PROVIDER' already exists"
  echo "   (if you changed REPO, update its --attribute-condition by hand:"
  echo "    gcloud iam workload-identity-pools providers update-oidc $PROVIDER \\"
  echo "      --location=global --workload-identity-pool=$POOL \\"
  echo "      --attribute-condition=\"assertion.repository == '$REPO'\")"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" \
    --display-name="GitHub" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${REPO}'" \
    --project "$PROJECT_ID"
  echo "   provider created, scoped to $REPO"
fi

# ---------------------------------------------------------------------------
say "4. The account the workflow acts as"
# ---------------------------------------------------------------------------
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "$SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "   $SA already exists"
else
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="travel-a2ui deployer" --project "$PROJECT_ID"
  echo "   created"
fi

# Three roles, one per step of the deploy: create and update the service, push
# the image, and tell Cloud Run which identity the service runs as — which
# counts as *using* that account and is why the third is needed.
for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role="$role" --condition=None >/dev/null
  echo "   $role"
done

# ---------------------------------------------------------------------------
say "5. Let that repository impersonate that account"
# ---------------------------------------------------------------------------
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --project "$PROJECT_ID" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  >/dev/null
echo "   $REPO may now act as $SA_NAME"

# ---------------------------------------------------------------------------
cat <<SETTINGS

────────────────────────────────────────────────────────────────────────────
Done. Put these in GitHub → the repository → Settings →
Secrets and variables → Actions.

  Variables tab
    GCP_PROJECT_ID        ${PROJECT_ID}
    GCP_REGION            ${REGION}

  Secrets tab
    WIF_PROVIDER          projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}
    WIF_SERVICE_ACCOUNT   ${SA}

Then: Actions → "travel-a2ui Cloud Run" → Run workflow.

The bottom two are not passwords and not keys — nothing was downloaded here.
They name a rule that says GitHub may act as this account, and only from
${REPO}. They are secrets rather than variables because naming your
infrastructure in public invites people to probe it, not because knowing them
grants anything.
────────────────────────────────────────────────────────────────────────────
SETTINGS
