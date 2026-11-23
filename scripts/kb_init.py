"""Create the local knowledge base on install.

The base is deliberately unglamorous: a folder of markdown and a Chroma index
beside it. No git, no remote, no account. It exists so that `recall` and
`remember` have somewhere to work the moment the plugin is installed, instead of
the operator discovering months later that extended memory was never configured.

Layout created:

    ~/.local/share/smartclaude/kb/
      vk.py                    indexer (sync | index | query | stats)
      categorias/geral/        notes, plain markdown
      .venv/                   interpreter that has chromadb
      README.md                what this folder is

The index lives at `~/.cache/smartclaude/kb-index`, outside the tree, so the notes
stay portable text.

Three behaviours worth stating:

- **Idempotent.** Running again reuses the existing venv and leaves notes alone.
  It never deletes a note.
- **Never fatal.** If Chroma cannot be installed (offline, no pip, a proxy), the
  notes folder is still created and the failure is reported as a warning with the
  command to finish the job by hand. An installer that aborts because an optional
  feature could not be provisioned is worse than one that says what is missing.
- **Local only.** No path here touches a remote. `SMARTCLAUDE_KB_REPO` overrides
  the location for anyone who wants the base somewhere else.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VK_TEMPLATE = REPO_ROOT / "templates" / "vk.py"
VENV_TIMEOUT = int(os.environ.get("SMARTCLAUDE_VENV_TIMEOUT", "900"))

README = """# Knowledge base

Plain markdown notes with a semantic index built beside them. Written by
`/remember`, searched by `/recall`.

- **Nothing is versioned and nothing is uploaded.** This folder is local.
- `categorias/<category>/<note>.md` — one fact per note, H1 title, H2 sections.
  The indexer chunks on headings; a note without them indexes as one diluted blob
  and stops being findable.
- The search index lives outside this folder, in `~/.cache/smartclaude/kb-index`.
  Deleting it is safe — `index` rebuilds it from the notes.

```bash
.venv/bin/python vk.py index          # reindex after adding notes by hand
.venv/bin/python vk.py query "..."    # search
.venv/bin/python vk.py stats          # what is indexed
```
"""


@dataclass
class Result:
    action: str                       # created | exists | created-no-index | error
    root: Path
    steps: list[str] = field(default_factory=list)
    warning: str = ""

    def describe(self) -> str:
        if self.action == "error":
            return f"{self.root}: {self.warning or 'failed'}"
        lines = [f"{self.root}: {self.action}"]
        lines += [f"  {s}" for s in self.steps]
        if self.warning:
            lines.append(f"  warning: {self.warning}")
        return "\n".join(lines)


def default_root() -> Path:
    override = os.environ.get("SMARTCLAUDE_KB_REPO")
    if override:
        return Path(override).expanduser().absolute()
    share = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(share) / "smartclaude" / "kb"


def _venv_python(venv: Path) -> Path:
    for rel in ("bin/python", "Scripts/python.exe"):
        candidate = venv / rel
        if candidate.is_file():
            return candidate
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _has_chromadb(python: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(python), "-c", "import chromadb"],
            capture_output=True, timeout=120,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _build_venv(root: Path) -> tuple[bool, str]:
    """Create the venv and install chromadb. Returns (ok, message)."""
    venv = root / ".venv"
    python = _venv_python(venv)

    if not python.is_file():
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv)],
                check=True, capture_output=True, timeout=VENV_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"could not create the venv: {exc.__class__.__name__}"

    if _has_chromadb(python):
        return True, "chromadb already present"

    for extra in ([], ["--user"]):
        try:
            proc = subprocess.run(
                [str(python), "-m", "pip", "install", "--quiet", *extra, "chromadb"],
                capture_output=True, text=True, timeout=VENV_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"pip failed: {exc.__class__.__name__}"
        if proc.returncode == 0 and _has_chromadb(python):
            return True, "chromadb installed"
        last = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        message = last[0][:160]
    return False, f"could not install chromadb ({message})"


def _reindex(root: Path) -> tuple[bool, str]:
    python = _venv_python(root / ".venv")
    try:
        proc = subprocess.run(
            [str(python), str(root / "vk.py"), "index"],
            cwd=str(root), capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"index failed: {exc.__class__.__name__}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return False, f"index failed: {tail[0][:160]}"
    return True, (proc.stdout or "").strip().splitlines()[-1][:120] if proc.stdout.strip() else "indexed"


def install(root: Path | None = None, install_deps: bool = True) -> Result:
    """Create the knowledge base.

    ``install_deps=False`` builds the layout and the indexer but skips the venv and
    the chromadb install. That path takes milliseconds instead of half a minute and
    needs no network, which is what the test suite uses for its structural checks —
    a test suite should not silently hit PyPI. The installer always leaves it True.
    """
    root = Path(root).expanduser() if root else default_root()
    steps: list[str] = []

    fresh = not root.exists()
    for sub in ("categorias/geral",):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(README, encoding="utf-8")

    if VK_TEMPLATE.is_file():
        shutil.copyfile(VK_TEMPLATE, root / "vk.py")
        os.chmod(root / "vk.py", 0o755)
        steps.append("indexer written")
    else:
        return Result("error", root, steps, f"missing template: {VK_TEMPLATE}")

    if not install_deps:
        steps.append("dependencies skipped")
        return Result("exists" if not fresh else "created-no-index", root, steps,
                      "dependencies were not installed")

    ok, message = _build_venv(root)
    if not ok:
        return Result(
            "created-no-index", root, steps,
            f"{message}. Notes still work; to finish by hand: "
            f"cd {root} && python3 -m venv .venv && .venv/bin/pip install chromadb && .venv/bin/python vk.py index",
        )
    steps.append(message)

    indexed, index_message = _reindex(root)
    if indexed:
        steps.append(index_message)
    else:
        return Result("created-no-index", root, steps, index_message)

    return Result("exists" if not fresh else "created", root, steps)


def status(root: Path | None = None) -> Result:
    root = Path(root).expanduser() if root else default_root()
    if not root.exists():
        return Result("error", root, [], "not created yet")
    steps = []
    if (root / "vk.py").is_file():
        steps.append("indexer present")
    notes = list((root / "categorias").rglob("*.md")) if (root / "categorias").is_dir() else []
    steps.append(f"{len(notes)} note(s)")
    python = _venv_python(root / ".venv")
    steps.append("chromadb ready" if _has_chromadb(python) else "chromadb MISSING")
    return Result("exists", root, steps)


def _main(argv: list[str]) -> int:
    import argparse, json

    ap = argparse.ArgumentParser(description="Create the local smartclaude knowledge base")
    ap.add_argument("action", nargs="?", default="install", choices=["install", "status"])
    ap.add_argument("--root", help="where to create it (default: XDG data dir)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    fn = {"install": install, "status": status}[args.action]
    result = fn(Path(args.root) if args.root else None)

    if args.json:
        print(json.dumps({
            "action": result.action, "root": str(result.root),
            "steps": result.steps, "warning": result.warning,
        }))
    else:
        print(result.describe())
    return 1 if result.action == "error" else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
