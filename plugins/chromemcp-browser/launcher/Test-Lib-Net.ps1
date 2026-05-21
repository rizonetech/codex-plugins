#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Unit tests for Lib-Net.ps1. Pure-function tests — no admin needed.

.DESCRIPTION
    Run from Windows PowerShell or PowerShell Core (pwsh on Linux). Exits
    non-zero on any failure. Used to validate Get-IPv4Subnet so the
    firewall rule's RemoteAddress stays correct across Microsoft's
    occasional WSL2 subnet allocation changes.

.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File launcher/Test-Lib-Net.ps1
    pwsh -File launcher/Test-Lib-Net.ps1
#>
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Lib-Net.ps1"

# Each case: a name, an IP somewhere within the network, a prefix, and
# the network address we expect Get-IPv4Subnet to return.
$cases = @(
    @{ Name = 'WSL2 default /20 anchored low';     IP = '172.28.112.5';   Prefix = 20; Expected = '172.28.112.0/20' },
    @{ Name = '/20 from non-zero offset';          IP = '172.28.115.42';  Prefix = 20; Expected = '172.28.112.0/20' },
    @{ Name = '/24 narrow';                        IP = '172.28.112.5';   Prefix = 24; Expected = '172.28.112.0/24' },
    @{ Name = '/16 wide';                          IP = '192.168.1.10';   Prefix = 16; Expected = '192.168.0.0/16' },
    @{ Name = '/8 even wider (class A)';           IP = '10.5.6.7';       Prefix = 8;  Expected = '10.0.0.0/8' },
    @{ Name = '/12 (RFC1918 lower bound)';         IP = '172.16.5.10';    Prefix = 12; Expected = '172.16.0.0/12' },
    @{ Name = '/12 from offset within block';      IP = '172.31.255.254'; Prefix = 12; Expected = '172.16.0.0/12' },
    @{ Name = '/22 (mid-octet boundary)';          IP = '172.28.113.5';   Prefix = 22; Expected = '172.28.112.0/22' },
    @{ Name = '/30 (point-to-point)';              IP = '10.0.0.5';       Prefix = 30; Expected = '10.0.0.4/30' },
    @{ Name = '/32 (single host)';                 IP = '127.0.0.1';      Prefix = 32; Expected = '127.0.0.1/32' },
    @{ Name = '/0 (everything)';                   IP = '8.8.8.8';        Prefix = 0;  Expected = '0.0.0.0/0' },
    @{ Name = 'WSL2 /28 hypothetical';             IP = '172.28.112.5';   Prefix = 28; Expected = '172.28.112.0/28' },
    @{ Name = 'WSL2 /16 hypothetical (Microsoft could go this way)';
                                                   IP = '172.28.112.5';   Prefix = 16; Expected = '172.28.0.0/16' }
)
$pass = 0; $fail = 0; $failedNames = @()
foreach ($c in $cases) {
    $got = Get-IPv4Subnet -IPAddress $c.IP -PrefixLength $c.Prefix
    if ($got -eq $c.Expected) {
        $pass++
        Write-Host ("PASS  {0,-50} {1}/{2} -> {3}" -f $c.Name, $c.IP, $c.Prefix, $got)
    } else {
        $fail++; $failedNames += $c.Name
        Write-Host ("FAIL  {0,-50} {1}/{2}: got '{3}', expected '{4}'" -f $c.Name, $c.IP, $c.Prefix, $got, $c.Expected)
    }
}

# Negative tests — bad prefix lengths and bad IPs must throw.
foreach ($bad in @(33, -1, 64)) {
    try {
        Get-IPv4Subnet -IPAddress '172.28.112.5' -PrefixLength $bad | Out-Null
        Write-Host "FAIL  prefix=$bad did not throw"
        $fail++; $failedNames += "prefix=$bad"
    } catch {
        Write-Host "PASS  prefix=$bad correctly throws"
        $pass++
    }
}
foreach ($badIp in @('not.an.ip', '1.2.3', '::1')) {
    try {
        Get-IPv4Subnet -IPAddress $badIp -PrefixLength 20 | Out-Null
        Write-Host "FAIL  IPAddress='$badIp' did not throw"
        $fail++; $failedNames += "ip=$badIp"
    } catch {
        Write-Host "PASS  IPAddress='$badIp' correctly throws"
        $pass++
    }
}

Write-Host ""
Write-Host "================================"
Write-Host "PASS: $pass"
Write-Host "FAIL: $fail"
if ($fail -gt 0) {
    Write-Host "Failed: $($failedNames -join ', ')"
    exit 1
}
Write-Host "All subnet tests passed."
exit 0
