#!/usr/bin/env python3
"""Snapshot / verify / rollback around a skill edit — following symlinks.

The contract, stated plainly because it differs from the upstream project:

  * A skill reachable from ``~/.claude/skills`` is in scope **however it got
    there** — real directory or symlink to another tree.
  * The snapshot records, for every path, the *real file* it resolves to. That
    is the identity used for change detection, so a write through a link shows
    up as a change to the origin, not as "no change" because the link was
    skipped.
  * Rollback writes to the real file. Restoring a link by replacing the link
    would destroy the share; restoring its origin is what an undo means.

Loop safety: links are followed with an explicit visited-set of real
directories, so a link cycle terminates instead of hanging.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from . import paths


@dataclass
class Entry:
    """One file as the tree sees it, plus the real file it lands on."""

    written: Path          # how it was reached from the root
    real: Path             # resolved destination
    digest: str
    mode: int
    via_link: bool


def _iter_files(root: Path) -> Iterator[Entry]:
    """Yield every file under `root`, following symlinks without looping.

    ``os.walk(followlinks=True)`` would recurse forever on a cycle and gives no
    way to record which path resolved where, so the walk is explicit.
    """
    seen_dirs: set[str] = set()
    stack: List[Path] = [root]

    while stack:
        current = stack.pop()
        try:
            real_dir = str(paths.resolve(current))
        except OSError:
            continue
        if real_dir in seen_dirs:
            continue
        seen_dirs.add(real_dir)

        try:
            entries = list(os.scandir(str(current)))
        except OSError:
            continue

        for entry in entries:
            written = current / entry.name
            try:
                if entry.is_dir(follow_symlinks=True):
                    stack.append(written)
                    continue
                if not entry.is_file(follow_symlinks=True):
                    continue
            except OSError:
                continue

            real = paths.resolve(written)
            digest = paths.digest_file(real)
            if digest is None:
                continue
            try:
                mode = os.stat(str(real)).st_mode
            except OSError:
                mode = 0
            yield Entry(
                written=written,
                real=real,
                digest=digest,
                mode=mode,
                via_link=paths.is_symlink(written) or not paths.is_inside(written, root),
            )


class Snapshot:
    """The tree's state at one instant, keyed by resolved path.

    Keying by ``real`` is the whole point: two links to the same origin are one
    file, and an edit through either must be seen once.
    """

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else paths.skills_root()
        self.entries: Dict[str, Entry] = {}
        self.contents: Dict[str, bytes] = {}
        self.escapes: List[Tuple[Path, Path]] = []

    def capture(self) -> "Snapshot":
        for entry in _iter_files(self.root):
            key = str(entry.real)
            self.entries[key] = entry
            try:
                self.contents[key] = Path(entry.real).read_bytes()
            except OSError:
                pass
            outside = paths.escape_target(entry.real, self.root)
            if outside is not None:
                self.escapes.append((entry.written, outside))
        return self

    # -- reporting ---------------------------------------------------------

    def changed(self, after: "Snapshot") -> List[str]:
        """Resolved paths whose bytes differ, or that appeared / vanished."""
        keys = set(self.entries) | set(after.entries)
        out = []
        for key in sorted(keys):
            before_digest = self.entries[key].digest if key in self.entries else None
            after_digest = after.entries[key].digest if key in after.entries else None
            if before_digest != after_digest:
                out.append(key)
        return out

    def escaped_from(self, root: Optional[Path] = None) -> List[Dict[str, str]]:
        """Every skill file that resolves outside the tree.

        Not an error — it is the documented state of a mirrored skill library.
        It is printed so a human can see which trees an edit can reach.
        """
        root = Path(root) if root else self.root
        out = []
        for key, entry in self.entries.items():
            outside = paths.escape_target(key, root)
            if outside is not None:
                out.append(
                    {
                        "skill": paths.skill_name(key),
                        "link": str(entry.written),
                        "real": str(entry.real),
                    }
                )
        return sorted(out, key=lambda d: d["skill"])


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore(real: Path, original: Optional[bytes], mode: Optional[int] = None) -> bool:
    """Put `original` back at the **real** path.

    Writing to the origin, never to the link, is what makes an undo an undo: the
    link keeps pointing at the shared tree and the shared tree gets its old bytes
    back, which is also what the other machines reading that tree needed.
    """
    try:
        if original is None:
            real.unlink(missing_ok=True)
            return True
        real.parent.mkdir(parents=True, exist_ok=True)
        tmp = real.with_suffix(real.suffix + ".smartclaude-tmp")
        with open(str(tmp), "wb") as fh:
            fh.write(original)
        if mode is not None:
            shutil.copymode(str(real), str(tmp)) if real.exists() else os.chmod(str(tmp), mode)
        os.replace(str(tmp), str(real))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_KEYS = ("name", "description")


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """(frontmatter, body) from a SKILL.md. Tolerant: a broken block yields {}."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    block = text[3:end]
    body = text[end + 4 :]
    data: Dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip().strip("\"'")
    return data, body


def problems_in(text: str, *, is_new: bool, max_description: int = 1024) -> List[str]:
    """Structural complaints, or an empty list when the file is acceptable.

    Only things that make a skill *fail to work* are blocking: a missing
    ``description`` (Claude Code will never surface the skill) and oversized
    description or body (it costs context in every session). Style is not a
    reason to reject a skill an agent wrote.
    """
    problems: List[str] = []
    fm, body = parse_frontmatter(text)

    for key in REQUIRED_KEYS:
        if not fm.get(key):
            problems.append(f"missing {key}")

    description = fm.get("description", "")
    if len(description) > max_description:
        problems.append(f"description {len(description)} chars > {max_description}")

    if not body.strip():
        problems.append("empty body")

    if is_new and len(text) > 200_000:
        problems.append(f"body {len(text)} chars is too large for a new skill")

    return problems
