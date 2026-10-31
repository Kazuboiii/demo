Set-NetFirewallRule -DisplayName "HOMS-Local-Web" -Profile Any
Set-NetFirewallRule -DisplayName "HOMS-Local-API" -Profile Any
Set-NetFirewallRule -DisplayName "HOMS-Discovery" -Profile Any
Get-NetFirewallRule -DisplayName "HOMS*" | Format-Table Name,Profile,Direction,Action -AutoSize
