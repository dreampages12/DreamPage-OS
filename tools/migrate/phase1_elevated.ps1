# De tre tingene som krever administrator. Alt annet er alt gjort.
#
# Startes med UAC-dialog fra en vanlig sesjon:
#   Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\DreamPage-OS\tools\migrate\phase1_elevated.ps1'
#
#   1. Stopp den gamle ComfyUI. Den ble startet elevert, saa en
#      medium-integritets prosess kan ikke terminere den - det er en
#      sikkerhetsgrense i Windows, ikke en manglende rettighet vi kan omgaa.
#      Den eier fortsatt port 8188 og ~1 GB CUDA-kontekst, og modellmappa den
#      ble startet med finnes ikke lenger.
#
#   2. Stopp den gamle mockup-serveren. Samme sak - elevert - og den kjoerer
#      fra C:\ComfyUI\server, som skal slettes.
#
#   3. Pek scheduled task "DreamPage dp_bot" paa den nye ensure_dp_bot.ps1.
#      Uten dette er boten DOED neste gang maskinen starter, og ingenting
#      sier fra. Den var doed i to doegn 12.08.2026 av noeyaktig den grunnen.
#
# Skriptet starter INGENTING. Oppstarten gjoeres etterpaa av dreampage.ps1,
# som kjoerer uten elevering - en tjeneste startet elevert er nettopp det som
# skapte dette problemet.
$ErrorActionPreference = 'Continue'
$LOG = 'C:\DreamPage-OS\state\elevated.log'

function Say($m, $c = 'Gray') {
    $line = "$((Get-Date).ToString('s'))  $m"
    Write-Host $line -ForegroundColor $c
    try { Add-Content $LOG $line -Encoding utf8 } catch {}
}

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Say 'IKKE ELEVERT - ingenting gjort.' Red
    Start-Sleep -Seconds 10
    exit 1
}

Say '=== elevert opprydding ===' Cyan

# ---------------------------------------------------------------------------
# 1 + 2: stopp de gamle, elevette prosessene
#
# Matcher paa kommandolinja, men ALDRI paa denne prosessen selv: et moenster
# som 'dp-mockup-server' finnes ogsaa i dette skriptets egen kommandolinje, og
# da dreper skriptet seg selv midt i jobben. Det skjedde.
# ---------------------------------------------------------------------------
$me = $PID
$targets = @(
    @{ Name = 'gammel ComfyUI';   Match = 'ComfyUI[\\/]main\.py' },
    @{ Name = 'gammel mockup';    Match = 'ComfyUI[\\/]server[\\/]dp-mockup-server|dp-mockup-server[\\/]src' }
)
foreach ($t in $targets) {
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $me -and $_.CommandLine -and
            $_.CommandLine -match $t.Match -and
            $_.CommandLine -notmatch 'phase1_elevated'
        })
    if (-not $procs) { Say "  $($t.Name): kjorer ikke"; continue }
    foreach ($p in $procs) {
        $cmd = if ($p.CommandLine.Length -gt 70) { $p.CommandLine.Substring(0, 70) } else { $p.CommandLine }
        Say "  $($t.Name): pid $($p.ProcessId)  $cmd"
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Say "      stoppet" Green }
        catch { Say "      KUNNE IKKE: $($_.Exception.Message)" Red }
    }
}
Start-Sleep -Seconds 5

foreach ($port in 8188, 8790) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    Say ("  port {0}: {1}" -f $port, $(if ($c) { "FORTSATT OPPE pid=$($c[0].OwningProcess)" } else { 'ledig' })) `
        $(if ($c) { 'Red' } else { 'Green' })
}

# ---------------------------------------------------------------------------
# 3: vaktmesteren
# ---------------------------------------------------------------------------
Say ''
Say '=== scheduled task ===' Cyan
$TASK = 'DreamPage dp_bot'
$NEW = 'C:\DreamPage-OS\flow\ensure_dp_bot.ps1'
if (-not (Test-Path $NEW)) {
    Say "  $NEW finnes ikke - roerer ikke tasken" Red
} else {
    try {
        $before = Get-ScheduledTask -TaskName $TASK -ErrorAction Stop
        foreach ($a in $before.Actions) { Say "  foer : $($a.Execute) $($a.Arguments)" }
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$NEW`""
        Set-ScheduledTask -TaskName $TASK -Action $action | Out-Null
        Enable-ScheduledTask -TaskName $TASK | Out-Null
        $after = Get-ScheduledTask -TaskName $TASK
        foreach ($a in $after.Actions) { Say "  etter: $($a.Execute) $($a.Arguments)" Green }
        Say "  state: $($after.State)" Green
    } catch {
        Say "  FEIL: $($_.Exception.Message)" Red
    }
}

Say ''
Say '=== ferdig ===' Cyan
Say 'Startet ingenting. Kjor deretter, UTEN elevering:' Yellow
Say '  .\dreampage.ps1 restart' Yellow
Say ''
Say 'Vinduet lukkes om 20 sekunder.'
Start-Sleep -Seconds 20
