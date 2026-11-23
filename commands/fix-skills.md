---
description: Fix the skills that /audit-skills flagged — rewrite descriptions that never say when, split oversized bodies into references, remove dead links. Use when the audit reported defects and the operator wants them corrected rather than explained, or asks how to make the red rows go away.
argument-hint: "[skills-directory] [skill-name-to-fix]"
---

# Fix Flagged Skills

Turns the audit's list of defects into corrected files, one skill at a time, and
proves each fix by re-running the measurement.

This command writes to the operator's skill tree. That is the whole point of it, and
also the reason every step below asks before it acts.

## Steps

1. **Get the defects and the material to fix them, in one call.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" ${ARGUMENTS:-~/.claude/skills} --explain
   ```

   `--explain` prints, per flagged skill: the file to edit, the description as it
   stands, and what specifically to change for each flag. Use that output — do not
   reconstruct it from memory or re-read every `SKILL.md` yourself.

   If it prints `nothing to fix.`, say so and stop. Do not invent work.

2. **Fix one skill at a time, saying which one before you touch it.** Never batch.
   The operator's descriptions are their words; running over twenty files in one go is
   how a helpful fix becomes a rewrite nobody asked for.

   If the operator named a skill, fix only that one.

3. **Per flag, do exactly this:**

   - **`NEVER SAYS WHEN` / `NO DESCRIPTION`** — rewrite the `description` so the
     trigger is named, keeping what was already there. Put the trigger first:
     `Use when <situation>. <what it does>.` The audit matches the literal phrases
     `use when`, `use this when`, `when you`, `when the`, `if you`, `for when`,
     `trigger on`. Stay under 1,024 characters. Do not add a trigger that misdescribes
     the skill — a wrong `use when` is worse than none, because it fires and misleads.

   - **`OVER TOKEN CEILING` / `OVER LINE CEILING`** — split the body: move the
     branch-specific material into `references/<topic>.md` beside the skill, and leave
     one line where it was saying what moved and where. **Move, do not delete** — the
     content is needed, it just should not cost tokens on every message. Split by
     topic, not by line count: a section that is only relevant to one scenario is the
     right thing to move.

   - **`NAME TOO LONG`** — rename the directory and the `name:` field together. One
     without the other leaves a skill answering to a name that is not on disk.

   - **`DEAD LINK`** — the skill no longer exists. Report what it pointed at and ask
     whether to re-run `/mirror-skills` or drop the link. Do not delete a directory
     without being told to.

   - **`SHIPS CODE`** — not a defect by itself. Read the files and tell the operator
     what they do. Never delete someone's scripts to clear a flag.

4. **A mirrored skill (`->`) is edited at its origin.** `--explain` prints that path.
   Say plainly that the edit lands in the other tree, because that is a different
   repository and the operator may want to commit it there.

5. **Re-run the audit on what you touched and show the result.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" ${ARGUMENTS:-~/.claude/skills} --only-defects
   ```

   The skill you fixed must come back clean. If it does not, say so — a fix you did
   not verify is a fix you cannot claim. If the token count moved in the wrong
   direction, the split went wrong: check that the pointer line is there and that the
   moved file is actually inside `references/`.

## Rules

- **Never rewrite a body you were not asked to rewrite.** These commands clear flags;
  they do not improve skills. A flag is not permission to refactor.
- **Do not "fix" a skill by deleting it.** Removing a skill is the operator's call,
  and turning it off is usually better than deleting it.
- **If a `description` change would alter the meaning,** show the proposed line and
  ask first. Description is the one field that decides whether the skill ever runs.
- **Two skills, same name, different trees** is a real situation — do not merge them.
