<#
.SYNOPSIS
    Launches Chrome with CDP enabled against a project-local profile directory.

.DESCRIPTION
    Resolves all paths relative to this script's own location, so the entire
    ChromeMCP folder can be moved or copied without breaking. Idempotent:
    if CDP is already responding on the chosen port, exits cleanly with the
    existing endpoint info instead of trying to spawn a duplicate.

.PARAMETER Port
    CDP port to bind. Default 9222.

.PARAMETER ChromeExe
    Override path to chrome.exe. If omitted, standard install locations are tried.

.PARAMETER Force
    Launch a new Chrome process even if CDP is already responding on the port.
#>
[CmdletBinding()]
param(
    [int]$Port = 9222,
    [string]$ChromeExe,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# Resolve project paths relative to this script (portable across moves).
$ScriptDir   = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir

# Profile lives in %LOCALAPPDATA%, not in the project directory. Browser data
# (~hundreds of MB of SQLite/mmap files, accessed at high frequency) belongs
# on Windows-native storage; the project code itself can live anywhere.
# Path matches Chrome's own convention (%LOCALAPPDATA%\<vendor>\<app>).
$ProfileDir  = Join-Path $env:LocalAppData 'ChromeMCP\Profile'

function Find-Chrome {
    if ($ChromeExe) {
        if (Test-Path $ChromeExe) { return (Resolve-Path $ChromeExe).Path }
        throw "Chrome path not found: $ChromeExe"
    }
    $candidates = @(
        (Join-Path $env:ProgramFiles            'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)}     'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LocalAppData            'Google\Chrome\Application\chrome.exe')
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }

    $cmd = Get-Command chrome.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    throw "Could not locate chrome.exe. Pass -ChromeExe <path> explicitly."
}

function Test-Cdp {
    param([int]$Port)
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" `
                                 -TimeoutSec 2 -ErrorAction Stop
    } catch { return $null }
}

$chrome = Find-Chrome

Write-Host ""
Write-Host "ChromeMCP launcher" -ForegroundColor Cyan
Write-Host "  chrome.exe : $chrome"
Write-Host "  profile    : $ProfileDir"
Write-Host "  CDP port   : $Port"
Write-Host ""

# Idempotency: if CDP is already up, just report and exit.
$existing = Test-Cdp -Port $Port
if ($existing -and -not $Force) {
    Write-Host "CDP is already responding on port $Port - nothing to do." -ForegroundColor Green
    Write-Host "  Browser : $($existing.Browser)"
    Write-Host "  WS URL  : $($existing.webSocketDebuggerUrl)"
    Write-Host ""
    Write-Host "(Use -Force to spawn another Chrome anyway. It will fail to bind the port" -ForegroundColor DarkGray
    Write-Host " unless you change -Port, since CDP is already held by the running process.)" -ForegroundColor DarkGray
    exit 0
}

# Ensure the project-local profile directory exists.
if (-not (Test-Path $ProfileDir)) {
    New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null
    Write-Host "Created profile directory."
}

$chromeArgs = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$ProfileDir"
)

Write-Host "Starting Chrome..."
Start-Process -FilePath $chrome -ArgumentList $chromeArgs | Out-Null

# Wait up to 15s for CDP to come up.
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    $resp = Test-Cdp -Port $Port
    if ($resp) {
        Write-Host ""
        Write-Host "CDP ready." -ForegroundColor Green
        Write-Host "  Browser : $($resp.Browser)"
        Write-Host "  WS URL  : $($resp.webSocketDebuggerUrl)"
        Write-Host ""
        Write-Host "Sign in to the sites you want the agent to access. Cookies persist in"
        Write-Host "the per-user profile at: $ProfileDir"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

Write-Error "Chrome was launched but CDP did not respond on port $Port within 15s."
exit 1
