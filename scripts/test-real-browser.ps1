param(
  [string]$CdpEndpoint = "http://172.28.112.1:9222",
  [string]$Clientapp2Root = "/home/<user>/www/clientapp2",
  [string]$ClientappRoot = "/home/<user>/www/clientapp"
)

$ErrorActionPreference = "Stop"

function ConvertTo-WslPath {
  param([Parameter(Mandatory = $true)][string]$Path)

  $resolved = [System.IO.Path]::GetFullPath($Path)
  if ($resolved.StartsWith("\\wsl.localhost\") -or $resolved.StartsWith("\\wsl$\")) {
    $parts = $resolved.TrimStart("\").Split("\")
    if ($parts.Length -le 2) {
      return "/"
    }
    return "/" + (($parts | Select-Object -Skip 2) -join "/")
  }

  if ($resolved -match '^([A-Za-z]):(.*)$') {
    $drive = $Matches[1].ToLowerInvariant()
    $rest = $Matches[2] -replace '\\', '/'
    return "/mnt/$drive$rest"
  }

  throw "Cannot convert path to WSL path: $resolved"
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $scriptRoot
$wslRepoRoot = ConvertTo-WslPath $repoRoot

if ([string]::IsNullOrWhiteSpace($wslRepoRoot)) {
  throw "Could not resolve repository path inside WSL."
}

$command = @"
set -euo pipefail
cd "$wslRepoRoot/plugins/chromemcp-browser/mcp"
npm ci --no-audit --no-fund >/dev/null
CHROMEMCP_CDP_ENDPOINT="$CdpEndpoint" \
CLIENTAPP2_ROOT="$Clientapp2Root" \
CLIENTAPP_ROOT="$ClientappRoot" \
node "$wslRepoRoot/scripts/real-browser-smoke-test.js"
"@

& wsl.exe -- bash -lc $command
