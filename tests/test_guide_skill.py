#!/usr/bin/env python3
"""The guidance skill must install, stay current, and pass our own audit.

The last assertion is the one with teeth: a skill that teaches how to write skills
has no excuse for failing the measurement it recommends. If `smartclaude-guide`
ever gets a `NEVER SAYS WHEN` flag or crosses a ceiling, this test fails before a
user sees it.

Run: python3 tests/test_guide_skill.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import guide  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def tracked_skill_files() -> list[str]:
    """SKILL.md files that git has committed here.

    The rule is that the repository ships no skill — not that a working copy can
    never hold one. Anyone exercising the mirror or the importer will end up with an
    untracked SKILL.md, and failing them for that says nothing about what ships.

    If git is unavailable the check falls back to the filesystem, which is stricter
    but only ever wrong in the safe direction.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "*/SKILL.md", "SKILL.md"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0:
            return [line for line in out.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return [str(p.relative_to(REPO)) for p in REPO.rglob("SKILL.md") if ".git" not in p.parts]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smartclaude-guide-"))

    print("the repository ships no SKILL.md")
    found = tracked_skill_files()
    check("zero SKILL.md committed", not found, str(found[:3]))
    untracked = [p for p in REPO.rglob("SKILL.md")
                 if ".git" not in p.parts and str(p.relative_to(REPO)) not in found]
    if untracked:
        print(f"  note: {len(untracked)} untracked SKILL.md in the working copy "
              f"({', '.join(str(p.relative_to(REPO)) for p in untracked[:3])}) — not a failure")
    check("template exists", guide.TEMPLATE.is_file())

    print("installs into an empty tree")
    root = tmp / "skills"
    first = guide.install(root)
    dest = root / guide.SKILL_NAME / "SKILL.md"
    check("action is created", first.action == "created", first.action)
    check("file is there", dest.is_file())
    check("has frontmatter", dest.read_text().startswith("---\nname: "))

    print("is idempotent")
    before = dest.read_bytes()
    second = guide.install(root)
    check("second run unchanged", second.action == "unchanged", second.action)
    check("file not touched", dest.read_bytes() == before)

    print("refreshes an outdated copy")
    dest.write_text(dest.read_text().replace("# Working with skills", "# SIMON SAYS OLD"))
    third = guide.install(root)
    check("action is updated", third.action == "updated", third.action)
    check("old content gone", "SIMON SAYS OLD" not in dest.read_text())

    print("never overwrites a hand-written skill")
    foreign_root = tmp / "foreign"
    fdest = foreign_root / guide.SKILL_NAME / "SKILL.md"
    fdest.parent.mkdir(parents=True)
    fdest.write_text("---\nname: smartclaude-guide\ndescription: mine. Use when x.\n---\n\nmine\n")
    fbefore = fdest.read_bytes()
    refused = guide.install(foreign_root)
    check("action is foreign", refused.action == "foreign", refused.action)
    check("file untouched", fdest.read_bytes() == fbefore)

    print("removal takes the skill and the empty folder")
    guide.remove(root)
    check("file gone", not dest.exists())
    check("empty folder gone", not (root / guide.SKILL_NAME).exists())
    check("removing twice is quiet", guide.remove(root).action == "absent")

    print("the generated skill passes our own audit")
    fresh = tmp / "audited"
    guide.install(fresh)
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "audit.py"), str(fresh), "--json"],
        capture_output=True, text=True,
    )
    check("audit ran", proc.returncode == 0, proc.stderr[-300:])
    rows = json.loads(proc.stdout) if proc.stdout.strip() else []
    row = rows[0] if rows else {}
    check("exactly one skill measured", len(rows) == 1, str(len(rows)))
    check("no defects", row.get("defects") == [], str(row.get("defects")))
    check("description says when", row.get("says_when") is True, str(row.get("says_when")))
    check("under the token ceiling", row.get("tokens", 0) < 5000, str(row.get("tokens")))
    check("under the line ceiling", row.get("lines", 0) < 500, str(row.get("lines")))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
