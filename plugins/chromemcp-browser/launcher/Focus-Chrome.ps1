<#
.SYNOPSIS
    Brings the visible ChromeMCP Chrome window to the foreground.

.DESCRIPTION
    ChromeMCP is meant to be watchable. This helper is intentionally small and
    best-effort: it restores and focuses a visible chrome.exe window so MCP
    actions can be monitored by the user. It does not launch Chrome and it does
    not fail the MCP request when Windows refuses foreground activation.
#>
[CmdletBinding()]
param(
    [int]$Port = 9222
)

$ErrorActionPreference = 'Stop'

$typeName = 'ChromeMCP.NativeWindow'
if (-not ($typeName -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace ChromeMCP {
    public static class NativeWindow {
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    }
}
'@
}

$SW_RESTORE = 9

$profileNeedle = Join-Path $env:LocalAppData 'ChromeMCP\Profile'
$profileProcessIds = @(Get-CimInstance Win32_Process -Filter "name = 'chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileNeedle) } |
    ForEach-Object { [int]$_.ProcessId })

$windows = Get-Process chrome -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Sort-Object StartTime -Descending

if (-not $windows) {
    exit 0
}

# Prefer the dedicated ChromeMCP profile window. If Windows does not expose
# the command line, fall back to the newest visible Chrome window.
$window = $windows |
    Where-Object { $profileProcessIds -contains $_.Id } |
    Select-Object -First 1

if (-not $window) {
    $window = $windows | Select-Object -First 1
}

[ChromeMCP.NativeWindow]::ShowWindowAsync($window.MainWindowHandle, $SW_RESTORE) | Out-Null
[ChromeMCP.NativeWindow]::SetForegroundWindow($window.MainWindowHandle) | Out-Null
