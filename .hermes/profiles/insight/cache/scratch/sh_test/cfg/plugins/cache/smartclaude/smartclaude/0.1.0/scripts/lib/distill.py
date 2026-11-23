#!/usr/bin/env python3
"""Distillation: detect a substantial stretch of work, queue it, distill it later.

Shape of the loop, and why each part exists:

  Stop hook        -> analyze the transcript; queue a job when the work was big
  detached worker  -> claim one job, run a fenced `claude -p` session, verify
  skill guard      -> snapshot before, validate after, roll back what broke

The threshold is not "a turn happened". A skill library that grows on every turn
stops being findable — the reference implementation hit 385 skills of which only
13 could be listed. So a job is only queued when the segment shows **volume and
artifacts**: enough tool calls *and* enough real file edits, or a long read-only
investigation that produced a conclusion worth keeping.

Nothing here writes to a skill itself. The worker runs an agent; the guard judges
what that agent wrote. Keeping those separate is what makes a rollback possible.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import paths

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}

# Volume thresholds. Deliberately borrowed from a project that shipped this loop
# and tuned it: 40 calls with 3+ edits, or 80 calls when nothing was edited.
MIN_CALLS = int(os.environ.get("SMARTCLAUDE_MIN_CALLS", "40"))
MIN_EDITS = int(os.environ.get("SMARTCLAUDE_MIN_EDITS", "3"))
READONLY_CALLS = int(os.environ.get("SMARTCLAUDE_READONLY_CALLS", "80"))

WORKER_BIN = os.environ.get("SMARTCLAUDE_CLAUDE_BIN", "claude")
JOB_TIMEOUT = int(os.environ.get("SMARTCLAUDE_JOB_TIMEOUT", "900"))


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def db_path() -> Path:
    return paths.state_dir() / "jobs.db"


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS jobs (
               id         INTEGER PRIMARY KEY AUTOINCREMENT,
               session    TEXT NOT NULL,
               transcript TEXT NOT NULL,
               created    REAL NOT NULL,
               state      TEXT NOT NULL DEFAULT 'queued',
               attempts   INTEGER NOT NULL DEFAULT 0,
               note       TEXT
           )"""
    )
    return conn


def enqueue(session: str, transcript: str) -> Optional[int]:
    """Add a job, refusing duplicates for the same transcript.

    A Stop hook can fire more than once for a segment; without the guard the
    queue fills with the same distillation and the model pays for it twice.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM jobs WHERE transcript = ? AND state IN ('queued','running')",
            (transcript,),
        ).fetchone()
        if row:
            return None
        cur = conn.execute(
            "INSERT INTO jobs (session, transcript, created) VALUES (?,?,?)",
            (session, transcript, time.time()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def claim() -> Optional[Dict[str, object]]:
    """Take exactly one queued job, atomically.

    The UPDATE is the claim: two workers racing cannot both win a job whose
    state they changed from 'queued' in the same statement.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, session, transcript, attempts FROM jobs WHERE state='queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        cur = conn.execute(
            "UPDATE jobs SET state='running', attempts=attempts+1 WHERE id=? AND state='queued'",
            (row[0],),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        return {"id": row[0], "session": row[1], "transcript": row[2], "attempts": row[3] + 1}
    finally:
        conn.close()


def finish(job_id: int, state: str, note: str = "") -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE jobs SET state=?, note=? WHERE id=?", (state, note[:2000], job_id))
        conn.commit()
    finally:
        conn.close()


def queue_report() -> Dict[str, object]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM jobs GROUP BY state"
        ).fetchall()
        recent = conn.execute(
            "SELECT id, session, state, note FROM jobs ORDER BY id DESC LIMIT 5"
        ).fetchall()
        return {
            "counts": {r[0]: r[1] for r in rows},
            "recent": [
                {"id": r[0], "session": (r[1] or "")[:8], "state": r[2], "note": (r[3] or "")[:160]}
                for r in recent
            ],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _state_file() -> Path:
    return paths.state_dir() / "distill-state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(str(tmp), str(path))
    except OSError:
        pass


@dataclass
class Segment:
    session: str
    transcript: str
    calls: int
    edits: int
    anchored: bool

    @property
    def should_fire(self) -> bool:
        if self.calls >= MIN_CALLS and self.edits >= MIN_EDITS:
            return True
        return self.edits == 0 and self.calls >= READONLY_CALLS

    @property
    def reason(self) -> str:
        if self.edits == 0:
            return f"{self.calls} calls, read-only investigation"
        return f"{self.calls} calls, {self.edits} file edits"


def analyze(transcript_path: str) -> Optional[Segment]:
    """Count the work since the last distillation for this session.

    The anchor is a line number, not a timestamp: transcripts are append-only, so
    a line offset survives a clock change and cannot re-count old work.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    session = Path(transcript_path).stem
    state = _load_state()
    anchor = int(state.get(session, {}).get("anchor", 0))

    calls = 0
    edits = 0
    line_no = 0
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line_no, line in enumerate(fh, 1):
                if line_no <= anchor:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                content = (record.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        calls += 1
                        if block.get("name") in EDIT_TOOLS:
                            edits += 1
    except OSError:
        return None

    return Segment(session=session, transcript=transcript_path, calls=calls, edits=edits, anchored=anchor > 0)


def mark_distilled(session: str, line_no: int) -> None:
    """Advance the anchor so the next segment starts here."""
    state = _load_state()
    state.setdefault(session, {})["anchor"] = line_no
    state[session]["at"] = int(time.time())
    _save_state(state)


def transcript_lines(path: str) -> int:
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Worker spawn
# ---------------------------------------------------------------------------


def spawn(transcript: str) -> bool:
    """Start a detached worker and return whether it launched.

    Detached on purpose: the Stop hook must return immediately so the operator's
    turn ends normally. A worker that inherits the session's process group would
    be killed with it.
    """
    here = Path(__file__).resolve().parent.parent
    worker = here / "worker.py"
    if not worker.is_file():
        return False
    try:
        subprocess.Popen(
            [sys.executable, str(worker), "--transcript", transcript],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def headless_ready() -> bool:
    """Whether a background `claude -p` can authenticate right now.

    Probed, never assumed: `claude auth status` reports loggedIn while `-p`
    still returns 401, so the status command is not evidence. Cheap probe, short
    timeout, and a failure means "fall back", not "retry forever".
    """
    try:
        proc = subprocess.run(
            [WORKER_BIN, "-p", "ok", "--allowedTools", ""],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    blob = (proc.stdout + proc.stderr).lower()
    if "401" in blob or "authenticate" in blob or "expired" in blob:
        return False
    return proc.returncode == 0
