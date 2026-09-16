# Vaktmester for operatoerboten: starter dp_bot.py hvis den ikke kjorer.
#
# Kjores av scheduled task "DreamPage dp_bot" ved innlogging og hvert 5. minutt.
# Boten dode 12.08.2026 da maskinen ble restartet, og ingenting startet den
# igjen - to dogn uten bot. Denne skal fange bade omstart og krasj.
#
# Trygg aa kjore nar som helst: gjor ingenting hvis boten allerede lever.
$ErrorActionPreference = 'Stop'
$py  = (Get-Command python).Source
$bot = 'C:\DreamPage-OS\flow\dp_bot.py'
$out = 'C:\DreamPage-OS\state\dp_bot.out.log'
$err = 'C:\DreamPage-OS\state\dp_bot.err.log'
$log = 'C:\DreamPage-OS\state\dp_bot_watchdog.log'

function Note($message) {
    "$((Get-Date).ToString('s'))  $message" | Add-Content -Path $log -Encoding utf8
}

# Windows sin -RedirectStandardError TOEMMER fila naar prosessen starter. Ble
# boten drept midt i en jobb, slettet vaktmesterens omstart nettopp den
# tracebacken som forklarte hvorfor - det skjedde 05.09.2026 kl. 14.56 og
# gjorde et avbrutt bygg umulig aa diagnostisere. Ta vare paa den forst.
function Save-CrashLog($path) {
    if ((Test-Path $path) -and ((Get-Item $path).Length -gt 0)) {
        $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
        Move-Item $path "$path.$stamp" -Force
        # Behold de ti siste; eldre krasj er ikke verdt diskplassen.
        Get-ChildItem "$path.*" | Sort-Object LastWriteTime -Descending |
            Select-Object -Skip 10 | Remove-Item -Force -ErrorAction SilentlyContinue
    }
}

$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*dp_bot.py*' }
if ($running) { exit 0 }   # lever - ikke stoy i loggen

# To pollere paa samme token spiser hverandres oppdateringer, saa vi starter
# bare naar ingen kjorer.
Save-CrashLog $err
Start-Process -FilePath $py -ArgumentList $bot -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err
Note "startet dp_bot (var ikke i gang)"
