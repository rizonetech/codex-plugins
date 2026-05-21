param(
  [string]$CodexConfigHome = $env:CODEX_HOME,
  [string]$CodexPluginHome = "",
  [string]$WorkspaceRoot = "",
  [switch]$SkipClone,
  [switch]$KeepOldLocalMarketplaces
)

$ErrorActionPreference = "Stop"

function ConvertTo-ExtendedPath {
  param([string]$Path)

  if ($Path.StartsWith("\\?\")) {
    return $Path
  }

  if ($Path.StartsWith("\\")) {
    return "\\?\UNC\" + $Path.Substring(2)
  }

  return "\\?\" + $Path
}

if ([string]::IsNullOrWhiteSpace($CodexConfigHome)) {
  $CodexConfigHome = Join-Path $HOME ".codex"
}

$ScriptRoot = Split-Path -Parent $PSCommandPath
$CatalogRepo = Split-Path -Parent $ScriptRoot

if ([string]::IsNullOrWhiteSpace($CodexPluginHome)) {
  $CodexPluginHome = $CodexConfigHome

  if ($CatalogRepo -match '^(\\\\wsl\.localhost\\[^\\]+\\home\\[^\\]+)\\') {
    $CodexPluginHome = Join-Path $Matches[1] ".codex"
  }
}

if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) {
  $WorkspaceRoot = Split-Path -Parent $CatalogRepo
}

$CodexConfigHome = [System.IO.Path]::GetFullPath($CodexConfigHome)
$CodexPluginHome = [System.IO.Path]::GetFullPath($CodexPluginHome)
$WorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$repos = @(
  @{
    Name = "ChromeMCP"
    Url = "https://github.com/rizonetech/ChromeMCP.git"
    Path = Join-Path $WorkspaceRoot "ChromeMCP"
  },
  @{
    Name = "Bashlane"
    Url = "https://github.com/rizonetech/Bashlane.git"
    Path = Join-Path $WorkspaceRoot "Bashlane"
  }
)

foreach ($repo in $repos) {
  if (Test-Path $repo.Path) {
    Write-Host "Using existing $($repo.Name): $($repo.Path)"
    continue
  }

  if ($SkipClone) {
    throw "$($repo.Name) repo not found at $($repo.Path). Remove -SkipClone or clone it manually."
  }

  Write-Host "Cloning $($repo.Name) into $($repo.Path)"
  git clone $repo.Url $repo.Path
}

$chromePluginSource = Join-Path $repos[0].Path "plugins\chromemcp-browser"
$bashlanePluginSource = $repos[1].Path

foreach ($required in @(
  (Join-Path $chromePluginSource ".codex-plugin\plugin.json"),
  (Join-Path $chromePluginSource ".mcp.json"),
  (Join-Path $bashlanePluginSource ".codex-plugin\plugin.json")
)) {
  if (-not (Test-Path $required)) {
    throw "Required plugin file not found: $required"
  }
}

$marketplaceRoot = Join-Path $CodexPluginHome "plugins\rizonetech-local"
$pluginsRoot = Join-Path $marketplaceRoot "plugins"
$marketplacePath = Join-Path $marketplaceRoot ".agents\plugins\marketplace.json"
$chromePluginDest = Join-Path $pluginsRoot "chromemcp-browser"
$bashlanePluginDest = Join-Path $pluginsRoot "bashlane"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $marketplacePath) | Out-Null
New-Item -ItemType Directory -Force -Path $pluginsRoot | Out-Null

foreach ($target in @($chromePluginDest, $bashlanePluginDest)) {
  $resolvedRoot = [System.IO.Path]::GetFullPath($marketplaceRoot)
  if (Test-Path $target) {
    $resolvedTarget = [System.IO.Path]::GetFullPath($target)
    if (-not $resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to remove path outside marketplace root: $resolvedTarget"
    }
    Remove-Item -Recurse -Force -LiteralPath $resolvedTarget
  }
}

Copy-Item -Recurse -Force $chromePluginSource $chromePluginDest
Copy-Item -Recurse -Force $bashlanePluginSource $bashlanePluginDest -Exclude ".git"

foreach ($manifestPath in @(
  (Join-Path $chromePluginDest ".codex-plugin\plugin.json"),
  (Join-Path $bashlanePluginDest ".codex-plugin\plugin.json")
)) {
  $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
  $manifest.interface.category = "Rizonetech"
  [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 20) + "`n", $utf8NoBom)
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
    }
  )
}

$marketplaceJson = $marketplace | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($marketplacePath, $marketplaceJson + "`n", $utf8NoBom)

$configPath = Join-Path $CodexConfigHome "config.toml"
if (-not (Test-Path $configPath)) {
  New-Item -ItemType File -Force -Path $configPath | Out-Null
}

$config = Get-Content -Raw $configPath
$removeBlocks = @(
  '(?ms)^# ChromeMCP local Codex marketplace\.\r?\n\[marketplaces\.chromemcp-local\].*?(?=^\[|\z)',
  '(?ms)^\[marketplaces\.chromemcp-local\].*?(?=^\[|\z)',
  '(?ms)^\[plugins\."chromemcp-browser@chromemcp-local"\].*?(?=^\[|\z)',
  '(?ms)^# Bashlane local Codex marketplace\.\r?\n\[marketplaces\.bashlane-local\].*?(?=^\[|\z)',
  '(?ms)^\[marketplaces\.bashlane-local\].*?(?=^\[|\z)',
  '(?ms)^\[plugins\."bashlane@bashlane-local"\].*?(?=^\[|\z)',
  '(?ms)^# Rizonetech Codex plugin catalog\.\r?\n\[marketplaces\.rizonetech-codex-plugins\].*?(?=^\[|\z)',
  '(?ms)^\[marketplaces\.rizonetech-codex-plugins\].*?(?=^\[|\z)',
  '(?ms)^# Rizonetech local Codex marketplace\.\r?\n\[marketplaces\.rizonetech-local\].*?(?=^\[|\z)',
  '(?ms)^\[marketplaces\.rizonetech-local\].*?(?=^\[|\z)',
  '(?ms)^\[plugins\."chromemcp-browser@rizonetech-local"\].*?(?=^\[|\z)',
  '(?ms)^\[plugins\."bashlane@rizonetech-local"\].*?(?=^\[|\z)'
)

foreach ($pattern in $removeBlocks) {
  $config = [regex]::Replace($config, $pattern, "")
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
"@

[System.IO.File]::WriteAllText($configPath, $config.TrimEnd() + $block + "`r`n", $utf8NoBom)

if (-not $KeepOldLocalMarketplaces) {
  foreach ($old in @(
    (Join-Path $CodexPluginHome "plugins\chromemcp-local"),
    (Join-Path $CodexPluginHome "plugins\bashlane-local")
  )) {
    if (Test-Path $old) {
      $resolvedOld = [System.IO.Path]::GetFullPath($old)
      $resolvedPlugins = [System.IO.Path]::GetFullPath((Join-Path $CodexPluginHome "plugins"))
      if (-not $resolvedOld.StartsWith($resolvedPlugins, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside Codex plugins root: $resolvedOld"
      }
      Remove-Item -Recurse -Force -LiteralPath $resolvedOld
      Write-Host "Removed old local marketplace: $resolvedOld"
    }
  }
}

Write-Host "Installed Rizonetech local marketplace: $marketplaceRoot"
Write-Host "Updated Codex config: $configPath"
