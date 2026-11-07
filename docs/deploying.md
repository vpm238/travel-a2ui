# Deploying

One server, one target. It serves the API, the React client, the Flutter web
client and the quickstart site from a single origin — one deploy, one URL,
nothing to configure for cross-origin requests.

| | Server | Target |
| --- | --- | --- |
| **Cloud Run** | `apps/server` (Python) | One Cloud Run service, deployed from `main` |

The workflow is `.github/workflows/travel-a2ui-cloudrun.yml` in the development
repository and `.github/workflows/cloudrun.yml` in the published one; it shows
up in Actions as **travel-a2ui Cloud Run**.

---

## Cloud Run

### What gets built

The `Dockerfile` at the repository root builds in stages: Node builds the React
client and the quickstart site, a Flutter stage builds the Flutter web client
(served under `/flutter/`), and a Python stage runs the server. The toolchains
do not travel into the runtime image —
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
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository == '${REPO}' && assertion.ref == 'refs/heads/main'"

# The attribute-condition is not optional. Without the repository half the
# provider trusts a token from *any* repository on GitHub; without the ref half,
# any branch of yours can deploy. The deploy runs from `main` only.

# 2. The account the workflow acts as.
gcloud iam service-accounts create travel-a2ui-deployer \
  --display-name="travel-a2ui deployer"

SA="travel-a2ui-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

for role in roles/run.developer roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA}" --role="$role"
done

# 2b. The account the service itself runs as: no project roles at all. The app
#     calls Gemini with the visitor's key (or GEMINI_API_KEY), not as itself.
gcloud iam service-accounts create travel-a2ui-runtime \
  --display-name="travel-a2ui runtime"
RUNTIME_SA="travel-a2ui-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

# 3. Let that one repository impersonate that one account.
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"

# 4. The deployer may act as the runtime account, and only that one.
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --role=roles/iam.serviceAccountUser --member="serviceAccount:${SA}"

echo "WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github"
echo "WIF_SERVICE_ACCOUNT=${SA}"
echo "RUNTIME_SERVICE_ACCOUNT=${RUNTIME_SA}"
```

Each grant is needed for one step: **Cloud Run Developer** to create and update
the service, **Artifact Registry Writer** to push the image, and **Service
Account User** on the runtime account alone, because deploying a service names
the identity it runs as. Nothing is granted project-wide that the deploy does
not use. (Cloud Run Developer cannot make a service public; run the first
deploy, or `gcloud run services add-iam-policy-binding travel-a2ui
--member=allUsers --role=roles/run.invoker`, as an owner once.)

### Repository settings

| Name | Kind | Example |
| --- | --- | --- |
| `GCP_PROJECT_ID` | variable | `my-project` |
| `GCP_REGION` | variable | `us-central1` |
| `WIF_PROVIDER` | secret | `projects/123.../providers/github` |
| `WIF_SERVICE_ACCOUNT` | secret | `travel-a2ui-deployer@my-project.iam.gserviceaccount.com` |
| `RUNTIME_SERVICE_ACCOUNT` | variable, recommended | `travel-a2ui-runtime@my-project.iam.gserviceaccount.com`; without it the service runs as the default compute account, and the deploy says so |
| `GOOGLE_MAPS_API_KEY` | secret, optional | a browser key restricted by HTTP referrer, for the map components |

The workflow checks the first four before doing anything, so a missing one is a
message in the first ten seconds rather than an obscure `gcloud` error three
minutes into a build.

### Running it

A push to `main` deploys once CI has passed on it: the deploy workflow runs when
**travel-a2ui CI** completes successfully, and builds the commit CI tested. A
red CI deploys nothing. Actions → **travel-a2ui Cloud Run** → Run workflow runs it
by hand as well, for a re-deploy without a commit.

The build ends with `RUN python -c "import travel_a2ui.doors.http"`, and that
line is worth keeping. Everything above it can succeed and still produce a
container that cannot start — a module reading a data file nobody copied, a
static mount pointing at a directory that is not there. Cloud Run reports all of
it identically ("failed to start and listen on the port"), several minutes after
the build went green, in a log the deploy does not show you. Importing the app at
build time turns that into a build failure that names the file.

### The one setting not to change without reading this

```
--max-instances 1
```

That is a **correctness** constraint, not a cost one.

Conversations live in the server's memory. Nothing is written to disk, which is
what "we do not store your conversation beyond the session" has to mean if it
means anything. Each typed turn ends with a `resume` receipt the client hands
back — the Gemini interaction, the trip and the prompt it was started against —
so a turn that lands on another instance still continues the same conversation.
What does not travel is the rest of the session: the server's mirror of what the
renderer holds (`Canvas`), and a voice call's Live resumption handle. On a
second instance those start empty, the panel is drawn again, and a call starts
a fresh Live session.

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

**A shared key makes every visitor's turn yours to pay for.** The server limits
what it will do on it (`doors/guard.py`): a client may only choose a model and
effort the server advertises, the voice socket only accepts browsers from this
site or `ALLOWED_ORIGINS`, and each address gets `SHARED_KEY_TURNS_PER_HOUR`
turns (default 60) on the shared key before it is asked for its own. That is a
brake, not access control: for a deployment that must not be public, put it
behind [IAP](https://cloud.google.com/iap/docs/enabling-cloud-run) or an API
gateway, and give the key a quota in Google AI Studio.

`GOOGLE_MAPS_API_KEY`, when the repository secret is set, is passed through to
the service and handed to the page by `/api/meta`, because the browser is what
loads the Maps library. Restrict it by HTTP referrer rather than keeping it
secret.

---

## After a deploy

Check the same three things:

```bash
curl -fsS https://<url>/healthz              # the process is up
curl -fsS https://<url>/api/meta | jq .      # the catalog and skills loaded
open https://<url>                           # a surface actually renders
```

`/healthz` returning 200 means the container started. `/api/meta` returning a
catalog means it found its data files, which is the failure a container image
gets wrong first. Only the third tells you the app works.
