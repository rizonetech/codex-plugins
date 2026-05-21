param(
  [string]$CodexConfigHome = $env:CODEX_HOME,
  [string]$CodexPluginHome = "",
  [switch]$KeepOldLocalMarketplaces,
  [switch]$SkipToolInstall
)

$ErrorActionPreference = "Stop"

function ConvertTo-ExtendedPath {
  param([Parameter(Mandatory = $true)][string]$Path)

  if ($Path.StartsWith("\\?\")) {
    return $Path
  }

  if ($Path.StartsWith("\\")) {
    return "\\?\UNC\" + $Path.Substring(2)
  }

  return "\\?\" + $Path
}

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

function Remove-DirectoryInside {
  param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Root
  )

  if (-not (Test-Path -LiteralPath $Target)) {
    return
  }

  $resolvedTarget = [System.IO.Path]::GetFullPath($Target)
  $resolvedRoot = [System.IO.Path]::GetFullPath($Root)

  if (-not $resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove path outside expected root: $resolvedTarget"
  }

  Remove-Item -Recurse -Force -LiteralPath $resolvedTarget
}

function Remove-TomlBlock {
  param(
    [AllowEmptyString()][string]$Text,
    [Parameter(Mandatory = $true)][string]$Header
  )

  $escapedHeader = [regex]::Escape($Header)
  return [regex]::Replace($Text, "(?ms)^\[$escapedHeader\]\r?\n.*?(?=^\[|\z)", "")
}

function Copy-DirectoryClean {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  $skipNames = @(
    ".git",
    "node_modules",
    "logs",
    ".playwright-mcp",
    "demo-output",
    "__pycache__",
    "artifacts"
  )

  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  $sourceRoot = [System.IO.Path]::GetFullPath($Source).TrimEnd("\", "/")

  Get-ChildItem -LiteralPath $Source -Recurse -Force | ForEach-Object {
    $fullName = [System.IO.Path]::GetFullPath($_.FullName)
    if (-not $fullName.StartsWith($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to copy path outside source root: $fullName"
    }
    $relative = $fullName.Substring($sourceRoot.Length).TrimStart("\", "/")
    $parts = $relative -split '[\\/]'

    foreach ($part in $parts) {
      if ($skipNames -contains $part) {
        return
      }
    }

    if (-not $_.PSIsContainer -and $_.Name -like "*.pyc") {
      return
    }

    $target = Join-Path $Destination $relative
    if ($_.PSIsContainer) {
      New-Item -ItemType Directory -Force -Path $target | Out-Null
    } else {
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
      Copy-Item -Force -LiteralPath $_.FullName -Destination $target
    }
  }
}

if ([string]::IsNullOrWhiteSpace($CodexConfigHome)) {
  $CodexConfigHome = Join-Path $HOME ".codex"
}

$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Split-Path -Parent $ScriptRoot
$SourcePluginsRoot = Join-Path $RepoRoot "plugins"

if ([string]::IsNullOrWhiteSpace($CodexPluginHome)) {
  $CodexPluginHome = $CodexConfigHome

  if ($RepoRoot.StartsWith("\\wsl.localhost\") -or $RepoRoot.StartsWith("\\wsl$\")) {
    $parts = $RepoRoot.TrimStart("\").Split("\")
    if ($parts.Length -ge 4 -and $parts[2] -eq "home") {
      $CodexPluginHome = "\\" + (Join-Path (($parts | Select-Object -First 4) -join "\") ".codex")
    }
  }
}

$CodexConfigHome = [System.IO.Path]::GetFullPath($CodexConfigHome)
$CodexPluginHome = [System.IO.Path]::GetFullPath($CodexPluginHome)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$plugins = @(
  @{
    Name = "chromemcp-browser"
    Source = Join-Path $SourcePluginsRoot "chromemcp-browser"
    Requires = @(".codex-plugin\plugin.json", ".mcp.json")
  },
  @{
    Name = "bashlane"
    Source = Join-Path $SourcePluginsRoot "bashlane"
    Requires = @(".codex-plugin\plugin.json", "scripts\install.ps1", "scripts\wsl-run.ps1")
  },
  @{
    Name = "overnight-runner"
    Source = Join-Path $SourcePluginsRoot "overnight-runner"
    Requires = @(".codex-plugin\plugin.json", "scripts\overnight-runner.py", "skills\overnight-runner\SKILL.md")
  }
)

foreach ($plugin in $plugins) {
  if (-not (Test-Path -LiteralPath $plugin.Source)) {
    throw "Plugin source not found: $($plugin.Source)"
  }

  foreach ($required in $plugin.Requires) {
    $requiredPath = Join-Path $plugin.Source $required
    if (-not (Test-Path -LiteralPath $requiredPath)) {
      throw "Required plugin file not found: $requiredPath"
    }
  }
}

$marketplaceRoot = Join-Path $CodexPluginHome "plugins\rizonetech-local"
$pluginsDestRoot = Join-Path $marketplaceRoot "plugins"
$marketplacePath = Join-Path $marketplaceRoot ".agents\plugins\marketplace.json"
$toolsRoot = Join-Path $CodexPluginHome "tools"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $marketplacePath) | Out-Null
New-Item -ItemType Directory -Force -Path $pluginsDestRoot | Out-Null
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null

foreach ($plugin in $plugins) {
  $dest = Join-Path $pluginsDestRoot $plugin.Name
  Remove-DirectoryInside -Target $dest -Root $pluginsDestRoot
  Copy-DirectoryClean -Source $plugin.Source -Destination $dest

  $manifestPath = Join-Path $dest ".codex-plugin\plugin.json"
  $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
  $manifest.interface.category = "Rizonetech"
  [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 20) + "`n", $utf8NoBom)
}

$chromeDest = Join-Path $pluginsDestRoot "chromemcp-browser"
$token = $null
try {
  $wslChromeDest = ConvertTo-WslPath $chromeDest
  & wsl.exe --cd $wslChromeDest -- bash -lc "chmod +x bridge-check chrome chromemcp mcp-* setup-bridge mcp/*.sh 2>/dev/null || true" | Out-Null
  $token = (& wsl.exe --cd $wslChromeDest -- bash -lc "bash ./mcp-token" 2>$null) -join ""
  $token = $token.Trim()
} catch {
  $token = ""
}

if ([string]::IsNullOrWhiteSpace($token) -or $token.Length -lt 32) {
  Write-Warning "Could not generate ChromeMCP auth token during install. Leaving placeholder .mcp.json; run plugins/chromemcp-browser/mcp-token and update .mcp.json before enabling MCP auth."
} else {
  $mcpConfig = @{
    mcpServers = @{
      "chromemcp-playwright" = @{
        type = "http"
        url = "http://localhost:8931/mcp"
        headers = @{
          Authorization = "Bearer $token"
        }
        note = "Local ChromeMCP Playwright MCP server. Start it with plugins/chromemcp-browser/mcp-up before use. Token generated by plugins/chromemcp-browser/mcp-token."
      }
    }
  }
  [System.IO.File]::WriteAllText((Join-Path $chromeDest ".mcp.json"), ($mcpConfig | ConvertTo-Json -Depth 10) + "`n", $utf8NoBom)
}

$marketplace = @{
  name = "rizonetech-local"
  interface = @{
    displayName = "Rizonetech Local"
  }
  plugins = @(
    @{
      name = "chromemcp-browser"
      source = @{
        source = "local"
        path = "./plugins/chromemcp-browser"
      }
      policy = @{
        installation = "AVAILABLE"
        authentication = "ON_INSTALL"
      }
      category = "Rizonetech"
    },
    @{
      name = "bashlane"
      source = @{
        source = "local"
        path = "./plugins/bashlane"
      }
      policy = @{
        installation = "AVAILABLE"
        authentication = "ON_INSTALL"
      }
      category = "Rizonetech"
    },
    @{
      name = "overnight-runner"
      source = @{
        source = "local"
        path = "./plugins/overnight-runner"
      }
      policy = @{
        installation = "AVAILABLE"
        authentication = "ON_INSTALL"
      }
      category = "Rizonetech"
    }
  )
}

[System.IO.File]::WriteAllText($marketplacePath, ($marketplace | ConvertTo-Json -Depth 10) + "`n", $utf8NoBom)

$overnightRunnerShim = @'
#!/usr/bin/env bash
set -euo pipefail

script="$HOME/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py"
if [ ! -f "$script" ]; then
  echo "Overnight Runner helper not found: $script" >&2
  echo "Run scripts/install-rizonetech-local.ps1 from the codex-plugins repository, then restart Codex." >&2
  exit 127
fi

exec python3 "$script" "$@"
'@
$overnightRunnerShimPath = Join-Path $toolsRoot "overnight-runner"
[System.IO.File]::WriteAllText($overnightRunnerShimPath, $overnightRunnerShim.Replace("`r`n", "`n") + "`n", $utf8NoBom)

try {
  $wslToolsRoot = ConvertTo-WslPath $toolsRoot
  & wsl.exe --cd $wslToolsRoot -- bash -lc "chmod +x overnight-runner 2>/dev/null || true" | Out-Null
} catch {
  Write-Warning "Could not chmod Overnight Runner helper shim. If using WSL, run: chmod +x ~/.codex/tools/overnight-runner"
}

$configPath = Join-Path $CodexConfigHome "config.toml"
if (-not (Test-Path -LiteralPath $configPath)) {
  New-Item -ItemType File -Force -Path $configPath | Out-Null
}

$config = Get-Content -Raw -LiteralPath $configPath
if ($null -eq $config) {
  $config = ""
}
$commentPatterns = @(
  '(?ms)^# ChromeMCP local Codex marketplace\.\r?\n',
  '(?ms)^# Bashlane local Codex marketplace\.\r?\n',
  '(?ms)^# Rizonetech Codex plugin catalog\.\r?\n',
  '(?ms)^# Rizonetech local Codex marketplace\.\r?\n'
)

foreach ($pattern in $commentPatterns) {
  $config = [regex]::Replace($config, $pattern, "")
}

foreach ($header in @(
  'marketplaces.chromemcp-local',
  'plugins."chromemcp-browser@chromemcp-local"',
  'marketplaces.bashlane-local',
  'plugins."bashlane@bashlane-local"',
  'marketplaces.rizonetech-codex-plugins',
  'marketplaces.rizonetech-local',
  'plugins."chromemcp-browser@rizonetech-local"',
  'plugins."bashlane@rizonetech-local"',
  'plugins."overnight-runner@rizonetech-local"'
)) {
  $config = Remove-TomlBlock -Text $config -Header $header
}

$sourcePath = ConvertTo-ExtendedPath $marketplaceRoot
$block = @"

# Rizonetech local Codex marketplace.
[marketplaces.rizonetech-local]
source_type = "local"
source = '$sourcePath'

[plugins."chromemcp-browser@rizonetech-local"]
enabled = true

[plugins."bashlane@rizonetech-local"]
enabled = true

[plugins."overnight-runner@rizonetech-local"]
enabled = true
"@

[System.IO.File]::WriteAllText($configPath, $config.TrimEnd() + $block + "`r`n", $utf8NoBom)

if (-not $KeepOldLocalMarketplaces) {
  foreach ($oldName in @("chromemcp-local", "bashlane-local")) {
    $old = Join-Path (Join-Path $CodexPluginHome "plugins") $oldName
    Remove-DirectoryInside -Target $old -Root (Join-Path $CodexPluginHome "plugins")
  }
}

if (-not $SkipToolInstall) {
  $bashlaneInstaller = Join-Path $pluginsDestRoot "bashlane\scripts\install.ps1"
  & powershell -ExecutionPolicy Bypass -File $bashlaneInstaller
}

Write-Host "Installed Rizonetech local marketplace: $marketplaceRoot"
Write-Host "Updated Codex config: $configPath"
