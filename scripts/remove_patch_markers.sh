#!/usr/bin/env bash
# scripts/remove_patch_markers.sh
# Finds and removes blocks between "*** Begin Patch" and "*** End Patch" in text files tracked by git.
# WARNING: Run locally and review changes before pushing to main; this script commits the fixes on the current branch.

set -euo pipefail

# Find files containing the marker
files=$(git grep -l "\*\*\* Begin Patch" || true)
if [ -z "$files" ]; then
  echo "No files with patch markers found."
  exit 0
fi

echo "Found files with patch markers:" 
printf "%s
" "$files"

for f in $files; do
  echo "Cleaning $f"
  # Only operate on regular text files
  awk '/\*\*\* Begin Patch/{f=1;next}/\*\*\* End Patch/{f=0;next}!f' "$f" > "$f.fixed"
  mv "$f.fixed" "$f"
  git add "$f"
done

msg="fix: remove leftover patch markers (cleanup)"

git commit -m "$msg" || echo "No changes to commit"

echo "Done. Committed cleanup changes. Review and push when ready: git push origin $(git rev-parse --abbrev-ref HEAD)"
