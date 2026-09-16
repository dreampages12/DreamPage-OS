# Pek scheduled task "DreamPage dp_bot" paa den nye stien.
#
# Vaktmesteren kjoerer hvert 5. minutt og ved innlogging, og starter boten hvis
# den ikke lever. Etter overgangen peker den fortsatt paa
# C:\ComfyUI\script\ensure_dp_bot.ps1 - en fil som snart ikke finnes. Da
# hadde boten vaert doed neste gang maskinen ble startet, og ingenting ville
# sagt fra. Boten var doed i to doegn 12.08.2026 av noeyaktig den grunnen; det
# er derfor vaktmesteren finnes i det hele tatt.
#
# MAA kjoeres som administrator: Set-ScheduledTask krever det.
#
#   powershell -ExecutionPolicy Bypass -File tools\migrate\fix_scheduled_task.ps1
[CmdletBinding()]
param([switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$TASK = 'DreamPage dp_bot'
$NEW = 'C:\DreamPage-OS\flow\ensure_dp_bot.ps1'

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not (Test-Path $NEW)) {
    Say "STOPP: $NEW finnes ikke" Red
    exit 1
}

try { $task = Get-ScheduledTask -TaskName $TASK -ErrorAction Stop }
catch { Say "STOPP: fant ingen scheduled task '$TASK'" Red; exit 1 }

Say "task     $TASK"
Say "state    $($task.State)"
foreach ($a in $task.Actions) { Say "naa      $($a.Execute) $($a.Arguments)" }
Say "skal bli powershell.exe ... -File `"$NEW`""

if ($WhatIf) { Say 'WhatIf - ingenting endret' Green; exit 0 }
if (-not $elevated) {
    Say 'STOPP: ikke elevert. Set-ScheduledTask krever administrator.' Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$NEW`""
Set-ScheduledTask -TaskName $TASK -Action $action | Out-Null
Enable-ScheduledTask -TaskName $TASK | Out-Null

$after = Get-ScheduledTask -TaskName $TASK
Say ''
Say "state    $($after.State)" Green
foreach ($a in $after.Actions) { Say "naa      $($a.Execute) $($a.Arguments)" Green }
Say ''
Say 'Test den med:  Start-ScheduledTask -TaskName "DreamPage dp_bot"' Yellow
Say 'Boten skal da dukke opp som en python-prosess innen noen sekunder.' Yellow
