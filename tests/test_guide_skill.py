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
import os
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


def tracked_skill_files() -> list[str] | None:
    """SKILL.md files that are committed here; None when that cannot be judged.

    The rule is that the repository ships no skill — not that a working copy can
    never hold one. Anyone exercising the mirror or the importer will end up with an
    untracked SKILL.md, and failing them for that says nothing about what ships.

    HEAD is the right question, not the index: what gets published is the commit.
    Outside a git checkout there is nothing to judge — the published tree is the
    commit — so this returns None and the caller skips the check with a note instead
    of failing on whatever happens to sit on disk.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [line.strip() for line in out.stdout.splitlines()
            if line.strip() == "SKILL.md" or line.strip().endswith("/SKILL.md")]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smartclaude-guide-"))

    print("the repository ships no SKILL.md")
    found = tracked_skill_files()
    if found is None:
        print("  note: not a git checkout — nothing to judge against, skipping "
              "(what ships is the commit, not the working copy)")
        found = []
    else:
        check("zero SKILL.md committed", not found,
              "; ".join(found[:5]) + (" ..." if len(found) > 5 else ""))
        if found:
            print("       these SKILL.md files are in HEAD — the repository would")
            print("       publish them. Untrack and commit to clear this test:")
            for p in found[:10]:
                print(f"         git rm --cached '{p}'")
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

    print("the report never passes an estimate off as measured")
    # The audit re-launches itself under an interpreter that has tiktoken. With the
    # re-launch disabled it must still say, in plain words, which mode produced the
    # numbers — a guessed token count presented as measured is worse than no count.
    plain = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "audit.py"), str(fresh)],
        capture_output=True, text=True,
        env=dict(os.environ, SMARTCLAUDE_AUDIT_REEXEC="1"),
    )
    check("audit runs without the re-launch", plain.returncode == 0, plain.stderr[-300:])
    check("declares the token mode",
          "MEASURED with tiktoken" in plain.stdout or "ESTIMATED from character count" in plain.stdout,
          plain.stdout[:200])

    print("the remediation mode names the file and the change")
    # Diagnosing without saying where to edit is half a job, and on a mirrored skill
    # the obvious file is the wrong one — the link edits the tree at its origin.
    with tempfile.TemporaryDirectory() as broken:
        skill = os.path.join(broken, "vague-skill")
        os.makedirs(skill)
        with open(os.path.join(skill, "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nname: vague-skill\ndescription: Does a thing.\n---\n\n# Vague\n")
        out = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "audit.py"), broken, "--explain"],
            capture_output=True, text=True,
            env=dict(os.environ, SMARTCLAUDE_AUDIT_REEXEC="1"),
        )
        check("explain runs", out.returncode == 0, out.stderr[-300:])
        check("names the defect", "NEVER SAYS WHEN" in out.stdout, out.stdout[:200])
        check("quotes the current description", "Does a thing." in out.stdout, out.stdout[:300])
        check("says what to change", "fix :" in out.stdout, out.stdout[:200])
        check("names the file", "edit:" in out.stdout or "origin" in out.stdout, out.stdout[:200])

    print("measures by borrowing the package when it cannot re-launch")
    # execv() replaces the process, which a sandboxed host can refuse or mask. The
    # package is on disk either way, so adding its site-packages to sys.path must be
    # enough — and that path is what has to keep working where exec does not.
    with tempfile.TemporaryDirectory() as fake:
        site = os.path.join(fake, ".venv", "lib", "python3.99", "site-packages")
        os.makedirs(site)
        with open(os.path.join(site, "tiktoken.py"), "w", encoding="utf-8") as fh:
            fh.write(
                "def get_encoding(name):\n"
                "    return type('E', (), {'encode': lambda self, s: s.split()})()\n"
            )
        probe = subprocess.run(
            [sys.executable, "-c", "import tiktoken"],
            capture_output=True, text=True,
        )
        if probe.returncode == 0:
            print("  note: this interpreter already has tiktoken — borrowing not exercised")
        else:
            out = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "audit.py"), "--doctor"],
                capture_output=True, text=True,
                env=dict(os.environ, SMARTCLAUDE_KB_REPO=fake,
                         SMARTCLAUDE_AUDIT_REEXEC="1", XDG_DATA_HOME="/nonexistent"),
            )
            check("doctor says it borrowed", "borrowed from" in out.stdout, out.stdout[:400])
            check("no re-launch needed", "no re-launch" in out.stdout, out.stdout[:300])

            run = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "audit.py"), str(fresh)],
                capture_output=True, text=True,
                env=dict(os.environ, SMARTCLAUDE_KB_REPO=fake, XDG_DATA_HOME="/nonexistent"),
            )
            check("report says MEASURED", "MEASURED with tiktoken" in run.stdout,
                  run.stdout[:300])

    print("an unusable tokenizer is reported as unusable, not as missing")
    # Importing tiktoken and using it are different failures: get_encoding fetches the
    # vocabulary on first call, so a host with no network or a read-only cache imports
    # fine and then cannot measure. Calling that 'not installed' sends the operator
    # after a package that is already there.
    with tempfile.TemporaryDirectory() as broken:
        site = os.path.join(broken, ".venv", "lib", "python3.99", "site-packages")
        os.makedirs(site)
        with open(os.path.join(site, "tiktoken.py"), "w", encoding="utf-8") as fh:
            fh.write(
                '__version__ = "0.0.0"\n'
                "def get_encoding(name):\n"
                '    raise ConnectionError("no network for the vocabulary")\n'
            )
        env = dict(os.environ, SMARTCLAUDE_KB_REPO=broken, XDG_DATA_HOME="/nonexistent",
                   SMARTCLAUDE_AUDIT_REEXEC="1")
        out = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "audit.py"), "--doctor"],
            capture_output=True, text=True, env=env,
        )
        check("doctor catches the encoding failure", "FAILS" in out.stdout, out.stdout[:400])
        check("doctor names the reason", "no network for the vocabulary" in out.stdout,
              out.stdout[:500])

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
