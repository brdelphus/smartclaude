#!/usr/bin/env python3
"""Index a local markdown tree into a local Chroma database.

This is the indexer smartclaude ships for the knowledge base it creates on
install. It is deliberately small and has exactly one dependency: `chromadb`.

Two design notes, both learned the hard way elsewhere:

**Chunk by heading.** Measured on a real corpus with a ground-truth benchmark of
18 queries: indexing whole files gave recall@5 94.4% and MRR 0.861; indexing per
section gave recall@5 100% and MRR 0.972. Without it, one table in a long note
dilutes the whole file's embedding and the file stops being found. Each chunk is
prefixed with the document title so it does not lose its context.

**Nothing leaves this machine.** There is no git here and no remote. `sync` exists
only so the CLI surface matches what `memory.py` probes; it reindexes the local
tree.

Layout it expects:

    <kb>/categorias/<category>/<note>.md    the text
    <kb>/.venv/bin/python                   interpreter with chromadb

The vector database lives outside the tree, in `~/.cache/smartclaude/kb-index`,
so the notes stay plain text and can be copied, grepped and backed up by hand.

Verbs: sync | index | query | stats
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

KB_ROOT = Path(__file__).resolve().parent
NOTES = KB_ROOT / "categorias"
DB = Path(os.environ.get("SMARTCLAUDE_KB_INDEX") or Path.home() / ".cache" / "smartclaude" / "kb-index")

MIN_CHUNK = 80  # characters; below this a chunk is noise (a bare heading)

import chromadb  # noqa: E402


def get_collection(client):
    return client.get_or_create_collection("notes", metadata={"hnsw:space": "cosine"})


def split_sections(text: str):
    """Split on markdown headings, prefixing each chunk with the document title."""
    title = ""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if m:
        title = m.group(1).strip()
    parts = re.split(r"(?m)^(?=#{1,6}\s)", text)
    out = []
    for part in parts:
        part = part.strip()
        if len(part) < MIN_CHUNK:
            continue
        if title and not part.startswith("# "):
            part = f"{title}\n\n{part}"
        out.append(part)
    return out or ([text.strip()] if text.strip() else [])


def index() -> int:
    client = chromadb.PersistentClient(path=str(DB))
    col = get_collection(client)

    ids, documents, metadatas = [], [], []
    for note in sorted(NOTES.rglob("*.md")):
        rel = note.relative_to(KB_ROOT).as_posix()
        parts = note.relative_to(NOTES).parts
        category = parts[0] if len(parts) > 1 else "uncategorized"
        try:
            text = note.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"skipped {rel}: {exc.__class__.__name__}", file=sys.stderr)
            continue
        for i, chunk in enumerate(split_sections(text)):
            ids.append(f"{rel}#{i}")
            documents.append(chunk)
            metadatas.append({"category": category, "path": rel, "chunk": i})

    if not documents:
        print("indexed: 0 files, 0 chunks (no notes yet)")
        return 0

    existing = set(col.get()["ids"])
    col.upsert(ids=ids, documents=documents, metadatas=metadatas)
    stale = existing - set(ids)
    if stale:
        col.delete(ids=sorted(stale))

    files = len({m["path"] for m in metadatas})
    categories = len({m["category"] for m in metadatas})
    print(f"indexed: {files} files, {len(documents)} chunks, {categories} categories")
    return 0


def query(text: str, category: str | None = None, n: int = 5) -> int:
    client = chromadb.PersistentClient(path=str(DB))
    col = get_collection(client)
    if col.count() == 0:
        print("the knowledge base is empty; nothing to search", file=sys.stderr)
        return 1

    where = {"category": category} if category else None
    # Ask for more than n: several chunks of the same file usually rank together.
    result = col.query(
        query_texts=[text],
        n_results=min(n * 4, col.count()),
        where=where,
    )

    best: dict[str, tuple[str, float]] = {}
    for doc, meta, dist in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        path = meta["path"]
        if path not in best or dist < best[path][1]:
            best[path] = (doc, dist)

    if not best:
        return 0
    for path, (doc, dist) in sorted(best.items(), key=lambda kv: kv[1][1])[:n]:
        print(f"\n### {path}  (dist {dist:.3f})")
        print(doc.strip()[:600])
    return 0


def stats() -> int:
    client = chromadb.PersistentClient(path=str(DB))
    col = get_collection(client)
    got = col.get()
    metadatas = got.get("metadatas") or []
    files = sorted({m["path"] for m in metadatas})
    print(f"total: {len(got['ids'])} chunks in {len(files)} files")
    for m in metadatas:
        print(f"  {m['category']:14s} {m['path']}")
    return 0


def sync() -> int:
    """Reindex the local tree.

    Kept so the CLI matches what memory.py probes. There is no remote: this
    knowledge base is local and unversioned by design.
    """
    return index()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="vk.py", description="Index local markdown into local Chroma.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="reindex the local tree")
    sub.add_parser("index", help="(re)index categorias/**/*.md")
    q = sub.add_parser("query", help="semantic search")
    q.add_argument("texto")
    q.add_argument("--cat", default=None)
    q.add_argument("-n", type=int, default=5)
    sub.add_parser("stats", help="what is indexed")
    args = ap.parse_args(argv)

    if args.cmd == "sync":
        return sync()
    if args.cmd == "index":
        return index()
    if args.cmd == "query":
        return query(args.texto, args.cat, args.n)
    return stats()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
