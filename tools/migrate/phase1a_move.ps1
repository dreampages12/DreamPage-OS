# Fase 1a - doep om C:\ComfyUI til C:\DreamPage-OS\DreamPage-image.
#
# MAA KJOERES SOM ADMINISTRATOR, og fra et vindu som IKKE staar i C:\ComfyUI.
# Grunnen til at dette er et eget skript og ikke gjort av agenten: ComfyUI ble
# startet elevert, saa en ikke-elevert prosess kan ikke stoppe den, og en
# katalog kan ikke doepes om saa lenge noen har den som arbeidsmappe.
#
# Skriptet gjoer BARE det som krever elevering:
#   stopp prosessene -> flytt treet -> lag junction -> start ComfyUI igjen
# Resten av fase 1 (stirettinger i vaar kode, i n8n og i custom_nodes) skjer
# etterpaa og trenger ingen rettigheter.
#
# Trygghetsnett: `mklink /J C:\ComfyUI <ny sti>` rett etter flyttingen. Da
# fortsetter alle de 175 hardkodede stiene aa virke mens de ryddes. Junctionen
# fjernes helt til slutt (fase 1b) - saa lenge den finnes vet vi ikke om
# inventaret er komplett.
#
# Flyttingen er en NTFS-rename paa samme volum: metadata, ikke kopiering. Den
# er atomisk - enten skjer den, eller ingenting skjer. Det er ogsaa grunnen til
# at det ikke finnes noen halvveis tilstand aa rulle tilbake fra.
#
#   powershell -ExecutionPolicy Bypass -File C:\DreamPage-OS\tools\migrate\phase1a_move.ps1
#   ... og -WhatIf for aa bare se forhaandssjekkene:
#   powershell -ExecutionPolicy Bypass -File ...\phase1a_move.ps1 -WhatIf
[CmdletBinding()]
param(
    [switch]$WhatIf,
    # Sett denne hvis du vil kjoere videre selv om en forhaandssjekk klager.
    # Ikke bruk den uten aa ha lest hva den klaget paa.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$OLD = 'C:\ComfyUI'
$NEW = 'C:\DreamPage-OS\DreamPage-image'
$LOG = 'C:\DreamPage-OS\state\phase1a.log'

function Note($msg, $color = 'Gray') {
    $line = "$((Get-Date).ToString('s'))  $msg"
    Write-Host $line -ForegroundColor $color
    try { New-Item -ItemType Directory -Path (Split-Path $LOG) -Force | Out-Null
          Add-Content -Path $LOG -Value $line -Encoding utf8 } catch {}
}
function Fail($msg) { Note "STOPP: $msg" Red; exit 1 }

# Start ComfyUI fra $root. Argumentene er hentet fra den kjorende prosessen
# foer flyttingen (/system_stats -> system.argv), ikke gjettet:
#   main.py --listen 0.0.0.0 --port 8188 --disable-auto-launch
function Start-Comfy($root) {
    $py = 'C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe'
    if (-not (Test-Path $py)) { Note "fant ikke python: $py" Red; return $false }
    Start-Process -FilePath $py `
        -ArgumentList "$root\main.py", '--listen', '0.0.0.0', '--port', '8188', '--disable-auto-launch' `
        -WorkingDirectory $root -WindowStyle Minimized
    Note "startet ComfyUI fra $root - venter paa svar..."
    for ($i = 1; $i -le 60; $i++) {
        Start-Sleep -Seconds 5
        try {
            $s = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 5
            Note "ComfyUI $($s.system.comfyui_version) svarer etter $($i*5) s" Green
            Note "    argv: $($s.system.argv -join ' ')"
            return $true
        } catch { }
    }
    Note 'ComfyUI svarte ikke innen 5 minutter. Se loggen:' Red
    Note "    $root\user\comfyui_8188.log" Red
    return $false
}

Note '=== fase 1a: navnebytte ===' Cyan

# --------------------------------------------------------------------------
# 0. Forutsetninger
# --------------------------------------------------------------------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail 'ikke elevert. Hoyreklikk PowerShell -> "Kjor som administrator".'
}
if ((Get-Location).Path -like "$OLD*") {
    Fail "dette vinduet staar i $OLD. En katalog kan ikke doepes om mens den er arbeidsmappe. Kjor `Set-Location C:\` forst."
}
if (-not (Test-Path $OLD)) {
    if ((Get-Item $NEW -ErrorAction SilentlyContinue)) { Note 'allerede flyttet - ingenting aa gjoere' Green; exit 0 }
    Fail "$OLD finnes ikke"
}
if (Test-Path $NEW) { Fail "$NEW finnes allerede - rydd den bort foerst" }
if ((Get-Item $OLD).LinkType) { Fail "$OLD er allerede en lenke, ikke en katalog" }

# Samme volum? Ellers blir dette en kopiering av 335 GB, og det er det ikke
# plass til (185 GB ledig).
if ($OLD[0] -ne $NEW[0]) { Fail 'kilde og maal er paa ulike volum - dette maa vaere en rename' }

# --------------------------------------------------------------------------
# 1. Kjorer det en ordre naa?
#
# Aa flytte treet midt i en ordre dreper den. Tre uavhengige kilder sjekkes:
# laasefila, ComfyUI-koen og n8n sine uferdige executions.
# --------------------------------------------------------------------------
Note '--- forhaandssjekk: kjorer det en ordre? ---' Cyan

$lock = Join-Path $OLD '.dreampage-comfy.lock'
if (Test-Path $lock) {
    Note "laasefila finnes: $lock" Yellow
    Get-Content $lock | ForEach-Object { Note "    $_" Yellow }
    if (-not $Force) { Fail 'en ordre holder ComfyUI-laasen. Vent til den er ferdig, eller bruk -Force hvis laasen er dod.' }
}

try {
    $q = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/queue' -TimeoutSec 10
    $running = @($q.queue_running).Count
    $pending = @($q.queue_pending).Count
    Note "ComfyUI-koen: $running kjorer, $pending venter"
    if (($running + $pending) -gt 0 -and -not $Force) { Fail 'ComfyUI har jobber i koen' }
} catch { Note 'ComfyUI svarer ikke paa 8188 (allerede stoppet?)' Yellow }

$n8ndb = "$env:USERPROFILE\.n8n\database.sqlite"
if (Test-Path $n8ndb) {
    # n8n holder databasen aapen, saa vi leser read-only gjennom python.
    $py = 'C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe'
    if (Test-Path $py) {
        $code = @'
import sqlite3, os, sys
db = os.path.expanduser(r"~/.n8n/database.sqlite")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
n = con.execute("select count(*) from execution_entity where stoppedAt is null").fetchone()[0]
print(n)
'@
        $n = (& $py -c $code 2>$null)
        Note "n8n uferdige executions: $n"
        if ([int]$n -gt 0 -and -not $Force) { Fail 'n8n har en execution som kjorer' }
    }
}

if ($WhatIf) { Note 'WhatIf - stopper her, ingenting endret' Green; exit 0 }

# --------------------------------------------------------------------------
# 2. Stopp det som holder mappa
#
# n8n stoppes IKKE: databasen ligger i ~\.n8n, utenfor treet, og en jobb som
# kommer paa RabbitMQ mens vi jobber blir liggende i koen - der er den trygg.
# Agenten deaktiverer worker-workflowen foer dette skriptet kjoeres, saa det
# ikke finnes noen konsument i det hele tatt.
# --------------------------------------------------------------------------
Note '--- stopper prosesser ---' Cyan

# Vaktmesteren starter boten igjen hvert 5. minutt. Skru den av foerst, ellers
# kommer boten tilbake midt i flyttingen og tar nye handles.
try {
    Disable-ScheduledTask -TaskName 'DreamPage dp_bot' -ErrorAction Stop | Out-Null
    Note 'scheduled task "DreamPage dp_bot" deaktivert'
} catch { Note "kunne ikke deaktivere scheduled task: $($_.Exception.Message)" Yellow }

$targets = @(
    @{ Name = 'dp_bot';        Match = 'dp_bot\.py' },
    @{ Name = 'mockup-server'; Match = 'dp-mockup-server' },
    @{ Name = 'ComfyUI';       Match = 'ComfyUI\\main\.py|ComfyUI/main\.py' }
)
foreach ($t in $targets) {
    $procs = Get-CimInstance Win32_Process |
             Where-Object { $_.CommandLine -match $t.Match }
    if (-not $procs) { Note "$($t.Name): kjorer ikke"; continue }
    foreach ($p in $procs) {
        Note "$($t.Name): stopper pid $($p.ProcessId)"
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop }
        catch { Note "  kunne ikke stoppe pid $($p.ProcessId): $($_.Exception.Message)" Yellow }
    }
}
Start-Sleep -Seconds 4

# --------------------------------------------------------------------------
# 3. Flytt
#
# Med retry: Windows slipper handles litt etter at prosessen er dod, og en
# virusskanner eller Explorer-forhaandsvisning kan holde mappa et oeyeblikk.
# --------------------------------------------------------------------------
Note '--- flytter treet ---' Cyan
$moved = $false
for ($i = 1; $i -le 6; $i++) {
    try {
        Move-Item -LiteralPath $OLD -Destination $NEW -ErrorAction Stop
        $moved = $true
        Note "flyttet: $OLD -> $NEW (forsok $i)" Green
        break
    } catch {
        Note "forsok $i blokkert: $($_.Exception.Message)" Yellow
        Start-Sleep -Seconds 5
    }
}
if (-not $moved) {
    Note 'kunne ikke flytte. Noe holder fortsatt mappa.' Red
    Note 'Finn ut hva med en av disse:' Yellow
    Note '   openfiles /query /fo table   (krever at "openfiles /local on" er skrudd paa + omstart)' Yellow
    Note '   handle64.exe C:\ComfyUI      (Sysinternals)' Yellow
    Note 'Vanlige syndere: et terminalvindu som staar i C:\ComfyUI, Utforsker,' Yellow
    Note 'VS Code, en python-prosess fra en custom node, eller OneDrive.' Yellow
    Note 'Treet staar der det stod - ingenting er flyttet.' Yellow
    Note 'Setter produksjonen tilbake i drift paa gammel sti:' Yellow
    [void](Start-Comfy $OLD)
    Enable-ScheduledTask -TaskName 'DreamPage dp_bot' -ErrorAction SilentlyContinue | Out-Null
    Note 'scheduled task reaktivert - den starter dp_bot innen 5 minutter' Yellow
    Note 'Kjor skriptet paa nytt naar synderen er borte.' Yellow
    exit 1
}

# --------------------------------------------------------------------------
# 4. Trygghetsnett: junction paa den gamle stien
#
# Fra naa av virker BAADE C:\ComfyUI\... og C:\DreamPage-OS\DreamPage-image\...
# Det er meningen: de 175 hardkodede stiene, de 24 n8n-nodene og de to
# custom_nodes-ini-filene ryddes i ro etterpaa. Junctionen fjernes i fase 1b.
# --------------------------------------------------------------------------
Note '--- lager junction som trygghetsnett ---' Cyan
& cmd.exe /c mklink /J "$OLD" "$NEW" | ForEach-Object { Note "    $_" }
if (-not (Test-Path (Join-Path $OLD 'main.py'))) {
    Note 'ADVARSEL: junctionen virker ikke. Gammel sti er DOD.' Red
    Note "Lag den for haand: mklink /J `"$OLD`" `"$NEW`"" Red
} else {
    Note 'junction OK - gammel sti virker fortsatt' Green
}

# --------------------------------------------------------------------------
# 5. Start ComfyUI igjen, fra den nye stien
#
# --input-directory/--output-directory settes IKKE her. De hoerer til steget
# der input/, output/ og models/ flyttes ut paa rota, og det gjoeres etter at
# denne kjoringen er verifisert - ett steg om gangen.
# --------------------------------------------------------------------------
Note '--- starter ComfyUI fra ny sti ---' Cyan
[void](Start-Comfy $NEW)

Note ''
Note '=== fase 1a ferdig ===' Cyan
Note "treet ligger naa i  $NEW"
Note "gammel sti virker via junction:  $OLD"
Note ''
Note 'NESTE (trenger ikke elevering - agenten gjoer det):' Yellow
Note '  * flytt books/, config/, server/, state/, tmp/, input/, output/, models/' Yellow
Note '    og dreampage-headswap/ ut paa DreamPage-OS-rota' Yellow
Note '  * rett stier i vaar kode, i de 24 n8n-nodene og i de to custom_nodes-ini-filene' Yellow
Note '  * lag custom_nodes-junctionen til headswap paa nytt' Yellow
Note '  * start mockup-serveren og dp_bot, og reaktiver scheduled task + n8n-workflowen' Yellow
Note '  * kjor en ekte ordre. Deretter fase 1b: fjern junctionen og kjor en ordre til.' Yellow
