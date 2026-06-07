#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

# 1. Write .wslconfig (mirrored networking, prevent VM shutdown)
$wslConfig = @'
[wsl2]
networkingMode=mirrored
vmIdleTimeout=-1
memory=24GB

[general]
instanceIdleTimeout=-1
'@
Set-Content -Path "$env:USERPROFILE\.wslconfig" -Value $wslConfig -Encoding UTF8

# 2. Enable systemd in WSL2
wsl -d Ubuntu -- bash -c 'grep -q "systemd=true" /etc/wsl.conf 2>/dev/null || echo -e "[boot]\nsystemd=true" | sudo tee /etc/wsl.conf'

# 3. Restart WSL to apply .wslconfig and wsl.conf
Write-Host "Restarting WSL..."
wsl --shutdown
do { Start-Sleep -Seconds 1 } while ((wsl --list --running 2>$null | Out-String) -match 'Ubuntu')
wsl -d Ubuntu -- echo "WSL restarted with new configuration"

# 4. Install and enable SSH server in WSL2
Write-Host "Installing SSH server in WSL2..."
wsl -d Ubuntu -- bash -c 'sudo apt-get update && sudo apt-get install -y openssh-server && sudo systemctl enable ssh && sudo systemctl start ssh'

# 5. Create Hyper-V firewall rules for inbound traffic
Write-Host "Configuring Hyper-V firewall rules..."
$ports = @(
    @{Name="WSL-SSH"; Port=22},
    @{Name="WSL-Traefik-HTTP"; Port=80},
    @{Name="WSL-Traefik-HTTPS"; Port=443},
    @{Name="WSL-TabbyAPI"; Port=5000}
)
foreach ($p in $ports) {
    Remove-NetFirewallHyperVRule -Name $p.Name -ErrorAction SilentlyContinue
    New-NetFirewallHyperVRule -Name $p.Name -DisplayName $p.Name `
        -Direction Inbound `
        -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' `
        -Protocol TCP -LocalPorts $p.Port
}

# 6. Create scheduled task to start WSL on Windows boot (before user login)
Write-Host "Creating WSL boot task..."
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu --exec /bin/true"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "WSL Boot" -Action $action -Trigger $trigger -Principal $principal -Force

# 7. Verify GPU passthrough
Write-Host "`nVerifying GPU access in WSL2..."
wsl -d Ubuntu -- nvidia-smi
