"""Append a managed block to an existing CLAUDE.md, never rewrite it.

The file belongs to the operator. It may already import other files
(`@RTK.md`), carry house rules, or be a symlink into a dotfiles repo. So the
only edit this module is allowed to make is *inside* its own markers:

    <!-- smartclaude:begin -->
    ...
    <!-- smartclaude:end -->

Everything outside those two lines is copied through byte for byte. Three
consequences worth stating, because each one is a bug if broken:

- **Existence is not ownership.** If the file has content, we append. If it
  does not exist, we create it. We never replace it and we never "clean it up".
- **Idempotence.** Installing twice leaves one block, not two. An install that
  changed nothing reports `unchanged` and does not touch the file at all.
- **A half-written block is an error, not a guess.** A begin marker with no end
  marker means someone edited by hand or a write was truncated; guessing where
  the block ends risks deleting their text. We refuse and say so.

The write is atomic (temp file in the same directory, then `os.replace`) so an
interrupted install cannot leave a truncated CLAUDE.md.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

BEGIN = "<!-- smartclaude:begin -->"
END = "<!-- smartclaude:end -->"

BLOCK_BODY = """<!-- Managed by smartclaude. Everything between these markers is replaced on
     install. Content outside them is never touched. -->

## Extended memory

A markdown knowledge base is indexed for semantic search on this machine. It
holds what happened before this session: decisions, incident post-mortems,
infrastructure history, why something is configured the way it is.

- **Search it before answering** anything about past events, earlier decisions,
  or infrastructure that is already running. Use `/recall <question>`.
- **Save durable findings** with `/remember`. One fact per note, a heading that
  says what the note is about, and the answer rather than the investigation.
- **Do not save procedures here.** A procedure belongs in a skill; memory is for
  facts.
- **If `/recall` returns nothing**, the base is not configured on this machine.
  Say that, and answer from what you can read. Do not invent a history."""


@dataclass
class Result:
    action: str          # created | appended | updated | unchanged | removed | absent | broken | error
    path: Path
    detail: str = ""
    backup: Path | None = None

    def describe(self) -> str:
        if self.action == "unchanged":
            return f"{self.path}: already up to date"
        if self.action == "created":
            return f"{self.path}: created with the managed block"
        if self.action == "appended":
            return f"{self.path}: block appended, existing content preserved"
        if self.action == "updated":
            return f"{self.path}: managed block updated, rest untouched"
        if self.action == "removed":
            return f"{self.path}: managed block removed, rest untouched"
        if self.action == "absent":
            return f"{self.path}: no managed block, nothing to remove"
        return f"{self.path}: {self.detail or self.action}"


def _default_path() -> Path:
    root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return Path(root).expanduser() / "CLAUDE.md"


def _read(path: Path) -> str:
    """Read without newline translation.

    `Path.read_text()` runs universal-newline conversion, which silently turns
    CRLF into LF on the way in and rewrites the operator's whole file on the
    way out. A file that already exists must round-trip byte for byte.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _block(newline: str = "\n") -> str:
    body = BLOCK_BODY.replace("\n", newline)
    return f"{BEGIN}{newline}{body}{newline}{END}"


def _locate(text: str) -> tuple[int, int] | None:
    """Return (start, end) offsets of the markers, inclusive of the marker lines.

    Raises ValueError on a half-written block: begin without end, end before
    begin, or duplicates. None means no block at all.
    """
    n_begin = text.count(BEGIN)
    n_end = text.count(END)
    if n_begin == 0 and n_end == 0:
        return None
    if n_begin != 1 or n_end != 1:
        raise ValueError(
            f"expected exactly one {BEGIN!r} and one {END!r}, found {n_begin} and "
            f"{n_end}; fix the markers by hand rather than let a guess delete text"
        )
    start = text.index(BEGIN)
    end = text.index(END)
    if end < start:
        raise ValueError(f"{END!r} appears before {BEGIN!r}")
    end += len(END)
    return start, end


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".claude.md.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
        if path.exists():
            try:
                os.chmod(tmp, path.stat().st_mode & 0o7777)
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install(path: Path | None = None, body: str | None = None) -> Result:
    """Create the file, or add/replace only the managed block inside it."""
    path = Path(path) if path else _default_path()

    if not path.exists():
        _atomic_write(path, (body if body is not None else _block()) + "\n")
        return Result("created", path)

    raw = _read(path)
    block = body if body is not None else _block(_newline_of(raw))
    try:
        span = _locate(raw)
    except ValueError as exc:
        return Result("broken", path, str(exc))

    nl = _newline_of(raw)
    if span is None:
        if raw.endswith(nl * 2):
            sep = ""
        elif raw.endswith(nl):
            sep = nl
        else:
            sep = nl * 2
        merged = f"{raw}{sep}{block}{nl}"
        action = "appended"
    else:
        start, end = span
        merged = f"{raw[:start]}{block}{raw[end:]}"
        action = "unchanged" if merged == raw else "updated"

    if action == "unchanged":
        return Result("unchanged", path)
    _atomic_write(path, merged)
    return Result(action, path)


def remove(path: Path | None = None) -> Result:
    """Delete only the managed block. Never deletes the file itself."""
    path = Path(path) if path else _default_path()
    if not path.exists():
        return Result("absent", path)
    raw = _read(path)
    try:
        span = _locate(raw)
    except ValueError as exc:
        return Result("broken", path, str(exc))
    if span is None:
        return Result("absent", path)

    start, end = span
    nl = _newline_of(raw)
    head = raw[:start].rstrip("\r\n")
    tail = raw[end:].lstrip("\r\n")
    if head and tail:
        merged = f"{head}{nl}{nl}{tail}"
    elif head:
        merged = head + nl
    elif tail:
        merged = tail if tail.endswith("\n") else tail + nl
    else:
        merged = ""

    if not merged.strip():
        # The operator's file was only our block; remove the file we created.
        try:
            path.unlink()
        except OSError:
            _atomic_write(path, "")
        return Result("removed", path, "file contained only the managed block")

    _atomic_write(path, merged)
    return Result("removed", path)


def status(path: Path | None = None) -> Result:
    path = Path(path) if path else _default_path()
    if not path.exists():
        return Result("absent", path, "file does not exist")
    raw = _read(path)
    try:
        span = _locate(raw)
    except ValueError as exc:
        return Result("broken", path, str(exc))
    if span is None:
        return Result("absent", path, "file exists, no managed block")
    return Result("unchanged", path, "managed block is present")


def _main(argv: list[str]) -> int:
    import argparse, json

    ap = argparse.ArgumentParser(description="Manage the smartclaude block in CLAUDE.md")
    ap.add_argument("action", choices=["install", "remove", "status"])
    ap.add_argument("--path", help="target CLAUDE.md (default: $CLAUDE_CONFIG_DIR/CLAUDE.md)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    fn = {"install": install, "remove": remove, "status": status}[args.action]
    result = fn(Path(args.path) if args.path else None)

    if args.json:
        print(json.dumps({"action": result.action, "path": str(result.path), "detail": result.detail}))
    else:
        print(result.describe())
    return 1 if result.action in ("broken", "error") else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
