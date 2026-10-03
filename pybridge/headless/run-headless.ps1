<#
.SYNOPSIS
Runs an x64dbg script template with headless.exe (no GUI).

.DESCRIPTION
The template placeholders are replaced, the script is written to the output folder and
headless.exe executes it. The script must end with: log "[template] done"
headless.exe is closed when this line is printed, after the debuggee has stopped
(plus a short delay), or after -TimeoutSeconds.

Placeholders:
  %TARGET%  full path of -Target
  %MODULE%  file name of -Target (e.g. program.exe)
  %OUT%     output folder
  %BITS%    64 or 32

.EXAMPLE
.\run-headless.ps1 -Template api-log -Target C:\Windows\System32\whoami.exe

.EXAMPLE
.\run-headless.ps1 -Template trace-export -Target .\program.exe -X64dbgDir C:\path\to\x64dbg\bin
#>
param(
    [Parameter(Mandatory = $true)]
    [string] $Template,

    [Parameter(Mandatory = $true)]
    [string] $Target,

    [string] $OutDir,

    [ValidateSet('x64', 'x32')]
    [string] $Arch = 'x64',

    [string] $X64dbgDir,

    [int] $TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

if (-not $X64dbgDir) {
    $X64dbgDir = if ($env:X64DBG_DIR) { $env:X64DBG_DIR } else {
        Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\x64dbg.x64dbg_Microsoft.Winget.Source_8wekyb3d8bbwe\release'
    }
}
$headless = Join-Path $X64dbgDir "$Arch\headless.exe"
if (-not (Test-Path $headless)) { throw "headless.exe not found: $headless" }

$templatePath = if (Test-Path $Template) { $Template } else { Join-Path $PSScriptRoot "templates\$Template.txt" }
if (-not (Test-Path $templatePath)) { throw "template not found: $Template" }
$templateName = [IO.Path]::GetFileNameWithoutExtension($templatePath)

$targetPath = (Resolve-Path $Target).Path
if (-not $OutDir) {
    $OutDir = Join-Path (Get-Location) ("out\{0}-{1}" -f $templateName, (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

# Fill the placeholders. UTF-8 without BOM: a BOM would corrupt the first script line.
$script = (Get-Content -Raw $templatePath).
    Replace('%TARGET%', $targetPath).
    Replace('%MODULE%', [IO.Path]::GetFileName($targetPath)).
    Replace('%OUT%', $OutDir).
    Replace('%BITS%', $(if ($Arch -eq 'x64') { '64' } else { '32' }))
$scriptPath = Join-Path $OutDir 'script.txt'
[IO.File]::WriteAllText($scriptPath, $script, (New-Object Text.UTF8Encoding $false))

$logPath = Join-Path $OutDir 'headless.log'
$userDir = Join-Path $OutDir 'userdir'   # isolated settings: settingset in a template does not leak
New-Item -ItemType Directory -Force -Path $userDir | Out-Null

$psi = New-Object Diagnostics.ProcessStartInfo
$psi.FileName = $headless
$psi.Arguments = "-userdir `"$userDir`" -cf `"$scriptPath`""
$psi.WorkingDirectory = Split-Path $headless
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true    # headless.exe exits when stdin is closed
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [Text.Encoding]::UTF8

Write-Host "template : $templatePath"
Write-Host "target   : $targetPath"
Write-Host "output   : $OutDir"
$proc = [Diagnostics.Process]::Start($psi)
$errTask = $proc.StandardError.ReadToEndAsync()
$log = New-Object IO.StreamWriter($logPath, $false, (New-Object Text.UTF8Encoding $false))
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$stoppedAt = $null
$reason = 'timeout'
$readTask = $proc.StandardOutput.ReadLineAsync()
try {
    while ($true) {
        if ($readTask.Wait(200)) {
            $line = $readTask.Result
            $readTask = $null
            if ($null -eq $line) { $reason = 'headless exited'; break }
            $log.WriteLine($line)
            Write-Host $line
            if ($line -match '\[template\] done') { $reason = 'done'; break }
            if ($line -match 'Debugging stopped!') { $stoppedAt = Get-Date }
            $readTask = $proc.StandardOutput.ReadLineAsync()
        }
        if ($stoppedAt -and ((Get-Date) - $stoppedAt).TotalSeconds -gt 3) { $reason = 'debuggee stopped'; break }
        if ((Get-Date) -gt $deadline) { break }
    }
}
finally {
    if (-not $proc.HasExited) {
        try { $proc.StandardInput.WriteLine('exit'); $proc.StandardInput.Close() } catch { }
        if (-not $proc.WaitForExit(15000)) { $proc.Kill() }
    }
    # Keep the rest of the output (shutdown messages)
    if ($readTask -and $readTask.Wait(5000) -and $null -ne $readTask.Result) { $log.WriteLine($readTask.Result) }
    if (-not $readTask -or $readTask.IsCompleted) {
        $rest = $proc.StandardOutput.ReadToEnd()
        if ($rest) { $log.Write($rest) }
    }
    $log.Close()
    if ($errTask.Result) { Write-Warning $errTask.Result }
}

Write-Host ""
Write-Host "finished : $reason"
Write-Host "log      : $logPath"
if ($reason -ne 'done') { exit 1 }
