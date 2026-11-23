#!/usr/bin/env bash
#
# smartclaude installer — Linux and macOS.
#
# Windows uses install.ps1; this script refuses to run there rather than pretending.
#
# COVERAGE: both paths are tested end to end — Linux on Void x86_64 (fresh install,
# idempotent second run, --uninstall) and macOS on a real Mac (install completed).
# Untested on macOS: whether the plugin then loads and its hooks fire. The Windows
# path lives in install.ps1 and has not been run on Windows.
#
# Design rules:
#   - check before act: a missing prerequisite stops the install instead of
#     producing a half-working plugin that fails silently later
#   - never sudo: everything lands under the user's own config directory
#   - idempotent: running it twice is the same as running it once
#   - say what happened, or say why it did not
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="smartclaude"
MARKET_NAME="smartclaude"
MIN_PY_MINOR=9
PY_BIN=""
SKIP_TESTS=0

if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"; DIM="$(printf '\033[2m')"
  RED="$(printf '\033[31m')"; GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"; RESET="$(printf '\033[0m')"
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s  ok %s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s  !!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%s  xx%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
step() { printf '\n%s%s%s\n' "$BOLD" "$*" "$RESET"; }

usage() {
  cat <<EOF
smartclaude installer

  ./install.sh                 install for the current user
  ./install.sh --skip-tests    install without running the test suite
  ./install.sh --uninstall     remove the plugin registration
  ./install.sh --help          this text

Windows: use install.ps1 instead.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --skip-tests) SKIP_TESTS=1 ;;
    --uninstall)  UNINSTALL=1 ;;
    -h|--help)    usage; exit 0 ;;
    *)            die "unknown option: $arg (try --help)" ;;
  esac
done

# ---------------------------------------------------------------------------
# 1. Platform
# ---------------------------------------------------------------------------

step "Platform"

case "$(uname -s)" in
  Linux*)  PLATFORM="linux" ;;
  Darwin*) PLATFORM="macos" ;;
  MINGW*|MSYS*|CYGWIN*)
    die "this is Windows. Use install.ps1 in PowerShell instead." ;;
  *)
    die "unsupported platform: $(uname -s). Linux and macOS are supported; Windows uses install.ps1." ;;
esac
ok "$PLATFORM ($(uname -m))"

if [ "$PLATFORM" = "macos" ] && ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew not found. That is fine — it is only used to fetch python3 if missing."
fi

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------

step "Python 3.${MIN_PY_MINOR}+"

find_python() {
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, ${MIN_PY_MINOR}) else 1)" 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if PY_BIN="$(find_python)"; then
  ok "$("$PY_BIN" --version 2>&1) at $PY_BIN"
else
  if [ "$PLATFORM" = "macos" ] && command -v brew >/dev/null 2>&1; then
    warn "no Python 3.${MIN_PY_MINOR}+ found; Homebrew is available."
    printf 'Install it with Homebrew now? [y/N] '
    read -r answer </dev/tty || answer="n"
    case "$answer" in
      [yY]*)
        brew install python@3.12
        PY_BIN="$(find_python)" || die "Homebrew finished but python3 is still not usable on PATH"
        ok "$("$PY_BIN" --version 2>&1) at $PY_BIN"
        ;;
      *)
        die "install python3 yourself (brew install python@3.12) and re-run." ;;
    esac
  elif [ "$PLATFORM" = "linux" ]; then
    die "install python3 >= 3.${MIN_PY_MINOR} with your package manager (e.g. xbps-install -S python3, apt install python3) and re-run."
  else
    die "install python3 >= 3.${MIN_PY_MINOR} and re-run."
  fi
fi

# ---------------------------------------------------------------------------
# 3. Claude Code
# ---------------------------------------------------------------------------

step "Claude Code"

CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
if [ -z "$CLAUDE_BIN" ]; then
  die "the 'claude' CLI is not on PATH. Install Claude Code first, then re-run.
     If it is installed but not on PATH, add its bin directory to PATH."
fi
ok "$("$CLAUDE_BIN" --version 2>&1 | head -1) at $CLAUDE_BIN"

# ---------------------------------------------------------------------------
# 4. Uninstall path
# ---------------------------------------------------------------------------

if [ "${UNINSTALL:-0}" = "1" ]; then
  step "Uninstall"
  "$CLAUDE_BIN" plugin uninstall "${PLUGIN_NAME}@${MARKET_NAME}" 2>/dev/null \
    && ok "plugin uninstalled" || warn "plugin was not installed"
  "$CLAUDE_BIN" plugin marketplace remove "$MARKET_NAME" 2>/dev/null \
    && ok "marketplace removed" || warn "marketplace was not registered"
  warn "state (queue, snapshots) kept at \${SMARTCLAUDE_STATE_DIR:-~/.claude/smartclaude} — delete it by hand to remove"
  say ""
  say "Done."
  INSTR_OUT="$("$PY_BIN" "$REPO_ROOT/scripts/instructions.py" remove 2>&1)" || true
  [ -n "$INSTR_OUT" ] && ok "$INSTR_OUT"
  GUIDE_OUT="$("$PY_BIN" "$REPO_ROOT/scripts/guide.py" remove 2>&1)" || true
  [ -n "$GUIDE_OUT" ] && ok "$GUIDE_OUT"
  exit 0
fi

# ---------------------------------------------------------------------------
# 5. Validate the plugin before touching anything
# ---------------------------------------------------------------------------

step "Validate plugin"

"$CLAUDE_BIN" plugin validate "$REPO_ROOT" >/dev/null 2>&1 \
  && ok "manifest is valid" \
  || die "plugin manifest failed validation. Run: claude plugin validate $REPO_ROOT"

# ---------------------------------------------------------------------------
# 6. Tests
# ---------------------------------------------------------------------------

if [ "$SKIP_TESTS" = "0" ]; then
  step "Tests"
  for test_file in "$REPO_ROOT"/tests/test_*.py; do
    [ -f "$test_file" ] || continue
    name="$(basename "$test_file")"
    if "$PY_BIN" "$test_file" >/dev/null 2>&1; then
      ok "$name"
    else
      die "$name failed. Run it directly to see why: $PY_BIN $test_file"
    fi
  done
else
  step "Tests"
  warn "skipped (--skip-tests)"
fi

# ---------------------------------------------------------------------------
# 7. Register
# ---------------------------------------------------------------------------

step "Register with Claude Code"

CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
mkdir -p "$CONFIG_DIR/smartclaude" "$CONFIG_DIR/skills"
ok "config at $CONFIG_DIR"

if "$CLAUDE_BIN" plugin marketplace list 2>/dev/null | grep -q "$MARKET_NAME"; then
  "$CLAUDE_BIN" plugin marketplace update "$MARKET_NAME" >/dev/null 2>&1 \
    && ok "marketplace '$MARKET_NAME' refreshed" \
    || warn "marketplace '$MARKET_NAME' already registered (refresh skipped)"
else
  "$CLAUDE_BIN" plugin marketplace add "$REPO_ROOT" >/dev/null 2>&1 \
    && ok "marketplace '$MARKET_NAME' added from $REPO_ROOT" \
    || die "could not add the marketplace. Run it by hand: claude plugin marketplace add $REPO_ROOT"
fi

if "$CLAUDE_BIN" plugin list 2>/dev/null | grep -q "$PLUGIN_NAME"; then
  ok "plugin '$PLUGIN_NAME' already installed"
else
  "$CLAUDE_BIN" plugin install "${PLUGIN_NAME}@${MARKET_NAME}" >/dev/null 2>&1 \
    && ok "plugin '$PLUGIN_NAME' installed" \
    || die "could not install the plugin. Run it by hand: claude plugin install ${PLUGIN_NAME}@${MARKET_NAME}"
fi

# ---------------------------------------------------------------------------
# 8. Next steps
# ---------------------------------------------------------------------------

step "CLAUDE.md"
# Add our block to the operator's CLAUDE.md, or create the file if there is none.
# Never rewrites what is already there: everything outside our markers is
# preserved byte for byte (see scripts/instructions.py).
INSTR_OUT="$("$PY_BIN" "$REPO_ROOT/scripts/instructions.py" install 2>&1)" \
  || die "could not update CLAUDE.md: $INSTR_OUT"
ok "$INSTR_OUT"

step "Guidance skill"
GUIDE_OUT="$("$PY_BIN" "$REPO_ROOT/scripts/guide.py" install 2>&1)" \
  || warn "guidance skill not installed: $GUIDE_OUT"
ok "$GUIDE_OUT"

step "Knowledge base"
# Local, unversioned: markdown notes plus a Chroma index. Never fatal — if chromadb
# cannot be installed the notes folder still exists and the warning says how to
# finish by hand.
KB_OUT="$("$PY_BIN" "$REPO_ROOT/scripts/kb_init.py" install 2>&1)" || true
if printf '%s' "$KB_OUT" | grep -q 'warning:'; then
  warn "$KB_OUT"
else
  ok "$KB_OUT"
fi

step "Installed"

cat <<EOF
The plugin ships with no skills — that is deliberate. Bring yours in:

  ${DIM}# see what exists on this machine, writes nothing${RESET}
  python3 "$REPO_ROOT/scripts/import_skills.py"

  ${DIM}# import from your previous tools${RESET}
  python3 "$REPO_ROOT/scripts/import_skills.py" --from cursor
  python3 "$REPO_ROOT/scripts/import_skills.py" --from copilot

  ${DIM}# or link a tree you already maintain${RESET}
  python3 "$REPO_ROOT/scripts/sync_skills.py" --src /path/to/skills

  ${DIM}# extended memory (optional)${RESET}
  export SMARTCLAUDE_KB_REPO=/path/to/your/markdown-notes

Then, in a new Claude Code session:

  /audit-skills     what is broken, what never fires, what it costs
  /import-skills    bring skills from another agent
  /status           skill count and whether the base is reachable

Uninstall with: $REPO_ROOT/install.sh --uninstall
EOF
