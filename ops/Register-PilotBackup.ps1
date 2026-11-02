param([ValidatePattern('^[a-zA-Z0-9_.-]+$')][string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$taskName = 'GoldenStock - daily encrypted backup'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'A task with this name exists. Review it in Task Scheduler.'
}
$runner = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'nightly-backup.sh')).Path
$linuxPath = (& wsl.exe -d $Distribution -- wslpath -u $runner)
if ($LASTEXITCODE -ne 0 -or $linuxPath -notmatch '^/' -or $linuxPath -match '["\r\n]') {
    throw 'Could not obtain the WSL path of the backup runner.'
}
$action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\wsl.exe') -Argument ('-d {0} -- /bin/sh "{1}"' -f $Distribution,$linuxPath)
$trigger = New-ScheduledTaskTrigger -Daily -At '02:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal
