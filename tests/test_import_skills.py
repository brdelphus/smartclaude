#!/usr/bin/env python3
"""Importing from another agent: what it converts, and what it refuses to destroy.

The importer is the only part of smartclaude that writes over a tree full of someone
else's skills, so the collisions are the interesting part. Two agents can both own a
skill called `skill-audit` and neither is wrong — the import has to keep that a choice
the operator makes, not a coin flip.

Run: python3 tests/test_import_skills.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "import_skills.py"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def make(home: Path, where: str, name: str, description: str, body: str = "corpo\n") -> Path:
    """Drop a skill into the tree a source would have, or the destination tree."""
    skill = home / where / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}", encoding="utf-8"
    )
    return skill


def run(home: Path, dst: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--from", "copilot", "--dst", str(dst), *args],
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, HOME=str(home), PYTHONPATH=""),
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)

        print("a collision does not cost the operator their working skill")
        # Both tools legitimately own the name. Skipping loses the import; forcing
        # loses the skill that already worked. Rename is the only answer that keeps
        # both, and it is the one a person would pick if asked.
        make(home, ".copilot/skills", "skill-audit", "Use when auditing: from copilot.")
        dst = home / ".claude/skills"
        make(home, ".claude/skills", "skill-audit", "Use when auditing: mine.", "MINHA\n")

        out = run(home, dst)
        check("default run succeeds", out.returncode == 0, out.stderr[-300:])
        check("default skips the collision", "skipped" in out.stdout, out.stdout[:300])
        check("existing skill untouched",
              "MINHA" in (dst / "skill-audit" / "SKILL.md").read_text())

        out = run(home, dst, "--on-conflict", "rename")
        renamed = dst / "skill-audit-copilot"
        check("rename run succeeds", out.returncode == 0, out.stderr[-300:])
        check("renamed skill exists", renamed.is_dir(), str(renamed))
        check("original still there", (dst / "skill-audit" / "SKILL.md").is_file())
        check("original untouched",
              "MINHA" in (dst / "skill-audit" / "SKILL.md").read_text())
        check("renamed copy is the imported one",
              "copilot" in renamed.joinpath("SKILL.md").read_text())
        # Renaming only the folder leaves a skill that answers to a name that is not
        # on disk — the agent loads `name:`, not the directory.
        check("frontmatter name follows the folder",
              "name: skill-audit-copilot" in renamed.joinpath("SKILL.md").read_text(),
              renamed.joinpath("SKILL.md").read_text()[:120])

        print("\na dry run tells the truth about collisions")
        out = run(home, dst, "--on-conflict", "rename", "--dry-run")
        check("dry run succeeds", out.returncode == 0, out.stderr[-300:])
        check("dry run predicts the new name", "skill-audit-copilot" in out.stdout,
              out.stdout[:300])

        print("\nforce is available, and only when asked for")
        out = run(home, dst, "--on-conflict", "force")
        check("force run succeeds", out.returncode == 0, out.stderr[-300:])
        check("force replaced the skill",
              "copilot" in (dst / "skill-audit" / "SKILL.md").read_text(),
              (dst / "skill-audit" / "SKILL.md").read_text()[:120])

        print("\na description that never says when is flagged at import time")
        # Import preserves someone else's wording on purpose. But a description with no
        # trigger produces a skill that loads on every message and can never fire, and
        # nobody looks at the file again once it is in the tree.
        make(home, ".copilot/skills", "sem-gatilho", "Checklist de PR da empresa.")
        out = run(home, dst, "--on-conflict", "rename")
        check("import succeeds", out.returncode == 0, out.stderr[-300:])
        check("warns about the missing trigger",
              "never says WHEN" in out.stdout, out.stdout[:400])

        print("\na second collision does not silently reuse the name")
        # Own source tree and own destination: what is under test is the increment, not
        # the re-scan of whatever the earlier rounds left behind.
        home2 = Path(tempfile.mkdtemp(prefix="smartclaude-import2-"))
        dst2 = home2 / ".claude" / "skills"
        make(home2, ".claude/skills", "outra", "Use when mine.", "MINE\n")
        make(home2, ".claude/skills", "outra-copilot", "Use when other.", "OTHER\n")
        make(home2, ".copilot/skills", "outra", "Use when testing.", "A\n")
        out = run(home2, dst2, "--on-conflict", "rename")
        check("second rename picks a free name", "outra-copilot-2" in out.stdout,
              out.stdout[:400])
        check("all three variants on disk",
              all((dst2 / n).is_dir() for n in ("outra", "outra-copilot", "outra-copilot-2")),
              str(sorted(p.name for p in dst2.iterdir()) if dst2.is_dir() else "no dst"))
        check("the pre-existing variant was not overwritten",
              "OTHER" in (dst2 / "outra-copilot" / "SKILL.md").read_text())
        shutil.rmtree(home2, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
