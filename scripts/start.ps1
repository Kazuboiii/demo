# Start HOMS on the laptop and advertise it to phones on the local network.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtime = Join-Path $root ".runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$python = Join-Path $root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) { throw "Install the root Python environment first (see README)." }
function Test-ProcessAlive($pidFile) {
    if (!(Test-Path -LiteralPath $pidFile)) { return $false }
    $storedPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($pid -eq $null -or $pid -eq "") { return $false }
    try {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        return $proc -ne $null
    } catch {
        return $false
    }
}
function Get-ExistingListenerPort($port, $udp) {
    if ($udp) {
        $ep = Get-NetUDPEndpoint -LocalPort $port -ErrorAction SilentlyContinue
        return if ($ep) { $true } else { $false }
    } else {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        return if ($conn) { $true } else { $false }
    }
}
function Start-HomsService($name, $program, $arguments, $directory, $port, $udp = $false) {
    $pidFile = Join-Path $runtime "$name.pid"
    if (Test-ProcessAlive $pidFile) {
        Write-Host "$name already running (pid $(Get-Content -LiteralPath $pidFile))"
        return
    }
    if (Get-ExistingListenerPort $port $udp) { Write-Host "$name already listening on port $port"; return }
    $process = Start-Process -FilePath $program -ArgumentList $arguments -WorkingDirectory $directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$name.log") -RedirectStandardError (Join-Path $runtime "$name.error.log")
    $process.Id | Set-Content -Path $pidFile
}
Start-HomsService "backend" $python @("manage.py", "runserver", "0.0.0.0:8000", "--noreload") (Join-Path $root "backend") 8000
Start-HomsService "discovery" $python @("discovery_supervisor.py") $PSScriptRoot 45873 $true -RedirectStandardOutput (Join-Path $runtime "discovery-supervisor.log") -RedirectStandardError (Join-Path $runtime "discovery-supervisor.error.log")
Start-HomsService "frontend" (Get-Command node.exe).Source @("node_modules/next/dist/bin/next", "dev", "--hostname", "0.0.0.0", "--port", "3000") (Join-Path $root "frontend") 3000
Write-Host "Application: http://localhost:3000"
Write-Host "Admin panel: http://localhost:8000/admin/"
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } | ForEach-Object { Write-Host "Phone browser: http://$($_.IPAddress):3000" }
Write-Host "Installed Android app: connect to the same Wi-Fi, then sign in. No API URL needed."
Write-Host "If Windows blocks LAN access, run scripts/enable-lan.ps1 once as Administrator."
Write-Host "Logs: $runtime"
