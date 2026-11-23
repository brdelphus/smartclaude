---
description: "Report smartclaude's state: how many skills exist, which are mirrored and where they resolve, and whether the knowledge base is reachable. Use when the operator asks what the current setup looks like, why a skill is not showing up, or whether extended memory is wired before relying on it."
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" status
```

Report the numbers as they are. In particular: a mirrored skill is not a local
copy, so any plan to edit one should name the origin tree it will change.
