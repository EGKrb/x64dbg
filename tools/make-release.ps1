<#
.SYNOPSIS
Builds the release archives of this fork from an existing build.

.DESCRIPTION
Prerequisites (see README.md, "Compiler"):
  - bin\x64 and bin\x32 built (cmake --build build64 / build32)
  - pybridge\build-x64\pybridge.dp64 and pybridge\build-x32\pybridge.dp32 built

Steps:
  1. downloads the x64dbg translations (like the official CI)
  2. runs cmake\release.cmake (official layout: release\, pluginsdk\, pdb\)
  3. adds ScyllaHide and xAnalyzer (official downloads, SHA-256 checked) and pybridge
  4. adds the Python client, examples, headless templates, licenses and LISEZMOI.md
  5. writes dist\x64dbg-egkrb_<Version>.zip and dist\x64dbg-egkrb_<Version>_symbols.zip

OllyDumpEx is not redistributable: the archive contains install-plugins.ps1 to download it.

.EXAMPLE
.\tools\make-release.ps1 -Version 2026.10.03
#>
param(
    [string] $Version = (Get-Date -Format 'yyyy.MM.dd'),
    [string] $OutDir
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }

function Invoke-Download([string] $Url, [string] $File) {
    & curl.exe -4 -fsSL --retry 3 -o $File $Url
    if ($LASTEXITCODE -ne 0) { throw "download failed: $Url" }
}

# 0. Checks
$required = @(
    'bin\x64\x64dbg.exe', 'bin\x64\headless.exe', 'bin\x32\x32dbg.exe', 'bin\x32\headless.exe', 'bin\x96dbg.exe',
    'pybridge\build-x64\pybridge.dp64', 'pybridge\build-x32\pybridge.dp32'
)
foreach ($file in $required) {
    if (-not (Test-Path (Join-Path $root $file))) { throw "missing $file, build it first" }
}
$commit = (git -C $root rev-parse HEAD).Trim()
if (git -C $root status --porcelain --untracked-files=no -- src pybridge/src) {
    Write-Warning "uncommitted changes in src or pybridge\src: the binaries may not match commit $commit"
}

# 1. Translations (same source as the official CI)
$qm = Join-Path $root 'bin\qm.zip'
Invoke-Download 'https://github.com/x64dbg/translations/releases/download/translations/qm.zip' $qm
Expand-Archive -Force $qm (Join-Path $root 'bin')
Remove-Item $qm

# 2. Official release layout
cmake -P (Join-Path $root 'cmake\release.cmake')
if ($LASTEXITCODE -ne 0) { throw 'cmake\release.cmake failed' }
$package = Join-Path $root 'release'
$main = Join-Path $package 'release'

# 3. Plugins
& (Join-Path $root 'plugins\install-plugins.ps1') -X64dbgDir $main -Plugins ScyllaHide, xAnalyzer -Force
Copy-Item (Join-Path $root 'pybridge\build-x64\pybridge.dp64') (Join-Path $main 'x64\plugins')
Copy-Item (Join-Path $root 'pybridge\build-x32\pybridge.dp32') (Join-Path $main 'x32\plugins')
Copy-Item (Join-Path $root 'plugins\install-plugins.ps1') $main

# 4. pybridge client, examples, templates
$pybridge = Join-Path $main 'pybridge'
New-Item -ItemType Directory -Force $pybridge | Out-Null
foreach ($item in 'python', 'examples', 'headless', 'README.md') {
    Copy-Item -Recurse (Join-Path $root "pybridge\$item") $pybridge
}
Get-ChildItem -Recurse -Directory $pybridge -Filter '__pycache__' | Remove-Item -Recurse -Force

# Licenses
$licenses = Join-Path $main 'licenses'
New-Item -ItemType Directory -Force $licenses | Out-Null
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $licenses 'x64dbg-LICENSE.txt')
Invoke-Download 'https://raw.githubusercontent.com/x64dbg/ScyllaHide/master/LICENSE' (Join-Path $licenses 'ScyllaHide-LICENSE.txt')
Invoke-Download 'https://raw.githubusercontent.com/ThunderCls/xAnalyzer/master/LICENSE' (Join-Path $licenses 'xAnalyzer-LICENSE.txt')
Copy-Item (Join-Path $root 'plugins\THIRD-PARTY.md') $licenses

# Quick start inside the archive
$readme = Get-Content -Raw (Join-Path $root 'tools\LISEZMOI.md')
$readme = $readme.Replace('%VERSION%', $Version).Replace('%COMMIT%', $commit)
[IO.File]::WriteAllText((Join-Path $main 'LISEZMOI.md'), $readme, (New-Object Text.UTF8Encoding $false))

# 5. Archives
New-Item -ItemType Directory -Force $OutDir | Out-Null
$zip = Join-Path $OutDir "x64dbg-egkrb_$Version.zip"
$symbols = Join-Path $OutDir "x64dbg-egkrb_${Version}_symbols.zip"
Remove-Item -Force $zip, $symbols, (Join-Path $OutDir 'SHA256SUMS.txt') -ErrorAction SilentlyContinue
Compress-Archive -CompressionLevel Optimal -Path (Join-Path $package 'release'), (Join-Path $package 'pluginsdk'), (Join-Path $package 'commithash.txt') -DestinationPath $zip
Compress-Archive -CompressionLevel Optimal -Path (Join-Path $package 'pdb'), (Join-Path $package 'commithash.txt') -DestinationPath $symbols

foreach ($file in $zip, $symbols) {
    $hash = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant()
    "{0}  {1}" -f $hash, (Split-Path -Leaf $file) | Add-Content -Encoding ascii (Join-Path $OutDir 'SHA256SUMS.txt')
    "{0,-45} {1,8:N1} MB  sha256 {2}" -f (Split-Path -Leaf $file), ((Get-Item $file).Length / 1MB), $hash
}
