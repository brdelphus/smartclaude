# Upstream: what came from where

Honest provenance, because "inspired by" is doing a lot of work in a lot of
READMEs and a reader deserves better.

## The reference implementation

[`UniM0cha/self-improving-skills`](https://github.com/UniM0cha/self-improving-skills)
— MIT, © 2026 이정윤. It ports the Nous Research Hermes Agent learn/curate loop
into Claude Code as a plugin, with four host ports (Claude Code, Cowork, Codex,
ChatGPT). It is the closest existing thing to what this repo does, and reading
it is how the symlink problem below was found.

## What was taken

**Design, not code.** No file was copied. Every script here was written for this
repo. What was carried over is the shape of the problem and several hard-won
lessons visible in that codebase:

- Skills are the right unit of procedural memory, and a loop that never prunes
  produces a library nobody can search. Their own note: the library reached 385
  skills "of which the session listing could show 13". That is a warning to
  anyone adding a distiller to an existing library, and it shaped the decision
  here to ship **no auto-distiller at all** in v0.1.
- Prefer patching an existing skill over creating a new one.
- A snapshot → validate → rollback cycle around every skill edit is the minimum
  bar for letting an agent write to a skill at all.
- Hooks that can break a session are worse than hooks that do nothing: swallow
  your own errors and exit 0.
- A hook receives the path the *tool* was given; the guard needs the path the
  file *resolves to*. Keeping those straight is the whole job.

## What was deliberately not carried

**The symlink stance.** This is the reason the repo exists.

Their guard walks with `os.walk(root, followlinks=False)`, so a symlinked skill
lands in a separate `symlinks` list and never enters `files`. Change detection
then derives `changed` from `after.files`, which means a symlinked skill is never
visited, and the `realpath` containment check that *would* have refused the write
is never reached. The module docstring says it plainly: symlinked entries are
"neither snapshotted nor reverted nor flagged".

The consequence: an edit through a link changes the origin file with no backup,
no validation and no rollback. The remaining defence is prompt text in their
distiller asking the child not to write outside the tree — model discipline, not
enforcement — and the preferred action there is PATCH over CREATE, which is
exactly the blind path.

smartclaude inverts it: follow the link, key on the real file, validate those
bytes, restore the origin. See `tests/test_symlink_guard.py` for the assertion
that this works.

**The background distiller.** Theirs runs a detached `claude -p` worker with a
SQLite queue. It is a good design and it needs a headless credential, which is a
subscription-gated `setup-token` — so on a machine without one it degrades to an
interrupting in-turn nudge. v0.1 of smartclaude does not ship it at all: a
distiller that silently does nothing is worse than no distiller, and the
knowledge-base write-back covers the same need with a human in the loop.

**The curator loop.** Theirs ages unused agent-created skills to stale at 30 days
and archives at 45, keyed on `origin: distilled` in the frontmatter so
hand-written and linked-in skills are skipped. Sensible, and unnecessary here:
with no auto-distiller there is no fast growth to prune, and the knowledge base
already has git history.

## What was added

**Extended memory.** Neither project's problem originally: a searchable
knowledge base that outlives the repo and the machine. smartclaude reads from and
appends to an existing markdown-plus-indexer base rather than inventing storage.

**Symlink awareness in the report.** `SessionStart` and `/status` name the
mirrored skills and where they resolve, so "an edit here is an edit there" is
stated before the edit rather than discovered after a rollback.

## Licensing

Their license is MIT with the copyright notice intact upstream. This repo is MIT
and carries no copy of their source, so nothing is redistributed. The attribution
above exists because credit is owed for design and, more importantly, because a
reader evaluating the two projects should know exactly which claim differs.
