#!/usr/bin/env python3
"""Index a local markdown tree so it can be searched. Two engines, one dependency.

Default engine is **lexical**: a JSON index and BM25 ranking, written with nothing but
the standard library. If `chromadb` happens to be importable, `index` also builds a
vector collection and `query` uses it — semantic search when it is available, working
search when it is not.

That order is deliberate. The knowledge base is notes on disk; needing 490 MB of
onnxruntime to find a sentence in them was a bad trade, and it failed on machines
where the dependency could not be installed at all, leaving the base with no index.

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
    <kb>/.venv/bin/python                   optional: interpreter with chromadb

Both indexes live outside the tree, in `~/.cache/smartclaude/kb-index`, so the notes
stay plain text and can be copied, grepped and backed up by hand.

Verbs: sync | index | query | stats
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

KB_ROOT = Path(__file__).resolve().parent
NOTES = KB_ROOT / "categorias"
DB = Path(os.environ.get("SMARTCLAUDE_KB_INDEX") or Path.home() / ".cache" / "smartclaude" / "kb-index")
LEXICON = DB / "index.json"

MIN_CHUNK = 80  # characters; below this a chunk is noise (a bare heading)

try:  # optional on purpose — see the module docstring
    import chromadb

    HAVE_CHROMA = True
except ImportError:  # pragma: no cover - depends on the interpreter
    chromadb = None
    HAVE_CHROMA = False

# Words that carry no signal and would match everything. Portuguese first, because
# the notes are written in Portuguese, plus the English function words that leak in.
STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas
que e é ou se com sem para pra por mais menos muito muita muito pouco sobre entre até
ao aos à às já não nao sim como quando onde qual quais quem cujo cuja seu sua seus suas
este esta estes estas esse essa esses essas aquele aquela isso isto aquilo eu tu ele ela
nós nos vos eles elas me te lhe lhes mim ti si meu minha meus minhas teu tua teus tuas
nosso nossa nossos nossas dele dela deles delas está esta estou estão estava estavam ser
sou somos são era eram sido sendo ter tem tinha tinham tive teve haver há havia foi foram
vai vão vou pode podem podia deve devem faz fazem fez feito nem também tambem já so só
apenas cada todo toda todos todas outro outra outros outras mesmo mesma aqui ali lá
the a an and or of to in is are was were be been being it this that these those for on
with as at by from not no but if then than so such can could should would will
""".split())

K1, B = 1.5, 0.75  # BM25 constants; the usual defaults, and they hold up on notes


def get_collection(client):
    return client.get_or_create_collection("notes", metadata={"hnsw:space": "cosine"})


def _client():
    """One place that knows chromadb is optional, so the checker stops guessing."""
    if chromadb is None:
        raise RuntimeError("chromadb is not installed")
    return chromadb.PersistentClient(path=str(DB))


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


def tokenize(text: str) -> list[str]:
    """Lowercase, strip accents, drop stopwords. 'Índice' and 'indice' must match."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return [t for t in re.findall(r"[a-z0-9_]+", text) if len(t) > 1 and t not in STOPWORDS]


def collect() -> list[dict]:
    """Every chunk on disk, in a stable order."""
    chunks: list[dict] = []
    if not NOTES.is_dir():
        return chunks
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
            chunks.append({
                "id": f"{rel}#{i}",
                "path": rel,
                "category": category,
                "chunk": i,
                "text": chunk,
            })
    return chunks


def index_lexical(chunks: list[dict]) -> None:
    df: Counter = Counter()
    lengths = []
    for chunk in chunks:
        tokens = tokenize(chunk["text"])
        chunk["len"] = len(tokens)
        lengths.append(len(tokens))
        for term in set(tokens):
            df[term] += 1
    DB.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "engine": "lexical",
        "chunks": chunks,
        "df": dict(df),
        "avgdl": (sum(lengths) / len(lengths)) if lengths else 0.0,
    }
    tmp = LEXICON.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, LEXICON)


def query_lexical(text: str, category: str | None, n: int) -> int:
    if not LEXICON.is_file():
        print("no index yet; run: vk.py index", file=sys.stderr)
        return 1
    payload = json.loads(LEXICON.read_text(encoding="utf-8"))
    chunks = payload["chunks"]
    if category:
        chunks = [c for c in chunks if c["category"] == category]
    if not chunks:
        return 0

    qterms = tokenize(text)
    if not qterms:
        print("nothing searchable in that query", file=sys.stderr)
        return 1

    df = payload.get("df") or {}
    avgdl = payload.get("avgdl") or 1.0
    total = len(payload["chunks"])

    scored = []
    for chunk in chunks:
        tf = Counter(tokenize(chunk["text"]))
        dl = chunk.get("len") or 1
        score = 0.0
        for term in qterms:
            if term not in tf:
                continue
            # BM25: rare terms count more, long chunks are normalised down.
            idf = math.log(1 + (total - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            score += idf * (tf[term] * (K1 + 1)) / (
                tf[term] + K1 * (1 - B + B * dl / avgdl)
            )
        if score > 0:
            scored.append((score, chunk))

    best: dict[str, tuple[str, float]] = {}
    for score, chunk in scored:
        path = chunk["path"]
        if path not in best or score > best[path][1]:
            best[path] = (chunk["text"], score)

    for path, (doc, score) in sorted(best.items(), key=lambda kv: -kv[1][1])[:n]:
        print(f"\n### {path}  (score {score:.3f})")
        print(doc.strip()[:600])
    return 0


def index() -> int:
    chunks = collect()
    if not chunks:
        # Write the empty index anyway: a base with no notes yet should still answer
        # `stats` and `status` truthfully instead of looking broken.
        index_lexical([])
        print("indexed: 0 files, 0 chunks (no notes yet)")
        return 0

    files = len({c["path"] for c in chunks})
    categories = len({c["category"] for c in chunks})

    index_lexical(chunks)
    engine = "lexical"

    if HAVE_CHROMA:
        try:
            col = get_collection(_client())
            existing = set(col.get()["ids"])
            ids = [c["id"] for c in chunks]
            col.upsert(
                ids=ids,
                documents=[c["text"] for c in chunks],
                metadatas=[{"category": c["category"], "path": c["path"], "chunk": c["chunk"]}
                           for c in chunks],
            )
            stale = existing - set(ids)
            if stale:
                col.delete(ids=sorted(stale))
            engine = "lexical + vector"
        except Exception as exc:  # noqa: BLE001 - a broken vector store must not cost the index
            print(f"vector index skipped: {exc.__class__.__name__}", file=sys.stderr)

    print(f"indexed: {files} files, {len(chunks)} chunks, {categories} categories ({engine})")
    return 0


def query(text: str, category: str | None = None, n: int = 5) -> int:
    if HAVE_CHROMA and not (LEXICON.is_file() and not (DB / "chroma.sqlite3").exists()):
        try:
            col = get_collection(_client())
            if col.count() > 0:
                return query_vector(col, text, category, n)
        except Exception as exc:  # noqa: BLE001
            print(f"vector search unavailable ({exc.__class__.__name__}); using lexical",
                  file=sys.stderr)
    return query_lexical(text, category, n)


def query_vector(col, text: str, category: str | None, n: int) -> int:
    where = {"category": category} if category else None
    # Ask for more than n: several chunks of the same file usually rank together.
    result = col.query(query_texts=[text], n_results=min(n * 4, col.count()), where=where)

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
    if LEXICON.is_file():
        payload = json.loads(LEXICON.read_text(encoding="utf-8"))
        chunks = payload["chunks"]
        files = sorted({c["path"] for c in chunks})
        engine = "lexical"
        if HAVE_CHROMA and (DB / "chroma.sqlite3").exists():
            engine = "lexical + vector"
        print(f"total: {len(chunks)} chunks in {len(files)} files (engine: {engine})")
        seen = set()
        for chunk in chunks:
            if chunk["path"] in seen:
                continue
            seen.add(chunk["path"])
            print(f"  {chunk['category']:14s} {chunk['path']}")
        return 0

    if HAVE_CHROMA:
        col = get_collection(_client())
        got = col.get()
        metadatas = got.get("metadatas") or []
        files = sorted({m["path"] for m in metadatas})
        print(f"total: {len(got['ids'])} chunks in {len(files)} files (engine: vector)")
        for m in metadatas:
            print(f"  {m['category']:14s} {m['path']}")
        return 0

    print("nothing indexed yet; run: vk.py index")
    return 0


def sync() -> int:
    """Reindex the local tree.

    Kept so the CLI matches what memory.py probes. There is no remote: this
    knowledge base is local and unversioned by design.
    """
    return index()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="vk.py", description="Index local markdown and search it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="reindex the local tree")
    sub.add_parser("index", help="(re)index categorias/**/*.md")
    q = sub.add_parser("query", help="search the notes")
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
