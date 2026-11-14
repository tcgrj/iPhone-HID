#!/bin/bash
# Fetch exact official source and apply only the reviewed local patch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/wireless/vendor/UxPlay"
UPSTREAM=https://github.com/FDH2/UxPlay.git
COMMIT=21eef8df25d91e12635c36d8176ad192725baca2
PATCH="$ROOT/patches/uxplay-mirror-resume.patch"
command -v git >/dev/null || { echo 'Install Xcode Command Line Tools (git) first.' >&2; exit 1; }
if [[ -e "$DEST" && ! -d "$DEST/.git" ]]; then
  echo 'UxPlay destination exists without Git metadata; preserve it and choose a clean checkout.' >&2; exit 1
fi
if [[ ! -d "$DEST/.git" ]]; then
  mkdir -p "$DEST"
  git -C "$DEST" init -q
  git -C "$DEST" remote add origin "$UPSTREAM"
fi
[[ "$(git -C "$DEST" remote get-url origin)" == "$UPSTREAM" ]] || { echo 'Unexpected UxPlay remote; not modifying it.' >&2; exit 1; }
HEAD="$(git -C "$DEST" rev-parse HEAD 2>/dev/null || true)"
if [[ "$HEAD" != "$COMMIT" ]]; then
  [[ -z "$(git -C "$DEST" status --porcelain)" ]] || { echo 'UxPlay has local changes; not replacing them.' >&2; exit 1; }
  git -C "$DEST" fetch --depth 1 origin "$COMMIT"
  git -C "$DEST" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "$DEST" rev-parse HEAD)" == "$COMMIT" ]] || { echo 'UxPlay revision mismatch.' >&2; exit 1; }
if git -C "$DEST" apply --check "$PATCH" 2>/dev/null; then
  git -C "$DEST" apply "$PATCH"
elif ! git -C "$DEST" apply --reverse --check "$PATCH" 2>/dev/null; then
  echo 'UxPlay patch conflict; not changing existing source.' >&2; exit 1
fi
printf 'UxPlay fixed revision ready: %s\n' "$COMMIT"
