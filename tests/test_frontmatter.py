#!/usr/bin/env python3
"""Every frontmatter and manifest path must parse, or the plugin loads degraded.

This exists because three command files shipped with broken YAML and nobody
noticed: `argument-hint: [terms] [--cat x]` is an unquoted flow sequence to a YAML
parser, and one description had a stray tuple around it (`"('text',)"`) that parsed
fine but rendered as garbage. Claude Code tolerates both by dropping the metadata
silently — the command still exists and never fires correctly. That is the worst
failure mode: no error, no behaviour.

Also checks that `icon` points at a real, square PNG. The field is only read by
Anthropic's directory listing, and `claude plugin validate` reports it as an
unknown field before Claude Code v2.1.281 — so the test asserts the file is valid
rather than assuming the validator covered it.

Run: python3 tests/test_frontmatter.py
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def frontmatter_files() -> list[Path]:
    found = []
    for path in sorted(REPO.rglob("*.md")):
        if ".git" in path.parts:
            continue
        if path.parts[len(REPO.parts)] in ("docs",) or path.name == "README.md":
            continue
        if path.read_text(encoding="utf-8").startswith("---\n"):
            found.append(path)
    return found


def split_frontmatter(text: str) -> tuple[str, str] | None:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1), text[m.end():]) if m else None


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("SKIPPED: PyYAML is not installed, cannot parse frontmatter")
        return 0

    files = frontmatter_files()
    print(f"parsing frontmatter in {len(files)} file(s)")
    check("found the command and agent files", len(files) >= 9, str(len(files)))

    for path in files:
        rel = path.relative_to(REPO)
        parts = split_frontmatter(path.read_text(encoding="utf-8"))
        if parts is None:
            check(f"{rel} has a closing ---", False)
            continue
        block, _ = parts
        try:
            data = yaml.safe_load(block)
        except Exception as exc:
            check(f"{rel} parses as YAML", False, str(exc).splitlines()[0][:120])
            continue
        check(f"{rel} parses as YAML", True)
        if not isinstance(data, dict):
            check(f"{rel} is a mapping", False, repr(data)[:80])
            continue

        desc = data.get("description")
        if desc is not None:
            check(f"{rel} description is a string", isinstance(desc, str), type(desc).__name__)
            if isinstance(desc, str):
                # A description wrapped in a tuple serialised badly and survived a
                # careless patch: it parses, and it is wrong.
                check(f"{rel} description is clean", not (desc.startswith('"(') or "',)" in desc),
                      desc[:70])
                check(f"{rel} description is a sentence", len(desc) > 40, desc[:60])

        hint = data.get("argument-hint")
        if hint is not None:
            # Unquoted, "[a] [b]" is a flow sequence and fails to parse; if it did
            # parse, the hint must be a string for the runtime to render it.
            check(f"{rel} argument-hint is a string", isinstance(hint, str), type(hint).__name__)

    print("manifest and icon")
    manifest_path = REPO / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    check("plugin.json parses", isinstance(manifest, dict))
    check("name present", bool(manifest.get("name")))
    check("marketplace.json parses",
          isinstance(json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text()), dict))

    icon = manifest.get("icon")
    check("icon is declared", bool(icon), repr(icon))
    if icon:
        # removeprefix, never lstrip: lstrip("./") strips a *character set* and
        # eats the leading dot of ".claude-plugin".
        icon_path = (REPO / icon.removeprefix("./")).resolve()
        check("icon file exists", icon_path.is_file(), str(icon_path))
        if icon_path.is_file():
            raw = icon_path.read_bytes()
            check("icon is a PNG", raw[:8] == b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", raw[16:24])
            check("icon is square", width == height, f"{width}x{height}")
            check("icon is at least 256px", width >= 256, str(width))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
