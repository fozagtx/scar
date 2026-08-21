# Parallel Development Workspace

This directory contains state for parallel development of **SCAR** (Stored Corrections And Recall) for Hack Hydra.

## Structure

- `PARALLEL_PLAN.md` - Main plan with all subtasks
- `worktrees/` - Subtask-specific worktrees and state
- `integration/` - Merge planning and logs
- `scripts/` - Helper utilities

## Commands

- `/plan-parallel <feature>` - Create parallel development plan
- `/work-on <subtask>` - Start working on a subtask
- `/worktree-review` - Review current subtask
- `/merge-parallel <branch>` - Merge all subtasks

## Manual Status Check

```bash
bash .claude-workspace/scripts/status-check.sh
```

## Cleanup

After successful merge, worktrees and branches are cleaned up automatically.
To manually clean up:

```bash
git worktree list
git worktree remove <path>
```
