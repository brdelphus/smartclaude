#!/usr/bin/env python3
"""Guard the rule: this plugin assumes Claude Code and nothing else.

The rule is not decoration. Anything that reads another agent's directory by
default turns an install into a host-specific setup: it works on the machine it
was written on and does nothing on a clean one, and the failure is silent. So the
source of a mirror is always explicit, and the executable code never names a
foreign agent.

A path like `~/.hermes/profiles/.../skills` may appear in prose as an example —
that is documentation, not behaviour. This test only fails on executable code.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Trees that run. Documentation is deliberately excluded.
EXECUTABLE = ["scripts", "hooks", ".claude-plugin"]

# Other agents, by the names that would reveal an assumption.
FOREIGN = ["hermes", "openclaw", "cursor-agent", "aider", "continue.dev"]


def executable_files():
    for name in EXECUTABLE:
        base = ROOT / name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".json", ".sh", ".md"}:
                yield path


def test_no_foreign_agent_in_code():
    offenders = []
    for path in executable_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for foreign in FOREIGN:
            if foreign in text:
                offenders.append(f"{path.relative_to(ROOT)} mentions {foreign!r}")
    assert not offenders, "foreign agent assumed in executable code:\n  " + "\n  ".join(offenders)


def test_mirror_refuses_without_source():
    """No --src and no env must fail loudly, never guess a source tree."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": tmp,
            "CLAUDE_CONFIG_DIR": f"{tmp}/.claude",
        }
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sync_skills.py")],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode != 0, "mirror ran without a source tree"
        assert "--src" in (proc.stdout + proc.stderr), "no explanation printed"


def test_mirror_refuses_self_source():
    """src == dst would walk the tree it is writing — refused, not tolerated."""
    with tempfile.TemporaryDirectory() as tmp:
        skills = pathlib.Path(tmp) / ".claude" / "skills"
        (skills / "demo").mkdir(parents=True)
        (skills / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "CLAUDE_CONFIG_DIR": f"{tmp}/.claude"}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sync_skills.py"), "--src", str(skills)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode != 0, "mirror accepted src == dst"


def test_audit_needs_no_other_agent():
    """A clean tree audits on its own, with no auto-memory or agent dirs present."""
    with tempfile.TemporaryDirectory() as tmp:
        skill = pathlib.Path(tmp) / "only" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            '---\nname: only\ndescription: "Use when proving it runs alone."\n---\n\n# Only\n'
        )
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "CLAUDE_CONFIG_DIR": f"{tmp}/.claude"}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "audit.py"), tmp, "--json"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        assert '"skill": "only"' in proc.stdout


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
