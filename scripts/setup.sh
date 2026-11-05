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

system_python="$(command -v python3 || true)"
if [[ -z "$system_python" ]]; then
  echo "python3 is required (3.11 or newer): the server, the examples and the" >&2
  echo "skills are all built with it." >&2
  exit 1
fi
echo "  $("$system_python" --version)"

# Which Python the server is installed into, and every step below runs with.
#
# One interpreter for all of it, chosen once. This script used to run the
# generators with whatever `python3` was on the path, *before* anything had
# installed the server package they import — and one step hardcoded `python3`
# where the rest used the chosen interpreter. On a fresh clone, step one of the
# README failed:
#
#     build_examples.py → ImportError: travel_a2ui → "pip install a2ui-agent-sdk"
#
# which named the wrong package as well.
#
# A virtualenv rather than the system interpreter, unless one is already
# active: current Debian, Ubuntu and Homebrew Pythons refuse a bare
# `pip install` outright (PEP 668), so installing into the system is not "out
# of the box" anywhere it matters.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  python_bin="$VIRTUAL_ENV/bin/python"
  echo "  using the active virtualenv: $VIRTUAL_ENV"
else
  if [[ ! -x .venv/bin/python ]]; then
    "$system_python" -m venv .venv
  fi
  python_bin="$PWD/.venv/bin/python"
  echo "  using .venv (activate it with: source .venv/bin/activate)"
fi

step "Installing dependencies"
npm install --no-fund --no-audit
# Before anything imports it. The examples compile with the server's own parser
# and the skills are generated through the server's catalog loader.
"$python_bin" -m pip install --quiet --upgrade pip
"$python_bin" -m pip install --quiet -e ./apps/server pytest httpx

step "Generating the catalog, the examples and the skills"
"$python_bin" scripts/build_catalog.py
"$python_bin" scripts/build_examples.py
"$python_bin" scripts/build_skills.py

step "Building"
npm run --silent build

step "Testing"
npm test --silent

"$python_bin" -m pytest tools/tests apps/server/tests -q

cat <<'DONE'

Ready.

  source .venv/bin/activate          # unless you were already in a virtualenv
  uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src

Open http://127.0.0.1:8080 and paste a Gemini API key when asked, or skip the
form entirely:

  http://127.0.0.1:8080/#key=...

The Catalog tab needs no key at all — it draws every component with the A2UI
SDK and no model in the path, so it is the fastest way to see A2UI render.

Other things you can do:

  npm run dev:web           Vite with hot reload, proxying to :8080
  npm run e2e               drive a whole turn in a browser, with a scripted model
  npm run screenshots       regenerate docs/screenshots
  npm run check             every generated file and golden is current

Deploying is a push to main; see docs/deploying.md for Cloud Run.
DONE
