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


def _say(verbose: bool, message: str) -> None:
    """Progress goes to stderr, so a caller can still capture the result line."""
    if verbose:
        print(f"  {message}", file=sys.stderr, flush=True)


def _has_pip(python: Path) -> bool:
    try:
        return subprocess.run(
            [str(python), "-m", "pip", "--version"],
            capture_output=True, timeout=120,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _run(cmd: list[str], verbose: bool, timeout: int) -> tuple[int, str]:
    """Run a command, streaming its output when verbose, and keep the tail.

    Capturing and quieting made a working download look like a hang. Streaming alone
    would throw the error away, and then the operator gets "could not install
    chromadb: " with no reason. So: stream if asked, always keep the last lines.
    """
    if not verbose:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, ((proc.stderr or "") + (proc.stdout or ""))

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
        tail.append(line.rstrip())
        if len(tail) > 40:
            tail.pop(0)
    try:
        return proc.wait(timeout=timeout), "\n".join(tail)
    except subprocess.TimeoutExpired:
        proc.kill()
        return 1, f"timed out after {timeout}s"


def _build_venv(root: Path, verbose: bool = False) -> tuple[bool, str]:
    """Create the venv and install chromadb. Returns (ok, message).

    ``verbose`` lets pip draw its own progress bar and the caller see it. Installing
    chromadb pulls onnxruntime, numpy and tokenizers — a few hundred megabytes. With
    output captured and --quiet, that is several minutes of an installer appearing to
    hang on a machine that is working perfectly.
    """
    venv = root / ".venv"
    python = _venv_python(venv)

    if not python.is_file():
        _say(verbose, f"creating the Python environment at {venv}")
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv)],
                check=True, capture_output=not verbose, timeout=VENV_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"could not create the venv: {exc.__class__.__name__}"

    # Debian and Ubuntu ship a python3 whose venv has no pip unless python3-venv is
    # installed; `python -m venv` succeeds and every later pip call says "No module
    # named pip". ensurepip is bundled with CPython and fixes it.
    if not _has_pip(python):
        _say(verbose, "the new environment has no pip — bootstrapping it with ensurepip")
        _run([str(python), "-m", "ensurepip", "--default-pip"], verbose, VENV_TIMEOUT)
        if not _has_pip(python):
            return False, ("the environment has no pip and ensurepip could not provide one. "
                           "On Debian or Ubuntu install it first: sudo apt install python3-venv")

    if _has_chromadb(python):
        return True, "chromadb already present"

    _say(verbose, "installing chromadb — 84 packages: about 106 MB to download and "
                  "490 MB on disk (onnxruntime alone is 78 MB). Minutes on a slow link.")
    # No --user fallback: pip refuses it outright inside a virtualenv ("Can not
    # perform a '--user' install"), so the retry could never succeed and only buried
    # the first, real error under a second, invented one.
    cmd = [str(python), "-m", "pip", "install"]
    if not verbose:
        cmd.append("--quiet")
    cmd.append("chromadb")
    try:
        code, output = _run(cmd, verbose, VENV_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run pip: {exc.__class__.__name__}"
    if code == 0 and _has_chromadb(python):
        return True, "chromadb installed"
    tail = output.strip().splitlines()[-1:] or ["no output"]
    return False, f"could not install chromadb: {tail[0][:200]}"


def _reindex(root: Path, verbose: bool = False) -> tuple[bool, str]:
    python = _venv_python(root / ".venv")
    _say(verbose, "indexing the notes")
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


def install(root: Path | None = None, install_deps: bool = True, verbose: bool = False) -> Result:
    """Create the knowledge base.

    ``install_deps=False`` builds the layout and the indexer but skips the venv and
    the chromadb install. That path takes milliseconds instead of half an hour and
    needs no network, which is what the test suite uses for its structural checks —
    a test suite should not silently hit PyPI. The installer always leaves it True.

    ``verbose`` narrates each step on stderr. An installer that goes quiet for
    minutes while pip runs looks broken, and the operator kills it.
    """
    root = Path(root).expanduser() if root else default_root()
    steps: list[str] = []

    fresh = not root.exists()
    _say(verbose, f"knowledge base at {root}")
    for sub in ("categorias/geral",):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(README, encoding="utf-8")

    if VK_TEMPLATE.is_file():
        _say(verbose, "writing the indexer")
        shutil.copyfile(VK_TEMPLATE, root / "vk.py")
        os.chmod(root / "vk.py", 0o755)
        steps.append("indexer written")
    else:
        return Result("error", root, steps, f"missing template: {VK_TEMPLATE}")

    if not install_deps:
        steps.append("dependencies skipped")
        return Result("exists" if not fresh else "created-no-index", root, steps,
                      "dependencies were not installed")

    ok, message = _build_venv(root, verbose=verbose)
    if not ok:
        return Result(
            "created-no-index", root, steps,
            f"{message}. Notes still work; to finish by hand: "
            f"cd {root} && python3 -m venv .venv && .venv/bin/pip install chromadb && .venv/bin/python vk.py index",
        )
    steps.append(message)

    indexed, index_message = _reindex(root, verbose=verbose)
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
    ap.add_argument("--quiet", action="store_true",
                    help="no progress on stderr (the result line still prints)")
    args = ap.parse_args(argv)

    if args.action == "install":
        result = install(Path(args.root) if args.root else None, verbose=not args.quiet)
    else:
        result = status(Path(args.root) if args.root else None)

    if args.json:
        print(json.dumps({
            "action": result.action, "root": str(result.root),
            "steps": result.steps, "warning": result.warning,
        }))
    else:
        print(result.describe())
    # created-no-index is not a failure — the notes work, the index is just absent —
    # but it is not success either, and the caller has to be able to tell.
    if result.action == "error":
        return 1
    if result.action == "created-no-index":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
