# Start operatoerboten detached, som mockup-serveren.
#   powershell -ExecutionPolicy Bypass -File C:\ComfyUI\script\start_dp_bot.ps1
$ErrorActionPreference = 'Stop'
$py  = (Get-Command python).Source
$bot = 'C:\ComfyUI\script\dp_bot.py'
$out = 'C:\ComfyUI\state\dp_bot.out.log'
$err = 'C:\ComfyUI\state\dp_bot.err.log'

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

$existing = Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*dp_bot.py*' }
if ($existing) {
    # To pollere paa samme token spiser hverandres oppdateringer.
    throw "dp_bot.py kjorer allerede (PID $($existing.ProcessId)). Stopp den forst."
}

Save-CrashLog $err
Start-Process -FilePath $py -ArgumentList $bot -WindowStyle Hidden `
    -RedirectStandardOutput $out -RedirectStandardError $err
Write-Output "dp_bot startet. Logg: $out"
