#!/usr/bin/env python3
"""The claim smartclaude makes over its upstream: a write through a symlink is
detected, validated and reversible. This test proves it on a real tree."""
import os, sys, tempfile, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lib import paths, guard

def build(root: Path):
    origin = root / "origin" / "mailu-ops"
    origin.mkdir(parents=True)
    (origin / "SKILL.md").write_text("---\nname: mailu-ops\ndescription: \"Use when touching Mailu.\"\n---\n\n# body\n", encoding="utf-8")
    skills = root / ".claude" / "skills"
    skills.mkdir(parents=True)
    (skills / "mailu-ops").symlink_to(origin)
    # one real skill alongside, to prove both kinds are seen
    real = skills / "local-skill"
    real.mkdir()
    (real / "SKILL.md").write_text("---\nname: local-skill\ndescription: \"Local.\"\n---\n\nbody\n", encoding="utf-8")
    return skills, origin

def main():
    root = Path(tempfile.mkdtemp())
    try:
        skills, origin = build(root)
        before = guard.Snapshot(skills).capture()
        print(f"snapshot entries: {len(before.entries)}")
        assert len(before.entries) == 2, "symlinked skill must be IN the snapshot"

        escaped = before.escaped_from()
        print(f"escaping (outside tree): {[e['skill'] for e in escaped]}")
        assert [e["skill"] for e in escaped] == ["mailu-ops"], "must report the mirrored one"

        # the write the upstream cannot see: through the link
        linked = skills / "mailu-ops" / "SKILL.md"
        linked.write_text("---\nname: mailu-ops\ndescription: \"CURSED\"\n---\n\nbad\n", encoding="utf-8")
        after = guard.Snapshot(skills).capture()
        changed = before.changed(after)
        print(f"changed (resolved): {[paths.skill_name(c) for c in changed]}")
        assert len(changed) == 1, f"write through link NOT detected: {changed}"
        origin_real = str(paths.resolve(linked))
        assert changed[0] == origin_real, "change must be reported against the real file"

        # validation must read the real bytes and reject the cursed edit
        text = Path(origin_real).read_text(encoding="utf-8")
        probs = guard.problems_in(text, is_new=False)
        print(f"problems: {probs}")
        assert probs == [], "this edit is structurally fine, so it is accepted"

        # a structurally broken edit must be rejected
        linked.write_text("---\nname: mailu-ops\n---\n\n", encoding="utf-8")
        broken = Path(origin_real).read_text(encoding="utf-8")
        probs2 = guard.problems_in(broken, is_new=False)
        print(f"problems on broken: {probs2}")
        assert probs2, "missing description must be a blocking problem"

        # rollback writes to the ORIGIN, keeps the link
        ok = guard.restore(Path(origin_real), before.contents[origin_real])
        assert ok
        restored = (origin / "SKILL.md").read_text(encoding="utf-8")
        assert "Use when touching Mailu." in restored, "origin not restored"
        assert (skills / "mailu-ops").is_symlink(), "link must survive a rollback"
        print("restore: origin bytes back, link intact")
        print("\nALL ASSERTIONS PASSED")
    finally:
        shutil.rmtree(root)

if __name__ == "__main__":
    main()
