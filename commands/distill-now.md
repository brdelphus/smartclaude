---
description: Distill the current session into a skill now, ignoring the threshold. Use when a session taught something clearly worth keeping and waiting for the automatic trigger is not wanted.
argument-hint: "[--transcript caminho]"
---

## Distill immediately

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" distill-now $ARGUMENTS
```

With no argument it takes the most recently modified transcript.

## What happens to your files

A fenced `claude -p` child reads the transcript and may patch an existing skill or
write a new one. Before it runs, the whole skills tree is snapshotted. After it
finishes, every changed `SKILL.md` is re-read and validated, and anything invalid
or out of scope is **reverted to the bytes it had before** — including a file that
was written through a symlink, because the snapshot and the rollback both key on
the resolved path.

## How to report it

Read the `after:` line and the job note. Name what actually happened:

- `installed: <skill>` — which skill, patched or new
- `nothing_to_save` — the child judged this session taught nothing durable
- `rolled back — <skill>: <reason>` — say the reason and that the original bytes
  were restored. Do not present a rollback as a failure of the run; it is the
  guard working
- `timeout` / `child failed` — report verbatim, do not retry silently

Do not claim a skill was written without the note saying so.
