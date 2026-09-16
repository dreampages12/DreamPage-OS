# Fase 1c - siste halvdel av overgangen.
#
# Kjoeres NAAR den gamle, elevette ComfyUI-prosessen er stoppet. Alt annet er
# alt gjort av phase1_build_image.ps1 og de trinnene som ikke krevde
# elevering:
#
#   [x] DreamPage-image bygget og verifisert paa port 8189
#   [x] worker-workflowen xy8qiRUzcBpH52CI deaktivert (n8n lever som webhook)
#   [x] dp_bot stoppet, scheduled task deaktivert
#   [x] state/, books/*/orders/ og headswap-treningsdata flyttet
#   [x] stiene i vaar kode rettet
#   [ ] models/ input/ output/ tmp/  <- dette skriptet
#
# Trenger IKKE elevering selv, saa lenge ComfyUI er nede.
#
#   powershell -ExecutionPolicy Bypass -File tools\migrate\phase1_finish.ps1
[CmdletBinding()]
param([switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$OLD = 'C:\ComfyUI'
$ROOT = 'C:\DreamPage-OS'
$PY = 'C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe'
$LOG = Join-Path $ROOT 'state\cutover.log'

function Say($m, $c = 'Gray') {
    $line = "$((Get-Date).ToString('s'))  $m"
    Write-Host $line -ForegroundColor $c
    try { Add-Content $LOG $line -Encoding utf8 } catch {}
}
function Head($m) { Write-Host ''; Say "=== $m ===" Cyan }
function Fail($m) { Say "STOPP: $m" Red; exit 1 }

Head 'fase 1c: fullfoer overgangen'

# ---------------------------------------------------------------------------
# 0. Er ComfyUI virkelig nede?
#
# Flytter vi models/ mens den kjoerer, feiler Move-Item midt i - eller, verre,
# lykkes den mens ComfyUI har filhandles og etterlater en instans som leser
# fra et sted som ikke finnes lenger.
# ---------------------------------------------------------------------------
$comfy = @(Get-CimInstance Win32_Process -EA SilentlyContinue |
           Where-Object { $_.CommandLine -and $_.CommandLine -match 'ComfyUI[\\/]main\.py' })
if ($comfy) {
    Say "ComfyUI kjoerer fortsatt: pid $($comfy.ProcessId -join ', ')" Red
    Fail 'stopp den foerst, fra en PowerShell som administrator: Stop-Process -Id <pid> -Force'
}
Say 'ComfyUI er nede'

$lock = Join-Path $OLD '.dreampage-comfy.lock'
if (Test-Path $lock) { Say "MERK: gammel laasefil finnes ($lock) - den er doed naa" Yellow }

if ($WhatIf) {
    Head 'WhatIf'
    foreach ($d in 'models','input','output','tmp') {
        $p = Join-Path $OLD $d
        if (Test-Path $p) {
            $s = (Get-ChildItem $p -Recurse -File -Force -EA SilentlyContinue | Measure-Object Length -Sum).Sum
            Say ("  ville flyttet {0,-8} {1,8:N1} GB" -f $d, ($s/1GB))
        }
    }
    exit 0
}

# ---------------------------------------------------------------------------
# 1. Flytt de store mappene
#
# Move-Item paa samme volum er en rename: metadata, ikke kopiering. 212 GB
# tar sekunder, og det finnes ingen halvveis tilstand.
# ---------------------------------------------------------------------------
Head 'flytter models, input, output, tmp'
function MoveInto($from, $to, $label) {
    if (-not (Test-Path $from)) { Say "  $label : finnes ikke i kilden"; return }
    if (-not (Test-Path $to)) {
        Move-Item $from $to -Force
        Say "  $label : flyttet i helhet -> $to" Green
        return
    }
    $n = 0; $skip = 0
    foreach ($item in @(Get-ChildItem $from -Force)) {
        $dest = Join-Path $to $item.Name
        if (Test-Path $dest) { $skip++; continue }
        try { Move-Item $item.FullName $dest -Force -ErrorAction Stop; $n++ }
        catch { Say "      KUNNE IKKE $($item.Name): $($_.Exception.Message)" Red }
    }
    Say "  $label : $n flyttet$(if($skip){", $skip fantes alt"})" Green
}
foreach ($d in 'models', 'input', 'output', 'tmp') {
    MoveInto (Join-Path $OLD $d) (Join-Path $ROOT $d) $d
}

# ---------------------------------------------------------------------------
# 2. Modellstier
# ---------------------------------------------------------------------------
Head 'modellstier'
& $PY (Join-Path $ROOT 'tools\models.py') paths
& $PY (Join-Path $ROOT 'tools\models.py') check
if ($LASTEXITCODE -ne 0) { Fail 'modeller mangler - ikke start foer det er loest' }

# ---------------------------------------------------------------------------
# 3. Start DreamPage OS
# ---------------------------------------------------------------------------
Head 'starter DreamPage OS'
& powershell -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $ROOT 'dreampage.ps1') up -SkipModels

# ---------------------------------------------------------------------------
# 4. Kontroll
# ---------------------------------------------------------------------------
Head 'kontroll'
& $PY (Join-Path $ROOT 'tools\node_requirements.py') --check --object-info 'http://127.0.0.1:8188'
Say ("nodekrav: " + $(if ($LASTEXITCODE -eq 0) { 'OK' } else { 'SE OVER' })) `
    $(if ($LASTEXITCODE -eq 0) { 'Green' } else { 'Red' })

foreach ($d in 'models', 'input', 'output', 'state\orders', 'books') {
    $p = Join-Path $ROOT $d
    Say ("  {0,-16} {1,6} oppforinger" -f $d, @(Get-ChildItem $p -EA SilentlyContinue).Count)
}

Head 'ferdig - men ikke over'
Say 'DreamPage OS eier naa produksjonen. C:\ComfyUI staar igjen urort.' Yellow
Say '' Yellow
Say 'NESTE, i denne rekkefoelgen:' Yellow
Say '  1. Verifiser at Telegram-botten oppfoerer seg som foer.' Yellow
Say '  2. Reaktiver scheduled task:' Yellow
Say '       Enable-ScheduledTask -TaskName "DreamPage dp_bot"' Yellow
Say '     ... men rett foerst stien i den: den peker paa den gamle' Yellow
Say '     ensure_dp_bot.ps1. Se tools\migrate\fix_scheduled_task.ps1' Yellow
Say '  3. Roeykttest en RabbitMQ-jobb, og to samtidige.' Yellow
Say '  4. Foerst naar en EKTE ordre har gaatt gjennom: slett den gamle.' Yellow
Say '       Remove-Item C:\ComfyUI -Recurse -Force' Yellow
