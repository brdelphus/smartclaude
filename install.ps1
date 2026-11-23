<#
.SYNOPSIS
    smartclaude installer for Windows.

.DESCRIPTION
    Linux and macOS use install.sh; this script refuses to pretend otherwise.

    STATUS: NOT YET RUN ON WINDOWS.
    Syntax is validated by the real PowerShell parser and the full flow has been
    executed on Linux with the platform guard neutralised, but no Windows machine
    has run this end to end. PowerShell 5.1 is accepted but only 7.7 Core was
    exercised. Treat it as untested until you have run it, and report what breaks.

    Design rules, same as the POSIX installer:
      - check before act: a missing prerequisite stops the install instead of
        producing a half-working plugin that fails silently later
      - never elevate: everything lands under the user's own config directory
      - idempotent: running it twice is the same as running it once
      - say what happened, or say why it did not

.PARAMETER SkipTests
    Install without running the test suite.

.PARAMETER Uninstall
    Remove the plugin registration. State is kept.

.EXAMPLE
    .\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot   = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginName = 'smartclaude'
$MarketName = 'smartclaude'
$MinPyMinor = 9

function Write-Say  { param([string]$Text) Write-Host $Text }
function Write-Ok   { param([string]$Text) Write-Host '  ok ' -ForegroundColor Green -NoNewline; Write-Host $Text }
function Write-Warn { param([string]$Text) Write-Host '  !! ' -ForegroundColor Yellow -NoNewline; Write-Host $Text }
function Write-Die  { param([string]$Text) Write-Host "  xx $Text" -ForegroundColor Red; exit 1 }
function Write-Step { param([string]$Text) Write-Host ''; Write-Host $Text -ForegroundColor Cyan }

# ---------------------------------------------------------------------------
# 1. Platform
# ---------------------------------------------------------------------------

Write-Step 'Platform'

if (-not ($IsWindows -or $PSVersionTable.PSEdition -eq 'Desktop')) {
    Write-Die 'this is not Windows. Use ./install.sh instead.'
}

$psVersion = $PSVersionTable.PSVersion
if ($psVersion.Major -lt 5) {
    Write-Die "PowerShell 5.1 or newer is required (found $psVersion)."
}
$arch = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } elseif ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { 'unknown' }
Write-Ok "Windows, PowerShell $psVersion ($arch)"

# ---------------------------------------------------------------------------
# 2. Python
# ---------------------------------------------------------------------------

Write-Step "Python 3.$MinPyMinor+"

function Find-Python {
    $candidates = @('python3', 'python', 'py')
    foreach ($name in $candidates) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }

        $exe = $cmd.Source
        $args = @()
        if ($name -eq 'py') { $args = @('-3') }

        try {
            $probe = & $exe @args -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $exe; Args = $args }
            }
        } catch {
            continue
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Die @'
No Python 3.9+ found.

Install it with one of:
  winget install --id Python.Python.3.12 -e
  or download from https://www.python.org/downloads/windows/

Tick "Add python.exe to PATH" in the installer, then open a NEW terminal and re-run.
'@
}

$pyExe  = $python.Exe
$pyArgs = $python.Args
$pyVersion = (& $pyExe @pyArgs --version 2>&1) -join ''
Write-Ok "$pyVersion at $pyExe"

# ---------------------------------------------------------------------------
# 3. Claude Code
# ---------------------------------------------------------------------------

Write-Step 'Claude Code'

$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Write-Die @'
The 'claude' CLI is not on PATH.

Install Claude Code first, then open a NEW terminal so PATH refreshes, and re-run.
'@
}
$claudeExe = $claudeCmd.Source
$claudeVersion = (& $claudeExe --version 2>&1 | Select-Object -First 1)
Write-Ok "$claudeVersion at $claudeExe"

# ---------------------------------------------------------------------------
# 4. Uninstall path
# ---------------------------------------------------------------------------

if ($Uninstall) {
    Write-Step 'Uninstall'

    & $claudeExe plugin uninstall "$PluginName@$MarketName" 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Ok 'plugin uninstalled' } else { Write-Warn 'plugin was not installed' }

    & $claudeExe plugin marketplace remove $MarketName 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Ok 'marketplace removed' } else { Write-Warn 'marketplace was not registered' }

    $instrOut = & $pyExe @pyArgs (Join-Path $RepoRoot 'scripts/instructions.py') remove 2>&1
    if ($instrOut) { Write-Ok ($instrOut -join ' ') }
    $guideOut = & $pyExe @pyArgs (Join-Path $RepoRoot 'scripts/guide.py') remove 2>&1
    if ($guideOut) { Write-Ok ($guideOut -join ' ') }

    Write-Warn 'state (queue, snapshots) kept under your config dir — delete it by hand to remove'
    Write-Say ''
    Write-Say 'Done.'
    exit 0
}

# ---------------------------------------------------------------------------
# 5. Validate the plugin before touching anything
# ---------------------------------------------------------------------------

Write-Step 'Validate plugin'

& $claudeExe plugin validate $RepoRoot *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Ok 'manifest is valid'
} else {
    Write-Die "plugin manifest failed validation. Run: claude plugin validate $RepoRoot"
}

# ---------------------------------------------------------------------------
# 6. Tests
# ---------------------------------------------------------------------------

if (-not $SkipTests) {
    Write-Step 'Tests'
    $tests = Get-ChildItem -Path (Join-Path $RepoRoot 'tests') -Filter 'test_*.py' -ErrorAction SilentlyContinue
    foreach ($test in $tests) {
        & $pyExe @pyArgs $test.FullName *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok $test.Name
        } else {
            Write-Die "$($test.Name) failed. Run it to see why: $pyExe $($test.FullName)"
        }
    }
} else {
    Write-Step 'Tests'
    Write-Warn 'skipped (-SkipTests)'
}

# ---------------------------------------------------------------------------
# 7. Register
# ---------------------------------------------------------------------------

Write-Step 'Register with Claude Code'

$configDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
New-Item -ItemType Directory -Force -Path (Join-Path $configDir 'smartclaude') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $configDir 'skills')     | Out-Null
Write-Ok "config at $configDir"

$marketplaces = (& $claudeExe plugin marketplace list 2>&1) -join "`n"
if ($marketplaces -match [regex]::Escape($MarketName)) {
    & $claudeExe plugin marketplace update $MarketName *> $null
    if ($LASTEXITCODE -eq 0) { Write-Ok "marketplace '$MarketName' refreshed" }
    else { Write-Warn "marketplace '$MarketName' already registered (refresh skipped)" }
} else {
    & $claudeExe plugin marketplace add $RepoRoot *> $null
    if ($LASTEXITCODE -eq 0) { Write-Ok "marketplace '$MarketName' added from $RepoRoot" }
    else { Write-Die "could not add the marketplace. Run it by hand: claude plugin marketplace add $RepoRoot" }
}

# An installed plugin is the common case on a machine that has run this before, and
# reporting "already installed" left the cached copy frozen at whatever was there the
# first time: new commands and fixes never reached the user. Re-install it from the
# marketplace refreshed above.
$installed = (& $claudeExe plugin list 2>&1) -join "`n"
if ($installed -match [regex]::Escape($PluginName)) {
    & $claudeExe plugin uninstall "$PluginName@$MarketName" *> $null
    & $claudeExe plugin install "$PluginName@$MarketName" *> $null
    if ($LASTEXITCODE -eq 0) { Write-Ok "plugin '$PluginName' reinstalled from the current tree" }
    else { Write-Die "could not reinstall the plugin. Run it by hand: claude plugin install $PluginName@$MarketName" }
} else {
    & $claudeExe plugin install "$PluginName@$MarketName" *> $null
    if ($LASTEXITCODE -eq 0) { Write-Ok "plugin '$PluginName' installed" }
    else { Write-Die "could not install the plugin. Run it by hand: claude plugin install $PluginName@$MarketName" }
}

# ---------------------------------------------------------------------------
# 8. Next steps
# ---------------------------------------------------------------------------

Write-Step 'CLAUDE.md'
# Append our block to the operator's CLAUDE.md, or create it when there is none.
# Content outside our markers is never touched (see scripts/instructions.py).
$instrOut = & $pyExe @pyArgs (Join-Path $RepoRoot 'scripts/instructions.py') install 2>&1
if ($LASTEXITCODE -ne 0) { Write-Die "could not update CLAUDE.md: $($instrOut -join ' ')" }
Write-Ok ($instrOut -join ' ')

Write-Step 'Guidance skill'
$guideOut = & $pyExe @pyArgs (Join-Path $RepoRoot 'scripts/guide.py') install 2>&1
if ($LASTEXITCODE -ne 0) { Write-Warn ($guideOut -join ' ') } else { Write-Ok ($guideOut -join ' ') }

Write-Step 'Knowledge base'
# Local, unversioned: markdown notes plus a Chroma index. Never fatal.
#
# Uncapped on purpose: this installs chromadb (onnxruntime, numpy, tokenizers - a few
# hundred megabytes). Captured, it looked like a hang for minutes on a working link.
& $pyExe @pyArgs (Join-Path $RepoRoot 'scripts/kb_init.py') install
$kbRc = $LASTEXITCODE
switch ($kbRc) {
    0 { Write-Ok 'knowledge base ready' }
    2 { Write-Warn 'knowledge base created, index missing - the message above says how to finish by hand' }
    default { Write-Warn 'knowledge base could not be created - see the message above' }
}

Write-Step 'Installed' 

$py = "$pyExe $($pyArgs -join ' ')".Trim()

Write-Say @"

The plugin ships with no skills - that is deliberate. Bring yours in:

  # see what exists on this machine, writes nothing
  $py "$RepoRoot\scripts\import_skills.py"

  # import from your previous tools
  $py "$RepoRoot\scripts\import_skills.py" --from cursor
  $py "$RepoRoot\scripts\import_skills.py" --from copilot

  # or link a tree you already maintain
  $py "$RepoRoot\scripts\sync_skills.py" --src C:\path\to\skills

  # extended memory (optional)
  `$env:SMARTCLAUDE_KB_REPO = 'C:\path\to\your\markdown-notes'
  [Environment]::SetEnvironmentVariable('SMARTCLAUDE_KB_REPO', 'C:\path\to\your\markdown-notes', 'User')

Then, in a new Claude Code session:

  /audit-skills     what is broken, what never fires, what it costs
  /import-skills    bring skills from another agent
  /status           skill count and whether the base is reachable

Uninstall with: $RepoRoot\install.ps1 -Uninstall
"@
