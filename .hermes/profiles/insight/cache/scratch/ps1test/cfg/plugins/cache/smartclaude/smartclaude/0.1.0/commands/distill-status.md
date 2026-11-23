---
description: Show the distillation queue and whether background distillation can run. Use when asking whether skills are being learned automatically, why a stretch of work produced no skill, or whether headless auth is working.
---

## Report the distillation state

Run this and report what it printed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" distill-status
```

## How to read it

- **`headless: NOT available`** — a background `claude -p` cannot authenticate.
  In that state the loop only nudges at the end of a substantial session; nothing
  is queued. Say so plainly and check auth, rather than claiming distillation is
  working.
- **`queued` piling up** — the worker is not being spawned. That is a launch
  problem, not a detection problem; look at `spawn()` before touching thresholds.
- **`failed` with `timeout`** — the child ran longer than `SMARTCLAUDE_JOB_TIMEOUT`.
  Do not retry the same job blindly; the next run costs the same.
- **`jobs: empty`** — no segment has cleared the threshold yet. That is normal on
  a young install, not a bug. Detection needs real volume, not a turn happening.

Do not estimate the numbers. They come from the queue, and the queue is the answer.
