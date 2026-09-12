# Deploying

One server, one target. It serves the API, the MCP endpoint and the built web
client from a single origin — one deploy, one URL, nothing to configure for
cross-origin requests.

| | Server | Target |
| --- | --- | --- |
| **Cloud Run** | `apps/server` (Python) | One Cloud Run service, deployed from `main` |

There used to be two: a TypeScript Worker on Cloudflare and this one. The
cutover is done and the Worker is deleted. What made removing it a non-event was
the goldens in `tools/parity/` — they pinned every layer where two
implementations could silently disagree, so the second one could go without
anybody having to trust that it was safe.

---

## Cloudflare

### From your machine

```bash
npx wrangler login
npm run deploy          # builds, then deploys
```

### From CI

Push to `main`. [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)
runs the tests first and does not deploy a red build.

Two repository secrets:

| Secret | Where to get it |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Cloudflare dashboard → My Profile → API Tokens → Create → **Edit Cloudflare Workers** template |
| `CLOUDFLARE_ACCOUNT_ID` | Workers & Pages → the sidebar |

---

## Cloud Run

### What gets built

The `Dockerfile` at the repository root is two stages. Node builds the React
client; Python runs it. The toolchain does not travel into the runtime image —
Cloud Run pulls the image on every cold start, so its size is startup latency
and not merely registry space.

The front ends are built in the image rather than committed. A `dist/` in git is
a second copy of the app that stays right until someone forgets, and the way you
find out is a deploy serving last week's interface against this week's API.

### One-time setup

You need a Google Cloud project with billing enabled, and these APIs on:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com
```

An Artifact Registry repository to push images to:

```bash
gcloud artifacts repositories create travel-a2ui \
  --repository-format=docker \
  --location=us-central1
```

### Letting GitHub deploy without a key

The workflow authenticates with **Workload Identity Federation**, so no
service-account JSON key is stored in this repository or anywhere else. GitHub
mints a short-lived token describing the workflow that is running; Google
verifies it and hands back credentials that expire in an hour.

This matters more than it sounds. A service-account key in a repository secret
is a permanent credential that cannot be rotated by whoever eventually finds it
in a log, a fork, or a screenshot.

```bash
PROJECT_ID=your-project
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
REPO=vpm238/travel-a2ui           # owner/repo that is allowed to deploy

# 1. A pool, and a provider inside it that trusts GitHub's token issuer.
gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --display-name="GitHub" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '${REPO}'"

# The attribute-condition is not optional. Without it the provider trusts a
# token from *any* repository on GitHub, which is a stranger's pull request
# away from deploying to your project.

# 2. The account the workflow acts as.
gcloud iam service-accounts create travel-a2ui-deployer \
  --display-name="travel-a2ui deployer"

SA="travel-a2ui-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role="$role"
done

# 3. Let that one repository impersonate that one account.
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"

echo "WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
echo "WIF_SERVICE_ACCOUNT=${SA}"
```

Three roles, and each is needed for one step: **Cloud Run Admin** to create and
update the service, **Artifact Registry Writer** to push the image, and
**Service Account User** because deploying a Cloud Run service means telling it
which identity to run as, which counts as using that account.

### Repository settings

| Name | Kind | Example |
| --- | --- | --- |
| `GCP_PROJECT_ID` | variable | `my-project` |
| `GCP_REGION` | variable | `us-central1` |
| `WIF_PROVIDER` | secret | `projects/123.../providers/github` |
| `WIF_SERVICE_ACCOUNT` | secret | `travel-a2ui-deployer@my-project.iam.gserviceaccount.com` |

The workflow checks all four before doing anything, so a missing one is a
message in the first ten seconds rather than an obscure `gcloud` error three
minutes into a build.

### Running it

Actions → **travel-a2ui Cloud Run** → Run workflow.

Deliberately manual. The Worker is still the thing on the public URL, and two
deploys racing to serve the same users on every push is how a demo becomes
unexplainable. Once the cutover is done, change `on:` to `push: branches: [main]`.

### The one setting not to change without reading this

```
--max-instances 1
```

That is a **correctness** constraint, not a cost one.

Conversations live in the server's memory. Nothing is written to disk, which is
what "we do not store your conversation beyond the session" has to mean if it
means anything — but it also means a second instance would hold a second,
entirely separate set of conversations. A traveller whose next request happened
to land on the other instance would find their trip gone, intermittently, in a
way that looks exactly like the model forgetting.

To raise it, give the sessions somewhere shared to live first: put
`SessionStore` behind Firestore, Redis or Cloud SQL. The interface in
`apps/server/src/travel_a2ui/sessions.py` is small and nothing above it would
change — the store is already the only thing that knows how a session is kept.

### The other two settings worth knowing

`--timeout 600` — a turn is a streamed SSE response held open for as long as the
model takes to answer. The 5-minute default cuts a slow one off mid-sentence.

No `GEMINI_API_KEY` is set. Every visitor brings their own, which is what lets
this run as a public demo that costs its owner nothing and stores nobody's
credential. To run a shared deployment on one key instead:

```bash
gcloud run services update travel-a2ui --set-env-vars GEMINI_API_KEY=...
```

The app then stops asking — `/api/meta` reports `keyProvided: true` and the
client hides the form.

---

## After a deploy

Whichever target, check the same three things:

```bash
curl -fsS https://<url>/healthz              # the process is up
curl -fsS https://<url>/api/meta | jq .      # the catalog and skills loaded
open https://<url>                           # a surface actually renders
```

`/healthz` returning 200 means the container started. `/api/meta` returning a
catalog means it found its data files, which is the failure a container image
gets wrong first. Only the third tells you the app works.
