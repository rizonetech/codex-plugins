param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Command
)

$ErrorActionPreference = "Stop"

function Convert-ToWslPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WindowsPath
    )

    $resolvedPath = (Resolve-Path -LiteralPath $WindowsPath).Path
    $resolvedPath = $resolvedPath -replace "^Microsoft\.PowerShell\.Core\\FileSystem::", ""

    if ($resolvedPath -match "^\\\\wsl(?:\.localhost|\$)\\[^\\]+(\\.*)?$") {
        $linuxPath = $Matches[1]
        if ([string]::IsNullOrEmpty($linuxPath)) {
            return "/"
        }

        return ($linuxPath -replace "\\", "/")
    }

    if ($resolvedPath -match "^([A-Za-z]):(.*)$") {
        $drive = $Matches[1].ToLowerInvariant()
        $pathWithoutDrive = $Matches[2] -replace "\\", "/"
        return "/mnt/$drive$pathWithoutDrive"
    }

    throw "Cannot convert path to WSL path: $resolvedPath"
}

$commandText = $Command -join " "
$wslCwd = Convert-ToWslPath -WindowsPath (Get-Location).Path

wsl.exe --cd $wslCwd -- bash -lc $commandText
exit $LASTEXITCODE
