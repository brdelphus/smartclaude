---
description: Save a durable lesson to the external knowledge base. Use when a session produced something a future session would otherwise rediscover.
argument-hint: "[title]"
---

## What belongs here

A note is worth writing when it would save a future session real work: a
non-obvious command, a trap that cost time, a decision and the reason behind it.
It is **not** a place for narration of what just happened — that is what the
transcript is for.

Write the note in the knowledge base's own shape: an H1 title, then H2 sections.
Its chunker splits on headings, so a heading-less file indexes as one diluted
blob and stops being findable.

## Write it

Compose the note on stdin and save it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" remember "$ARGUMENTS" --cat <categoria> <<'NOTE'
# Título

## Contexto
O que estava acontecendo.

## O que foi feito
O comando, a config, a decisão — concreto.

## Por quê
O motivo. Sem isso a nota vira receita sem raciocínio e envelhece mal.
NOTE
```

Use the category that matches the operator's tree (`infra`, `infra`, `k3s`,
`void`...). Check with `ls` inside the knowledge base before inventing one.

## Then

Confirm the file path that was written. If the note duplicates an existing one,
say so and patch that file instead of creating a second copy that will drift.
