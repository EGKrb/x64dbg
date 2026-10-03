<#
.SYNOPSIS
Pushes fix/pybridge-emu-headless, builds the release archives and publishes the GitHub release 2026.10.03.5.

.DESCRIPTION
End-to-end script for the 2026.10.03.5 release of the EGKrb/x64dbg fork.

Steps (each one is skippable with a -Skip* flag, and -WhatIf prints what would run):

  1. preflight    checks: on branch fix/pybridge-emu-headless, tree clean (except CMakeLists.txt),
                  all build artifacts present, gh authenticated, tag v2026.10.03.5 is free
  2. push branch  git push fork fix/pybridge-emu-headless
  3. merge main   git checkout main; git merge --ff-only fix/pybridge-emu-headless; git push fork main
  4. tag          git tag -a v2026.10.03.5 -m ...; git push fork v2026.10.03.5
  5. make-release tools/make-release.ps1 -Version 2026.10.03.5
  6. gh release   gh release create v2026.10.03.5 ... with the two .zip + SHA256SUMS.txt

The CMakeLists.txt local change (cxx_std_17 build fix) is NOT touched: it stays in the
working tree. Commit it separately if you want it in the release's commit hash.

.PARAMETER DryRun
Print commands without running them.

.PARAMETER NoMerge
Push the feature branch but do not merge into main (useful if you want to open a PR instead).

.PARAMETER NoRelease
Push and tag but do not build the archives nor create the GitHub release.

.EXAMPLE
.\tools\publish-release-2026.10.03.5.ps1 -DryRun

.EXAMPLE
.\tools\publish-release-2026.10.03.5.ps1

.EXAMPLE
.\tools\publish-release-2026.10.03.5.ps1 -NoMerge   # open the PR yourself afterwards
#>
param(
    [switch] $DryRun,
    [switch] $NoMerge,
    [switch] $NoRelease
)

$ErrorActionPreference = 'Stop'
$Version = '2026.10.03.5'
$Tag     = "v$Version"
$Branch  = 'fix/pybridge-emu-headless'
$root    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dist    = Join-Path $root 'dist'

function Say([string] $line, [ConsoleColor] $color = 'Cyan') {
    Write-Host "==> $line" -ForegroundColor $color
}
function Run([scriptblock] $block, [string] $label) {
    Say $label
    if ($DryRun) { Write-Host "    (dry-run) $block" -ForegroundColor DarkGray; return }
    & $block
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
}

# -------------------------------------------------------------------- 1. Preflight

Say '1. Preflight' Yellow

$current = (git -C $root rev-parse --abbrev-ref HEAD).Trim()
if ($current -ne $Branch) { throw "expected branch $Branch, got $current" }

# Tree must be clean EXCEPT for CMakeLists.txt (the local cxx_std_17 fix we preserve)
$dirty = (git -C $root status --porcelain) -split "`n" | Where-Object { $_ -and ($_ -notmatch '^\s*M\s+CMakeLists\.txt$') }
if ($dirty) { throw "working tree has unexpected changes:`n$($dirty -join [Environment]::NewLine)" }

$required = @(
    'bin\x64\x64dbg.exe', 'bin\x64\headless.exe', 'bin\x32\x32dbg.exe', 'bin\x32\headless.exe', 'bin\x96dbg.exe',
    'pybridge\build-x64\pybridge.dp64', 'pybridge\build-x32\pybridge.dp32',
    'extracmds\build-x64\ExtraCmds.dp64', 'extracmds\build-x32\ExtraCmds.dp32',
    'build-cross-x64\minidump.exe'
)
$missing = $required | Where-Object { -not (Test-Path (Join-Path $root $_)) }
if ($missing) { throw "missing build artifacts (rebuild first):`n$($missing -join [Environment]::NewLine)" }

# gh present and authenticated (auto-discover: a fresh `winget install GitHub.cli` lands
# in Program Files but is not on PATH until the shell is restarted; we prepend it here).
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    foreach ($p in @('C:\Program Files\GitHub CLI', 'C:\Program Files (x86)\GitHub CLI')) {
        if (Test-Path (Join-Path $p 'gh.exe')) { $env:PATH = "$p;$env:PATH"; break }
    }
    $gh = Get-Command gh -ErrorAction SilentlyContinue
}
if (-not $gh) { throw 'gh CLI not found (install: winget install GitHub.cli, then restart the shell)' }
$ghStatus = (gh auth status 2>&1) -join [Environment]::NewLine
if ($ghStatus -match 'not logged') { throw "gh not authenticated. Run: gh auth login --hostname github.com --git-protocol https --web" }

# Tag must not already exist on the remote
$remoteTag = git -C $root ls-remote --tags fork refs/tags/$Tag
if ($remoteTag) { throw "tag $Tag already exists on fork remote" }

# Release notes must be ready
$notes = Join-Path $dist "RELEASE_NOTES_$Version.md"
if (-not (Test-Path $notes)) { throw "release notes not found: $notes" }

Say "   branch=$Branch, build artifacts OK, gh OK, tag $Tag free, notes at $notes" Green

# -------------------------------------------------------------------- 2. Push branch

Run { git -C $root push fork $Branch } "2. Push branch $Branch to fork"

if ($NoMerge) {
    Say "   -NoMerge set: stopping here. Open a PR at:" Green
    Say "   https://github.com/EGKrb/x64dbg/compare/main...$Branch?expand=1" Green
    return
}

# -------------------------------------------------------------------- 3. Merge main (fast-forward)

Run { git -C $root checkout main } "3a. git checkout main"
Run { git -C $root merge --ff-only $Branch } "3b. git merge --ff-only $Branch"
Run { git -C $root push fork main } "3c. git push fork main"

# -------------------------------------------------------------------- 4. Tag

$tagMessage = "Release ${Version}: pybridge pybridge.emu fixes for headless.exe"
Run { git -C $root tag -a $Tag -m $tagMessage } "4a. git tag $Tag"
Run { git -C $root push fork $Tag } "4b. git push fork $Tag"

if ($NoRelease) {
    Say "   -NoRelease set: stopping before build and gh release create" Green
    return
}

# -------------------------------------------------------------------- 5. Build release archives

Run { & (Join-Path $root 'tools\make-release.ps1') -Version $Version } "5. make-release.ps1 -Version $Version"

$zip     = Join-Path $dist "x64dbg-egkrb_$Version.zip"
$symbols = Join-Path $dist "x64dbg-egkrb_${Version}_symbols.zip"
$sums    = Join-Path $dist 'SHA256SUMS.txt'
foreach ($file in $zip, $symbols, $sums) {
    if (-not (Test-Path $file)) { throw "missing output: $file" }
}

# -------------------------------------------------------------------- 6. GitHub release

Say "6. Creating GitHub release $Tag" Yellow
if ($DryRun) {
    Write-Host "    (dry-run) gh release create $Tag --repo EGKrb/x64dbg --title ... --notes-file $notes $zip $symbols $sums" -ForegroundColor DarkGray
    return
}
gh release create $Tag `
    --repo EGKrb/x64dbg `
    --title "x64dbg EGKrb $Version" `
    --notes-file $notes `
    $zip $symbols $sums
if ($LASTEXITCODE) { throw 'gh release create failed' }

Say "Done. Release page: https://github.com/EGKrb/x64dbg/releases/tag/$Tag" Green
