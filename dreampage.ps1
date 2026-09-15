# DreamPage OS - én supervisor som eier alle prosessene.
#
#   .\dreampage.ps1 up        sjekk modeller, start ComfyUI, flow, mockup, bot, tunnel
#   .\dreampage.ps1 down      stopp alt vi eier (ikke midt i en ordre)
#   .\dreampage.ps1 status    hva lever, hva staar i koen, hvor er ordrene
#   .\dreampage.ps1 restart
#   .\dreampage.ps1 logs      foelg flow-loggen
#
# Bare metal og PowerShell, ikke Docker: CUDA paa Windows krever WSL2 og gir
# et lag til uten tilsvarende gevinst.
#
# ComfyUI og flow er SEPARATE prosesser som snakker HTTP. De skal ikke dele
# prosess - ComfyUI restartes jevnlig (nye custom nodes, VRAM, oppdateringer),
# og delt prosess ville gjort dagens bug permanent.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'down', 'restart', 'status', 'logs', 'models', 'test')]
    [string]$Command = 'status',

    # Hopp over modellsjekken. up bruker den selv etter foerste gang.
    [switch]$SkipModels,
    # down/restart nekter aa stoppe midt i en ordre uten denne.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot
$IMAGE = Join-Path $ROOT 'DreamPage-image'
$PY = 'C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe'
$LOGDIR = Join-Path $ROOT 'state\log'

function Say($msg, $color = 'Gray') { Write-Host $msg -ForegroundColor $color }
function Head($msg) { Write-Host "`n$msg" -ForegroundColor Cyan }

function Get-Proc($pattern) {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern }
}

function Test-Port($port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Get-Json($url, $token = $null, $timeout = 8) {
    try {
        $headers = @{}
        if ($token) { $headers['Authorization'] = "Bearer $token" }
        return Invoke-RestMethod -Uri $url -Headers $headers -TimeoutSec $timeout
    } catch { return $null }
}

function Get-ApiToken {
    $path = Join-Path $ROOT 'config\api.json'
    if (-not (Test-Path $path)) { return $null }
    try {
        $conf = Get-Content $path -Raw -Encoding utf8 | ConvertFrom-Json
        if ($conf.tokens) { return ($conf.tokens.PSObject.Properties | Select-Object -First 1).Name }
        return $conf.token
    } catch { return $null }
}

# ---------------------------------------------------------------------------
# Tjenestene, i oppstartsrekkefoelge
#
# ComfyUI foerst: flow sjekker den ved oppstart, og en worker som starter mot
# en doed ComfyUI logger bare feil i noen sekunder.
# ---------------------------------------------------------------------------
$SERVICES = @(
    @{
        Name  = 'comfyui'
        Match = 'DreamPage-image.main\.py|ComfyUI.main\.py'
        Port  = 8188
        # --output/--input/--models utenfor DreamPage-image er selve grunnen
        # til at mappa aldri maa redigeres: vi endrer ComfyUI ved aa gi den
        # andre stier, ikke ved aa endre filene dens.
        Start = {
            $args = @(
                (Join-Path $IMAGE 'main.py'),
                '--listen', '0.0.0.0', '--port', '8188', '--disable-auto-launch',
                '--output-directory', (Join-Path $ROOT 'output'),
                '--input-directory', (Join-Path $ROOT 'input'),
                '--temp-directory', (Join-Path $ROOT 'tmp\comfy')
            )
            $extra = Join-Path $ROOT 'config\extra_model_paths.yaml'
            if (Test-Path $extra) { $args += @('--extra-model-paths-config', $extra) }
            Start-Process -FilePath $PY -ArgumentList $args `
                -WorkingDirectory $IMAGE -WindowStyle Minimized
        }
        Health = { $null -ne (Get-Json 'http://127.0.0.1:8188/system_stats') }
        Wait   = 300
    },
    @{
        Name  = 'flow'
        Match = 'worker[\\/]main\.py'
        Port  = 8765
        Start = {
            $out = Join-Path $LOGDIR 'flow.out.log'
            $err = Join-Path $LOGDIR 'flow.err.log'
            New-Item -ItemType Directory -Path $LOGDIR -Force | Out-Null
            # -RedirectStandardError TOEMMER fila ved start. Ble prosessen
            # drept midt i en jobb, forsvant nettopp den tracebacken som
            # forklarte hvorfor - det skjedde 05.09.2026. Ta vare paa den.
            if ((Test-Path $err) -and (Get-Item $err).Length -gt 0) {
                Move-Item $err "$err.$((Get-Date).ToString('yyyyMMdd-HHmmss'))" -Force
                Get-ChildItem "$err.*" | Sort-Object LastWriteTime -Descending |
                    Select-Object -Skip 10 | Remove-Item -Force -ErrorAction SilentlyContinue
            }
            Start-Process -FilePath $PY `
                -ArgumentList (Join-Path $ROOT 'flow\worker\main.py') `
                -WorkingDirectory $ROOT -WindowStyle Hidden `
                -RedirectStandardOutput $out -RedirectStandardError $err
        }
        Health = {
            $token = Get-ApiToken
            if (-not $token) { return (Test-Port 8765) }
            $null -ne (Get-Json 'http://127.0.0.1:8765/api/health' $token)
        }
        Wait   = 60
    },
    @{
        Name  = 'mockup'
        Match = 'dp-mockup-server'
        Port  = 8790
        Start = {
            $dir = Join-Path $ROOT 'server\dp-mockup-server'
            Start-Process -FilePath 'node' -ArgumentList 'src/index.js' `
                -WorkingDirectory $dir -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $dir 'server.out.log') `
                -RedirectStandardError (Join-Path $dir 'server.err.log')
        }
        Health = { Test-Port 8790 }
        Wait   = 30
    },
    @{
        Name  = 'dp_bot'
        Match = 'dp_bot\.py'
        Port  = $null
        Start = {
            # Samme vaktmesterlogikk som ensure_dp_bot.ps1: to pollere paa
            # samme token spiser hverandres oppdateringer.
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ROOT 'flow\ensure_dp_bot.ps1')
        }
        Health = { $null -ne (Get-Proc 'dp_bot\.py') }
        Wait   = 30
    },
    @{
        Name  = 'tunnel'
        Match = 'cloudflared'
        Port  = $null
        Start = {
            $svc = Get-Service -Name 'Cloudflared' -ErrorAction SilentlyContinue
            if ($svc) {
                if ($svc.Status -ne 'Running') { Start-Service 'Cloudflared' }
            } else {
                Say '  cloudflared-tjenesten finnes ikke - se tunnel/README.md' Yellow
            }
        }
        Health = {
            $svc = Get-Service -Name 'Cloudflared' -ErrorAction SilentlyContinue
            $svc -and $svc.Status -eq 'Running'
        }
        Wait   = 30
    }
)

# ---------------------------------------------------------------------------
# Kjorer det en ordre?
# ---------------------------------------------------------------------------
function Get-BusyReason {
    $token = Get-ApiToken
    $health = Get-Json 'http://127.0.0.1:8765/api/health' $token
    if ($health -and $health.worker.running) {
        return "flow jobber med ordre $($health.worker.running) (steg: $($health.worker.running_step))"
    }
    $queue = Get-Json 'http://127.0.0.1:8188/queue'
    if ($queue) {
        $n = @($queue.queue_running).Count + @($queue.queue_pending).Count
        if ($n -gt 0) { return "ComfyUI har $n jobber i koeen" }
    }
    # Laasefila skal ikke finnes lenger. Gjoer den det, kjoerer n8n fortsatt
    # den gamle side-loekka, og da skal vi ikke stoppe noe.
    $lock = Join-Path $IMAGE '.dreampage-comfy.lock'
    if (Test-Path $lock) { return "gammel .dreampage-comfy.lock finnes - n8n eier sannsynligvis en ordre" }
    return $null
}

# ---------------------------------------------------------------------------
# Kommandoene
# ---------------------------------------------------------------------------
function Invoke-Models {
    Head 'modeller'
    $manifest = Join-Path $ROOT 'models\manifest.json'
    if (-not (Test-Path $manifest)) {
        Say "  fant ingen $manifest - hopper over" Yellow
        return $true
    }
    & $PY (Join-Path $ROOT 'tools\models.py') 'check'
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Up {
    Head 'DreamPage OS: up'

    if (-not (Test-Path $IMAGE)) {
        Say "  ComfyUI mangler: $IMAGE" Red
        Say '  Har fase 1a kjoert? tools/migrate/phase1a_move.ps1' Yellow
        exit 1
    }
    # Junctionen fra fase 1a skal vaere borte til slutt. Saa lenge den finnes,
    # vet vi ikke om sti-inventaret er komplett.
    if (Test-Path 'C:\ComfyUI') {
        $item = Get-Item 'C:\ComfyUI'
        if ($item.LinkType) {
            Say '  MERK: C:\ComfyUI finnes fortsatt som junction (fase 1b gjenstaar).' Yellow
        } else {
            Say '  ADVARSEL: C:\ComfyUI er en EKTE mappe. Navnebyttet er ikke gjort.' Red
        }
    }

    if (-not $SkipModels) { [void](Invoke-Models) }

    foreach ($svc in $SERVICES) {
        Head "start: $($svc.Name)"
        if (& $svc.Health) { Say '  lever allerede' Green; continue }
        & $svc.Start
        $deadline = (Get-Date).AddSeconds($svc.Wait)
        $ok = $false
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 3
            if (& $svc.Health) { $ok = $true; break }
        }
        if ($ok) { Say '  OK' Green }
        else { Say "  svarte ikke innen $($svc.Wait) s" Red }
    }

    Head 'RabbitMQ'
    $token = Get-ApiToken
    $health = Get-Json 'http://127.0.0.1:8765/api/health' $token 20
    if ($health) {
        $mq = $health.rabbitmq
        if ($mq.connected) {
            Say "  tilkoblet koen '$($mq.queue)', prefetch=$($mq.prefetch), $($mq.broker_depth) melding(er) venter" Green
        } else {
            Say "  IKKE tilkoblet: $($mq.last_error)" Red
        }
    } else {
        Say '  flow-API-et svarer ikke - kan ikke sjekke koen' Yellow
    }

    Invoke-Status
}

function Invoke-Down {
    Head 'DreamPage OS: down'
    $busy = Get-BusyReason
    if ($busy -and -not $Force) {
        Say "  NEKTER: $busy" Red
        Say '  Vent til ordren er ferdig, eller bruk -Force.' Yellow
        Say '  En ordre som drepes midt i side-loekka maa kjoeres om - sidene' Yellow
        Say '  som alt ligger paa disk gjenbrukes, saa det koster bare tid.' Yellow
        exit 1
    }
    if ($busy) { Say "  -Force: stopper selv om $busy" Yellow }

    # Omvendt rekkefoelge av up: flow ned FOER ComfyUI, saa ingen ny jobb
    # starter mot en ComfyUI som er paa vei ned. dp_bot og mockup foerst,
    # fordi de er uavhengige og holder filhandles.
    $order = @('dp_bot', 'mockup', 'flow', 'comfyui')
    foreach ($name in $order) {
        $svc = $SERVICES | Where-Object { $_.Name -eq $name }
        $procs = Get-Proc $svc.Match
        if (-not $procs) { Say "  $name : kjoerer ikke"; continue }
        foreach ($p in $procs) {
            Say "  $name : stopper pid $($p.ProcessId)"
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop }
            catch { Say "    kunne ikke stoppe: $($_.Exception.Message)" Yellow }
        }
    }
    Say '  tunnelen er en Windows-tjeneste og blir staaende (den eksponerer bare API-et)' Gray
}

function Invoke-Status {
    Head 'tjenester'
    foreach ($svc in $SERVICES) {
        $procs = @(Get-Proc $svc.Match)
        $alive = & $svc.Health
        $mark = if ($alive) { 'OPP ' } else { 'NED ' }
        $color = if ($alive) { 'Green' } else { 'Red' }
        $extra = @()
        if ($procs.Count) { $extra += "pid $($procs[0].ProcessId)" }
        if ($svc.Port) { $extra += "port $($svc.Port)" }
        Say ("  {0} {1,-10} {2}" -f $mark, $svc.Name, ($extra -join '  ')) $color
    }

    $token = Get-ApiToken
    if (-not $token) {
        Say "`n  config/api.json mangler - kan ikke spoerre flow om koen" Yellow
        return
    }
    $health = Get-Json 'http://127.0.0.1:8765/api/health' $token
    if (-not $health) { Say "`n  flow-API-et svarer ikke" Yellow; return }

    Head 'jobber'
    $j = $health.jobs
    Say ("  pending {0}   running {1}   done {2}   failed {3}   cancelled {4}" -f `
        $j.pending, $j.running, $j.done, $j.failed, $j.cancelled)
    if ($health.worker.running) {
        Say ("  naa: {0}  steg={1}  {2} s" -f $health.worker.running,
            $health.worker.running_step, $health.worker.running_seconds) Cyan
    }
    if ($j.failed -gt 0) {
        $failed = Get-Json 'http://127.0.0.1:8765/api/jobs?status=failed&limit=5' $token
        Head 'feilede ordre'
        foreach ($job in $failed.jobs) {
            Say ("  {0,-10} {1,-24} {2}" -f $job.job_key, $job.book_slug, $job.error) Red
        }
        Say '  detaljer:  .\dreampage.ps1 logs   eller   GET /api/jobs/<job_key>' Gray
    }

    $queue = Get-Json 'http://127.0.0.1:8765/api/queue' $token
    if ($queue -and $queue.pending.Count) {
        Head 'koe'
        foreach ($p in $queue.pending) {
            Say ("  {0}. {1,-10} {2}" -f $p.position, $p.job_key, $p.book_slug)
        }
    }
}

function Invoke-Logs {
    $path = Join-Path $LOGDIR 'flow.log'
    if (-not (Test-Path $path)) { Say "fant ingen $path" Yellow; return }
    Say "foelger $path  (Ctrl+C for aa avslutte)" Gray
    Get-Content $path -Tail 40 -Wait
}

function Invoke-Test {
    Head 'tester'
    & $PY (Join-Path $ROOT 'flow\worker\tests\test_flow.py')
    exit $LASTEXITCODE
}

switch ($Command) {
    'up'      { Invoke-Up }
    'down'    { Invoke-Down }
    'restart' { Invoke-Down; Start-Sleep -Seconds 5; Invoke-Up }
    'status'  { Invoke-Status }
    'logs'    { Invoke-Logs }
    'models'  { if (Invoke-Models) { exit 0 } else { exit 1 } }
    'test'    { Invoke-Test }
}
