#!/usr/bin/env python3
"""Mirror a skill tree into Claude Code's discovery path, by symlink.

    python3 scripts/sync_skills.py [--src DIR] [--dst DIR] [--prune] [--dry-run]

Why symlink and not copy: the source tree is the single place the text is edited.
Two copies is how one machine keeps running a rule the other already fixed. This
is the same decision the upstream project's ecosystem arrived at, with one
addition that matters — the mirror is **recorded**, so the write guard and the
session report know these skills resolve outside the tree and say so instead of
silently treating them as local.

Exit codes: 0 done, 1 source missing, 2 bad argument.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import paths  # noqa: E402

SKIP_DIRS = {".archive", ".trash", "node_modules", "__pycache__"}


def find_skills(src: Path):
    """Yield (name, dir) for every SKILL.md under `src`, skipping archives."""
    for skill_md in src.rglob("SKILL.md"):
        if any(part in SKIP_DIRS for part in skill_md.parts):
            continue
        yield skill_md.parent.name, skill_md.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=os.environ.get("SMARTCLAUDE_SKILLS_SRC"))
    ap.add_argument("--dst", default=str(paths.skills_root()))
    ap.add_argument("--prune", action="store_true", help="remove links whose target is gone")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.src:
        sys.exit(
            "No source tree given. Mirroring is opt-in: pass --src <dir> or set "
            "SMARTCLAUDE_SKILLS_SRC. This plugin never assumes where skills come "
            "from, because it does not require any other agent to be installed."
        )
    src = Path(args.src).expanduser().absolute()
    dst = Path(args.dst).expanduser().absolute()
    if src == dst:
        sys.exit(f"Source and destination are the same tree: {src}")
    if not src.is_dir():
        print(f"source not found: {src}", file=sys.stderr)
        return 1
    dst.mkdir(parents=True, exist_ok=True)

    created = updated = kept = collisions = 0
    seen: set[str] = set()

    for name, path in find_skills(src):
        if name in seen:
            print(f"  collision: {name} ({path}) — first one wins", file=sys.stderr)
            collisions += 1
            continue
        seen.add(name)

        link = dst / name
        if link.is_symlink():
            if os.path.realpath(link) == os.path.realpath(path):
                kept += 1
                continue
            if not args.dry_run:
                link.unlink()
            updated += 1
        elif link.exists():
            print(f"  kept (not a link): {link}", file=sys.stderr)
            kept += 1
            continue
        else:
            created += 1

        if not args.dry_run:
            link.symlink_to(path)

    pruned = 0
    if args.prune:
        for link in sorted(dst.iterdir()) if dst.is_dir() else []:
            if link.is_symlink() and not link.exists():
                if not args.dry_run:
                    link.unlink()
                pruned += 1

    print(
        f"src={src}\ndst={dst}\n"
        f"created={created} updated={updated} kept={kept} "
        f"pruned={pruned} collisions={collisions}"
        + ("  (dry-run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
