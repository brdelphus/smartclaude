#!/usr/bin/env python3
"""Path rules — the one place that decides what a skill file is and where it lives.

Why this module exists at all: the upstream project this borrows from walks the
skill tree with ``os.walk(..., followlinks=False)``. A symlinked skill is then
invisible to its snapshot, so a write through the link edits the origin bytes
with no backup, no validation and no rollback — and the code that *would* have
refused it (a ``realpath`` containment check) is never reached because the path
never appears in the changed set.

smartclaude takes the opposite stance on purpose. A skill symlinked to another
tree is a **first-class skill**: the snapshot follows it, records the real file
it lands on, and validates/rolls back that real file. Patching the origin is the
intent, not an accident — a skill that lives in a shared tree should improve for
every machine that tree serves. What must never happen is a silent write.

So containment is decided by **destination**, not by path prefix. ``resolve()``
answers "which real file does this path mean", and every caller reasons about
that answer.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def user_home() -> Path:
    """HOME, honouring the env var on every OS.

    ``Path.home()`` consults USERPROFILE on Windows and ignores HOME, which
    would leak a sandboxed test run onto the real profile.
    """
    for name in ("HOME", "USERPROFILE"):
        configured = os.environ.get(name)
        if configured and os.path.isabs(configured):
            return Path(configured)
    return Path.home()


def config_dir() -> Path:
    """Where Claude Code keeps its per-user state."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override).expanduser().absolute()
    return user_home() / ".claude"


def skills_root() -> Path:
    """The directory Claude Code discovers skills from."""
    return config_dir() / "skills"


def state_dir() -> Path:
    """smartclaude's own state: queue, telemetry, snapshots, quarantine."""
    configured = os.environ.get("SMARTCLAUDE_STATE_DIR")
    if configured:
        return Path(configured).expanduser().absolute()
    return config_dir() / "smartclaude"


def knowledge_repo() -> Optional[Path]:
    """The external knowledge base, when one is configured.

    This is the "extended memory": a git repo of markdown with a vector index
    built beside it. smartclaude never invents storage — it appends markdown and
    asks the repo's own indexer to re-read. Unset means the feature is off, and
    every memory command degrades to a no-op instead of failing.
    """
    for name in ("SMARTCLAUDE_KB_REPO", "VALERIA_KNOWLEDGE_REPO"):
        configured = os.environ.get(name)
        if configured:
            return Path(configured).expanduser().absolute()

    # The base this plugin creates on install. Local, unversioned, made here.
    share = os.environ.get("XDG_DATA_HOME") or (user_home() / ".local" / "share")
    local = Path(share) / "smartclaude" / "kb"
    if (local / "vk.py").is_file():
        return local

    # A base that predates this one, still honoured when it is the only option.
    legacy = user_home() / "projects" / "valeria-knowledge"
    return legacy if (legacy / "vk.py").is_file() else None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def resolve(path: Path | str) -> Path:
    """The real file a path means, symlinks and all."""
    return Path(os.path.realpath(str(path)))


def is_symlink(path: Path | str) -> bool:
    return os.path.islink(str(path))


def is_skill_file(path: Path | str) -> bool:
    """A SKILL.md inside any ``.claude/skills`` tree, by the path as written.

    Deliberately a string test: hooks receive the path the *tool* was given, and
    that is the path the user will see in their transcript. Resolution happens
    separately, in :func:`resolve`.
    """
    norm = str(path or "").replace("\\", "/")
    return "/.claude/skills/" in norm and norm.endswith("SKILL.md")


def skill_name(path: Path | str) -> str:
    """Identity of a skill: its directory name, following the link.

    Following matters here. ``~/.claude/skills/mailu-ops`` is a link to
    ``.../skills/devops/mailu-ops``; the identity a human and a usage record
    care about is ``mailu-ops`` either way, so this reads the *written* path's
    parent first and falls back to the resolved one.
    """
    norm = Path(str(path or ""))
    return norm.parent.name or resolve(norm).parent.name


def real_skill_dir(path: Path | str) -> Path:
    """The directory that actually holds the skill's files."""
    return resolve(path).parent


def is_inside(child: Path | str, parent: Path | str) -> bool:
    """True when `child` resolves to a location under `parent`.

    Both sides are resolved, so neither a symlink escaping the tree nor a
    symlink parent can lie about containment.
    """
    try:
        base = resolve(parent)
        target = resolve(child)
        return base == target or base in target.parents
    except (OSError, ValueError):
        return False


def escape_target(path: Path | str, root: Path | str | None = None) -> Optional[Path]:
    """If `path` resolves outside the skills tree, return where it escapes to.

    Returns None when the path is inside the tree — the common case. This is the
    function the write guard consults before allowing an edit, and what the
    report shows so a human can see which trees are exposed.
    """
    root = Path(root) if root else skills_root()
    if is_inside(path, root):
        return None
    return resolve(path)


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path | str) -> Optional[str]:
    """sha256 of the file as the destination sees it, or None if unreadable."""
    try:
        h = hashlib.sha256()
        with open(str(path), "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def backup_path(path: Path | str, backups: Path | None = None) -> Path:
    """Where the pre-edit copy of `path` lives.

    Keyed on the **resolved** path, not the path as written. Two different links
    can point at the same origin file; keying on the link would give the same
    origin two divergent backups and let one rollback restore the other's bytes.
    """
    target = resolve(path)
    digest = hashlib.sha256(str(target).encode("utf-8", "surrogateescape")).hexdigest()[:12]
    base = backups or (state_dir() / "backups")
    return Path(base) / f"{skill_name(path)}-{digest}.bak"
