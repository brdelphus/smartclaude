---
description: "Link an external skills tree into the Claude Code skills directory by symlink, idempotently. Use when the operator maintains skills elsewhere and wants them visible here, asks why an external skill is not loading, or after the source tree gained or lost a skill."
---

## Mirror, never copy

The source tree owns the text. Copying it creates two truths, and the machine
ends up running the stale one.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sync_skills.py" --prune $ARGUMENTS
```

Default source is `~/.claude/skills` itself; set `SMARTCLAUDE_SKILLS_SRC` (or
pass `--src`) when the skills live in another tree.

## What to check afterwards

- `created` / `updated` / `kept` / `pruned` counts — a suddenly huge `created`
  means the source path is wrong, not that the library grew.
- `collisions` — two skills with the same directory name; the first wins, and the
  other silently does not exist in Claude Code.
- Run `--dry-run` first when the source is not obviously correct.

Then report which skills resolve outside the tree. An edit to one of those is an
edit to the shared origin — say so before editing, not after.
