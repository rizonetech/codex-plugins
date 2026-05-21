$ErrorActionPreference = "Stop"

$pluginRoot = Split-Path -Parent $PSScriptRoot
$toolDir = Join-Path $HOME ".codex\tools"
$toolPath = Join-Path $toolDir "wsl-run.ps1"

New-Item -ItemType Directory -Force -Path $toolDir | Out-Null

Copy-Item -Force -LiteralPath (Join-Path $pluginRoot "scripts\wsl-run.ps1") -Destination $toolPath

$hook = @'

function wsl-run {
    & "$HOME\.codex\tools\wsl-run.ps1" @args
}
'@

$profilePaths = @(
    (Join-Path $HOME "Documents\PowerShell\Microsoft.PowerShell_profile.ps1"),
    (Join-Path $HOME "Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1")
)

foreach ($profilePath in $profilePaths) {
    $profileDir = Split-Path -Parent $profilePath
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

    if (-not (Test-Path -LiteralPath $profilePath)) {
        New-Item -ItemType File -Force -Path $profilePath | Out-Null
    }

    $profileText = Get-Content -Raw -LiteralPath $profilePath
    if ([string]::IsNullOrEmpty($profileText) -or $profileText -notmatch "function\s+wsl-run") {
        Add-Content -LiteralPath $profilePath -Value $hook
    }
}

Write-Host "Installed wsl-run to $toolPath"
