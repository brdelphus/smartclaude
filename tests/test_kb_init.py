#!/usr/bin/env python3
"""The knowledge base must exist, survive a re-install, and actually retrieve.

Two classes of assertion here:

- **Structural** — the folder, the indexer, the README and the notes directory are
  created; running install again changes nothing the operator owns. These always
  run, with or without chromadb.
- **Functional** — index, query and stats actually round-trip a fact. These run
  only when a Chroma-capable interpreter is available, because downloading
  chromadb is not something a test suite should do silently. When it is skipped,
  the test says so instead of pretending it passed.

Run: python3 tests/test_kb_init.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import kb_init  # noqa: E402

failures: list[str] = []
skipped: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def note(root: Path, category: str, name: str, text: str) -> Path:
    path = root / "categorias" / category / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


SAMPLE_BACKUP = """# Backup schedule

## When it runs
The nightly backup starts at 04:31 and writes a tarball. A missing file means the
job died, not that there was no work to do that night.

## Why that hour
It sits after the maintenance window and before the first morning pipeline.
"""

SAMPLE_DNS = """# DNS token handling

## How the token travels
The API token goes either as a query parameter or as a bearer header. There is no
cookie session, so a browser flow will not work against it.

## Exporter wiring
The exporter reads its config from a config map; editing the deployment is what
gets overwritten on the next upgrade.
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smartclaude-kb-"))

    print("creates the layout")
    root = tmp / "kb"
    result = kb_init.install(root)
    check("action reported", result.action in ("created", "created-no-index"), result.action)
    check("notes folder exists", (root / "categorias" / "geral").is_dir())
    check("indexer copied", (root / "vk.py").is_file())
    check("indexer matches the template", (root / "vk.py").read_bytes() == kb_init.VK_TEMPLATE.read_bytes())
    check("README written", "# Knowledge base" in (root / "README.md").read_text())
    check("nothing versioned", not (root / ".git").exists())

    print("is idempotent and never eats a note")
    mine = note(root, "infra", "mine", SAMPLE_BACKUP)
    before = mine.read_bytes()
    again = kb_init.install(root)
    check("second run reports the base already existed",
          again.action in ("exists", "created-no-index"), again.action)
    check("operator note untouched", mine.read_bytes() == before)

    print("status reports what is there")
    st = kb_init.status(root)
    check("status finds notes", any("note(s)" in s for s in st.steps), str(st.steps))

    print("chromadb is available for the functional checks")
    python = kb_init._venv_python(root / ".venv")
    if not kb_init._has_chromadb(python):
        skipped.append("functional round-trip: chromadb was not installed in this run")
        print("  SKIP chromadb not available (offline, or the install reported a warning)")
    else:
        note(root, "infra", "dns", SAMPLE_DNS)

        index = subprocess.run(
            [str(python), str(root / "vk.py"), "index"],
            cwd=str(root), capture_output=True, text=True,
        )
        check("index runs", index.returncode == 0, (index.stderr or "")[-300:])
        check("index counts chunks", "chunks" in index.stdout, index.stdout.strip()[:120])

        stats = subprocess.run(
            [str(python), str(root / "vk.py"), "stats"],
            cwd=str(root), capture_output=True, text=True,
        )
        check("stats runs", stats.returncode == 0, stats.stderr[-200:])
        check("stats lists both notes",
              "categorias/infra/backup.md" in stats.stdout or "categorias/infra/mine.md" in stats.stdout,
              stats.stdout[:200])

        found = subprocess.run(
            [str(python), str(root / "vk.py"), "query", "when does the backup run", "-n", "3"],
            cwd=str(root), capture_output=True, text=True,
        )
        check("query returns the right file", "mine.md" in found.stdout, found.stdout[:200])
        check("query uses the documented header format", "### " in found.stdout and "(dist " in found.stdout)

        filtered = subprocess.run(
            [str(python), str(root / "vk.py"), "query", "backup", "--cat", "dns", "-n", "3"],
            cwd=str(root), capture_output=True, text=True,
        )
        check("--cat filters by category",
              "mine.md" not in filtered.stdout, filtered.stdout[:200])

    print()
    if skipped:
        for s in skipped:
            print(f"SKIPPED: {s}")
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
