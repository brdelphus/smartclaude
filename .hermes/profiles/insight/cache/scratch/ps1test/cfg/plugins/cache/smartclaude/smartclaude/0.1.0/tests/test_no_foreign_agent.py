#!/usr/bin/env python3
"""Guard the rule: this plugin never reads another agent's tree on its own.

It ships with **no skills**. Everything it knows about skills comes from the
operator importing them on purpose, or from a human writing one.

So the rule is not "never mention another agent" — import is a feature, and the
sources are declared in `SOURCES`. The rule is **no implicit read**: no default
path into a foreign directory, no autodiscovery that installs behind your back,
and no conversion that quietly loses a meaning the source had.

Every test builds its own throwaway trees, so this runs on a machine where none of
those agents is installed — which is exactly the machine the plugin has to work on.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run(script: str, *args: str, home: str):
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "CLAUDE_CONFIG_DIR": f"{home}/.claude"}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=home,
    )


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Ships empty, and stays empty on its own
# ---------------------------------------------------------------------------


def test_repo_ships_no_skills():
    """The plugin must install clean: bundled skills would fire before any import."""
    offenders = [
        str(p.relative_to(ROOT))
        for p in ROOT.rglob("SKILL.md")
        if ".git" not in p.parts and "node_modules" not in p.parts
    ]
    assert not offenders, "the repo ships skills, it must not: " + ", ".join(offenders)


def test_no_implicit_read_on_list():
    """With no --from, nothing is written whatever exists on the machine."""
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".hermes/skills/alpha/SKILL.md",
              '---\nname: alpha\ndescription: "Use when testing."\n---\n\n# A\n')
        write(pathlib.Path(tmp) / ".cursor/rules/beta.mdc",
              '---\ndescription: "Use when beta."\n---\n\n# B\n')
        write(pathlib.Path(tmp) / ".copilot/skills/gamma/SKILL.md",
              '---\nname: gamma\ndescription: "Use when gamma."\n---\n\n# G\n')
        proc = run("import_skills.py", home=tmp)
        assert proc.returncode == 0, proc.stderr
        assert "importable" in proc.stdout, proc.stdout
        installed = pathlib.Path(tmp) / ".claude/skills"
        assert not installed.exists() or not list(installed.iterdir()), "listing installed"


def test_claude_root_is_never_a_foreign_default():
    """The skills root comes from Claude's config, never from another agent."""
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".hermes/skills/decoy/SKILL.md",
              '---\nname: decoy\ndescription: "Use when decoying."\n---\n\n# D\n')
        proc = run("audit.py", "--json", home=tmp)
        assert proc.returncode != 0 or "decoy" not in proc.stdout, \
            "audit reached into a foreign tree by default"


def test_mirror_refuses_without_source():
    with tempfile.TemporaryDirectory() as tmp:
        proc = run("sync_skills.py", home=tmp)
        assert proc.returncode != 0, "mirror ran without a source tree"
        assert "--src" in (proc.stdout + proc.stderr), "no explanation printed"


def test_mirror_refuses_self_source():
    with tempfile.TemporaryDirectory() as tmp:
        skills = pathlib.Path(tmp) / ".claude" / "skills"
        write(skills / "demo" / "SKILL.md", "---\nname: demo\n---\n")
        proc = run("sync_skills.py", "--src", str(skills), home=tmp)
        assert proc.returncode != 0, "mirror accepted src == dst"


def test_audit_needs_no_other_agent():
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / "only/SKILL.md",
              '---\nname: only\ndescription: "Use when proving it runs alone."\n---\n\n# Only\n')
        proc = run("audit.py", tmp, "--json", home=tmp)
        assert proc.returncode == 0, proc.stderr
        assert '"skill": "only"' in proc.stdout


# ---------------------------------------------------------------------------
# Import works, on a machine where that agent is not installed
# ---------------------------------------------------------------------------


def test_import_native_skill_carries_assets():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp) / ".hermes/skills/ops/deploy"
        write(base / "SKILL.md",
              '---\nname: deploy\ndescription: "Use when deploying to staging."\n---\n\n# Deploy\n')
        write(base / "scripts/run.sh", "#!/bin/sh\n")
        write(base / "references/notes.md", "# n\n")
        proc = run("import_skills.py", "--from", "hermes", home=tmp)
        assert proc.returncode == 0, proc.stderr
        target = pathlib.Path(tmp) / ".claude/skills/deploy"
        assert (target / "SKILL.md").is_file(), "skill not imported"
        assert (target / "scripts/run.sh").is_file(), "scripts/ not carried"
        assert (target / "references/notes.md").is_file(), "references/ not carried"
        text = (target / "SKILL.md").read_text()
        assert "name: deploy" in text and "Use when deploying" in text


def test_import_cursor_mdc_is_converted_and_flagged():
    """A .mdc rule becomes a skill; alwaysApply is reported, never silently dropped."""
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".cursor/rules/style.mdc",
              '---\ndescription: "Use when writing React components."\n'
              'globs: "**/*.tsx"\nalwaysApply: false\n---\n\n# React style\n\nUse hooks.\n')
        write(pathlib.Path(tmp) / ".cursor/rules/always.mdc",
              '---\ndescription: "Use when anywhere."\nalwaysApply: true\n---\n\n# Always\n')
        proc = run("import_skills.py", "--from", "cursor", home=tmp)
        assert proc.returncode == 0, proc.stderr
        skill = pathlib.Path(tmp) / ".claude/skills/style/SKILL.md"
        assert skill.is_file(), "mdc not converted"
        text = skill.read_text()
        assert "Use when writing React components" in text
        assert "**/*.tsx" in text, "globs lost in conversion"
        assert "alwaysApply" in proc.stdout, "always-applied rule not flagged"


def test_import_copilot_instructions_is_flagged():
    """The repo-wide Copilot file has no trigger; importing it silently would be wrong."""
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".github/copilot-instructions.md", "# Rules\n\nUse tabs.\n")
        write(pathlib.Path(tmp) / ".github/instructions/tests.instructions.md",
              '---\napplyTo: "**/*_test.py"\ndescription: "Use when writing tests."\n---\n\n# Tests\n')
        proc = run("import_skills.py", "--from", "copilot", home=tmp)
        assert proc.returncode == 0, proc.stderr
        assert (pathlib.Path(tmp) / ".claude/skills/copilot-instructions/SKILL.md").is_file()
        assert (pathlib.Path(tmp) / ".claude/skills/tests/SKILL.md").is_file()
        assert "not a skill" in proc.stdout, "repo-wide file imported without a warning"


def test_import_refuses_to_overwrite_without_force():
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".hermes/skills/mine/SKILL.md",
              '---\nname: mine\ndescription: "Use when importing."\n---\n\n# imported\n')
        write(pathlib.Path(tmp) / ".claude/skills/mine/SKILL.md",
              '---\nname: mine\ndescription: "Use when hand written."\n---\n\n# mine\n')
        proc = run("import_skills.py", "--from", "hermes", home=tmp)
        text = (pathlib.Path(tmp) / ".claude/skills/mine/SKILL.md").read_text()
        assert "hand written" in text, "overwrote a hand-written skill without --force"
        assert "skipped" in proc.stdout.lower()

        run("import_skills.py", "--from", "hermes", "--force", home=tmp)
        text = (pathlib.Path(tmp) / ".claude/skills/mine/SKILL.md").read_text()
        assert "imported" in text, "--force did not overwrite"


def test_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".hermes/skills/x/SKILL.md",
              '---\nname: x\ndescription: "Use when ex."\n---\n\n# X\n')
        proc = run("import_skills.py", "--from", "hermes", "--dry-run", home=tmp)
        assert proc.returncode == 0, proc.stderr
        assert not (pathlib.Path(tmp) / ".claude/skills/x").exists(), "dry-run wrote to disk"


def test_imported_skill_audits_clean():
    """End to end: import, then the audit must accept what it produced."""
    with tempfile.TemporaryDirectory() as tmp:
        write(pathlib.Path(tmp) / ".hermes/skills/good/SKILL.md",
              '---\nname: good\ndescription: "Use when proving the round trip works."\n'
              '---\n\n# Good\n\nBody.\n')
        run("import_skills.py", "--from", "hermes", home=tmp)
        proc = run("audit.py", str(pathlib.Path(tmp) / ".claude/skills"), "--json", home=tmp)
        assert proc.returncode == 0, proc.stderr
        rows = json.loads(proc.stdout)
        assert len(rows) == 1 and rows[0]["defects"] == [], rows


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
