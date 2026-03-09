#!/usr/bin/env bash
set -euo pipefail

target_branch="${1:-}"
source_ref="${2:-HEAD}"

if [[ -z "${target_branch}" ]]; then
  echo "Usage: ./scripts/deploy-branch.sh <gamma|main> [source-ref]" >&2
  exit 1
fi

if [[ "${target_branch}" != "gamma" && "${target_branch}" != "main" ]]; then
  echo "Only gamma and main are supported release targets." >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "${repo_root}"

if [[ -n "$(git status --short)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before deploying." >&2
  exit 1
fi

git fetch origin "${target_branch}"

resolved_source="$(git rev-parse "${source_ref}")"
resolved_remote="$(git rev-parse "origin/${target_branch}")"

if ! git merge-base --is-ancestor "${resolved_remote}" "${resolved_source}"; then
  echo "Ref ${source_ref} is not a fast-forward of origin/${target_branch}." >&2
  echo "Rebase or merge it first, then retry." >&2
  exit 1
fi

echo "Deploying ${resolved_source} to ${target_branch}..."
git push origin "${resolved_source}:refs/heads/${target_branch}"
echo "Triggered ${target_branch} deployment from commit ${resolved_source}."
