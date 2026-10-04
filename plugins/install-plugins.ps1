<#
.SYNOPSIS
Downloads and installs third-party x64dbg plugins and tools from their official sources.

.DESCRIPTION
Installs five extras into <X64dbgDir>:
  - ScyllaHide, xAnalyzer, OllyDumpEx: x64dbg plugins -> x32\plugins and x64\plugins
  - TitanHide: x64dbg plugin -> x32\plugins and x64\plugins, PLUS the kernel driver and GUI
               copied to <X64dbgDir>\titanhide\ (see titanhide\README.md for the install steps;
               running the driver requires test-signing and disabled PatchGuard, which this
               script does NOT change on your machine).
  - PE-sieve: hasherezade's scanner for in-memory PE anomalies (both exe variants) ->
               <X64dbgDir>\tools\pesieve\.

Every download is checked against a pinned SHA-256 hash. Already-installed items are skipped
unless -Force is given.

OllyDumpEx is closed-source freeware without a redistribution license, so it is never shipped in
this repository or its releases: this script downloads it from the author's website.
TitanHide is open-source but AV products often flag its driver as a HackTool; the download is
over HTTPS from the author's GitHub release and the SHA-256 is verified.

.EXAMPLE
.\install-plugins.ps1                          # all extras, into ..\bin (development build)

.EXAMPLE
.\install-plugins.ps1 -Plugins OllyDumpEx       # in a release folder: only the missing one

.EXAMPLE
.\install-plugins.ps1 -X64dbgDir C:\Tools\x64dbg\release -Plugins TitanHide, PE-sieve
#>
param(
    # Folder that contains x32\ and x64\
    [string] $X64dbgDir,

    [ValidateSet('ScyllaHide', 'xAnalyzer', 'OllyDumpEx', 'TitanHide', 'PE-sieve')]
    [string[]] $Plugins = @('ScyllaHide', 'xAnalyzer', 'OllyDumpEx', 'TitanHide', 'PE-sieve'),

    [switch] $Force
)

$ErrorActionPreference = 'Stop'

if (-not $X64dbgDir) {
    # In a release package this script is next to x32\ and x64\, in the repository it is in plugins\
    $X64dbgDir = if (Test-Path (Join-Path $PSScriptRoot 'x64')) { $PSScriptRoot } else { Join-Path $PSScriptRoot '..\bin' }
}
if (-not (Test-Path (Join-Path $X64dbgDir 'x64')) -and -not (Test-Path (Join-Path $X64dbgDir 'x32'))) {
    throw "x32\ or x64\ not found in '$X64dbgDir', use -X64dbgDir"
}
$X64dbgDir = (Resolve-Path $X64dbgDir).Path

$Sources = @{
    ScyllaHide = @{
        Version = 'v1.4'
        Files   = @(@{ Url = 'https://github.com/x64dbg/ScyllaHide/releases/download/v1.4/ScyllaHide_2023-03-24_13-03.zip'; Sha256 = 'edeb0dd203fd1ef38e1404e8a1bd001e05c50b6096e49533f546d13ffdcb7404' })
        Marker  = 'ScyllaHideX64DBGPlugin'
    }
    xAnalyzer  = @{
        Version = '2.5.12'
        Files   = @(
            @{ Url = 'https://github.com/ThunderCls/xAnalyzer/releases/download/2.5.12/xAnalyzer.dp32'; Sha256 = 'ec586fdc19e87656a630c8b4359495e0a5dc4d29bf0bb0781c4ae907efbe8a08' },
            @{ Url = 'https://github.com/ThunderCls/xAnalyzer/releases/download/2.5.12/xAnalyzer.dp64'; Sha256 = '8240a3ca76b21f4181fef0b047521177a5cbff13b9760340a35848b782b38117' },
            @{ Url = 'https://github.com/ThunderCls/xAnalyzer/releases/download/2.5.12/apis_def.zip'; Sha256 = '606c9b3144de24878817fcf8391e399ce00c67651abe85373358db9195aa47f1' }
        )
        Marker  = 'xAnalyzer'
    }
    OllyDumpEx = @{
        Version = 'v1.86'
        Files   = @(@{ Url = 'https://low-priority.appspot.com/ollydumpex/OllyDumpEx.zip'; Sha256 = '3b39e7d8d0b8d1c1407ec93531f2a35fd57ee7d26d4ce71cdc1dc3d9d766f758' })
        Marker  = 'OllyDumpEx_X64Dbg'
    }
    TitanHide  = @{
        Version = 'v0019'
        Files   = @(@{ Url = 'https://github.com/mrexodia/TitanHide/releases/download/v0019/TitanHide-f1fbb18ec89ce8d072296faeda8ff7aa9a4468cb.zip'; Sha256 = '6799ea6f77ef190dab04ff03923242446ce0bcebfed98d7872e99ba43d2fe2b6' })
        Marker  = 'TitanHide'
    }
    'PE-sieve' = @{
        Version = 'v0.4.1.1'
        Files   = @(
            @{ Url = 'https://github.com/hasherezade/pe-sieve/releases/download/v0.4.1.1/pe-sieve32.exe'; Sha256 = 'ee684b34b37af24d1c1e9ca80ceeee6878cc80bb24c0c3793840c9acf905bd59' },
            @{ Url = 'https://github.com/hasherezade/pe-sieve/releases/download/v0.4.1.1/pe-sieve64.exe'; Sha256 = '9f3ff2884a2c61006cd0a92b7572a815b8dc17012be7747a6abd6ca07c503a3b' }
        )
        # PE-sieve is a standalone .exe (not a .dp plugin), so the standard marker check
        # does not apply; the switch body below sets its own CheckFile.
        Marker  = $null
        CheckFile = 'tools\pesieve\pe-sieve64.exe'
    }
}

function Get-Download([string] $Url, [string] $Sha256, [string] $Folder) {
    $file = Join-Path $Folder ([IO.Path]::GetFileName($Url))
    # curl.exe -4: Invoke-WebRequest can hang forever on machines with broken IPv6
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -4 -fsSL --retry 3 -o $file $Url
        if ($LASTEXITCODE -ne 0) { throw "download failed: $Url" }
    }
    else {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $file
    }
    $hash = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant()
    if ($hash -ne $Sha256) {
        throw "SHA-256 mismatch for $Url`n  expected $Sha256`n  got      $hash`nThe file changed upstream: check it, then update the hash in this script."
    }
    return $file
}

function Expand-Zip([string] $Zip, [string] $Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        foreach ($entry in $archive.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
            if (-not $target.StartsWith([IO.Path]::GetFullPath($Destination))) { throw "unsafe path in $Zip" }
            if ($entry.FullName.EndsWith('/')) { New-Item -ItemType Directory -Force $target | Out-Null; continue }
            New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
        }
    }
    finally { $archive.Dispose() }
}

$archs = @('x32', 'x64') | Where-Object { Test-Path (Join-Path $X64dbgDir $_) }
$temp = Join-Path ([IO.Path]::GetTempPath()) ("x64dbg-plugins-" + [Guid]::NewGuid())
New-Item -ItemType Directory $temp | Out-Null
try {
    foreach ($name in $Plugins) {
        $source = $Sources[$name]
        if ($source.CheckFile) {
            # Non-plugin tools (PE-sieve: standalone exe) advertise their own install sentinel
            $allInstalled = Test-Path (Join-Path $X64dbgDir $source.CheckFile)
        }
        else {
            $installed = $archs | Where-Object { Test-Path (Join-Path $X64dbgDir "$_\plugins\$($source.Marker).dp$(if ($_ -eq 'x64') { '64' } else { '32' })") }
            $allInstalled = @($installed).Count -eq @($archs).Count
        }
        if ($allInstalled -and -not $Force) {
            Write-Host "$name $($source.Version): already installed (use -Force to reinstall)"
            continue
        }
        Write-Host "$name $($source.Version): downloading..."
        $files = @(foreach ($f in $source.Files) { Get-Download $f.Url $f.Sha256 $temp })

        foreach ($arch in $archs) {
            $bits = if ($arch -eq 'x64') { '64' } else { '32' }
            $pluginDir = Join-Path $X64dbgDir "$arch\plugins"
            New-Item -ItemType Directory -Force $pluginDir | Out-Null
            switch ($name) {
                'ScyllaHide' {
                    $unpacked = Join-Path $temp 'ScyllaHide'
                    Expand-Zip $files[0] $unpacked
                    Copy-Item (Join-Path $unpacked "x64dbg\$arch\plugins\*") $pluginDir -Force
                }
                'xAnalyzer' {
                    Copy-Item ($files | Where-Object { $_ -like "*.dp$bits" }) $pluginDir -Force
                    # xAnalyzer refuses to load without its definitions in plugins\apis_def\
                    Expand-Zip ($files | Where-Object { $_ -like '*apis_def.zip' }) (Join-Path $pluginDir 'apis_def')
                }
                'OllyDumpEx' {
                    $unpacked = Join-Path $temp 'OllyDumpEx'
                    Expand-Zip $files[0] $unpacked
                    Copy-Item (Get-ChildItem -Recurse $unpacked -Filter "OllyDumpEx_X64Dbg.dp$bits").FullName $pluginDir -Force
                }
                'TitanHide' {
                    # The release zip has x32\plugins\TitanHide.dp32 and x64\plugins\TitanHide.dp64,
                    # plus the kernel driver (x64\TitanHide.sys), its signing cert, and a GUI for
                    # both archs. The .dp goes to <X64dbgDir>\<arch>\plugins; the driver and GUI
                    # land in a sibling titanhide\ folder with install docs. The driver install
                    # itself (sc create, service start) requires admin + test-signing and is left
                    # for the user to do, after reading titanhide\README.md.
                    $unpacked = Join-Path $temp 'TitanHide'
                    if (-not (Test-Path $unpacked)) { Expand-Zip $files[0] $unpacked }
                    $plugin = Join-Path $unpacked "$arch\plugins\TitanHide.dp$bits"
                    if (Test-Path $plugin) { Copy-Item $plugin $pluginDir -Force }
                    # Driver + GUI copies happen once (on the last arch iteration), not per arch.
                    if ($arch -eq ($archs | Select-Object -Last 1)) {
                        $titan = Join-Path $X64dbgDir 'titanhide'
                        New-Item -ItemType Directory -Force $titan | Out-Null
                        # Kernel driver + certificate: keep original filenames.
                        foreach ($name in 'TitanHide.sys', 'TitanHide.cer') {
                            $src = Join-Path $unpacked "x64\$name"
                            if (Test-Path $src) { Copy-Item $src (Join-Path $titan $name) -Force }
                        }
                        # The 32 and 64 bit GUIs are distinct binaries: suffix by arch to keep both.
                        foreach ($a in 'x32', 'x64') {
                            $gui = Join-Path $unpacked "$a\TitanHideGUI.exe"
                            if (Test-Path $gui) { Copy-Item $gui (Join-Path $titan "TitanHideGUI-$a.exe") -Force }
                        }
                        $readme = Join-Path $PSScriptRoot 'README-TitanHide.md'
                        if (Test-Path $readme) { Copy-Item $readme (Join-Path $titan 'README.md') -Force }
                    }
                }
                'PE-sieve' {
                    # Both exe variants live under <X64dbgDir>\tools\pesieve\. Written once on
                    # the first arch iteration; the second iteration is a no-op.
                    if ($arch -eq (($archs | Select-Object -First 1))) {
                        $pesieve = Join-Path $X64dbgDir 'tools\pesieve'
                        New-Item -ItemType Directory -Force $pesieve | Out-Null
                        Copy-Item ($files | Where-Object { $_ -like '*pe-sieve32.exe' }) $pesieve -Force
                        Copy-Item ($files | Where-Object { $_ -like '*pe-sieve64.exe' }) $pesieve -Force
                        $readme = Join-Path $PSScriptRoot 'README-PE-sieve.md'
                        if (Test-Path $readme) { Copy-Item $readme (Join-Path $pesieve 'README.md') -Force }
                    }
                }
            }
        }
        $where = switch ($name) {
            'TitanHide' { "$(($archs | ForEach-Object { "$_\plugins" }) -join ', '), titanhide\" }
            'PE-sieve'  { 'tools\pesieve\' }
            default     { ($archs | ForEach-Object { "$_\plugins" }) -join ', ' }
        }
        Write-Host "$name $($source.Version): installed in $where"
    }
}
finally {
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
}
