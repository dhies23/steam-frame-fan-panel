# dev_deploy.ps1 - push the bundle to the Frame and (re)start the service.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\dev_deploy.ps1
#   powershell ... -File tools\dev_deploy.ps1 -Action stop
#   powershell ... -File tools\dev_deploy.ps1 -Action cycle
#
# Requires an ssh host alias "frame" in %USERPROFILE%\.ssh\config.
param(
    [ValidateSet('deploy', 'stop', 'cycle', 'status')]
    [string]$Action = 'deploy',
    [string]$HostAlias = 'frame',
    [string]$SudoPassword = $env:SF_SUDO_PASS
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Dev = Join-Path $Root 'sf-fan-qam\device'
$Dest = '/home/steamos/sf-fan-qam'

# sudo needs the password on stdin; never echo it back
$Sudo = if ($SudoPassword) {
    "echo '$SudoPassword' | sudo -S -p '' "
} else {
    'sudo '
}

function Invoke-Dev([string]$Cmd) {
    & ssh -o BatchMode=yes $HostAlias $Cmd
}

switch ($Action) {
    'stop' {
        Invoke-Dev "${Sudo}systemctl stop sf-fan-qamd.service; sleep 2; systemctl is-active sf-fan-qamd.service; true"
    }
    'cycle' {
        Invoke-Dev "${Sudo}systemctl stop sf-fan-qamd.service; sleep 3; ${Sudo}systemctl start sf-fan-qamd.service; sleep 4; systemctl is-active sf-fan-qamd.service; ${Sudo}journalctl -u sf-fan-qamd.service -n 8 --no-pager"
    }
    'status' {
        Invoke-Dev "systemctl is-enabled sf-fan-qamd.service; systemctl is-active sf-fan-qamd.service; ${Sudo}journalctl -u sf-fan-qamd.service -n 15 --no-pager"
    }
    'deploy' {
        & scp -o BatchMode=yes `
            (Join-Path $Dev 'sf_fan_qam.js') `
            (Join-Path $Dev 'sf_fan_qamd.py') `
            (Join-Path $Dev 'sf-fan-qamd.service') `
            "${HostAlias}:$Dest/"
        Invoke-Dev "${Sudo}install -m 0644 $Dest/sf-fan-qamd.service /etc/systemd/system/sf-fan-qamd.service && ${Sudo}systemctl daemon-reload && ${Sudo}systemctl restart sf-fan-qamd.service && sleep 4 && systemctl is-active sf-fan-qamd.service && ${Sudo}journalctl -u sf-fan-qamd.service -n 6 --no-pager"
    }
}
