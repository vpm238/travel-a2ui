#!/usr/bin/env bash
#
# Sets up and starts Travel A2UI with the client you choose.
#
#   ./scripts/quickstart.sh react      Python server + React web client
#   ./scripts/quickstart.sh flutter    Python server + Flutter client
#   ./scripts/quickstart.sh both       Python server + both clients
#
# Needs Python 3.11+, plus Node 20+ for React and Flutter 3.47+ for Flutter.
# Then open http://127.0.0.1:8080 (React) or http://127.0.0.1:8080/flutter/.
# Set PORT to use another port. Run it again at any time; it picks up changes.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

client="${1:-}"
port="${PORT:-8080}"

case "$client" in
  react | flutter | both) ;;
  *)
    echo "Usage: ./scripts/quickstart.sh react|flutter|both" >&2
    exit 2
    ;;
esac

step() { printf '\n\033[1;36m→ %s\033[0m\n' "$1"; }
fail() {
  echo "$1" >&2
  exit 1
}
wants() { [[ "$client" == "$1" || "$client" == "both" ]]; }

step "Checking what is installed"
command -v python3 >/dev/null || fail "Python 3.11 or newer is required: https://www.python.org/downloads/"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
  fail "Python 3.11 or newer is required; this is $(python3 --version)."
echo "  $(python3 --version)"
if wants react; then
  command -v node >/dev/null || fail "Node 20 or newer is required for React: https://nodejs.org"
  node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' ||
    fail "Node 20 or newer is required for React; this is $(node --version)."
  echo "  node $(node --version)"
fi
if wants flutter; then
  command -v flutter >/dev/null ||
    fail "Flutter 3.47 or newer is required: https://docs.flutter.dev/get-started/install"
  echo "  $(flutter --version 2>/dev/null | head -n 1)"
fi

step "The Python server"
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  python="$VIRTUAL_ENV/bin/python"
else
  [[ -x .venv/bin/python ]] || python3 -m venv .venv
  python="$PWD/.venv/bin/python"
fi
"$python" -m pip install --quiet --upgrade pip
"$python" -m pip install --quiet -r apps/server/requirements.lock
"$python" -m pip install --quiet --no-deps -e apps/server
echo "  installed into ${VIRTUAL_ENV:-.venv}"

if wants react; then
  step "The React client"
  npm ci --no-fund --no-audit --loglevel=error
  npm run --silent build
fi

if wants flutter; then
  step "The Flutter client"
  (cd renderers/flutter && flutter pub get >/dev/null && flutter build web --release --base-href=/flutter/)
fi

step "Starting on port $port"
wants react && echo "  React:   http://127.0.0.1:$port"
wants flutter && echo "  Flutter: http://127.0.0.1:$port/flutter/"
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "  No GEMINI_API_KEY set: paste a key into the app when it asks."
fi
echo "  Stop with Ctrl+C."
echo
exec "$python" -m uvicorn travel_a2ui.doors.http:app --host 127.0.0.1 --port "$port" --app-dir apps/server/src
