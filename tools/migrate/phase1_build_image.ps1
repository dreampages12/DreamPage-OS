# Fase 1 - bygg DreamPage-image ved siden av produksjonen.
#
# Dette ERSTATTER phase1a_move.ps1. Den gamle planen var aa doepe om
# C:\ComfyUI til DreamPage-image, og det gikk ikke: ComfyUI er startet
# elevert, og en katalog kan ikke doepes om mens den er en prosess'
# arbeidsmappe. Flyttingen ble forsoekt og avvist med "Prosessen faar ikke
# tilgang til filen fordi den brukes av en annen prosess".
#
# Den nye planen er bedre, ikke bare mulig:
#
#   * Et FRISKT utsjekk av ComfyUI paa noeyaktig den commiten produksjonen
#     kjoerer (8505abf5). Verifisert bit-identisk: 846 av 846 sammenlignbare
#     filer. Treet blir 0,05 GB i stedet for 21,5 GB .git-historikk.
#   * Ingen elevering, ingen 335 GB flytting, ingen nedetid.
#   * Den gamle C:\ComfyUI staar og selger boeker mens dette bygges.
#   * `DreamPage-image` blir det den skal vaere: rent upstream, aldri redigert.
#
# Skriptet roerer IKKE C:\ComfyUI. Den slettes foerst naar DreamPage OS er
# verifisert live - se tools/migrate/phase1_cutover.ps1.
#
#   powershell -ExecutionPolicy Bypass -File tools\migrate\phase1_build_image.ps1
#   ... -WhatIf for bare aa se hva som ville skjedd
[CmdletBinding()]
param([switch]$WhatIf, [switch]$Force)

$ErrorActionPreference = 'Stop'
$OLD = 'C:\ComfyUI'
$ROOT = 'C:\DreamPage-OS'
$IMAGE = Join-Path $ROOT 'DreamPage-image'
$PINNED = '8505abf52e42f4441d9d53baf4c31a2ec7123400'

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Head($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Fail($m) { Say "STOPP: $m" Red; exit 1 }

# Vaare EGNE noder. De skal ligge i nodes/ og junctes inn, ikke ligge som
# tredjeparts-kode inne i et tre vi har lovet aa aldri redigere.
$OURS = @(
    @{ Node = 'dreampage_headswap'
       Target = 'nodes\dreampage-headswap\comfyui_dreampage_headswap' },
    @{ Node = 'comfyui_head_hair_mask_guard'
       Target = 'nodes\comfyui_head_hair_mask_guard' }
)

Head 'fase 1: bygg DreamPage-image'

if (-not (Test-Path $OLD)) { Fail "$OLD finnes ikke - er den alt slettet?" }

# ---------------------------------------------------------------------------
# 1. Utsjekket
# ---------------------------------------------------------------------------
Head 'ComfyUI-utsjekk'
if (Test-Path (Join-Path $IMAGE '.git')) {
    $have = (& git -C $IMAGE rev-parse HEAD).Trim()
    if ($have -eq $PINNED) { Say "  finnes alt paa $PINNED" Green }
    else { Say "  finnes, men paa $have (ventet $PINNED)" Yellow }
} elseif ($WhatIf) {
    Say "  ville hentet $PINNED"
} else {
    New-Item -ItemType Directory -Path $IMAGE -Force | Out-Null
    Push-Location $IMAGE
    try {
        & git init -q
        # Lokal transport tillater aa hente en vilkaarlig SHA. Vi tar den
        # NOEYAKTIGE commiten produksjonen kjoerer - ikke taggen v0.21.0, som
        # ligger 17 commits bak.
        & git remote add local $OLD
        & git fetch -q --depth 1 local $PINNED
        & git checkout -q FETCH_HEAD
        & git checkout -q -b pinned
        & git remote remove local
        & git remote add origin 'https://github.com/comfyanonymous/ComfyUI.git'
        Say "  hentet $PINNED" Green
    } finally { Pop-Location }
}

# ---------------------------------------------------------------------------
# 2. custom_nodes
#
# Kopieres VERBATIM. Flere av dem er haandpatchet - PuLID/ControlNet/Kontext-
# hooken maa patches manuelt og mistes ved node-oppdatering - og de nodene har
# ikke eget git-repo, saa endringene kan ikke oppdages. En verbatim kopi
# bevarer dem; aa reinstallere via Manager ville stille mistet dem.
# ---------------------------------------------------------------------------
Head 'custom_nodes'
$src = Join-Path $OLD 'custom_nodes'
$dst = Join-Path $IMAGE 'custom_nodes'
$skip = @('__pycache__') + ($OURS | ForEach-Object { $_.Node })
if ($WhatIf) {
    $n = (Get-ChildItem $src -Directory | Where-Object { $skip -notcontains $_.Name }).Count
    Say "  ville kopiert $n noder (hopper over: $($skip -join ', '))"
} else {
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    & robocopy $src $dst /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 /XD $skip /XJ | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy feilet ($LASTEXITCODE)" }
    # websocket_image_save.py og example_node.py.example er filer, ikke mapper
    Get-ChildItem $src -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $dst $_.Name) -Force
    }
    $n = (Get-ChildItem $dst -Directory).Count
    Say "  $n noder kopiert" Green
}

# ---------------------------------------------------------------------------
# 3. Vaare egne noder -> nodes/, junctet inn
# ---------------------------------------------------------------------------
Head 'egne noder'
foreach ($own in $OURS) {
    $target = Join-Path $ROOT $own.Target
    $link = Join-Path $dst $own.Node
    $from = Join-Path $src $own.Node

    if (-not (Test-Path $target)) {
        if ($WhatIf) { Say "  ville flyttet $($own.Node) -> $($own.Target)"; continue }
        $item = Get-Item $from -ErrorAction SilentlyContinue
        if ($null -eq $item) { Say "  $($own.Node): finnes ikke i kilden" Yellow; continue }
        if ($item.LinkType) {
            Say "  $($own.Node): junction i kilden, maalet finnes alt i nodes/"
        } else {
            New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
            & robocopy $from $target /E /NFL /NDL /NJH /NJS /NP /XD '__pycache__' | Out-Null
            Say "  $($own.Node) kopiert til $($own.Target)" Green
        }
    } else {
        Say "  $($own.Node): $($own.Target) finnes alt"
    }

    if ($WhatIf) { Say "  ville junctet $link -> $target"; continue }
    if (Test-Path $link) { Remove-Item $link -Force -Recurse -ErrorAction SilentlyContinue }
    & cmd.exe /c mklink /J "`"$link`"" "`"$target`"" | ForEach-Object { Say "  $_" }
}

# ---------------------------------------------------------------------------
# 4. user/ - ComfyUI-Manager sin config og lagrede workflows
# ---------------------------------------------------------------------------
Head 'user/'
if ($WhatIf) { Say '  ville kopiert user/ (0,02 GB, uten logger)' }
else {
    & robocopy (Join-Path $OLD 'user') (Join-Path $IMAGE 'user') /E /NFL /NDL /NJH /NJS /NP `
        /XF '*.log' '*.log.*' | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy user/ feilet ($LASTEXITCODE)" }
    Say '  kopiert (logger utelatt - de hoerer til den gamle installasjonen)' Green
}

# ---------------------------------------------------------------------------
# 5. Hardkodede stier inne i custom_nodes
#
# To ini-filer peker paa C:\ComfyUI. De er ikke vaar kode, saa
# rewrite_paths.py roerer dem ikke - og de er lette aa glemme.
# ---------------------------------------------------------------------------
Head 'stier i custom_nodes'
$fixes = @(
    @{ File = 'comfyui-impact-pack\impact-pack.ini'; Key = 'custom_wildcards' },
    @{ File = 'was-ns\was_suite_config.json';        Key = 'wildcards_path' }
)
foreach ($fix in $fixes) {
    $path = Join-Path $dst $fix.File
    if (-not (Test-Path $path)) { Say "  $($fix.File): finnes ikke" Yellow; continue }
    $text = Get-Content $path -Raw -Encoding utf8
    $new = $text.Replace('C:\\ComfyUI', 'C:\\DreamPage-OS\\DreamPage-image').Replace('C:\ComfyUI', 'C:\DreamPage-OS\DreamPage-image').Replace('C:/ComfyUI', 'C:/DreamPage-OS/DreamPage-image')
    if ($new -eq $text) { Say "  $($fix.File): ingen sti aa rette" }
    elseif ($WhatIf) { Say "  ville rettet $($fix.Key) i $($fix.File)" }
    else {
        Set-Content $path $new -Encoding utf8 -NoNewline
        Say "  $($fix.Key) rettet i $($fix.File)" Green
    }
}

# ---------------------------------------------------------------------------
# 6. Kontroll
# ---------------------------------------------------------------------------
Head 'kontroll'
if ($WhatIf) { Say '  WhatIf - ingenting endret' Green; exit 0 }

$checks = @(
    @{ What = 'main.py';      Path = Join-Path $IMAGE 'main.py' },
    @{ What = 'comfy/';       Path = Join-Path $IMAGE 'comfy' },
    @{ What = 'custom_nodes'; Path = $dst },
    @{ What = 'user/';        Path = Join-Path $IMAGE 'user' }
)
foreach ($c in $checks) {
    Say ("  {0,-14} {1}" -f $c.What, $(if (Test-Path $c.Path) { 'OK' } else { 'MANGLER' })) `
        $(if (Test-Path $c.Path) { 'Green' } else { 'Red' })
}
$srcCount = (Get-ChildItem $src -Directory | Where-Object { $_.Name -ne '__pycache__' }).Count
$dstCount = (Get-ChildItem $dst -Directory).Count
Say ("  noder         {0} i kilden, {1} i imaget" -f $srcCount, $dstCount) `
    $(if ($dstCount -ge $srcCount) { 'Green' } else { 'Yellow' })

$left = Select-String -Path (Join-Path $dst '*\*.ini'), (Join-Path $dst '*\*.json') `
    -Pattern 'C:[\\/]{1,2}ComfyUI' -SimpleMatch:$false -ErrorAction SilentlyContinue
if ($left) {
    Say '  gjenstaaende C:\ComfyUI-stier i custom_nodes:' Yellow
    $left | Select-Object -First 8 | ForEach-Object { Say "      $($_.Path):$($_.LineNumber)" Yellow }
}

Say ''
Say 'NESTE: proev imaget paa en egen port, uten aa roere produksjonen.' Yellow
Say '  tools\migrate\phase1_try_image.ps1' Yellow
