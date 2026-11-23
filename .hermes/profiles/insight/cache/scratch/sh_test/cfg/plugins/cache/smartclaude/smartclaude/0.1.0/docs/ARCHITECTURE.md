# Architecture

Three modules and one entry point. The point of keeping it this small is that
the security boundary fits in one file a reviewer can read in five minutes.

## `lib/paths.py` — the boundary

Everything that decides *what a file is* lives here, so the hook, the guard and
the CLI cannot disagree.

- `resolve(path)` — the real file a path means. Every containment decision is made
  on this answer, never on the path string.
- `is_inside(child, parent)` — both sides resolved, so neither a symlink escaping
  the tree nor a symlink parent can lie.
- `escape_target(path)` — returns where a path escapes to, or None when it is
  inside. This is what the report uses to name mirrored skills.
- `backup_path(path)` — keyed on the **resolved** path. Two links to one origin
  are one file with one backup; keying on the link would let one rollback restore
  the other's bytes.

## `lib/guard.py` — snapshot, verify, restore

- `_iter_files` walks with an explicit visited-set of resolved directories.
  `os.walk(followlinks=True)` would loop on a cycle and cannot record where a
  path resolved, which is the information the whole design needs.
- `Snapshot.capture` keys entries by `real`, so change detection sees an edit
  through any link exactly once.
- `Snapshot.changed` compares digests across the union of both key sets, so a
  file that appeared or vanished is a change too — a deleted skill is not "no
  change".
- `restore(real, bytes)` writes to the origin and leaves the link alone.
- `problems_in` blocks only what makes a skill fail to work: missing `name` or
  `description`, empty body, an oversized body for a new skill.

## `lib/memory.py` — the extended memory

The knowledge base owns its format, its chunking and its vector store. This
module only knows three things about it: the script that indexes, the `categorias/`
layout to append into, and the interpreter that can import its dependencies
(its own venv — the system python was proven not to have them).

`recall` parses the indexer's human output defensively: an unrecognised line is
treated as body text rather than dropped, so a format change degrades instead of
silently returning nothing.

`remember` writes markdown with an H1 and H2 sections because the indexer chunks
on headings; a heading-less file indexes as one diluted blob and stops being
findable.

## `hook.py` — one entry point

One subcommand per event, every failure swallowed, always exit 0. A hook that
can kill a session is worse than a hook that does nothing.

The `pre-tool` / `post-tool` pair must agree on two things or rollback silently
fails:

1. **The match test** is on the path as written (`is_skill_file`), because that is
   the path the tool was given.
2. **The identity** is the resolved path, because that is the file whose bytes
   changed.

Disagree on the first and the hook never fires; disagree on the second and the
edit looks like a brand-new file, so there is nothing to restore.

## `lib/distill.py` + `worker.py` — the loop

Detection is a **line anchor**, not a timestamp: transcripts are append-only, so a
line offset survives a clock change and cannot re-count old work.

Firing needs volume *and* artifacts — `MIN_CALLS` with `MIN_EDITS`, or a long
read-only investigation. A library that grows every turn stops being findable.

The worker is detached (`start_new_session=True`) because the `Stop` hook must
return immediately; a child in the parent's process group dies with the turn. The
claim is a single `UPDATE ... WHERE state='queued'` so two workers cannot both pay
for one job.

`headless_ready()` **probes** with a real `claude -p`. `claude auth status` reports
`loggedIn: true` while `-p` still returns 401, so the status command is not
evidence. A failed probe degrades to a nudge — it never retries in a loop.

The child is fenced: no Bash, writes only under the skills root, no credential
paths, and it is told the transcript is untrusted data. It is also told that
writing through a symlink is **allowed here** — for this design that is the
supported path, not an escape, and the guard makes it reversible.

## Choices worth defending

**No second database.** The loop keeps its queue in one SQLite file, not a second
store to keep in sync with git.
**No second database.** The knowledge base already has git, a chunker and an
index. A parallel store would drift within a month.

**Mirrored does not mean read-only.** The share is intentional; the fix is to make
the edit visible and reversible, not to forbid it. Forbidding it would push people
back to copying, which is the failure mode that started all of this.
