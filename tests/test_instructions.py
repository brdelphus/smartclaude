#!/usr/bin/env python3
"""The CLAUDE.md block must never cost the operator a byte of their own file.

Every assertion here exists because the naive implementation breaks it: a
`write_text(open(...).read() + block)` passes a happy-path test and destroys the
file on the second run, on a CRLF file, or on a file whose only content is an
import line like `@RTK.md`.

Run: python3 tests/test_instructions.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import instructions as ins  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        failures.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smartclaude-instr-"))

    print("appends instead of overwriting")
    operator = tmp / "user.md"
    operator.write_text("@RTK.md\n\n## House rules\n- never touch this\n", encoding="utf-8")
    original = operator.read_bytes()
    result = ins.install(operator)
    after = operator.read_text(encoding="utf-8")
    check("action is appended", result.action == "appended", result.action)
    check("import line survived", after.startswith("@RTK.md\n"))
    check("house rules survived", "never touch this" in after)
    check("block was added", ins.BEGIN in after and ins.END in after)

    print("is idempotent")
    before = operator.read_bytes()
    second = ins.install(operator)
    check("second run reports unchanged", second.action == "unchanged", second.action)
    check("file not touched", operator.read_bytes() == before)
    check("exactly one block", after.count(ins.BEGIN) == 1 and operator.read_text().count(ins.BEGIN) == 1)

    print("removal restores the original bytes")
    ins.remove(operator)
    check("byte-for-byte identical to what the operator had", operator.read_bytes() == original)

    print("preserves CRLF and non-ASCII")
    crlf = tmp / "crlf.md"
    crlf.write_bytes("Regras: ação\r\nlinha 2\r\n".encode("utf-8"))
    crlf_original = crlf.read_bytes()
    ins.install(crlf)
    raw = crlf.read_bytes()
    check("accent intact", "ação".encode("utf-8") in raw)
    check("no bare LF introduced", b"\n" not in raw.replace(b"\r\n", b""))
    ins.remove(crlf)
    check("round-trip byte-for-byte", crlf.read_bytes() == crlf_original)

    print("creates the file when there is none")
    fresh = tmp / "fresh" / "CLAUDE.md"
    created = ins.install(fresh)
    check("action is created", created.action == "created", created.action)
    check("file exists and has the block", fresh.exists() and ins.BEGIN in fresh.read_text())

    print("refuses a half-written block instead of guessing")
    broken = tmp / "broken.md"
    broken.write_text("operator text\n<!-- smartclaude:begin -->\nhalf written\n", encoding="utf-8")
    broken_bytes = broken.read_bytes()
    refused = ins.install(broken)
    check("action is broken", refused.action == "broken", refused.action)
    check("file untouched", broken.read_bytes() == broken_bytes)

    print("refuses duplicated markers")
    dup = tmp / "dup.md"
    dup.write_text(f"a\n{ins.BEGIN}\nx\n{ins.END}\nb\n{ins.BEGIN}\ny\n{ins.END}\n", encoding="utf-8")
    check("action is broken", ins.install(dup).action == "broken")

    print("removes the file only when it held nothing else")
    only_block = tmp / "only.md"
    ins.install(only_block)
    ins.remove(only_block)
    check("file deleted when our block was all of it", not only_block.exists())

    print("refreshes a stale block without touching the rest")
    stale = tmp / "stale.md"
    stale.write_text("@RTK.md\n", encoding="utf-8")
    ins.install(stale, body=f"{ins.BEGIN}\nOLD BODY\n{ins.END}")
    updated = ins.install(stale, body=f"{ins.BEGIN}\nNEW BODY\n{ins.END}")
    text = stale.read_text()
    check("action is updated", updated.action == "updated", updated.action)
    check("old body gone", "OLD BODY" not in text)
    check("new body present", "NEW BODY" in text)
    check("operator content still first", text.startswith("@RTK.md"))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
