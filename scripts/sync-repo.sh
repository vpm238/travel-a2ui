#!/usr/bin/env bash
#
# Updates an already-extracted standalone repository from this one.
#
# `extract-repo.sh` refuses a non-empty target, which is right for the first
# extraction and useless for every one after it: the standalone repo has its own
# git history, its own secrets and its own deploy, and none of that should be
# thrown away to pick up a week of changes.
#
# So this does the same copy over an existing checkout, and — the part that
# matters — *removes* files the source no longer has. A sync that only adds is
# how a deleted module goes on being deployed: the standalone keeps building it,
# the monorepo has forgotten it exists, and the two are different programs.
#
#   ./scripts/sync-repo.sh ~/code/travel-a2ui
#
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 <existing-standalone-checkout>" >&2
  exit 1
fi

if [[ ! -d "$TARGET/.git" ]]; then
  echo "$TARGET is not a git checkout. Use extract-repo.sh for a fresh one." >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$HERE")"

# Anything generated, installed, or local to one machine. The same list as the
# extraction, kept here rather than shared because a sync that silently stopped
# excluding `node_modules` would be a very slow way to find out.
EXCLUDES=(
  './node_modules' './.venv' './.git' './.github'
  '**/node_modules' '**/dist' '**/.wrangler' '**/__pycache__'
  '**/*.tsbuildinfo' '**/.agent.json' '**/.dev.vars' '**/.pytest_cache'
  '**/build/web'
)

tar_excludes=()
for pattern in "${EXCLUDES[@]}"; do
  tar_excludes+=(--exclude="$pattern")
done

echo "Removing files this repository no longer has…"
# Compared by path rather than by content: the question is "does the source
# still have this file", and `git ls-files` in the target is the list of things
# that would otherwise survive as orphans. `.github` is excluded because the
# standalone's workflows are rewritten below, not copied.
(
  cd "$TARGET"
  git ls-files | while IFS= read -r file; do
    case "$file" in
      .github/*) continue ;;
    esac
    if [[ ! -e "$HERE/$file" ]]; then
      echo "  - $file"
      rm -f "$file"
    fi
  done
)

echo "Copying the project…"
tar -C "$HERE" "${tar_excludes[@]}" -cf - . | tar -C "$TARGET" -xf -

echo "Rewriting the workflows…"
mkdir -p "$TARGET/.github/workflows"
for source in "$PARENT"/.github/workflows/travel-a2ui-*.yml; do
  [[ -e "$source" ]] || continue
  name="$(basename "$source" | sed 's/^travel-a2ui-//')"
  # Identical to extract-repo.sh, including the sentinel that keeps
  # `@travel-a2ui/express` from becoming `@express`.
  sed \
    -e '/^defaults:$/,/^$/d' \
    -e 's#@travel-a2ui/#\x01#g' \
    -e 's#travel-a2ui/package-lock.json#package-lock.json#' \
    -e 's#workingDirectory: travel-a2ui/apps/worker#workingDirectory: apps/worker#' \
    -e "s#paths: \['travel-a2ui/\*\*', '.github/workflows/travel-a2ui-\(.*\)'\]#paths: ['**']#" \
    -e "s#travel-a2ui/##g" \
    -e 's#\x01#@travel-a2ui/#g' \
    "$source" > "$TARGET/.github/workflows/$name"
  echo "  .github/workflows/$name"
done

echo "Rewriting workflow links in the README…"
sed -i \
  -e 's#(\.\./\.github/workflows/travel-a2ui-deploy\.yml)#(.github/workflows/deploy.yml)#g' \
  -e 's#(\.\./\.github/workflows/travel-a2ui-ci\.yml)#(.github/workflows/ci.yml)#g' \
  -e 's#(\.\./\.github/workflows/travel-a2ui-cloudrun\.yml)#(.github/workflows/cloudrun.yml)#g' \
  -e 's#`\.github/workflows/travel-a2ui-deploy\.yml`#`.github/workflows/deploy.yml`#g' \
  -e 's#`\.github/workflows/travel-a2ui-ci\.yml`#`.github/workflows/ci.yml`#g' \
  -e 's#`\.github/workflows/travel-a2ui-cloudrun\.yml`#`.github/workflows/cloudrun.yml`#g' \
  "$TARGET/README.md"

echo
echo "Synced. Review before pushing:"
echo "  git -C $TARGET status --short"
echo "  git -C $TARGET diff --stat"
