#!/usr/bin/env python3
"""Operator CLI — the same code the hooks run, callable by hand and by commands.

    cli.py recall <terms> [-n N] [--cat CAT]   search the knowledge base
    cli.py remember <title> [--cat CAT]        append a note (body on stdin)
    cli.py status                              skills, mirrors, memory base
    cli.py mirror [--prune] [--dry-run]        sync the skill tree into ~/.claude/skills

Everything prints plain text meant to be read by a model or a human, never JSON
on stdout that a slash command would then have to decode.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import distill, guard, memory, paths  # noqa: E402


def cmd_recall(args) -> int:
    if not memory.available():
        print("No knowledge base configured (set SMARTCLAUDE_KB_REPO).")
        return 1
    hits = memory.recall(" ".join(args.terms), limit=args.n, category=args.cat)
    if not hits:
        print(f"Nothing in the knowledge base for: {' '.join(args.terms)}")
        return 0
    print(f"{len(hits)} hit(s) in {paths.knowledge_repo()}:\n")
    for hit in hits:
        print(hit.render())
        print()
    return 0


def cmd_remember(args) -> int:
    body = sys.stdin.read()
    if not body.strip():
        print("Empty body — pipe the note on stdin.", file=sys.stderr)
        return 2
    path = memory.remember(" ".join(args.title), body, category=args.cat, overwrite=args.force)
    if path is None:
        print(
            "Not written: no knowledge base configured, or that note already "
            "exists. Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1
    print(f"Written: {path}")
    return 0


def cmd_status(_args) -> int:
    root = paths.skills_root()
    print(f"skills root : {root}")
    print(f"state dir   : {paths.state_dir()}")
    kb = paths.knowledge_repo()
    print(f"knowledge   : {kb if kb else 'not configured'}")
    if kb:
        print(f"interpreter : {memory.interpreter(kb)}")

    try:
        snap = guard.Snapshot(root).capture()
    except Exception as exc:
        print(f"snapshot failed: {exc.__class__.__name__}")
        return 0

    escaped = snap.escaped_from()
    unique = sorted({e["skill"] for e in escaped})
    print(f"\nfiles in tree     : {len(snap.entries)}")
    print(f"skills mirrored   : {len(unique)}")
    if unique:
        origins = sorted({str(Path(e["real"]).parent.parent.parent) for e in escaped})
        print("mirror origins    :")
        for origin in origins[:5]:
            print(f"  {origin}")
        print(
            "\nAn edit to a mirrored skill changes the origin tree, not a local "
            "copy. Hooks back up and validate the real file; the link survives a "
            "rollback."
        )
    return 0


def cmd_distill_status(_args) -> int:
    report = distill.queue_report()
    counts = report["counts"] or {}
    print(f"queue       : {distill.db_path()}")
    print(f"jobs        : {counts if counts else 'empty'}")
    print(f"thresholds  : {distill.MIN_CALLS} calls + {distill.MIN_EDITS} edits, "
          f"or {distill.READONLY_CALLS} calls read-only")
    ready = distill.headless_ready()
    print(f"headless    : {'ready' if ready else 'NOT available — jobs will only nudge'}")
    for job in report["recent"]:
        print(f"  #{job['id']} {job['session']} {job['state']:8} {job['note']}")
    return 0


def cmd_distill_now(args) -> int:
    transcript = args.transcript
    if transcript is None:
        candidates = sorted(
            Path(paths.config_dir() / "projects").glob("*/*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            print("No transcript found — pass --transcript.", file=sys.stderr)
            return 1
        transcript = str(candidates[-1])
    print(f"transcript: {transcript}")
    rc = subprocess.call([sys.executable,
                          str(Path(__file__).resolve().parent / "worker.py"),
                          "--transcript", transcript])
    report = distill.queue_report()
    print(f"after      : {report['counts']}")
    for job in report["recent"][:3]:
        print(f"  #{job['id']} {job['session']} {job['state']:8} {job['note']}")
    return rc


def cmd_mirror(args) -> int:
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "sync_skills.py")]
    if args.prune:
        cmd.append("--prune")
    if args.dry_run:
        cmd.append("--dry-run")
    return subprocess.call(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recall")
    r.add_argument("terms", nargs="+")
    r.add_argument("-n", type=int, default=5)
    r.add_argument("--cat", default=None)
    r.set_defaults(func=cmd_recall)

    m = sub.add_parser("remember")
    m.add_argument("title", nargs="+")
    m.add_argument("--cat", default="geral")
    m.add_argument("--force", action="store_true")
    m.set_defaults(func=cmd_remember)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    ds = sub.add_parser("distill-status")
    ds.set_defaults(func=cmd_distill_status)

    dn = sub.add_parser("distill-now")
    dn.add_argument("--transcript", default=None)
    dn.set_defaults(func=cmd_distill_now)

    mi = sub.add_parser("mirror")
    mi.add_argument("--prune", action="store_true")
    mi.add_argument("--dry-run", action="store_true")
    mi.set_defaults(func=cmd_mirror)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
