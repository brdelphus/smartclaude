---
description: Show the skill tree, which skills are mirrored, and whether the knowledge base is reachable.
---

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" status
```

Report the numbers as they are. In particular: a mirrored skill is not a local
copy, so any plan to edit one should name the origin tree it will change.
