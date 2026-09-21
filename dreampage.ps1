# DreamPage OS - én supervisor som eier alle prosessene.
#
#   .\dreampage.ps1 up        sjekk modeller, start ComfyUI, flow, mockup, bot, tunnel
#   .\dreampage.ps1 down      stopp alt vi eier (ikke midt i en ordre)
#   .\dreampage.ps1 status    hva lever, hva staar i koen, hvor er ordrene
#   .\dreampage.ps1 restart
#   .\dreampage.ps1 logs      foelg flow-loggen
#   .\dreampage.ps1 mode      hva denne PC-en er til: book eller preview
#   .\dreampage.ps1 mode preview     bytt modus (krever restart)
#
# BOOK er hele bokproduksjonen: koen dreampage-jobs, sider, PDF, Gelato-utkast.
# PREVIEW er forhaandsvisninger til nettbutikken: koen preview-jobs, ett bilde,
# ingenting som koster penger. Se docs/preview-modus.md.
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
    [ValidateSet('up', 'down', 'restart', 'status', 'logs', 'models', 'test', 'ensure', 'mode')]
    [string]$Command = 'status',

    # Hopp over modellsjekken. up bruker den selv etter foerste gang.
    [switch]$SkipModels,
    # down/restart nekter aa stoppe midt i en ordre uten denne.
    [switch]$Force,
    # `.\dreampage.ps1 mode preview` - hva denne server-PC-en er til.
    # Utelatt viser bare hva den staar til naa.
    [Parameter(Position = 1)]
    [ValidateSet('', 'book', 'preview')]
    [string]$Mode = ''
)

$ErrorActionPreference = 'Stop'
$ROOT = $PSScriptRoot
$IMAGE = Join-Path $ROOT 'DreamPage-image'
# ComfyUI-frontenden, i frontend\<versjon>\. Bytt tallet for aa oppgradere
# eller rulle tilbake - begge versjonene kan ligge side om side.
$FRONTEND_VERSION = '1.43.18'
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

# ComfyUI-porten staar ETT sted: config/flow.json -> comfy.url. Baade flow og
# denne supervisoren leser den derfra. Under overgangen kjoerte den nye ComfyUI
# paa 8189 mens den gamle elevette prosessen fortsatt eide 8188, og to steder
# med samme port hadde betydd at supervisoren startet én instans og workeren
# snakket med en annen.
function Get-ComfyUrl {
    $path = Join-Path $ROOT 'config/flow.json'
    if (Test-Path $path) {
        try {
            $conf = Get-Content $path -Raw -Encoding utf8 | ConvertFrom-Json
            if ($conf.comfy.url) { return [string]$conf.comfy.url }
        } catch {}
    }
    return 'http://127.0.0.1:8188'
}

function Get-ComfyPort {
    $url = Get-ComfyUrl
    if ($url -match ':(\d+)') { return [int]$Matches[1] }
    return 8188
}

function Test-OurComfy {
    # Svarer VAAR ComfyUI paa porten - fra DreamPage-image, med modeller?
    $stats = Get-Json "$(Get-ComfyUrl)/system_stats" $null 15
    if ($null -eq $stats) { return $false }
    $argv = (@($stats.system.argv) -join ' ')
    if ([string]::IsNullOrEmpty($argv)) { return $false }
    if ($argv -notlike "*DreamPage-image*") {
        Say "  ADVARSEL: ComfyUI paa $(Get-ComfyUrl) kjorer IKKE fra $script:IMAGE" Red
        Say "            argv: $argv" Red
        Say '            Den ser sannsynligvis ingen modeller. Stopp den.' Red
        return $false
    }
    return $true
}

# Hva denne server-PC-en er til: 'book' eller 'preview'. Staar i
# config/flow.json -> mode, og avgjoer hvilken RabbitMQ-koe flow lytter paa og
# hvilken pipeline den kjoerer.
#
# Leses gjennom Python og ikke ved aa parse JSON her, av samme grunn som
# ComfyUI-porten leses ETT sted: to tolkninger av den samme filen er to
# steder aa ta feil. tools/server_mode.py er den ene tolkningen.
function Get-ServerMode {
    try {
        $raw = & $PY (Join-Path $ROOT 'tools\server_mode.py') '--json' 2>$null
        if ($LASTEXITCODE -eq 0 -and $raw) { return ($raw | ConvertFrom-Json) }
    } catch {}
    return $null
}

function Show-ServerMode {
    $m = Get-ServerMode
    Head 'servermodus'
    if (-not $m) {
        Say '  kunne ikke lese modusen (tools/server_mode.py svarte ikke)' Red
        return $null
    }
    $color = if ($m.mode -eq 'book') { 'Green' } else { 'Cyan' }
    Say ("  {0}   koe={1}   pipeline={2}" -f $m.mode.ToUpper(), $m.queue, $m.pipeline) $color
    if ($m.env_override) {
        Say "  MERK: DP_MODE=$($m.env_override) i miljoeet overstyrer fila" Yellow
    }
    return $m
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
        Modes = @('book', 'preview')
        Match = 'DreamPage-image.main\.py'
        Port  = (Get-ComfyPort)
        # --output/--input/--models utenfor DreamPage-image er selve grunnen
        # til at mappa aldri maa redigeres: vi endrer ComfyUI ved aa gi den
        # andre stier, ikke ved aa endre filene dens.
        Start = {
            $args = @(
                (Join-Path $IMAGE 'main.py'),
                '--listen', '0.0.0.0', '--port', "$(Get-ComfyPort)", '--disable-auto-launch',
                '--output-directory', (Join-Path $ROOT 'output'),
                '--input-directory', (Join-Path $ROOT 'input'),
                '--temp-directory', (Join-Path $ROOT 'tmp\comfy')
            )
            $extra = Join-Path $ROOT 'config\extra_model_paths.yaml'
            if (Test-Path $extra) { $args += @('--extra-model-paths-config', $extra) }
            # Frontend-en ligger UTENFOR DreamPage-image og utenfor det delte
            # site-packages. ComfyUI 0.21 ber om 1.43.18; pip-pakken var
            # 1.26.13 (18.09.2026). Aa oppgradere pip-pakken ville endret
            # Python-miljoeet hele pipelinen kjoerer i - dette flagget kan
            # fjernes igjen uten spor. Se docs/SETUP-NEW-PC.md.
            #
            # Mangler mappa, faller ComfyUI tilbake paa pip-frontenden. Det er
            # ufarlig for ordrene (de bruker bare API-et), men det skal SIES.
            $fe = Join-Path $ROOT "frontend\$FRONTEND_VERSION\comfyui_frontend_package\static"
            if (Test-Path (Join-Path $fe 'index.html')) {
                $args += @('--front-end-root', $fe)
            } else {
                Write-Warning "frontend $FRONTEND_VERSION mangler ($fe) - ComfyUI bruker den gamle fra pip"
            }
            Start-Process -FilePath $PY -ArgumentList $args `
                -WorkingDirectory $IMAGE -WindowStyle Minimized
        }
        # Ikke "svarer noe paa porten" - men "svarer VAAR instans".
        #
        # 16.09.2026 svarte en ComfyUI startet fra den gamle C:\ComfyUI paa
        # 8188, elevert og uten mappe-flaggene. Den saa null modeller, saa
        # hver bokside ville feilet - og en helsesjekk som bare spurte om noe
        # svarte, sa OK. Supervisoren ville dessuten sett "lever allerede" og
        # aldri startet den riktige.
        # Ikke "svarer noe paa porten" - men "svarer VAAR instans".
        #
        # 16.09.2026 svarte en ComfyUI startet fra den gamle C:\ComfyUI paa
        # 8188, elevert og uten mappe-flaggene. Den saa null modeller, saa
        # hver bokside ville feilet - og en helsesjekk som bare spurte om noe
        # svarte, sa OK. Supervisoren ville sett "lever allerede" og aldri
        # startet den riktige.
        #
        # Sjekken er lagt i en egen funksjon, ikke i en scriptblokk her:
        # blokka kalles med & og ser da verken $IMAGE eller $PSScriptRoot,
        # saa den feilet med "Strengen kan ikke ha lengden null".
        Health = { Test-OurComfy }
        Wait   = 300
    },
    @{
        Name  = 'flow'
        Modes = @('book', 'preview')
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
            # 8766 er status-lytteren, og den kjoerer i en TRAAD inne i denne
            # prosessen. Doer traaden, lever prosessen videre og 8765 svarer
            # fint - da er tunnelen utenfor nede uten at noe annet merker det.
            # Derfor sjekkes begge portene.
            $token = Get-ApiToken
            if (-not $token) { return ((Test-Port 8765) -and (Test-Port 8766)) }
            ($null -ne (Get-Json 'http://127.0.0.1:8765/api/health' $token)) -and (Test-Port 8766)
        }
        Wait   = 60
    },
    @{
        Name  = 'mockup'
        Modes = @('book')
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
        Modes = @('book')
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
        # Vaar EGEN named tunnel: eksponerer BARE /api/status* paa
        # dp-01.hageai.com. Se tunnel/config.yml for hvorfor saa lite
        # slipper ut, og hvorfor det er hageai.com og ikke dreampage.store.
        #
        # Egen prosess, ikke Windows-tjenesten: tjenesten kjoerer en ANNEN
        # konto sin tunnel med --token, og aa slaa dem sammen ville krevd
        # dashbord-tilgang vi ikke har. To cloudflared-prosesser side om
        # side er helt normalt.
        Name  = 'tunnel-status'
        Modes = @('book', 'preview')
        Match = 'dp-01-status'
        Port  = $null
        Start = {
            $cf = 'C:\Users\tobia\Downloads\cloudflared.exe'
            if (-not (Test-Path $cf)) { Say '  cloudflared.exe finnes ikke' Yellow; return }
            New-Item -ItemType Directory -Path $LOGDIR -Force | Out-Null
            Start-Process -FilePath $cf `
                -ArgumentList @('tunnel', '--config',
                                (Join-Path $ROOT 'tunnel\config.yml'),
                                'run', 'dp-01-status') `
                -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $LOGDIR 'tunnel.out.log') `
                -RedirectStandardError (Join-Path $LOGDIR 'tunnel.err.log')
        }
        Health = { $null -ne (Get-Proc 'dp-01-status') }
        Wait   = 45
    },
    @{
        Name  = 'tunnel'
        Modes = @('book', 'preview')
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

# Tjenestene som hoerer hjemme i DENNE modusen.
#
# I bokmodus er det alle seks, akkurat som foer. I preview-modus faller to
# bort, og det er ikke ryddighet:
#
#   dp_bot   operatoerbotten poller Telegram med ETT token. To pollere paa
#            samme token spiser hverandres oppdateringer - det er derfor
#            ensure_dp_bot.ps1 finnes i det hele tatt. En preview-PC som
#            startet sin egen bot ville stjaalet kommandoer fra bok-PC-en,
#            og /bygg kunne havnet paa en maskin uten ordren.
#   mockup    lager produktbilder for WooCommerce ut fra ferdige bokordre.
#            En preview-PC har ingen ordre.
#
# Ukjent eller manglende Modes-noekkel betyr "alle moduser", saa en tjeneste
# som legges til senere ikke blir usynlig fordi noen glemte noekkelen.
function Get-ActiveServices {
    $mode = 'book'
    $m = Get-ServerMode
    if ($m -and $m.mode) { $mode = [string]$m.mode }
    $SERVICES | Where-Object { (-not $_.Modes) -or ($_.Modes -contains $mode) }
}

# ---------------------------------------------------------------------------
# Kjorer det en ordre?
# ---------------------------------------------------------------------------
function Get-BusyReason {
    $token = Get-ApiToken
    $health = Get-Json 'http://127.0.0.1:8765/api/health' $token
    if ($health -and $health.worker.running) {
        return "flow jobber med ordre $($health.worker.running) (steg: $($health.worker.running_step))"
    }
    $queue = Get-Json "$(Get-ComfyUrl)/queue"
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

# ---------------------------------------------------------------------------
# ensure: vaktmesteren for HELE stacken
#
# Bakgrunnen: fram til naa hadde bare dp_bot en vaktmester. Etter en omstart
# kom boten tilbake, men ComfyUI og flow gjorde det IKKE - og da hoper
# ordrene seg opp i RabbitMQ uten at noe sier fra. Det er samme feilklasse
# som drepte boten i to doegn 12.08.2026, bare med stoerre konsekvens: en
# doed bot merkes med en gang, en doed worker ser ut som stille.
#
# Kjoeres av scheduled task hvert 5. minutt og ved innlogging. Den er stille
# naar alt lever - ellers ville loggen vaert ubrukelig - og skriver bare naar
# den faktisk gjoer noe. Ingen modellsjekk: den er treg, og ensure skal vaere
# billig nok aa kjoere hvert 5. minutt for alltid.
# ---------------------------------------------------------------------------
function Invoke-Ensure {
    $log = Join-Path $ROOT 'state\watchdog.log'
    function Note($m) {
        $line = "$((Get-Date).ToString('s'))  $m"
        Write-Host $line
        try { Add-Content $log $line -Encoding utf8 } catch {}
    }

    # En kald ComfyUI kan bruke minutter paa aa svare. Uten denne laasen ville
    # neste kjoering (5 min senere) sett 'NED' og startet EN TO.
    $lock = Join-Path $ROOT 'state\watchdog.lock'
    if (Test-Path $lock) {
        $age = (Get-Date) - (Get-Item $lock).LastWriteTime
        if ($age.TotalMinutes -lt 15) { return 0 }
        Note "tar over en laas som er $([int]$age.TotalMinutes) min gammel"
    }
    try { Set-Content $lock ([string]$PID) -Encoding utf8 } catch {}

    $started = 0; $failed = 0
    $startedNames = @(); $failedNames = @()
    try {
        foreach ($svc in (Get-ActiveServices)) {
            $alive = $false
            try { $alive = [bool](& $svc.Health) } catch { $alive = $false }
            if ($alive) { continue }

            Note "$($svc.Name): NED - starter"
            try { & $svc.Start } catch { Note "$($svc.Name): start feilet: $($_.Exception.Message)" }
            $deadline = (Get-Date).AddSeconds($svc.Wait)
            $ok = $false
            while ((Get-Date) -lt $deadline) {
                Start-Sleep -Seconds 3
                try { if (& $svc.Health) { $ok = $true; break } } catch {}
            }
            if ($ok) { Note "$($svc.Name): OPP igjen"; $started++; $startedNames += $svc.Name }
            else     { Note "$($svc.Name): SVARTE IKKE innen $($svc.Wait) s"; $failed++; $failedNames += $svc.Name }
        }
    } finally {
        Remove-Item $lock -Force -ErrorAction SilentlyContinue
    }

    if ($started -or $failed) { Note "ferdig: $started startet, $failed feilet" }

    # SI FRA. Fram til 16.09.2026 endte en mislykket restart her: en linje i
    # state\watchdog.log og exit 1 til Task Scheduler - to steder ingen ser
    # paa. En ComfyUI som ikke lot seg starte var usynlig til ordrene hadde
    # hopet seg opp i RabbitMQ. Varselet er et sidespor: feiler det, skal
    # vaktmesteren fortsatt rapportere riktig exit-kode.
    if ($failed) {
        try {
            & $PY (Join-Path $ROOT 'flow\worker\notify.py') 'watchdog' `
                ($failedNames -join ',') ($startedNames -join ',') | Out-Null
        } catch { Note "kunne ikke varsle: $($_.Exception.Message)" }
    }

    # Varsler som ikke kom fram (nattbruddet 04:30-05:05) ligger i utboksen.
    # Uten dette ville de ventet til NESTE varsel - som kan vaere timer unna.
    # Python startes bare naar det faktisk ligger noe der.
    $outbox = Join-Path $ROOT 'state\notify_outbox'
    if (Get-ChildItem $outbox -Filter '*.json' -EA SilentlyContinue | Select-Object -First 1) {
        try {
            $res = & $PY (Join-Path $ROOT 'flow\worker\notify.py') 'flush'
            Note "utboksen: $res"
        } catch { Note "utboksen kunne ikke toemmes: $($_.Exception.Message)" }
    }

    # Exit-koden blir 'Last Result' i scheduled task, saa den skal si sant.
    if ($failed) { return 1 } else { return 0 }
}
function Invoke-Up {
    Head 'DreamPage OS: up'
    [void](Show-ServerMode)

    if (-not (Test-Path $IMAGE)) {
        Say "  ComfyUI mangler: $IMAGE" Red
        Say '  Har fase 1a kjoert? tools/migrate/phase1a_move.ps1' Yellow
        exit 1
    }
    # Den gamle installasjonen skal vaere borte til slutt. Saa lenge den staar
    # der, ligger det 21 GB git-historikk og en duplisert kopi av boekene som
    # kan forvirre - og vi vet ikke sikkert at ingenting leser derfra.
    #
    # Stien settes fra deler: tools/migrate/rewrite_paths.py rettet en gang
    # denne sjekken til aa peke paa seg selv, fordi den matchet literalen.
    $legacy = 'C:' + 'Comfy' + 'UI'
    if (Test-Path $legacy) {
        $n = @(Get-ChildItem $legacy -Force -EA SilentlyContinue).Count
        Say "  MERK: $legacy finnes fortsatt ($n oppforinger). Slett den naar en" Yellow
        Say '        ekte ordre har gaatt gjennom DreamPage OS.' Yellow
    }

    if (-not $SkipModels) { [void](Invoke-Models) }

    foreach ($svc in (Get-ActiveServices)) {
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

function Invoke-Mode {
    if (-not $Mode) { [void](Show-ServerMode); return 0 }
    & $PY (Join-Path $ROOT 'tools\server_mode.py') $Mode
    return $LASTEXITCODE
}

function Invoke-Status {
    # Modusen foerst. Alt under - hvilken koe som telles, hvilke tjenester som
    # skal leve, hva "ordre" i det hele tatt betyr - avhenger av den.
    [void](Show-ServerMode)

    Head 'tjenester'
    foreach ($svc in (Get-ActiveServices)) {
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

# Kjoerer ALLE testfilene, ikke en navngitt liste.
#
# Fram til 16.09.2026 stod det én sti her: test_flow.py. Da
# tests/test_drive_upload.py kom til, var den usynlig fra dag én - ingen
# hadde gjort noe galt, filen var bare ikke nevnt. En testkommando som maa
# oppdateres hver gang noen skriver en test, blir ikke oppdatert.
#
# check_assets kjoeres til slutt fordi den sjekker EKTE filer paa denne
# maskinen, ikke kode: den kan feile paa en riktig installasjon der kunsten
# ikke er lastet ned enda, og da skal det staa tydelig hvilken av delene som
# feilet.
function Invoke-Test {
    Head 'tester'
    $testDir = Join-Path $ROOT 'flow\worker\tests'
    $files = Get-ChildItem $testDir -Filter 'test_*.py' -File | Sort-Object Name
    if (-not $files) { Say "  fant ingen testfiler i $testDir" Yellow; exit 1 }

    $failed = @()
    foreach ($f in $files) {
        Say "`n--- $($f.Name)" Cyan
        & $PY $f.FullName
        if ($LASTEXITCODE -ne 0) { $failed += $f.Name }
    }

    Say "`n--- check_assets" Cyan
    & $PY (Join-Path $ROOT 'tools\check_assets.py')
    if ($LASTEXITCODE -ne 0) { $failed += 'check_assets.py' }

    # Viser GUI-ets workflow-liste fortsatt det vi faktisk kjoerer? Snakker
    # ikke med ComfyUI - den sammenligner sha1-en filene baerer med kildene.
    # Endrer noen en workflow_api.json uten aa synke, aapner operatoeren en
    # graf som SER ut som produksjonen og ikke er det.
    Say "`n--- comfy_workflows" Cyan
    & $PY (Join-Path $ROOT 'tools\comfy_workflows.py') --check
    if ($LASTEXITCODE -ne 0) { $failed += 'comfy_workflows.py --check' }

    # Ville dette treet kjoert paa Linux? Nye maskiner settes opp der, og
    # forskjellene er usynlige herfra: en hardkodet C:-sti, eller et filnavn
    # med feil bokstav - Windows aapner `Georgia.TTF` selv om fila heter
    # `Georgia.ttf`, Linux gjoer det ikke. Sjekken kjoeres HER, paa maskinen
    # der feilen ikke gjoer noe, i stedet for foerste gang noen setter opp
    # maskin nummer to. Se docs/SETUP-LINUX.md.
    Say "`n--- check_portability" Cyan
    & $PY (Join-Path $ROOT 'tools\check_portability.py')
    if ($LASTEXITCODE -ne 0) { $failed += 'check_portability.py' }

    Write-Host ''
    if ($failed) {
        Say "FEILET: $($failed -join ', ')" Red
        exit 1
    }
    Say "alle $($files.Count + 3) testene bestaatt" Green
    exit 0
}

switch ($Command) {
    'ensure'  { exit (Invoke-Ensure) }
    'up'      { Invoke-Up }
    'down'    { Invoke-Down }
    'restart' { Invoke-Down; Start-Sleep -Seconds 5; Invoke-Up }
    'status'  { Invoke-Status }
    'logs'    { Invoke-Logs }
    'models'  { if (Invoke-Models) { exit 0 } else { exit 1 } }
    'test'    { Invoke-Test }
    'mode'    { exit (Invoke-Mode) }
}
