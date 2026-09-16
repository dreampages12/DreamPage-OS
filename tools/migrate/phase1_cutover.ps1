# Fase 1b - overgangen: DreamPage OS tar over produksjonen.
#
# Foer dette har DreamPage-image blitt bygget ved siden av
# (phase1_build_image.ps1) og verifisert paa port 8189. Den gamle C:\ComfyUI
# har kjoert videre hele tiden. Naa byttes de om.
#
# Skriptet FLYTTER data, det kopierer ikke: 159 GB modeller, 51 GB output og
# 72 GB ordremapper. Det er 282 GB, og det er 185 GB ledig - en kopi er fysisk
# umulig. En flytting paa samme volum er en metadataoperasjon og tar sekunder.
#
# C:\ComfyUI SLETTES IKKE her. Den staar igjen med sitt eget tre (0,05 GB kode
# + 21,5 GB .git + venv), og slettes foerst naar en ekte ordre har gaatt
# gjennom DreamPage OS. Se slutten av skriptet.
#
#   powershell -ExecutionPolicy Bypass -File tools\migrate\phase1_cutover.ps1 -WhatIf
#   powershell -ExecutionPolicy Bypass -File tools\migrate\phase1_cutover.ps1
#
# MAA kjoeres som administrator: den gamle ComfyUI ble startet elevert, og en
# ikke-elevert prosess kan ikke stoppe den.
[CmdletBinding()]
param([switch]$WhatIf, [switch]$Force)

$ErrorActionPreference = 'Stop'
$OLD = 'C:\ComfyUI'
$ROOT = 'C:\DreamPage-OS'
$IMAGE = Join-Path $ROOT 'DreamPage-image'
$PY = 'C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe'
$LOG = Join-Path $ROOT 'state\cutover.log'

function Say($m, $c = 'Gray') {
    $line = "$((Get-Date).ToString('s'))  $m"
    Write-Host $line -ForegroundColor $c
    try { New-Item -ItemType Directory -Path (Split-Path $LOG) -Force | Out-Null
          Add-Content $LOG $line -Encoding utf8 } catch {}
}
function Head($m) { Write-Host ''; Say "=== $m ===" Cyan }
function Fail($m) { Say "STOPP: $m" Red; exit 1 }

Head 'fase 1b: overgang'

# ---------------------------------------------------------------------------
# 0. Forutsetninger
# ---------------------------------------------------------------------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator) -and -not $WhatIf) {
    Fail 'ikke elevert. Den gamle ComfyUI ble startet som administrator og kan ikke stoppes uten.'
}
if ((Get-Location).Path -like "$OLD*") {
    Fail "dette vinduet staar i $OLD. Kjor `Set-Location C:\` forst."
}
if (-not (Test-Path (Join-Path $IMAGE 'main.py'))) {
    Fail "DreamPage-image er ikke bygget. Kjor tools\migrate\phase1_build_image.ps1 forst."
}

# ---------------------------------------------------------------------------
# 1. Kjorer det en ordre?  Fire uavhengige kilder.
# ---------------------------------------------------------------------------
Head 'kjorer det en ordre?'
$busy = @()

$lock = Join-Path $OLD '.dreampage-comfy.lock'
if (Test-Path $lock) {
    $busy += "laasefila finnes: $lock"
    Get-Content $lock | ForEach-Object { Say "    $_" Yellow }
}
try {
    $q = Invoke-RestMethod 'http://127.0.0.1:8188/queue' -TimeoutSec 10
    $n = @($q.queue_running).Count + @($q.queue_pending).Count
    Say "ComfyUI-koen: $n"
    if ($n -gt 0) { $busy += "ComfyUI har $n jobber i koeen" }
} catch { Say 'ComfyUI svarer ikke paa 8188 (allerede stoppet?)' Yellow }

$code = @'
import sqlite3, os
db = os.path.expanduser(r"~/.n8n/database.sqlite")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
print(con.execute("select count(*) from execution_entity where stoppedAt is null").fetchone()[0])
'@
try {
    $running = (& $PY -c $code 2>$null).Trim()
    Say "n8n uferdige executions: $running"
    if ([int]$running -gt 0) { $busy += "n8n har $running execution(er) som kjorer" }
} catch { Say 'kunne ikke lese n8n-databasen' Yellow }

# RabbitMQ: en melding som venter er GREIT - den blir liggende trygt i koen
# mens vi jobber, og plukkes opp etterpaa. Vi rapporterer den bare.
try {
    $mq = (& $PY (Join-Path $ROOT 'tools\migrate\queue_depth.py') 2>$null).Trim()
    if ($mq) { Say "RabbitMQ dreampage-jobs: $mq melding(er) venter (blir liggende)" }
} catch {}

if ($busy.Count -and -not $Force) {
    $busy | ForEach-Object { Say "  $_" Red }
    Fail 'vent til ordren er ferdig, eller bruk -Force hvis du vet at dette er rester.'
}

if ($WhatIf) {
    Head 'WhatIf - dette ville skjedd'
    Say '  1. stopp dp_bot, mockup-server, testinstans (8189) og gammel ComfyUI'
    Say '  2. flytt models/ input/ output/ tmp/ state/ og books/*/orders/'
    Say '  3. flytt dreampage-headswap/local_data + runs (15 GB treningsdata)'
    Say '  4. regenerer config/extra_model_paths.yaml med ny base_path'
    Say '  5. start ComfyUI fra DreamPage-image paa 8188'
    Say '  6. kontroller nodeklasser og modell-lister'
    Say '  C:\ComfyUI slettes IKKE - det er et eget steg etter en ekte ordre.'
    exit 0
}

# ---------------------------------------------------------------------------
# 2. Stopp alt
# ---------------------------------------------------------------------------
Head 'stopper prosesser'
try {
    Disable-ScheduledTask -TaskName 'DreamPage dp_bot' -ErrorAction Stop | Out-Null
    Say 'scheduled task "DreamPage dp_bot" deaktivert (vaktmesteren ville ellers startet boten midt i)'
} catch { Say "kunne ikke deaktivere scheduled task: $($_.Exception.Message)" Yellow }

$targets = @(
    @{ Name = 'dp_bot';        Match = 'dp_bot\.py' },
    @{ Name = 'mockup';        Match = 'dp-mockup-server' },
    @{ Name = 'flow';          Match = 'worker[\\/]main\.py' },
    @{ Name = 'testinstans';   Match = 'DreamPage-image[\\/]main\.py' },
    @{ Name = 'gammel ComfyUI'; Match = 'ComfyUI[\\/]main\.py' }
)
foreach ($t in $targets) {
    $procs = @(Get-CimInstance Win32_Process -EA SilentlyContinue |
               Where-Object { $_.CommandLine -and $_.CommandLine -match $t.Match })
    if (-not $procs) { Say "  $($t.Name): kjorer ikke"; continue }
    foreach ($p in $procs) {
        Say "  $($t.Name): stopper pid $($p.ProcessId)"
        try { Stop-Process -Id $p.ProcessId -Force -EA Stop }
        catch { Say "    kunne ikke stoppe: $($_.Exception.Message)" Red }
    }
}
Start-Sleep -Seconds 6

# ---------------------------------------------------------------------------
# 3. Flytt data
#
# Move-Item paa samme volum er en rename: metadata, ikke kopiering. Derfor er
# 282 GB like raskt som 282 MB - og derfor er det ingen halvveis tilstand.
# ---------------------------------------------------------------------------
Head 'flytter data'
function Move-Tree($from, $to, $label) {
    if (-not (Test-Path $from)) { Say "  $label : finnes ikke i kilden"; return }
    if (Test-Path $to) {
        # Maalet finnes (f.eks. de tomme mappene dreampage.ps1 lager). Flytt
        # innholdet i stedet, saa vi ikke feiler paa en tom mappe.
        $items = @(Get-ChildItem $from -Force)
        if (-not $items) { Say "  $label : kilden er tom"; return }
        foreach ($item in $items) {
            $dest = Join-Path $to $item.Name
            if (Test-Path $dest) { Say "  $label : $($item.Name) finnes alt i maalet - hopper over" Yellow; continue }
            Move-Item $item.FullName $dest -Force
        }
        Say "  $label : innhold flyttet -> $to" Green
    } else {
        Move-Item $from $to -Force
        Say "  $label : $from -> $to" Green
    }
}

foreach ($d in 'models', 'input', 'output', 'tmp') {
    Move-Tree (Join-Path $OLD $d) (Join-Path $ROOT $d) $d
}
# state/: DreamPage-OS har alt jobs.sqlite og logger. Flytt inn resten
# (orders/, gelato_drafts/, next_cover/, reprint/) - ordrecachen er det eneste
# stedet continue_code finnes etter at n8n er borte.
Move-Tree (Join-Path $OLD 'state') (Join-Path $ROOT 'state') 'state'

# books/*/orders/ - kundeartefaktene. books/ i DreamPage-OS har definisjonene
# fra git; ordremappene kommer hit.
Head 'flytter ordremapper'
$moved = 0
Get-ChildItem (Join-Path $OLD 'books') -Directory -EA SilentlyContinue | ForEach-Object {
    $src = Join-Path $_.FullName 'orders'
    if (-not (Test-Path $src)) { return }
    $dstBook = Join-Path $ROOT "books\$($_.Name)"
    if (-not (Test-Path $dstBook)) { New-Item -ItemType Directory $dstBook -Force | Out-Null }
    Move-Tree $src (Join-Path $dstBook 'orders') "books\$($_.Name)\orders"
    $moved++
}
Say "  $moved bokmapper"

# Treningsdata til headswap-noden. 15 GB, gitignorert, men ikke noe vi kan
# lage om igjen.
Head 'headswap-treningsdata'
foreach ($d in 'local_data', 'runs') {
    Move-Tree (Join-Path $OLD "dreampage-headswap\$d") `
              (Join-Path $ROOT "nodes\dreampage-headswap\$d") "headswap/$d"
}

# ---------------------------------------------------------------------------
# 4. Modellstier
# ---------------------------------------------------------------------------
Head 'modellstier'
& $PY (Join-Path $ROOT 'tools\models.py') paths
& $PY (Join-Path $ROOT 'tools\models.py') check
if ($LASTEXITCODE -ne 0) { Say '  MODELLER MANGLER - se over foer du starter' Red }

# ---------------------------------------------------------------------------
# 5. Start
# ---------------------------------------------------------------------------
Head 'starter DreamPage OS'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ROOT 'dreampage.ps1') up -SkipModels

# ---------------------------------------------------------------------------
# 6. Kontroll
# ---------------------------------------------------------------------------
Head 'kontroll'
& $PY (Join-Path $ROOT 'tools\node_requirements.py') --check --object-info 'http://127.0.0.1:8188'
$nodesOk = ($LASTEXITCODE -eq 0)
Say ("nodekrav: " + $(if ($nodesOk) { 'OK' } else { 'SE OVER' })) $(if ($nodesOk) { 'Green' } else { 'Red' })

foreach ($d in 'models', 'input', 'output', 'state\orders', 'books') {
    $p = Join-Path $ROOT $d
    $n = @(Get-ChildItem $p -EA SilentlyContinue).Count
    Say ("  {0,-16} {1,6} oppforinger" -f $d, $n)
}

Head 'ferdig - men ikke over'
Say 'DreamPage OS eier naa produksjonen. C:\ComfyUI staar igjen urort.' Yellow
Say '' Yellow
Say 'FOER du sletter den:' Yellow
Say '  1. Kjor en EKTE ordre gjennom hele veien, og se at boka blir riktig.' Yellow
Say '  2. Sjekk at dp_bot finner ordren (den leser state\orders).' Yellow
Say '  3. Reaktiver scheduled task "DreamPage dp_bot".' Yellow
Say '' Yellow
Say 'Naar det er gjort:' Yellow
Say '  Get-ChildItem C:\ComfyUI    # skal bare vaere ComfyUI-kode, .git og venv' Yellow
Say '  Remove-Item C:\ComfyUI -Recurse -Force' Yellow
Say '' Yellow
Say 'MERK: C:\ComfyUI\venv (4,9 GB) har headswap-pakka pip-installert editable.' Yellow
Say 'Et venv kan ikke flyttes - Scripts\*.exe har stien innbakt. Trenger du det,' Yellow
Say 'lag det paa nytt:  python -m venv C:\DreamPage-OS\nodes\dreampage-headswap\.venv' Yellow
Say 'og  pip install -e C:\DreamPage-OS\nodes\dreampage-headswap' Yellow
