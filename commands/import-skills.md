---
description: Import skills from another agent (Cursor, Copilot, Claude, Hermes, .agents) into this one. Use when the operator wants existing skills carried over, or asks what can be imported from another tool.
argument-hint: --from <agent> [--list] [--dry-run] [--force]
---

## Nothing is read unless the operator names it

Run without arguments to see what exists on this machine — this writes nothing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/import_skills.py"
```

Then, with the source named:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/import_skills.py" $ARGUMENTS
```

Useful shapes:

- `--from cursor --list` — what would come over, nothing written
- `--from copilot --dry-run` — full conversion, no writes
- `--from hermes` — install into `~/.claude/skills`
- `--only <name>` — one skill

## Two kinds of source, and they are not the same job

**Native** — the other agent already speaks Agent Skills (`SKILL.md` with `name` and
`description`). Claude Code, Cursor skills, Copilot skills, `.agents/skills` and
Hermes all use this open format. The folder is copied and its frontmatter
normalised; `scripts/`, `references/`, `assets/` and `templates/` travel with it.

**Legacy** — Cursor `.mdc` rules, Copilot `copilot-instructions.md` and
`*.instructions.md`. These are **converted**, and the conversion is lossy, so every
one of them prints a warning.

## Report the warnings, do not swallow them

- **`alwaysApply: true`** — that rule applied to *everything*. As a skill it only
  loads when its description matches. If it must always apply, it should stay a
  rule. Say this; do not decide it for the operator.
- **`copilot-instructions.md`** — repo-wide instructions with no trigger. Imported
  as reference text, flagged as *not a skill*. Splitting it into real skills is
  manual work.
- **`globs` / `applyTo`** — preserved as `paths`, which Cursor and Copilot both read.
- **`--force` was not given** — an existing skill is skipped, never overwritten.
  A hand-written skill outranks an imported one; that is the whole point of not
  clobbering it.

After importing, offer `/audit-skills`. Imported material is exactly the kind of
thing that has never been measured.
