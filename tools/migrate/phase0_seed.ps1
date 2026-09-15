# Fase 0 - saa strukturen i C:\DreamPage-OS ved aa KOPIERE egen kode ut av
# C:\ComfyUI. Ingenting i produksjon roeres: dette er rene kopier som ligger
# doede til fase 1 flytter treet og gjoer dem levende.
#
# Poenget er § 2 i oppdraget: all egen kode er untracked inne i en klone av
# comfyanonymous/ComfyUI, der et `git clean -fdx` sletter 11 boeker, tekstmotoren
# og botten. Foerste commit skal derfor skje FOER noe som helst flyttes.
#
# Idempotent: kan kjoeres om igjen. robocopy /MIR paa delmengder, ikke paa rota.
$ErrorActionPreference = 'Stop'

$SRC = 'C:\ComfyUI'
$DST = 'C:\DreamPage-OS'

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

# robocopy returnerer 0-7 som suksess (1 = filer kopiert, 2 = ekstra, 3 = begge).
# 8+ er feil. Uten denne sjekken ville $ErrorActionPreference ikke fanget noe,
# siden robocopy ikke kaster - og en halv kopi hadde sett ut som en hel.
function Copy-Tree($from, $to, [string[]]$excludeDirs = @(), [string[]]$excludeFiles = @()) {
    if (-not (Test-Path $from)) { Write-Host "  hopper over (finnes ikke): $from"; return }
    $args = @($from, $to, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:2')
    if ($excludeDirs.Count)  { $args += '/XD'; $args += $excludeDirs }
    if ($excludeFiles.Count) { $args += '/XF'; $args += $excludeFiles }
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy feilet ($LASTEXITCODE): $from -> $to" }
    Write-Host ("  {0,-46} -> {1}" -f (Split-Path $from -Leaf), $to)
}

Section 'mapper'
foreach ($d in 'flow','flow\tools','flow\text','flow\face_variants','books','nodes',
               'assets','panel','tunnel','archive','config','server','docs',
               'tools\migrate','state','output','models') {
    $p = Join-Path $DST $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
Write-Host '  ok'

# ---------------------------------------------------------------------------
# books/ - definisjonene, ikke kundeartefaktene.
# orders/ er 72,4 GB av 73 GB og hoerer i state, ikke i git.
# ---------------------------------------------------------------------------
Section 'books (uten orders/)'
Get-ChildItem "$SRC\books" -Directory | ForEach-Object {
    Copy-Tree $_.FullName (Join-Path "$DST\books" $_.Name) -excludeDirs @('orders','__pycache__')
}

# ---------------------------------------------------------------------------
# script/ splittes. Klassifiseringen staar i PLAN.md § 4.
#
# Lokalemappene (nb, nn, sv, en-US, en-GB) flyttes som UDELTE enheter: hver
# inneholder egne kopier av gelato_cover.py, dream_pdf_guard.py, fontene og
# logoen, og tekstscriptene gjoer bare `from gelato_cover import ...` - de
# stoler paa at scriptets egen mappe er paa sys.path. Splitter man dem,
# knekker alle 80 tekstscriptene samtidig.
# ---------------------------------------------------------------------------
Section 'flow/text (lokalebunter, udelt)'
foreach ($loc in 'nb','nn','sv','en-US','en-GB') {
    Copy-Tree "$SRC\script\$loc" "$DST\flow\text\$loc" -excludeDirs @('__pycache__')
}

Section 'flow (ekte pipeline)'
$pipeline = @(
    'build_gelato_pdf.py','build_last_page.py','gelato_cover.py','dream_pdf_guard.py',
    'dream_text_layout.py','drive_upload.py','dp_order.py','dp_bot.py','dp_merge.py',
    'dp_testbook.py','auto_merge_multibook.py','gelato_merge.py','regen_page.py',
    'reprint_order.py'
)
foreach ($f in $pipeline) {
    if (Test-Path "$SRC\script\$f") { Copy-Item "$SRC\script\$f" "$DST\flow\$f" -Force; Write-Host "  $f" }
    else { Write-Host "  MANGLER: $f" -ForegroundColor Yellow }
}
Copy-Tree "$SRC\script\face_variants" "$DST\flow\face_variants" -excludeDirs @('__pycache__')

Section 'flow/tools (operative verktoey)'
$tools = @(
    'finish_order.py','finish_merged_order.py','refresh_merged_draft.py','republish_job.py',
    'rerun_order_comfy.py','render_next_cover.py','make_headmask.py',
    'make_shorthair_templates.py','make_darkskin_templates.py','upscale_2x_ultrasharp.py',
    'sync_title_params.py','n8n_credential.py','ensure_dp_bot.ps1','start_dp_bot.ps1'
)
foreach ($f in $tools) {
    if (Test-Path "$SRC\script\$f") { Copy-Item "$SRC\script\$f" "$DST\flow\tools\$f" -Force; Write-Host "  $f" }
    else { Write-Host "  MANGLER: $f" -ForegroundColor Yellow }
}
Copy-Tree "$SRC\script\pre" "$DST\flow\tools\pre" -excludeDirs @('__pycache__')

# ---------------------------------------------------------------------------
# assets/ - fonter, logo, bakside, ryggrad, lastpages.
# Merk: kopiene som ligger INNE i hver lokalebunt blir vaerende der. De er
# duplikater, men de er ogsaa dagens oppfoersel, og fase 1 skal ikke endre
# oppfoersel.
# ---------------------------------------------------------------------------
Section 'assets'
foreach ($d in 'bakside','logo','lastpages','ryggrad') {
    Copy-Tree "$SRC\script\$d" "$DST\assets\$d"
}
Get-ChildItem "$SRC\script" -File | Where-Object { $_.Extension -in '.ttf','.otf','.png' } |
    ForEach-Object { Copy-Item $_.FullName "$DST\assets\$($_.Name)" -Force }
Write-Host ("  {0} font/bilde-filer" -f (Get-ChildItem "$DST\assets" -File).Count)

# ---------------------------------------------------------------------------
# archive/ - engangs-patcher. De blir verdiloese naar n8n er borte, men de er
# ogsaa den eneste skriftlige kilden til HVORFOR en node ser ut som den gjoer,
# saa de skal i git foer de legges bort. § 7 krever en gjennomgang av om noen
# av dem gjoer ekte arbeid; den staar i archive\README.md.
# ---------------------------------------------------------------------------
Section 'archive (engangs-patcher)'
$n = 0
Get-ChildItem "$SRC\script" -File | Where-Object {
    $_.Name -match '^(patch_|fix_|rewrite_|tune_|update_title_tester|motet_story|worker-continue-qr|build_gelato_pdf_without)'
} | ForEach-Object { Copy-Item $_.FullName "$DST\archive\$($_.Name)" -Force; $n++ }
Write-Host "  $n filer"

Section 'config, server'
Copy-Tree "$SRC\config" "$DST\config"
Copy-Tree "$SRC\server" "$DST\server" -excludeDirs @('node_modules','__pycache__','.next')

# ---------------------------------------------------------------------------
# nodes/ - egne ComfyUI custom nodes. local_data (15 GB modeller/datasett) og
# .venv-flux-test hoerer ikke i git.
# ---------------------------------------------------------------------------
Section 'nodes/dreampage-headswap'
Copy-Tree "$SRC\dreampage-headswap" "$DST\nodes\dreampage-headswap" `
    -excludeDirs @('local_data','.venv-flux-test','runs','build','__pycache__',
                   'dreampage_headswap.egg-info','.research','.git')

Section 'ferdig'
$size = (Get-ChildItem $DST -Recurse -File -Force -ErrorAction SilentlyContinue |
         Measure-Object Length -Sum).Sum
"{0:N2} GB kopiert til {1}" -f ($size/1GB), $DST
