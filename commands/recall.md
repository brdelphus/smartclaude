---
description: Search the external knowledge base and answer from what it found. Use when the question is about this fleet's history, past incidents, or a decision made before this session.
argument-hint: [terms] [--cat categoria]
---

## Search the knowledge base

The operator's notes live in an external markdown repo with a semantic index.
Search it before answering from memory or from the code alone.

Run this, passing the arguments verbatim:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" recall "$ARGUMENTS"
```

## How to use the result

- Ground the answer in the returned chunks and **name the source file** for each
  claim. A note can be stale; the live system wins.
- When a note contradicts what you observe now, say both and say which you
  trust, instead of quietly picking one.
- If nothing comes back, say the knowledge base has nothing on it — do not
  substitute a guess that reads like a finding.
- If the hit is close but the question is narrower, search again with a more
  specific phrase rather than stretching a loose chunk to fit.
