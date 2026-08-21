#!/bin/bash
# Validates subtask dependencies
set -euo pipefail

SUBTASK="${1:-}"
WORKSPACE=".claude-workspace"

if [[ -z "$SUBTASK" ]]; then
  echo "Usage: validate-dependencies.sh <subtask-name>"
  exit 1
fi

TASK_FILE="$WORKSPACE/worktrees/$SUBTASK/TASK.md"

if [[ ! -f "$TASK_FILE" ]]; then
  echo "Subtask not found: $SUBTASK"
  exit 1
fi

DEPENDENCIES=$(awk '/^---$/{c++; next} c==1' "$TASK_FILE" | grep "^dependencies:" | sed 's/dependencies:[[:space:]]*//' | tr -d '[]' | tr ',' ' ')

if [[ -z "$DEPENDENCIES" || "$DEPENDENCIES" == "null" ]]; then
  echo "No dependencies - ready to work"
  exit 0
fi

UNMET=()
for dep in $DEPENDENCIES; do
  dep=$(echo "$dep" | tr -d ' ')
  [[ -z "$dep" ]] && continue
  DEP_STATUS_FILE="$WORKSPACE/worktrees/$dep/STATUS.yml"

  if [[ ! -f "$DEP_STATUS_FILE" ]]; then
    UNMET+=("$dep (not found)")
  else
    DEP_STATUS=$(grep "^status:" "$DEP_STATUS_FILE" | awk '{print $2}')
    if [[ "$DEP_STATUS" != "complete" ]]; then
      UNMET+=("$dep ($DEP_STATUS)")
    fi
  fi
done

if [[ ${#UNMET[@]} -eq 0 ]]; then
  echo "All dependencies met"
  exit 0
else
  echo "Unmet dependencies:"
  for dep in "${UNMET[@]}"; do
    echo "  - $dep"
  done
  exit 1
fi
