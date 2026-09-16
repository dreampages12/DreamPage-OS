# De to siste tingene som krever administrator. Alt annet er gjort.
#
# Startes fra en vanlig PowerShell (gir UAC-dialog):
#
#   Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile',
#     '-ExecutionPolicy','Bypass','-File','C:\DreamPage-OS\tools\finish_elevated.ps1'
#
# Begge prosessene under ble startet ELEVERT, og en medium-integritets prosess
# kan ikke terminere en elevert. Det er en sikkerhetsgrense i Windows, ikke en
# manglende rettighet vi kan omgaa - derfor maa nettopp dette gjores av deg.
#
#   1. Den GAMLE ComfyUI paa port 8188 (pid var 13004 16.09.2026).
#      Den ser NULL modeller: modellmappa den ble startet med finnes ikke
#      lenger. Den svarer likevel paa HTTP, og det er hele faren - en naiv
#      helsesjekk mot 8188 sier "ok" mens ingen bokside kan bygges. Vaar egen
#      kjoerer paa 8189 og har modellene; flow nekter feil instans via
#      comfy.identity(). Den gamle holder ~1 GB CUDA-kontekst i tillegg.
#
#   2. Den GAMLE mockup-serveren paa 8790 (pid var 1808), som kjoerer fra
#      C:\ComfyUI\server. Den VIRKER, men fra en mappe som skal slettes. Den
#      nye kopien i C:\DreamPage-OS\server\dp-mockup-server er verifisert:
#      npm-pakkene er installert, og en fersk render (cache av) ga et bilde
#      som er PIKSELIDENTISK med det den gamle lager.
#
# Skriptet STARTER INGENTING. Det er med vilje: en tjeneste startet elevert er
# nettopp det som skapte dette problemet. Oppstarten gjores etterpaa av
# dreampage.ps1 ensure, UTEN elevering.
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
    Say 'Start paa nytt med -Verb RunAs, se toppen av denne fila.' Yellow
    Start-Sleep -Seconds 15
    exit 1
}

Say '=== siste elevette opprydding ===' Cyan
$me = $PID

# ---------------------------------------------------------------------------
# 1. Gammel ComfyUI paa 8188
#
# Identifiseres paa PORTEN, ikke paa navnet: elevert kommandolinje er ikke
# lesbar fra en vanlig prosess, men den ER lesbar herfra - saa vi bruker den
# til aa BEKREFTE at vi tar riktig prosess foer vi dreper noe.
# ---------------------------------------------------------------------------
Say ''
Say '--- port 8188: gammel ComfyUI ---' Cyan
$c = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue
if (-not $c) {
    Say '  8188 er alt ledig - ingenting aa gjore' Green
} else {
    $procId = $c[0].OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    $cmd = if ($proc.CommandLine) { $proc.CommandLine } else { '(ukjent)' }
    Say "  pid $procId"
    Say "  kommandolinje: $cmd"

    if ($procId -eq $me) {
        Say '  NEKTER: det er meg selv' Red
    } elseif ($cmd -like '*DreamPage-image*') {
        # Skulle noen ha flyttet VAAR instans til 8188, skal den staa.
        Say '  NEKTER: dette ER DreamPage-image. Roerer den ikke.' Yellow
    } elseif ($cmd -notlike '*main.py*' -and $cmd -ne '(ukjent)') {
        Say '  NEKTER: ser ikke ut som en ComfyUI. Sjekk manuelt.' Yellow
    } else {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Say '  STOPPET' Green
        } catch { Say "  KUNNE IKKE: $($_.Exception.Message)" Red }
    }
}

# ---------------------------------------------------------------------------
# 2. Gammel mockup-server paa 8790
# ---------------------------------------------------------------------------
Say ''
Say '--- port 8790: gammel mockup-server ---' Cyan
$m = Get-NetTCPConnection -LocalPort 8790 -State Listen -ErrorAction SilentlyContinue
if (-not $m) {
    Say '  8790 er ledig' Green
} else {
    $procId = $m[0].OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    $cmd = if ($proc.CommandLine) { $proc.CommandLine } else { '(ukjent)' }
    Say "  pid $procId"
    Say "  kommandolinje: $cmd"
    if ($cmd -like '*DreamPage-OS*') {
        Say '  NEKTER: dette er alt den NYE. Roerer den ikke.' Yellow
    } elseif ($procId -eq $me) {
        Say '  NEKTER: det er meg selv' Red
    } else {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Say '  STOPPET' Green
        } catch { Say "  KUNNE IKKE: $($_.Exception.Message)" Red }
    }
}

Start-Sleep -Seconds 4
Say ''
foreach ($port in 8188, 8790) {
    $x = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    Say ("  port {0}: {1}" -f $port, $(if ($x) { "FORTSATT OPPE pid=$($x[0].OwningProcess)" } else { 'ledig' })) `
        $(if ($x) { 'Red' } else { 'Green' })
}

Say ''
Say '=== ferdig. Startet ingenting. ===' Cyan
Say 'Kjor naa, UTEN elevering, i en vanlig PowerShell:' Yellow
Say '    cd C:\DreamPage-OS' Yellow
Say '    .\dreampage.ps1 ensure' Yellow
Say '' Yellow
Say 'Den starter den NYE mockup-serveren paa 8790 fra DreamPage-OS.' Yellow
Say 'ComfyUI blir staaende paa 8189 - se config/flow.json for hvorfor' Yellow
Say '8189 er den permanente porten, ikke en midlertidig omvei.' Yellow
Say ''
Say 'Vinduet lukkes om 30 sekunder.'
Start-Sleep -Seconds 30
