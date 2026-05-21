<#
.SYNOPSIS
    Pure network helpers for ChromeMCP. No side effects, no admin.

.DESCRIPTION
    Functions in this file are dot-sourced by Setup-WSL-Portproxy.ps1
    (which needs them at install time) AND by Test-Lib-Net.ps1 (which
    unit-tests them). Keep this file side-effect-free.
#>

function Get-IPv4Subnet {
<#
.SYNOPSIS
    Compute the CIDR network address for an IPv4 + prefix length.

.DESCRIPTION
    Byte-wise AND of the IP and the prefix-derived mask. Returns the
    network address as "A.B.C.D/N". Does NOT depend on the IP being
    "aligned" to the prefix — works for any host within the subnet.

.PARAMETER IPAddress
    Dotted-quad IPv4 string (e.g. "172.28.112.5"). [System.Net.IPAddress]
    is used to validate.

.PARAMETER PrefixLength
    CIDR prefix length in bits, 0..32.

.EXAMPLE
    Get-IPv4Subnet -IPAddress '172.28.115.42' -PrefixLength 20
    # -> "172.28.112.0/20"
#>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$IPAddress,
        [Parameter(Mandatory)] [int]$PrefixLength
    )
    if ($PrefixLength -lt 0 -or $PrefixLength -gt 32) {
        throw "Get-IPv4Subnet: PrefixLength must be 0..32, got $PrefixLength"
    }
    # .NET's IPAddress.Parse accepts legacy short forms like '1.2.3'
    # (treated as 1.2.0.3) and even single integers. Reject anything
    # that isn't a dotted-quad so typos don't silently produce a
    # surprising network address.
    if ($IPAddress -notmatch '^\d+\.\d+\.\d+\.\d+$') {
        throw "Get-IPv4Subnet: '$IPAddress' is not a dotted-quad IPv4 address"
    }
    $parsed = [System.Net.IPAddress]::Parse($IPAddress)
    $bytes = $parsed.GetAddressBytes()
    if ($bytes.Count -ne 4) {
        throw "Get-IPv4Subnet: '$IPAddress' is not IPv4"
    }
    # Build the netmask one byte at a time. Each byte gets either:
    #   - 0xFF if the prefix still has 8+ bits left to consume,
    #   - a partial top-bits mask if 1..7 bits remain,
    #   - 0 if the prefix is exhausted.
    $mask = New-Object byte[] 4
    $rem = $PrefixLength
    for ($i = 0; $i -lt 4; $i++) {
        if ($rem -ge 8) {
            $mask[$i] = 0xFF
            $rem -= 8
        } elseif ($rem -gt 0) {
            $mask[$i] = [byte]((0xFF -shl (8 - $rem)) -band 0xFF)
            $rem = 0
        } else {
            $mask[$i] = 0
        }
    }
    $net = New-Object byte[] 4
    for ($i = 0; $i -lt 4; $i++) { $net[$i] = $bytes[$i] -band $mask[$i] }
    return "$($net -join '.')/$PrefixLength"
}
