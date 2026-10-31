powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetConnectionProfile -InterfaceAlias 'Wi-Fi' | Set-NetConnectionProfile -NetworkCategory Private"
