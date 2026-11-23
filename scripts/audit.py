#!/usr/bin/env python3
"""Measure every SKILL.md under a root and report defects. No model in the loop.

Adapted from the `skill-audit` skill (MIT, sharbelxyz). The measurement model is
kept identical on purpose — same SPEC limits, same flags, same summary — so a
number produced here means the same thing as a number produced there.

Two things are added, because they only mean something in a tree that mirrors by
symlink:

  MIRRORED      the skill is a link; editing it writes into another tree
  DEAD          the link points nowhere — the skill silently stopped existing

Both are resolved with realpath, so a link to a link to a directory still reports
the origin a human can act on.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

SPEC = {"name_max": 64, "desc_max": 1024, "body_lines_max": 500, "body_tokens_max": 5000}
CODE_EXT = {".py", ".sh", ".js", ".ts", ".rb", ".pl", ".bash", ".zsh"}
WHEN = re.compile(
    r"\b(use when|use this when|when you|when the|if you|for when|triggers? on)\b", re.I
)


def count_tokens(text: str):
    """Exact when tiktoken is present, estimated otherwise — and say which."""
    try:
        import tiktoken

        return len(tiktoken.get_encoding("o200k_base").encode(text)), "measured"
    except Exception:
        return round(len(text) / 4.606), "estimated"


def _reexec_with_tokenizer(argv: list[str]) -> None:
    """Switch to an interpreter that has tiktoken, at most once.

    The whole point of this file is to say what a skill costs. Estimating from the
    character count is guesswork, and the difference matters at the 5,000-token
    ceiling. tiktoken is a small optional dependency living in the knowledge base's
    venv, which the installer creates — so instead of asking every caller to know
    which interpreter to use, the audit moves itself there.
    """
    if os.environ.get("SMARTCLAUDE_AUDIT_REEXEC"):
        return
    try:
        import tiktoken  # noqa: F401

        return
    except ImportError:
        pass

    roots = []
    configured = os.environ.get("SMARTCLAUDE_KB_REPO")
    if configured:
        roots.append(configured)
    share = os.environ.get("XDG_DATA_HOME") or str(os.path.expanduser("~/.local/share"))
    roots.append(os.path.join(share, "smartclaude", "kb"))

    for root in roots:
        for rel in (("bin", "python"), ("Scripts", "python.exe")):
            candidate = os.path.join(root, ".venv", *rel)
            if not os.path.isfile(candidate):
                continue
            try:
                probe = subprocess.run([candidate, "-c", "import tiktoken"],
                                       capture_output=True, timeout=60)
            except (OSError, subprocess.SubprocessError):
                continue
            if probe.returncode != 0:
                continue
            os.environ["SMARTCLAUDE_AUDIT_REEXEC"] = "1"
            sys.stdout.flush()
            sys.stderr.flush()
            try:
                os.execv(candidate, [candidate, os.path.abspath(__file__), *argv])
            except OSError:
                return


def parse(path: str):
    raw = open(path, encoding="utf-8", errors="replace").read()
    name = desc = None
    body = raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if m:
        fm, body = m.group(1), raw[m.end():]
        n = re.search(r"^name:\s*(.+)$", fm, re.M)
        d = re.search(r"^description:\s*(.+(?:\n[ \t]+.+)*)$", fm, re.M)
        name = n.group(1).strip().strip("\"'") if n else None
        desc = re.sub(r"\s+", " ", d.group(1)).strip().strip("\"'") if d else None
    return raw, body, name, desc


def link_info(skill_dir: str):
    """Where a skill really lives, and whether that is a different tree."""
    if not os.path.islink(skill_dir):
        return None, None
    if not os.path.isdir(skill_dir):
        return "dead", None
    return "mirrored", os.path.realpath(skill_dir)


def audit(root: str):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "**", "SKILL.md"), recursive=True)):
        skill_dir = os.path.dirname(path)
        status, origin = link_info(skill_dir)
        raw, body, name, desc = parse(path)
        scripts = [
            f
            for f in glob.glob(os.path.join(skill_dir, "**", "*"), recursive=True)
            if os.path.isfile(f) and os.path.splitext(f)[1] in CODE_EXT
        ]
        tokens, provenance = count_tokens(body)
        lines = body.count("\n") + 1

        defects = []
        if not desc:
            defects.append("NO DESCRIPTION")
        elif not WHEN.search(desc):
            defects.append("NEVER SAYS WHEN")
        if name and len(name) > SPEC["name_max"]:
            defects.append("NAME TOO LONG")
        if desc and len(desc) > SPEC["desc_max"]:
            defects.append("DESC TOO LONG")
        if tokens > SPEC["body_tokens_max"]:
            defects.append("OVER TOKEN CEILING")
        if lines > SPEC["body_lines_max"]:
            defects.append("OVER LINE CEILING")
        if scripts:
            defects.append(f"SHIPS CODE ({len(scripts)})")

        rows.append(
            dict(
                skill=os.path.basename(skill_dir),
                path=path,
                lines=lines,
                tokens=tokens,
                provenance=provenance,
                name_len=len(name) if name else 0,
                desc_len=len(desc) if desc else 0,
                says_when=bool(desc and WHEN.search(desc)),
                scripts=len(scripts),
                has_refs=os.path.isdir(os.path.join(skill_dir, "references")),
                link=status,
                origin=origin,
                defects=defects,
            )
        )

    # A dead link has no SKILL.md to walk into, so glob never reaches it. It is
    # still a skill that stopped existing, so it is swept separately.
    for entry in sorted(glob.glob(os.path.join(root, "*"))):
        if os.path.islink(entry) and not os.path.exists(entry):
            rows.append(
                dict(
                    skill=os.path.basename(entry),
                    path=entry,
                    lines=0,
                    tokens=0,
                    provenance="measured",
                    name_len=0,
                    desc_len=0,
                    says_when=False,
                    scripts=0,
                    has_refs=False,
                    link="dead",
                    origin=os.readlink(entry),
                    defects=["DEAD LINK"],
                )
            )
    return rows


def main() -> int:
    _reexec_with_tokenizer(sys.argv[1:])

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", nargs="?", default=os.path.expanduser("~/.claude/skills"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only-defects", action="store_true", help="hide the clean skills")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        sys.exit(f"No such directory: {args.root}")

    rows = audit(args.root)
    if not rows:
        sys.exit(f"No SKILL.md files found under {args.root}")

    if args.json:
        print(json.dumps(rows, indent=1))
        return 0

    rows.sort(key=lambda r: -r["tokens"])
    shown = [r for r in rows if r["defects"]] if args.only_defects else rows

    provenance = (
        "MEASURED with tiktoken o200k_base"
        if rows[0]["provenance"] == "measured"
        else "ESTIMATED from character count (tiktoken not installed)"
    )
    total = sum(r["tokens"] for r in rows)
    startup = sum(r["name_len"] + r["desc_len"] for r in rows)
    mirrored = [r for r in rows if r["link"] == "mirrored"]
    dead = [r for r in rows if r["link"] == "dead"]

    print(f"\n{len(rows)} skills under {args.root}")
    print(f"Token counts: {provenance}")
    if mirrored or dead:
        print(f"Links: {len(mirrored)} mirrored, {len(dead)} dead\n")
    else:
        print()

    print(f"{'SKILL':<32}{'LINES':>7}{'TOKENS':>9}{'':2}  DEFECTS")
    print("-" * 96)
    for r in shown:
        mark = "->" if r["link"] == "mirrored" else ("!!" if r["link"] == "dead" else "")
        print(
            f"{r['skill'][:31]:<32}{r['lines']:>7}{r['tokens']:>9}{mark:>2}  "
            f"{', '.join(r['defects']) or 'clean'}"
        )

    nowhen = [r for r in rows if not r["says_when"]]
    overtok = [r for r in rows if r["tokens"] > SPEC["body_tokens_max"]]
    withcode = [r for r in rows if r["scripts"]]
    refs = [r for r in rows if r["has_refs"]]

    print(f"\n{'':-<96}")
    print(f"  Cannot tell your agent WHEN to run       : {len(nowhen):>3} / {len(rows)}"
          f"  ({100 * len(nowhen) // max(len(rows), 1)}%)")
    print(f"  Over the 5,000 token ceiling            : {len(overtok):>3} / {len(rows)}")
    print(f"  Ship runnable code you may not have read: {len(withcode):>3} / {len(rows)}"
          f"   ({sum(r['scripts'] for r in rows)} scripts)")
    print(f"  Use a references/ folder                : {len(refs):>3} / {len(rows)}")
    if mirrored or dead:
        print(f"  Mirrored into another tree (edits land there): {len(mirrored):>3}")
        print(f"  Dead links (skill silently gone)             : {len(dead):>3}")
    print(f"\n  Loaded on EVERY message (names + descriptions): ~{round(startup / 4.606):,} tokens")
    print(f"  Total if every skill fired at once           : {total:,} tokens")

    if dead:
        print("\n  Dead links — the skill no longer exists:")
        for r in dead[:10]:
            print(f"    - {r['skill']}  -> {r['origin']}")
    if nowhen:
        print("\n  Fix these descriptions first, they never fire:")
        for r in nowhen[:10]:
            print(f"    - {r['skill']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
