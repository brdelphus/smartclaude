"""Where each skill came from.

`status` could only see symlinks, so a tree full of imported skills reported
"0 mirrored" and looked empty — technically true, useless in practice. An imported
skill is a local copy, indistinguishable from one written by hand, so the only way
to tell them apart afterwards is to write it down at import time.

This is a ledger, not a source of truth about what exists: the skills directory is
the truth. The ledger only answers "where did this one come from", and a missing
entry means "unknown", which is honest for anything imported before it existed.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

LEDGER = "imports.json"
VERSION = 1


def _path() -> Path:
    from . import paths  # local import: paths owns the location rules

    return paths.state_dir() / LEDGER


def load(path: Optional[Path] = None) -> Dict[str, dict]:
    """The recorded skills, keyed by skill name. Empty when there is no ledger."""
    target = Path(path) if path else _path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    skills = data.get("skills")
    return skills if isinstance(skills, dict) else {}


def record(entries: Iterable[dict], path: Optional[Path] = None) -> int:
    """Add or refresh entries. Returns how many were written.

    An existing entry is replaced rather than duplicated: importing the same skill
    twice should not grow the ledger. The write is atomic, because a half-written
    ledger would make every later status lie.
    """
    target = Path(path) if path else _path()
    current = load(target)
    written = 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        current[name] = {
            "source": entry.get("source") or "unknown",
            "kind": entry.get("kind") or "unknown",
            "from": entry.get("from") or "",
            "at": stamp,
        }
        written += 1

    if not written:
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": VERSION, "skills": current}, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".imports.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return written


def forget(names: Iterable[str], path: Optional[Path] = None) -> int:
    """Drop entries — used when a skill is removed on purpose."""
    target = Path(path) if path else _path()
    current = load(target)
    removed = [n for n in names if current.pop(n, None) is not None]
    if removed:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": VERSION, "skills": current}, indent=2, sort_keys=True)
        target.write_text(payload + "\n", encoding="utf-8")
    return len(removed)


def by_source(path: Optional[Path] = None) -> Dict[str, int]:
    """How many skills came from each source, most first."""
    tally: Dict[str, int] = {}
    for entry in load(path).values():
        source = str(entry.get("source") or "unknown")
        tally[source] = tally.get(source, 0) + 1
    return dict(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))


def classify(present: List[str], mirrored: Iterable[str], path: Optional[Path] = None) -> dict:
    """Split the skills that exist into mirrored, imported and hand-written.

    Mirrored wins over imported: a symlink points somewhere else, and that is the
    more useful fact about it. Anything in the tree the ledger does not know is
    reported as local — which is not the same as "hand-written", so the report says
    "unrecorded" rather than inventing an origin.
    """
    ledger = load(path)
    mirror_set = set(mirrored)
    imported, local = [], []
    for name in present:
        if name in mirror_set:
            continue
        # Keys can be nested ("security-auditor/llm-app-probing"); the ledger stores
        # the skill's own name, so match on the last component.
        (imported if (name.split("/")[-1] in ledger) else local).append(name)
    return {
        "total": len(present),
        "mirrored": sorted(mirror_set),
        "imported": sorted(imported),
        "local": sorted(local),
        "sources": by_source(path),
    }
