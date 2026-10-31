# Run once as Administrator.
# Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$networkProfiles = "Any"
$rules = @(
    @{ Name = "HOMS-Local-Web"; Protocol = "TCP"; Port = "3000" },
    @{ Name = "HOMS-Local-API"; Protocol = "TCP"; Port = "8000" },
    @{ Name = "HOMS-Discovery"; Protocol = "UDP"; Port = "45873" }
)
foreach ($rule in $rules) {
    if (Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue) {
        Set-NetFirewallRule -Name $rule.Name -Profile $networkProfiles -RemoteAddress LocalSubnet
    } else {
        New-NetFirewallRule -Name $rule.Name -DisplayName $rule.Name -Direction Inbound -Action Allow -Protocol $rule.Protocol -LocalPort $rule.Port -Profile $networkProfiles -RemoteAddress LocalSubnet | Out-Null
    }
}
Write-Host "HOMS enabled for devices on the local subnet. The firewall remains enabled."
