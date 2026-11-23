#!/usr/bin/env python3
"""Extended memory: recall from, and write into, an external markdown knowledge base.

The design rule here is *do not invent storage*. A knowledge base that already
exists (a git repo of markdown with its own indexer) owns its own format, its own
chunking and its own vector store. smartclaude's job is to read from it on
demand and append to it in the format it already uses — never to fork a second
database that drifts from the first.

Concretely, with the `valeria-knowledge` layout:

    <kb>/categorias/<cat>/<slug>.md   the text, tracked by git
    <kb>/vk.py                        index / query / stats
    <kb>/.venv/bin/python             the interpreter that has chromadb

Everything is discovered, nothing is hard-coded: `SMARTCLAUDE_KB_REPO` picks the
root, the interpreter comes from the repo's own venv when present, and the CLI
verb is probed rather than assumed. When no knowledge base is configured every
function returns empty and the caller degrades to a no-op.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import paths

INDEX_SCRIPT = "vk.py"
CATEGORIES = "categorias"
TIMEOUT = int(os.environ.get("SMARTCLAUDE_KB_TIMEOUT", "180"))


@dataclass
class Hit:
    source: str
    title: str
    body: str
    distance: float = 0.0

    def render(self, max_chars: int = 1200) -> str:
        body = self.body.strip()
        if len(body) > max_chars:
            body = body[:max_chars].rstrip() + "\n[...]"
        head = f"**{self.title}**  `{self.source}`"
        return f"{head}\n{body}"


def interpreter(kb: Path) -> str:
    """The python that can import the knowledge base's dependencies.

    Its own venv first — the system interpreter was proven not to have them.
    """
    for candidate in (kb / ".venv" / "bin" / "python", kb / "venv" / "bin" / "python"):
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return sys.executable


def available() -> bool:
    return paths.knowledge_repo() is not None


def _run(kb: Path, args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [interpreter(kb), str(kb / INDEX_SCRIPT), *args],
        cwd=str(kb),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


BLOCK_RE = re.compile(r"^###\s+(?P<src>\S+)\s+\(dist\s+(?P<dist>[0-9.]+)\)\s*$", re.M)


def parse_hits(stdout: str) -> List[Hit]:
    """Turn the indexer's human output into hits.

    The format is ``### <path>  (dist X)`` followed by the chunk. Parsed
    defensively: an unexpected line is treated as body text rather than dropped,
    so a format change degrades instead of returning nothing.
    """
    hits: List[Hit] = []
    marks = list(BLOCK_RE.finditer(stdout))
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(stdout)
        chunk = stdout[start:end].strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        title = lines[0].strip() if lines else ""
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else chunk
        hits.append(
            Hit(
                source=m.group("src"),
                title=title or Path(m.group("src")).stem,
                body=body,
                distance=float(m.group("dist")),
            )
        )
    return hits


def recall(query: str, limit: int = 5, category: Optional[str] = None) -> List[Hit]:
    """Semantic search in the knowledge base. Empty list when unavailable."""
    kb = paths.knowledge_repo()
    if kb is None or not query.strip():
        return []
    args = ["query", query, "-n", str(limit)]
    if category:
        args += ["--cat", category]
    try:
        proc = _run(kb, args)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return parse_hits(proc.stdout)


# ---------------------------------------------------------------------------
# Writing back
# ---------------------------------------------------------------------------


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "nota"


@dataclass
class WriteResult:
    path: Path
    chunks: Optional[int] = None
    sections: int = 0
    warning: Optional[str] = None

    def describe(self, kb: Path) -> str:
        rel = self.path.relative_to(kb)
        line = f"Written: {self.path}"
        if self.chunks is not None:
            line += f"\nIndexed: {self.chunks} chunk(s) from {self.sections} section(s) of {rel}"
        if self.warning:
            line += f"\nWarning: {self.warning}"
        return line


def count_sections(body: str) -> int:
    """Markdown headings in the body — what the base's chunker splits on."""
    return len(re.findall(r"^#{1,6}\s+\S", body, re.M))


def chunks_of(kb: Path, rel: str) -> Optional[int]:
    """How many chunks the index actually holds for this file.

    Read back from the base's own `stats`, which prints one line per chunk. A
    write is not done until the index shows it — the same rule as the audit:
    verify before reporting.
    """
    try:
        proc = _run(kb, ["stats"])
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return sum(1 for line in (proc.stdout or "").splitlines() if rel in line)


def remember(
    title: str,
    body: str,
    category: str = "geral",
    *,
    reindex: bool = True,
    overwrite: bool = False,
) -> Optional[Path]:
    """Append a note to the knowledge base as a markdown file.

    Written in the base's own shape — ``categorias/<cat>/<slug>.md``. An H1 is
    always supplied; H2 sections are the caller's job, and when the body has none
    the result says so, because a heading-less file indexes as one diluted blob
    and loses the section-level chunking. Returns a `WriteResult`, or None when no
    base is configured or the file exists and `overwrite` is false.
    """
    kb = paths.knowledge_repo()
    if kb is None or not body.strip():
        return None

    cat = re.sub(r"[^a-z0-9_-]+", "-", category.lower()).strip("-") or "geral"
    target_dir = kb / CATEGORIES / cat
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{slugify(title)}.md"
    if target.exists() and not overwrite:
        return None

    text = body if body.lstrip().startswith("# ") else f"# {title}\n\n{body.strip()}\n"
    temp = target.with_suffix(".md.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(str(temp), str(target))

    if reindex:
        try:
            _run(kb, ["index"])
        except (OSError, subprocess.SubprocessError):
            pass

    sections = count_sections(text)
    rel = str(target.relative_to(kb))
    chunks = chunks_of(kb, rel) if reindex else None

    # The chunker drops any section shorter than 80 characters, so heading count
    # predicts nothing — only the measured chunk count does. Report the measurement.
    warning = None
    if chunks is not None and chunks <= 1 and sections > 1:
        warning = (
            f"has {sections} headings but indexed as a single chunk: the base drops "
            "sections under 80 characters. Section-level chunking is what lifted "
            "recall@5 from 94.4% to 100%, so a note worth splitting needs sections "
            "with real body text under each heading, not one-liners."
        )
    elif chunks is not None and chunks <= 1 and sections == 0:
        warning = (
            "has no headings at all, so the whole note is one chunk and its "
            "embedding is diluted by everything in it. Group the content under `## ` "
            "headings with 80+ characters each."
        )
    return WriteResult(path=target, chunks=chunks, sections=sections, warning=warning)


def stats() -> str:
    kb = paths.knowledge_repo()
    if kb is None:
        return "no knowledge base configured"
    try:
        proc = _run(kb, ["stats"])
        return (proc.stdout or proc.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"stats failed: {exc.__class__.__name__}"
