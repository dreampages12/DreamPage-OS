# Daglig opprydding av midlertidige bot-filer.
#
# Kjores av scheduled task "DreamPage cleanup" en gang i dognet. All logikk og
# alle sperrer ligger i tools/cleanup_variants.py - dette skriptet finnes bare
# for aa kalle den og ta vare paa hva den gjorde. En opprydding du ikke kan
# lese i ettertid er en opprydding du ikke kan stole paa.
#
# Kjorer med --apply. Sperrene i verktoyet er det som holder igjen, ikke
# mangelen paa --apply: en ordre maa vaere betalt hos Gelato, uten aapen
# bot-okt, ute av jobbkoen, gammel nok, og ha den godkjente kopien i input/.
$ErrorActionPreference = 'Continue'
$ROOT = Split-Path $PSScriptRoot -Parent
$PY = 'C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe'
$LOG = Join-Path $ROOT 'state\cleanup.log'

New-Item -ItemType Directory -Path (Split-Path $LOG -Parent) -Force | Out-Null
$stamp = (Get-Date).ToString('s')
Add-Content $LOG "`n===== $stamp =====" -Encoding utf8

$output = & $PY (Join-Path $ROOT 'tools\cleanup_variants.py') --apply 2>&1
$code = $LASTEXITCODE
$output | ForEach-Object { Add-Content $LOG $_ -Encoding utf8 }
Add-Content $LOG "exit=$code" -Encoding utf8

# Behold de siste 2000 linjene. Loggen skal kunne leses, ikke arkiveres.
try {
    $lines = Get-Content $LOG
    if ($lines.Count -gt 2000) {
        $lines | Select-Object -Last 2000 | Set-Content $LOG -Encoding utf8
    }
} catch {}

exit $code
