---
description: Audit every installed skill and report what is broken, what never fires, and what it costs on every message. Use before installing a skill from a stranger, when a skill never triggers, or when the agent got heavier.
argument-hint: [caminho-da-arvore] [--only-defects]
---

## Measure, do not estimate

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" ${ARGUMENTS:-~/.claude/skills}
```

The script does every count itself. Do not recalculate any number — an estimate is
a different number every time. If the header says **ESTIMATED**, say so and offer
`pip install tiktoken` for the real count. Never present an estimate as measured.

## Report the table as printed

Do not summarise it away. The operator asked what is wrong, and the table is the
answer. Then give the fixes in this order:

1. **`NEVER SAYS WHEN`** — the skill is invisible. Only names and descriptions
   load at startup, so a description that never says *when* is a skill that can
   never fire. Rewriting that one line is the cheapest fix available.
2. **`OVER TOKEN CEILING` / `OVER LINE CEILING`** — move branch-specific detail
   into a `references/` folder, which the agent opens only when it needs it.
3. **`SHIPS CODE`** — read it before it runs again. Not a defect in itself; a
   problem if nobody has read it.
4. **`DEAD LINK`** — the link points at nothing, so the skill silently stopped
   existing. Either the origin moved or the mirror is stale; re-run
   `/mirror-skills` or drop the link.
5. **`->` (mirrored)** — edits to that skill land in another tree. Worth knowing
   before patching it, and it is exactly what the guard is there for.

## Prove it ran

If the script errored, found zero skills, or the path was wrong, say that plainly.
Do not report a successful audit you did not run.
