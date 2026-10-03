<#
.SYNOPSIS
Downloads and installs third-party x64dbg plugins from their official sources.

.DESCRIPTION
Installs ScyllaHide, xAnalyzer and OllyDumpEx into <X64dbgDir>\x32\plugins and <X64dbgDir>\x64\plugins.
Every download is checked against a pinned SHA-256 hash. Plugins that are already installed are
skipped unless -Force is given.

OllyDumpEx is closed-source freeware without a redistribution license, so it is never shipped in
this repository or its releases: this script downloads it from the author's website.

.EXAMPLE
.\install-plugins.ps1                          # all plugins, into ..\bin (development build)

.EXAMPLE
.\install-plugins.ps1 -Plugins OllyDumpEx       # in a release folder: only the missing plugin

.EXAMPLE
.\install-plugins.ps1 -X64dbgDir C:\Tools\x64dbg\release -Force
#>
param(
    # Folder that contains x32\ and x64\
    [string] $X64dbgDir,

    [ValidateSet('ScyllaHide', 'xAnalyzer', 'OllyDumpEx')]
    [string[]] $Plugins = @('ScyllaHide', 'xAnalyzer', 'OllyDumpEx'),

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
        $installed = $archs | Where-Object { Test-Path (Join-Path $X64dbgDir "$_\plugins\$($source.Marker).dp$(if ($_ -eq 'x64') { '64' } else { '32' })") }
        if (@($installed).Count -eq @($archs).Count -and -not $Force) {
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
            }
        }
        Write-Host "$name $($source.Version): installed in $(($archs | ForEach-Object { "$_\plugins" }) -join ', ')"
    }
}
finally {
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
}
