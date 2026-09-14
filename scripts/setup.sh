#!/usr/bin/env bash
#
# One command to go from a fresh clone to a running app.
#
#   ./scripts/setup.sh
#
# Installs, regenerates everything that is generated, builds, tests, and then
# tells you what to run. It is idempotent — running it again after editing the
# catalog is the normal way to pick up the change.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m→ %s\033[0m\n' "$1"; }
warn() { printf '\033[33m  %s\033[0m\n' "$1"; }

step "Checking prerequisites"
node_version="$(node --version 2>/dev/null || true)"
if [[ -z "$node_version" ]]; then
  echo "Node is required (22 or newer). https://nodejs.org" >&2
  exit 1
fi
major="${node_version#v}"
major="${major%%.*}"
if (( major < 20 )); then
  echo "Node $node_version is too old; 20 or newer is required." >&2
  exit 1
fi
echo "  node $node_version"

python_bin="$(command -v python3 || true)"
if [[ -z "$python_bin" ]]; then
  warn "python3 not found — the skill generator will be skipped."
else
  echo "  $("$python_bin" --version)"
fi

step "Installing dependencies"
npm install --no-fund --no-audit

step "Generating the catalog, the examples and the skills"
if [[ -n "$python_bin" ]]; then
  "$python_bin" scripts/build_catalog.py
else
  warn "skipped: the catalog is checked in, so this only matters if you edited it"
fi

# The example compiler is the TypeScript one, so it has to exist first.
npm run --silent build -w @travel-a2ui/express
python3 scripts/build_examples.py

if [[ -n "$python_bin" ]]; then
  "$python_bin" scripts/build_skills.py
else
  warn "skipped: the skills are checked in"
fi

step "Building"
npm run --silent build

step "Testing"
npm test --silent

if [[ -n "$python_bin" ]] && "$python_bin" -c 'import pytest' 2>/dev/null; then
  "$python_bin" -m pytest tools/tests -q
else
  warn "pytest not installed — skipping the Python tests (pip install pytest)"
fi

cat <<'DONE'

Ready.

  uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src

Open http://127.0.0.1:8080 and paste a Gemini API key when asked, or skip the
form entirely:

  http://127.0.0.1:8080/#key=...

The Catalog tab needs no key at all — it draws every component with the real
renderer and no model in the path, so it is the fastest way to see A2UI render.

Other things you can do:

  npm run dev:web           Vite with hot reload, proxying to :8080
  npm run e2e               drive a whole turn in a browser, with a scripted model
  npm run screenshots       regenerate docs/screenshots
  npm run deploy            ship it to Cloudflare
DONE
