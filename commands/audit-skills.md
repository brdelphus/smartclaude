---
description: Audit every installed skill and report what is broken, what never fires, and what it costs on every message. Use when asked to audit, check, review, measure or clean up skills, to find out why a skill never runs or triggers, to learn what the skills cost in tokens or context, or when the agent got slower or heavier since things were installed. Also use before installing a skill from a stranger.
argument-hint: "[skills-directory] [--only-defects] [--json] [--explain]"
---

# Skill Audit

Measures every installed skill and reports what is wrong with it.

Same measurement and same reporting order as the `skill-audit` skill: a number
produced here means exactly what the same number means there.

## Steps

1. **Find the skills directory.** Default is `~/.claude/skills`. If the operator
   names a different path, use theirs. If they say skills live somewhere else
   without naming it, ask — do not guess more than once.

2. **Run the script. Do not read it as reference material, run it.**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" ${ARGUMENTS:-~/.claude/skills}
   ```

   Add `--json` when the operator wants the raw rows to work with, `--only-defects`
   to hide the clean skills.

   The script does every count itself. Do not estimate any of these numbers and do
   not recalculate them, because you will get a different answer each time you try.

3. **Report the table exactly as the script printed it.** Do not summarise it away.
   The operator asked what is wrong with their skills, and the table is the answer.

4. **Then give them the three things to do first, in this order:**
   - Any skill flagged `NEVER SAYS WHEN` is invisible to you. It loads on every
     message and can never fire. Rewriting that one line is the cheapest fix
     available.
   - Any skill they do not recognise or have not used in a month should be **turned
     off, not deleted**. Say that explicitly — people hesitate. It costs context on
     every single message either way.
   - Any skill flagged `SHIPS CODE` should be opened and read before it runs again.

5. **When they ask how to fix a flag, run the remediation mode:**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" ${ARGUMENTS:-~/.claude/skills} --explain
   ```

   It prints, per broken skill: the file to edit (for a mirrored skill the file at
   the **origin** of the link, not the link), the description as it stands right
   now, and what specifically to change for each flag. Use it instead of describing
   the fixes from memory — the current description text matters, and you will not
   reproduce it.

6. **Offer to do the fix, one skill at a time.** Do not batch-rewrite twenty
   descriptions because the operator said "fix them". Say which skill you are about
   to change and why. A description is the operator's line in their own tree; some
   of them will want to write it themselves.

   - **`NEVER SAYS WHEN` / `NO DESCRIPTION`** — rewrite the description so the
     trigger is named. Keep what was already there; add the trigger, do not replace
     the meaning. Stay under 1,024 characters.
   - **`OVER TOKEN CEILING` / `OVER LINE CEILING`** — split the body into
     `references/<topic>.md` and leave a one-line pointer in `SKILL.md` where the
     detail used to be. Move the content, never delete it: the skill needs it, and
     the point is that it stops costing tokens on every message.
   - **`NAME TOO LONG`** — rename the folder and the `name:` field together, or the
     skill loads under the wrong name.
   - **`DEAD LINK`** — re-run `/mirror-skills`, or remove the link.
   - **`SHIPS CODE`** — read the files, or tell the operator what they do. Never
     silently delete someone's scripts.

7. **Re-run the audit after editing.** The same skill must come back clean; a fix
   you did not verify is a fix you cannot claim. If a mirrored skill was edited,
   say that the change landed in the tree the link points at.

8. **Verify before you report.** Open the output and check it against what was
   asked for. If the script errored, if it found zero skills, or if the path was
   wrong, say that plainly. Do not report a successful audit you did not run.

## What the flags mean

- `NEVER SAYS WHEN` — the description says what the skill is but not when to use
  it. Only names and descriptions load at startup, so this is the line that decides
  whether the skill ever runs.
- `OVER TOKEN CEILING` — body is over 5,000 tokens. Move branch-specific material
  into a `references/` folder the agent opens only when it needs it.
- `OVER LINE CEILING` — body is over 500 lines. Same fix.
- `NAME TOO LONG` / `DESC TOO LONG` — over the 64 and 1,024 character limits in the
  Agent Skills specification.
- `SHIPS CODE` — the skill folder contains executable files. Not a problem in
  itself. A problem if nobody has read them.
- `DEAD LINK` — the link points at nothing, so the skill silently stopped existing.
  Re-run `/mirror-skills` or drop the link.
- `->` beside a skill name — **mirrored**: it is a symlink into another tree, so an
  edit lands there. `--explain` prints the origin path for exactly this reason: edit
  the link and you edit someone else's tree, which is fine, but it must be on
  purpose. This is what the guard covers.

## Gotchas

- **If the report says ESTIMATED, the numbers are a guess — say so, and do not
  quietly report them as fact.** Then run the diagnostic instead of guessing why:

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/audit.py" --doctor
  ```

  It prints which interpreter runs the audit, whether that one can measure, which
  environment it borrows the tokenizer from, and every path it tried. Show that output
  to the operator. A report that estimates from character count can be off by a factor
  of two at the 5,000-token ceiling — on a 201-skill tree the estimate found 16 skills
  over the limit and measuring found 34.

  Do not tell the operator to "install tiktoken" without reading the doctor first: on
  a machine where it *is* installed, the problem is which interpreter is running, and
  installing it again fixes nothing.
- **`NEVER SAYS WHEN` is a text match, not a judgement.** It catches the common
  phrasings. A description can pass the check and still be useless. Read the
  flagged ones and sanity-check a couple that passed.
- **The startup number is the one that matters most.** It is what every skill costs
  on every message whether it fires or not. Most people have never seen it.
- **Mirrored skills are counted, not skipped.** `glob('**/SKILL.md')` follows
  directory symlinks, so a mirrored tree audits the same as a local one. Dead links
  are not reached by that walk and are swept separately — that is why they get their
  own flag.
