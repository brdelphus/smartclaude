#!/usr/bin/env python3
"""`status` must be able to say where a skill came from, and count what is there.

Three bugs are pinned here, each one real:

1. Counting only symlinks made a tree full of imported skills report `0 mirrored`
   and look empty. An imported skill is a plain copy; nothing in the filesystem
   distinguishes it from a hand-written one, so the origin has to be recorded.
2. `escaped_from()` overcounts — it walks into a skill's own subdirectories and
   reports references/, scripts/ and nested folders as separate skills (210 where
   the tree held 200).
3. Keying by bare name hides a real skill when the same name exists at two depths
   (`x/SKILL.md` and `y/x/SKILL.md`), which happened on a real machine.

Run: python3 tests/test_provenance.py
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

import cli  # noqa: E402
from lib import provenance  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def make_skill(root: Path, rel: str, name: str | None = None) -> Path:
    folder = root / rel
    folder.mkdir(parents=True, exist_ok=True)
    skill = folder / "SKILL.md"
    skill.write_text(
        f"---\nname: {name or Path(rel).name}\ndescription: Use when testing. Does a thing.\n---\n\n# T\n\nbody\n",
        encoding="utf-8",
    )
    return skill


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smartclaude-prov-"))
    ledger = tmp / "imports.json"

    print("the ledger records, replaces and counts")
    provenance.record(
        [
            {"name": "alpha", "source": "copilot", "kind": "legacy", "from": "/a"},
            {"name": "beta", "source": "hermes", "kind": "skill", "from": "/b"},
        ],
        path=ledger,
    )
    loaded = provenance.load(ledger)
    check("both recorded", set(loaded) == {"alpha", "beta"}, str(list(loaded)))
    check("source kept", loaded["alpha"]["source"] == "copilot")
    check("timestamp written", bool(loaded["alpha"]["at"]))

    provenance.record([{"name": "alpha", "source": "copilot", "kind": "legacy", "from": "/a2"}], path=ledger)
    check("re-record does not duplicate", len(provenance.load(ledger)) == 2)
    check("re-record updates the source path", provenance.load(ledger)["alpha"]["from"] == "/a2")
    check("by_source counts", provenance.by_source(ledger) == {"copilot": 1, "hermes": 1},
          str(provenance.by_source(ledger)))

    print("a corrupt ledger is treated as empty, not fatal")
    broken = tmp / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    check("no crash on invalid json", provenance.load(broken) == {})

    print("the tree is counted by path, not by bare name")
    tree = tmp / "skills"
    make_skill(tree, "plain")
    make_skill(tree, "nested/plain")          # same name, different depth
    make_skill(tree, "other")

    mirror_src = tmp / "elsewhere" / "mirrored"
    make_skill(mirror_src.parent, "mirrored")
    (tree / "mirrored").symlink_to(mirror_src, target_is_directory=True)

    on_disk = cli._skills_on_disk(tree)
    check("counts every SKILL.md, including the same name at two depths",
          len(on_disk) == 4, str(sorted(on_disk)))
    check("nested key is qualified", "nested/plain" in on_disk, str(sorted(on_disk)))
    check("symlinked skill detected", on_disk.get("mirrored") is True)
    check("local skill is not flagged as mirrored", on_disk.get("plain") is False)

    print("a root reached through a symlink does not turn every skill into a mirror")
    # macOS: tempfile.mkdtemp() returns /var/folders/... which resolves to
    # /private/var/folders/..., so an absolute-path comparison called every local
    # skill mirrored and the suite failed on a machine where nothing was wrong.
    real = tmp / "realtree"
    make_skill(real, "local-one")
    alias = tmp / "aliastree"
    alias.symlink_to(real, target_is_directory=True)
    aliased = cli._skills_on_disk(alias)
    check("local skill under an aliased root stays local",
          aliased.get("local-one") is False, str(aliased))
    (alias / "linked").symlink_to(tmp / "elsewhere" / "mirrored", target_is_directory=True)
    aliased = cli._skills_on_disk(alias)
    check("a real mirror under an aliased root is still detected",
          aliased.get("linked") is True, str(aliased))

    print("classify splits mirrored, imported and unrecorded")
    provenance.record([{"name": "plain", "source": "copilot"}], path=ledger)
    mirrored = [k for k, v in on_disk.items() if v]
    split = provenance.classify(sorted(on_disk), mirrored, path=ledger)
    check("total matches the tree", split["total"] == 4, str(split["total"]))
    check("mirrored is the symlink", split["mirrored"] == ["mirrored"], str(split["mirrored"]))
    # The ledger stores a skill's own name, so a nested copy of a recorded name
    # counts as imported too -- both are that skill, at different depths.
    check("imported includes the nested copy of a recorded name",
          split["imported"] == ["nested/plain", "plain"], str(split["imported"]))
    check("the rest is unrecorded", sorted(split["local"]) == ["other"], str(split["local"]))

    print("status reports it end to end")
    cfg = tmp / "cfg"
    (cfg / "skills").mkdir(parents=True, exist_ok=True)
    make_skill(cfg / "skills", "imported-one")
    (cfg / "smartclaude").mkdir(parents=True, exist_ok=True)
    (cfg / "smartclaude" / "imports.json").write_text(
        json.dumps({"version": 1, "skills": {"imported-one": {"source": "copilot", "kind": "legacy", "at": "x"}}}),
        encoding="utf-8",
    )
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(cfg))
    for key in ("SMARTCLAUDE_KB_REPO", "VALERIA_KNOWLEDGE_REPO"):
        env.pop(key, None)
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "cli.py"), "status"],
        capture_output=True, text=True, env=env,
    )
    text = out.stdout
    check("status ran", out.returncode == 0, out.stderr[-300:])
    check("reports the total", "skills total      : 1" in text, text)
    check("reports it as imported, not as zero", "skills imported   : 1" in text, text)
    check("names the source", "copilot 1" in text, text)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
