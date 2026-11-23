# smartclaude

Skills that learn from use, and memory that lives outside the session.

Claude Code already has skills, hooks, subagents and an auto-memory directory.
What it does not have is a **knowledge base** that survives across machines and
repos, and a safe way to let an agent edit a skill that is shared with another
tool. smartclaude adds those two, and nothing else.

## Scope

Runs on **Claude Code and nothing else**. No other agent has to be installed, and
none is read by default. The skills root is resolved from `CLAUDE_CONFIG_DIR` or
`~/.claude`, full stop.

Mirroring is opt-in and always names its source: `--src <dir>` or
`SMARTCLAUDE_SKILLS_SRC`. With neither, the command refuses rather than guessing,
because a guessed default works on one machine and silently does nothing on the
next. `tests/test_no_foreign_agent.py` fails the build if executable code ever
names another agent, or if a mirror runs without an explicit source.

The external knowledge base is likewise optional: unset means the memory commands
degrade to a no-op, never to an error.

## The two problems it solves

**1. Mirrored skills get written blindly.**

If your skills live in another tree (a shared dotfiles repo, another agent's
plugin source) and you symlink them into `~/.claude/skills/`, then a write through
the link edits *the origin*. Most skill-guard implementations walk the tree with
`followlinks=False`, so the symlinked skill never enters their snapshot: the edit
lands with no backup, no validation and no rollback, and the check that would
have refused it is never reached.

smartclaude treats a mirrored skill as a first-class skill. The snapshot follows
the link, keys on the **real file**, validates those bytes, and rolls back to the
origin — leaving the link intact, because restoring a link by replacing it would
destroy the share you built on purpose.

**2. Session memory dies with the session.**

Auto-memory is per repository and machine-local. smartclaude talks to an external
markdown knowledge base that has its own indexer, reads from it on demand, and
appends to it in the base's own format. It never creates a second database that
would drift from the first.

## Install

```bash
claude plugin marketplace add /caminho/para/smartclaude
claude plugin install smartclaude@smartclaude
```

Then point it at your trees:

```bash
export SMARTCLAUDE_SKILLS_SRC=~/./opt/shared/skills              # what to mirror (any tree)
export SMARTCLAUDE_KB_REPO=~/projects/valeria-knowledge           # extended memory
```

`SMARTCLAUDE_KB_REPO` is discovered automatically if it sits at
`~/projects/valeria-knowledge`; everything is env-driven, nothing is hard-coded.

## Use

| | |
|---|---|
| `/recall clamav mailu` | search the knowledge base, answer from the hits |
| `/remember Traefik route order` | save a durable lesson (body on stdin) |
| `/mirror-skills` | sync the source tree into `~/.claude/skills` by symlink |
| `/status` | skill count, mirrored skills, whether the base is reachable |
| `cli.py status` | the same, from a shell |

Recall can also run on every prompt:

```bash
export SMARTCLAUDE_RECALL_ON_PROMPT=1     # off by default — it costs latency
```

## What the hooks do

| Event | Behaviour |
|---|---|
| `SessionStart` | reports how many skills are mirrored and where they resolve to |
| `UserPromptSubmit` | optional recall injected as reference context |
| `PreToolUse` | copies the **real** file an edit is about to touch |
| `PostToolUse` | validates; rolls back an edit that produced a skill Claude Code would never load |

Blocking problems are structural only — a missing `description` (the skill would
never be surfaced), an empty body, a body too large to be worth its context. Taste
is not enforced. A rollback always writes to the origin.

## Layout

```
.claude-plugin/plugin.json   manifest
hooks/hooks.json             event wiring
scripts/hook.py              one entry point, one subcommand per event
scripts/cli.py               recall / remember / status / mirror
scripts/sync_skills.py       symlink mirror, idempotent
scripts/lib/paths.py         resolution + containment (the security boundary)
scripts/lib/guard.py         snapshot / verify / rollback / validation
scripts/lib/memory.py        knowledge-base recall and write-back
commands/ agents/            slash commands and the memory librarian subagent
tests/                       the symlink guarantee, proven
docs/                        architecture, upstream provenance
```

## Run the test

```bash
python3 tests/test_symlink_guard.py
```

It builds a throwaway tree with one real skill and one symlinked skill, writes
through the link, and asserts that the change is detected against the real file,
validated, and reversible without breaking the link. That is the whole thesis of
this repo in one file.

## Credit

The learn-from-use loop this project assumes is the design of
[UniM0cha/self-improving-skills](https://github.com/UniM0cha/self-improving-skills)
(MIT, © 2026 이정윤), which ports the Nous Research the Hermes Agent approach into Claude
Code. smartclaude is an independent implementation with a different stance on
symlinks — see [docs/UPSTREAM.md](docs/UPSTREAM.md) for what was taken as design
and what was deliberately not copied.

## License

MIT.
