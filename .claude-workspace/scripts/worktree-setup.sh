#!/bin/bash
# Parallel Worktree Setup Script
set -euo pipefail

SUBTASK=""
BRANCH=""
BASE_BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subtask) SUBTASK="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --base) BASE_BRANCH="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$SUBTASK" || -z "$BRANCH" ]]; then
  echo "Usage: worktree-setup.sh --subtask <name> --branch <branch> [--base <base-branch>]"
  exit 1
fi

GIT_ROOT=$(git rev-parse --show-toplevel)
WORKSPACE="$GIT_ROOT/.claude-workspace"
WORKTREE_DIR="$WORKSPACE/worktrees/$SUBTASK/worktree"
STATUS_FILE="$WORKSPACE/worktrees/$SUBTASK/STATUS.yml"

if [[ ! -f "$GIT_ROOT/.git/HEAD" ]] && [[ ! -d "$GIT_ROOT/.git" ]]; then
  echo "Not a git repository. Run git init and create an initial commit first."
  exit 1
fi

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "No commits yet. Create an initial commit on $BASE_BRANCH before adding worktrees."
  exit 1
fi

mkdir -p "$(dirname "$WORKTREE_DIR")"

echo "Updating $BASE_BRANCH..."
git fetch origin "$BASE_BRANCH" 2>/dev/null || git fetch origin 2>/dev/null || true

echo "Creating worktree at $WORKTREE_DIR..."
if git rev-parse --verify "origin/$BASE_BRANCH" >/dev/null 2>&1; then
  git worktree add -b "$BRANCH" "$WORKTREE_DIR" "origin/$BASE_BRANCH"
else
  git worktree add -b "$BRANCH" "$WORKTREE_DIR" "$BASE_BRANCH"
fi

echo "Copying environment files..."
for env_file in "$GIT_ROOT"/.env*; do
  if [[ -f "$env_file" ]]; then
    basename_file=$(basename "$env_file")
    if [[ "$basename_file" != ".env.example" ]]; then
      cp "$env_file" "$WORKTREE_DIR/$basename_file" 2>/dev/null || true
    fi
  fi
done

echo "Updating status..."
cat > "$STATUS_FILE" << EOF
id: $SUBTASK
status: in_progress
branch: $BRANCH
worktree_path: $WORKTREE_DIR
assigned_to: $$
started_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
completed_at: null
dependencies_met: true
conflicts: []
commit_sha: null
tests_passing: null
EOF

echo "Worktree setup complete: $WORKTREE_DIR"
echo "Branch: $BRANCH"
echo "Subtask: $SUBTASK"
