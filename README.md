# smartclaude

Skills you can take from anywhere, audit, and let improve themselves — plus a
memory that lives outside the session.

Claude Code already has skills, hooks, subagents and an auto-memory directory.
What it does not have is a **knowledge base** that survives across machines and
repos, a safe way to let an agent edit a skill that is shared with another tool,
or a deterministic way to tell which of your skills is quietly broken. smartclaude
adds those, and nothing else.

**It ships with zero skills.** A bundled skill would sit in context and fire before
you decided you wanted it.

## Install

Requires Python 3.9+ and Claude Code 2.x.

**Linux**

```bash
git clone https://github.com/Rgraeff/smartclaude.git
cd smartclaude
./install.sh
```

**macOS** — same script, with or without Homebrew. If `python3` is missing the
installer offers to get it via `brew install python@3.12`; if you prefer to manage
it yourself, install it first and the script just verifies what is there.

```bash
git clone https://github.com/Rgraeff/smartclaude.git
cd smartclaude
./install.sh
```

**Windows** — PowerShell 5.1 or 7+.

```powershell
git clone https://github.com/Rgraeff/smartclaude.git
cd smartclaude
.\install.ps1
```

If script execution is blocked, run it for one session:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer checks the prerequisites, registers the plugin with Claude Code,
creates its state directory, runs the test suite, and prints what to do next. It
refuses to continue on a missing prerequisite rather than installing something
half-working.

## Commands

| Command | What it does |
|---|---|
| `/audit-skills` | measure every skill: what is broken, what never fires, what it costs on every message |
| `/import-skills` | bring skills over from Cursor, Copilot, Claude, Hermes or `.agents/skills` |
| `/mirror-skills` | link an external skills tree into `~/.claude/skills`, idempotently |
| `/recall <terms>` | search the knowledge base and answer from the hits |
| `/remember <title>` | save a durable note into the knowledge base |
| `/distill-now` | turn this session into a skill now, ignoring the threshold |
| `/distill-status` | show the distillation queue and whether headless auth works |
| `/status` | skill count, mirrored skills, knowledge base reachability |

Everything the commands do is also reachable from a shell, because a plugin that
only works through a slash command cannot be scripted or tested:

```bash
python3 scripts/cli.py status
python3 scripts/cli.py recall "clamav mailu" -n 3 --cat infra
python3 scripts/audit.py ~/.claude/skills --only-defects
python3 scripts/import_skills.py --from cursor --list
```

## Feature: symlink-safe skills

If your skills live in another tree — a shared dotfiles repo, another agent's
source — and you symlink them into `~/.claude/skills/`, a write through the link
edits *the origin*.

Most skill-guard implementations walk the tree with `followlinks=False`, so a
symlinked skill never enters their snapshot: the edit lands with no backup, no
validation and no rollback, and the containment check that would have refused it
is never reached. Worse, patching an existing skill is usually the *preferred*
path, so the blind spot sits on the most frequent route.

smartclaude treats a mirrored skill as a first-class skill. The snapshot follows
the link, keys on the **real file**, validates those bytes, and rolls back to the
origin — leaving the link intact, because restoring a link by replacing it would
destroy the share you built on purpose.

This is proven, not asserted: `tests/test_symlink_guard.py` builds a throwaway
tree with one real skill and one symlinked skill, writes through the link, and
asserts the change is attributed to the real file, validated, and reversible
without breaking the link.

## Feature: extended memory

Auto-memory is per repository and machine-local. smartclaude talks to an external
markdown knowledge base that has its own indexer, reads from it on demand, and
appends to it in the base's own format. It never creates a second database that
would drift from the first — git holds the text, the vector store is a cache.

The base is optional. Unset means the memory commands degrade to a no-op, never to
an error. Discovery order: `SMARTCLAUDE_KB_REPO`, then a conventional location.

Writing back measures instead of guessing: after indexing it reads the base's own
chunk report and tells you when a note collapsed into a single chunk, because a
heading-less note embeds as one diluted blob and stops being findable.

## Feature: import from another agent

Agent Skills is an open format (`SKILL.md` + `name`/`description`, progressive
disclosure) spoken by Claude Code, Cursor, Copilot and Codex alike, so most imports
are a copy rather than a conversion.

```bash
python3 scripts/import_skills.py                      # what is importable, writes nothing
python3 scripts/import_skills.py --from cursor --list # preview
python3 scripts/import_skills.py --from copilot --dry-run
python3 scripts/import_skills.py --from hermes
```

Sources: `claude`, `cursor`, `copilot`, `hermes`, `agents`. Bundled `scripts/`,
`references/`, `assets/` and `templates/` travel with the skill.

Older formats are **converted**, and every conversion reports what it could not
preserve: a Cursor `.mdc` rule with `alwaysApply: true` applied to *everything*,
where a skill only loads when its description matches; a Copilot
`copilot-instructions.md` has no trigger at all and is imported as reference text,
flagged as *not a skill*. Preserved where possible: `globs` and `applyTo` become
`paths`.

Nothing is overwritten without `--force`. A hand-written skill outranks an imported
one.

## Feature: audit

`/audit-skills` measures every `SKILL.md` against the published Agent Skills limits
and reports the four things that actually cost you:

- **descriptions that never say when to use the skill** — only names and
  descriptions load at startup, so that line decides whether it ever fires
- bodies over 5,000 tokens or 500 lines, where a `references/` folder is the fix
- **how much context all names and descriptions cost on every single message**
- skills shipping executable code nobody has read

Plus, in a tree that mirrors by symlink: which skills are links into another tree,
and which links point at nothing — a skill that silently stopped existing.

Token counts are exact only when `tiktoken` is installed; the report says which
mode it used and never presents an estimate as measured.

## Feature: distillation

At the end of a substantial session, the work can be distilled into a skill for
the next one. Detection needs volume *and* artifacts — a threshold of tool calls
with real file edits, or a long read-only investigation — because a library that
grows on every turn stops being findable.

The worker runs detached, claims one job atomically from a SQLite queue, snapshots
the skills tree, runs a **fenced** `claude -p` child (no Bash, writes only under
the skills root, credential paths denied, the transcript declared untrusted data),
then re-snapshots, validates every changed `SKILL.md` and reverts anything invalid
or out of scope.

Whether a background child can authenticate is **probed**, not assumed: the status
command lies while `claude -p` returns 401, so only a real call counts. When it
cannot, the loop degrades to a nudge instead of retrying in a loop.

## Hooks

| Event | Behaviour |
|---|---|
| `SessionStart` | reports how many skills are mirrored and where they resolve to |
| `UserPromptSubmit` | optional recall injected as reference context |
| `Stop` | queues a distillation when the segment cleared the threshold |
| `PreToolUse` | copies the **real** file an edit is about to touch |
| `PostToolUse` | validates; rolls back an edit that produced a skill Claude Code would never load |

Blocking problems are structural only — a missing `description`, an empty body, a
body too large to be worth its context. Taste is not enforced. A rollback always
writes to the origin, and every hook exits 0: a hook that can kill a session is
worse than one that does nothing.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | where Claude Code keeps per-user state |
| `SMARTCLAUDE_STATE_DIR` | `<config>/smartclaude` | queue, snapshots, bookkeeping |
| `SMARTCLAUDE_KB_REPO` | discovered | the markdown knowledge base |
| `SMARTCLAUDE_SKILLS_SRC` | none | source tree for `/mirror-skills` — no default, on purpose |
| `SMARTCLAUDE_RECALL_ON_PROMPT` | off | recall on every prompt (costs latency) |
| `SMARTCLAUDE_MIN_CALLS` / `MIN_EDITS` / `READONLY_CALLS` | 40 / 3 / 80 | distillation thresholds |
| `SMARTCLAUDE_CLAUDE_BIN` | `claude` | the binary the worker invokes |
| `SMARTCLAUDE_JOB_TIMEOUT` | 900 | seconds per distillation job |

## Layout

```
.claude-plugin/          manifest + marketplace entry
hooks/hooks.json         event wiring
scripts/hook.py          one entry point, one subcommand per event
scripts/cli.py           recall / remember / status / distill / mirror
scripts/audit.py         skill measurement
scripts/import_skills.py import registry, native copy and legacy conversion
scripts/sync_skills.py   symlink mirror, idempotent
scripts/worker.py        detached distillation worker
scripts/lib/paths.py     resolution + containment (the security boundary)
scripts/lib/guard.py     snapshot / verify / rollback / validation
scripts/lib/memory.py    knowledge-base recall and write-back
scripts/lib/distill.py   threshold detection and the job queue
commands/ agents/        slash commands and the memory librarian subagent
tests/                   the guarantees, proven
docs/                    architecture, upstream provenance
```

## Tests

```bash
python3 tests/test_symlink_guard.py     # the symlink guarantee
python3 tests/test_no_foreign_agent.py  # ships empty; no implicit reads
```

Both build their own throwaway trees, so they run on a machine where none of those
agents is installed — which is exactly the machine this has to work on.

## Scope

Runs on **Claude Code and nothing else**. The skills root resolves from
`CLAUDE_CONFIG_DIR` or `~/.claude`, full stop. No foreign directory is read unless
you name a source with `--from`, and mirroring refuses without `--src` rather than
guessing: a guessed default works on one machine and silently does nothing on the
next.

## Credit

The learn-from-use loop this project assumes is the design of
[UniM0cha/self-improving-skills](https://github.com/UniM0cha/self-improving-skills)
(MIT, © 2026 이정윤). The audit's measurement model follows the `skill-audit` skill
(MIT, sharbelxyz), kept identical so a number produced by either means the same
thing. smartclaude is an independent implementation with a different stance on
symlinks — see [docs/UPSTREAM.md](docs/UPSTREAM.md) for what was taken as design
and what was deliberately not copied.

## License

MIT.
