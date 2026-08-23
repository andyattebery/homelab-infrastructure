#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$wslDistribution = 'Ubuntu-24.04'

# NOT 22. Mirrored networking (below) puts this distro on the Windows host's own IP, where the
# Windows OpenSSH server already holds 22, and a Linux bind on a port Windows owns is refused.
# Must match sshd_port in ansible/host_vars/wsl-01/vars.yaml.
$sshPort = 2222

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
wsl -d "$wslDistribution" -- bash -c 'grep -q "systemd=true" /etc/wsl.conf 2>/dev/null || echo -e "[boot]\nsystemd=true" | sudo tee /etc/wsl.conf'

# 3. Restart WSL to apply .wslconfig and wsl.conf
Write-Host "Restarting WSL..."
wsl --shutdown
do { Start-Sleep -Seconds 1 } while ((wsl --list --running 2>$null | Out-String) -match "$wslDistribution")
wsl -d "$wslDistribution" -- echo "WSL restarted with new configuration"

# 4. Install SSH server in WSL2 and move it off port 22
Write-Host "Installing SSH server in WSL2..."
wsl -d "$wslDistribution" -- bash -c 'sudo apt-get update && sudo apt-get install -y openssh-server && sudo systemctl enable ssh && sudo systemctl start ssh'

# Move sshd off 22. This has to happen here and not in Ansible: the playbook cannot connect to
# the host until the host is already answering on $sshPort.
#
# ssh.socket, not sshd_config -- Ubuntu socket-activates sshd from 22.10 on, and `Port` in
# sshd_config is ignored entirely under socket activation. The bare `ListenStream=` clears the
# inherited 22; without it you get both ports and the 22 collides with Windows. The address is
# spelled out because the packaged unit's `ListenStream=22` binds [::] only and relies on
# net.ipv6.bindv6only=0 for IPv4, which does not hold here -- see LP#2080216 and the matching
# task in ansible/playbook-wsl-01.yaml, which is what keeps this file in place afterwards.
Write-Host "Moving WSL sshd to port $sshPort..."
wsl -d "$wslDistribution" -u root -- bash -c "mkdir -p /etc/systemd/system/ssh.socket.d && printf '%s\n' '[Socket]' 'ListenStream=' 'ListenStream=0.0.0.0:$sshPort' > /etc/systemd/system/ssh.socket.d/port.conf && systemctl daemon-reload && systemctl restart ssh.socket && ss -tlnp | grep :$sshPort"

# 5. Create Hyper-V firewall rules for inbound traffic
Write-Host "Configuring Hyper-V firewall rules..."
$ports = @(
    @{Name="WSL-SSH"; Port=$sshPort},
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
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $wslDistribution --exec /bin/true"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "WSL Boot" -Action $action -Trigger $trigger -Principal $principal -Force

# 7. Verify GPU passthrough
Write-Host "`nVerifying GPU access in WSL2..."
wsl -d "$wslDistribution" -- nvidia-smi
