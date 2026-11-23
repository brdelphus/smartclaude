#!/usr/bin/env python3
"""Import skills from another agent's tree into this one.

Nothing here runs by default. There is no autodetection that silently reads a
foreign directory: you name the source with `--from`, and you can look before you
leap with `--list`. This plugin installs clean and stays clean.

Two kinds of source, and they are not the same job:

  native   the source already speaks Agent Skills (`SKILL.md` with `name` and
           `description`). Claude Code, Cursor skills, Copilot skills, the
           `.agents/skills` convention and Hermes all use it. The folder is
           copied and its frontmatter is normalised.

  legacy   the source uses an older, agent-specific format — Cursor `.mdc` rules,
           Copilot `copilot-instructions.md` and `*.instructions.md`. These are
           *converted*, and the conversion is lossy by nature, so every one of
           them is reported rather than silently normalised.

What conversion cannot preserve, it says out loud. A rule with `alwaysApply: true`
is an always-on instruction, not a skill that fires on context; turning it into a
skill changes when it runs. That is a decision for the operator, so it is flagged,
never guessed.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import paths, provenance  # noqa: E402

# ---------------------------------------------------------------------------
# Where each agent keeps things. Paths are relative to a home dir or to the
# current project, and are only probed when that agent is named.
# ---------------------------------------------------------------------------

SKILL_TREE = "skill"  # already Agent Skills
MDC_TREE = "mdc"  # Cursor rules
INSTR_TREE = "instructions"  # Copilot per-path instructions
COPILOT_FILE = "copilot_md"  # Copilot repo-wide single file

SOURCES: Dict[str, List[Tuple[str, str]]] = {
    "claude": [
        ("~/.claude/skills", SKILL_TREE),
        (".claude/skills", SKILL_TREE),
    ],
    "cursor": [
        ("~/.cursor/skills", SKILL_TREE),
        (".cursor/skills", SKILL_TREE),
        ("~/.cursor/rules", MDC_TREE),
        (".cursor/rules", MDC_TREE),
    ],
    "copilot": [
        ("~/.copilot/skills", SKILL_TREE),
        ("~/.config/github-copilot/skills", SKILL_TREE),
        (".github/skills", SKILL_TREE),
        (".github/instructions", INSTR_TREE),
        (".github/copilot-instructions.md", COPILOT_FILE),
    ],
    "hermes": [
        ("~/.hermes/skills", SKILL_TREE),
        ("~/.hermes/profiles/*/skills", SKILL_TREE),
    ],
    "agents": [
        ("~/.agents/skills", SKILL_TREE),
        (".agents/skills", SKILL_TREE),
    ],
}

SKIP_DIRS = {".archive", ".trash", ".git", "node_modules", "__pycache__", ".venv"}


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> Tuple[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def field(front: str, key: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(key)}:\s*(.+(?:\n[ \t]+.+)*)$", front, re.M)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip().strip("\"'")


def list_field(front: str, key: str) -> List[str]:
    """Read `key: a` , `key: [a, b]` or `key:` followed by `- a` lines."""
    inline = re.search(rf"^{re.escape(key)}:\s*\[(.*?)\]", front, re.M)
    if inline:
        return [v.strip().strip("\"'") for v in inline.group(1).split(",") if v.strip()]
    single = field(front, key)
    if single:
        return [v.strip() for v in single.split(",") if v.strip()]
    block = re.search(rf"^{re.escape(key)}:\s*\n((?:[ \t]*-[ \t]*.+\n?)+)", front, re.M)
    if block:
        return [
            line.split("-", 1)[1].strip().strip("\"'")
            for line in block.group(1).splitlines()
            if "-" in line
        ]
    return []


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:64] or "skill"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def expand(pattern: str) -> List[Path]:
    if pattern.startswith("~"):
        pattern = str(Path(os.path.expanduser(pattern)))
    return [Path(p) for p in glob.glob(pattern)]


def discover(source: str) -> List[Dict[str, object]]:
    """Everything importable from one named agent, without writing anything."""
    found: List[Dict[str, object]] = []
    for pattern, kind in SOURCES.get(source, []):
        for base in expand(pattern):
            if kind == SKILL_TREE:
                if not base.is_dir():
                    continue
                for skill_md in sorted(base.rglob("SKILL.md")):
                    if any(part in SKIP_DIRS for part in skill_md.parts):
                        continue
                    found.append({"kind": kind, "path": skill_md.parent, "md": skill_md})
            elif kind == MDC_TREE:
                if not base.is_dir():
                    continue
                for mdc in sorted(base.rglob("*.mdc")):
                    found.append({"kind": kind, "path": mdc.parent, "md": mdc})
            elif kind == INSTR_TREE:
                if not base.is_dir():
                    continue
                for inst in sorted(base.rglob("*.instructions.md")):
                    found.append({"kind": kind, "path": inst.parent, "md": inst})
            elif kind == COPILOT_FILE:
                if base.is_file():
                    found.append({"kind": kind, "path": base.parent, "md": base})
    return found


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def build_skill(item: Dict[str, object]) -> Tuple[str, str, List[str]]:
    """Return (name, SKILL.md text, warnings) for one discovered item."""
    path: Path = item["path"]  # type: ignore[assignment]
    md: Path = item["md"]  # type: ignore[assignment]
    kind = item["kind"]
    warnings: List[str] = []

    if kind == SKILL_TREE:
        text = md.read_text(encoding="utf-8", errors="replace")
        front, body = split_frontmatter(text)
        name = field(front, "name") or path.name
        desc = field(front, "description")
        if not desc:
            warnings.append("had no description; wrote a placeholder — fix it or it never fires")
            desc = f"Use when working on {name.replace('-', ' ')}."
        return slugify(name), _render(name, desc, body, list_field(front, "paths")), warnings

    if kind == MDC_TREE:
        text = md.read_text(encoding="utf-8", errors="replace")
        front, body = split_frontmatter(text)
        name = slugify(md.stem)
        desc = field(front, "description")
        globs = list_field(front, "globs") or list_field(front, "globsList")
        always = (field(front, "alwaysApply") or "").lower() == "true"
        if not desc:
            first = next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
            desc = f"Use when {first}." if first else f"Use when working on {name.replace('-', ' ')}."
            warnings.append("rule had no description; derived one from its first line")
        if always:
            warnings.append(
                "was an always-applied rule (alwaysApply: true). As a skill it will only "
                "load when its description matches — if it must always apply, keep it as a rule"
            )
        if globs:
            warnings.append(f"had file globs {globs}; preserved as `paths`")
        body = f"{body}\n\n<!-- imported from a Cursor rule: {md.name} -->\n"
        return name, _render(name, desc, body, globs or None), warnings

    if kind == INSTR_TREE:
        text = md.read_text(encoding="utf-8", errors="replace")
        front, body = split_frontmatter(text)
        name = slugify(md.name.replace(".instructions.md", ""))
        desc = field(front, "description")
        apply_to = field(front, "applyTo")
        if not desc:
            first = next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
            desc = f"Use when {first}." if first else f"Use when working on {name.replace('-', ' ')}."
            warnings.append("instructions had no description; derived one from the first line")
        if apply_to:
            warnings.append(f"scoped with applyTo={apply_to}; preserved as `paths`")
        body = f"{body}\n\n<!-- imported from a Copilot instruction file: {md.name} -->\n"
        paths_field = [apply_to] if apply_to else None
        return name, _render(name, desc, body, paths_field), warnings

    # Copilot repo-wide file: one long document, no name, no trigger.
    text = md.read_text(encoding="utf-8", errors="replace")
    _, body = split_frontmatter(text)
    name = "copilot-instructions"
    warnings.append(
        "is Copilot's repo-wide instruction file, not a skill: it has no trigger and would "
        "apply to everything. Imported as reference text — split out real skills by hand"
    )
    desc = "Use when reviewing what the previous Copilot setup instructed, before splitting it into skills."
    return name, _render(name, desc, body, None), warnings


def _render(name: str, description: str, body: str, path_globs: Optional[List[str]]) -> str:
    front = ["---", f"name: {name}", f'description: "{description}"']
    if path_globs:
        front.append("paths:")
        front.extend(f'  - "{g}"' for g in path_globs)
    front.append("---")
    return "\n".join(front) + "\n\n" + body.lstrip("\n")


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def install(item: Dict[str, object], dst_root: Path, force: bool) -> Dict[str, object]:
    name, text, warnings = build_skill(item)
    target = dst_root / name
    source_dir: Path = item["path"]  # type: ignore[assignment]
    md: Path = item["md"]  # type: ignore[assignment]

    if target.exists() and not force:
        return {"name": name, "state": "skipped", "warnings": warnings + ["already exists (use --force)"]}

    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(text, encoding="utf-8")

    # Bundled assets travel with a native skill. A converted rule is a single
    # file, so there is nothing else to carry.
    if item["kind"] == SKILL_TREE:
        for sub in ("scripts", "references", "assets", "templates"):
            origin = source_dir / sub
            if origin.is_dir():
                dest = target / sub
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(origin, dest, symlinks=False)
                warnings.append(f"carried {sub}/")

    return {"name": name, "state": "installed" if not target.exists() else "overwritten",
            "from": str(md), "source": item.get("source", "unknown"),
            "kind": item.get("kind", "unknown"), "warnings": warnings}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", choices=sorted(SOURCES) + ["all"],
                    help="which agent to import from; omitted means list only")
    ap.add_argument("--dst", default=None, help="skills root (default: the Claude Code one)")
    ap.add_argument("--list", action="store_true", help="show what is importable, write nothing")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite skills that already exist")
    ap.add_argument("--only", default=None, help="import just this skill name")
    args = ap.parse_args()

    dst_root = Path(args.dst).expanduser().absolute() if args.dst else paths.skills_root()

    if not args.source:
        print("Nothing is read unless you name a source. What is present on this machine:\n")
        any_found = False
        for name in sorted(SOURCES):
            items = discover(name)
            if items:
                any_found = True
                kinds: Dict[str, int] = {}
                for item in items:
                    kinds[str(item["kind"])] = kinds.get(str(item["kind"]), 0) + 1
                detail = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
                print(f"  {name:<10} {len(items):>4} importable   ({detail})")
        if not any_found:
            print("  nothing found")
        print(f"\nImport with:  import_skills.py --from <agent> [--list] [--dry-run]")
        print(f"Destination:  {dst_root}")
        return 0

    chosen = sorted(SOURCES) if args.source == "all" else [args.source]
    items: List[Dict[str, object]] = []
    for name in chosen:
        for found in discover(name):
            found["source"] = name
            items.append(found)

    if args.only:
        items = [i for i in items if slugify(Path(str(i["md"])).stem) == slugify(args.only)
                 or slugify(Path(str(i["path"])).name) == slugify(args.only)]

    if not items:
        print(f"Nothing importable from {args.source}.", file=sys.stderr)
        return 1

    if args.list:
        print(f"{len(items)} importable from {args.source} -> {dst_root}\n")
        for item in items:
            name, _, warnings = build_skill(item)
            flag = f"  [{len(warnings)} warning(s)]" if warnings else ""
            print(f"  {name:<34} {item['kind']:<12} {item['md']}{flag}")
        return 0

    results = []
    for item in items:
        if args.dry_run:
            name, _, warnings = build_skill(item)
            results.append({"name": name, "state": "would install", "warnings": warnings})
        else:
            results.append(install(item, dst_root, args.force))

    installed = [r for r in results if r["state"] in ("installed", "overwritten", "would install")]

    # Write down where each one came from: an imported skill is a local copy and
    # nothing else in the tree distinguishes it from a hand-written one.
    if not args.dry_run:
        recorded = provenance.record(
            {"name": r["name"], "source": r.get("source"), "kind": r.get("kind"), "from": r.get("from")}
            for r in installed
        )
        if recorded:
            print(f"recorded provenance for {recorded} skill(s)")
    skipped = [r for r in results if r["state"] == "skipped"]
    warned = [r for r in results if r["warnings"]]

    print(f"\n{len(installed)} {'would be ' if args.dry_run else ''}imported, "
          f"{len(skipped)} skipped, {len(warned)} with warnings -> {dst_root}")
    for r in installed:
        print(f"  + {r['name']}")
    for r in skipped:
        print(f"  = {r['name']}  {r['warnings'][-1]}")
    if warned:
        print("\nWarnings — read these, the conversion is lossy:")
        for r in warned:
            print(f"  {r['name']}:")
            for w in r["warnings"]:
                print(f"    - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
