#!/usr/bin/env bash
#
# Copies this project out into a standalone repository.
#
# It lives inside llm-module-runtime/ during development, which means its
# GitHub Actions workflows sit at the parent repository's root with a
# `working-directory: travel-a2ui` prefix. A standalone repo does not want that
# prefix, so this script moves the workflows up and strips it.
#
#   ./scripts/extract-repo.sh ~/code/travel-a2ui
#   cd ~/code/travel-a2ui && git init && git add -A && git commit -m "Initial commit"
#
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 <destination-directory>" >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$HERE")"

if [[ -e "$TARGET" && -n "$(ls -A "$TARGET" 2>/dev/null)" ]]; then
  echo "$TARGET exists and is not empty. Refusing to overwrite it." >&2
  exit 1
fi

mkdir -p "$TARGET"

echo "Copying the project…"
# Everything except build output and local state. Using tar rather than cp -r
# keeps the exclusions in one readable list.
tar -C "$HERE" \
  --exclude='./node_modules' \
  --exclude='./.venv' \
  --exclude='**/node_modules' \
  --exclude='**/dist' \
  --exclude='**/.wrangler' \
  --exclude='**/__pycache__' \
  --exclude='**/*.tsbuildinfo' \
  --exclude='**/.agent.json' \
  --exclude='**/.dev.vars' \
  -cf - . | tar -C "$TARGET" -xf -

echo "Moving the workflows to the repository root…"
mkdir -p "$TARGET/.github/workflows"
for source in "$PARENT"/.github/workflows/travel-a2ui-*.yml; do
  [[ -e "$source" ]] || continue
  name="$(basename "$source" | sed 's/^travel-a2ui-//')"
  # Drop the `defaults: run: working-directory: travel-a2ui` block, the
  # `cache-dependency-path` and `workingDirectory` prefixes, and the path
  # filters that only make sense in a monorepo.
  sed \
    -e '/^defaults:$/,/^$/d' \
    -e 's#travel-a2ui/package-lock.json#package-lock.json#' \
    -e 's#workingDirectory: travel-a2ui/apps/worker#workingDirectory: apps/worker#' \
    -e "s#paths: \['travel-a2ui/\*\*', '.github/workflows/travel-a2ui-\(.*\)'\]#paths: ['**']#" \
    -e "s#travel-a2ui/##g" \
    "$source" > "$TARGET/.github/workflows/$name"
  echo "  .github/workflows/$name"
done

# The README links to the workflows by their monorepo path, which is one
# directory up and differently named. A broken link on the front page of a
# repository is the first thing a reader clicks.
echo "Rewriting workflow links in the README…"
sed -i \
  -e 's#(\.\./\.github/workflows/travel-a2ui-deploy\.yml)#(.github/workflows/deploy.yml)#g' \
  -e 's#(\.\./\.github/workflows/travel-a2ui-ci\.yml)#(.github/workflows/ci.yml)#g' \
  -e 's#`\.github/workflows/travel-a2ui-deploy\.yml`#`.github/workflows/deploy.yml`#g' \
  -e 's#`\.github/workflows/travel-a2ui-ci\.yml`#`.github/workflows/ci.yml`#g' \
  "$TARGET/README.md"

cat <<'DONE'

Done. Next:

  cd <destination>
  npm install && npm test
  git init && git add -A && git commit -m "Initial commit"
  gh repo create <name> --private --source=. --push

Then set two repository secrets so the deploy workflow can run:

  CLOUDFLARE_API_TOKEN    an "Edit Cloudflare Workers" token
  CLOUDFLARE_ACCOUNT_ID   from the Workers dashboard sidebar
DONE
