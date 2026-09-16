<#
    Slipper kontrollpanelet paa en ANNEN maskin inn til det fulle API-et
    (8765) over Tailscale. Krever administrator - brannmurregler gjoer det.

        Start-Process powershell -Verb RunAs -ArgumentList `
          '-NoProfile','-ExecutionPolicy','Bypass','-File', `
          'C:\DreamPage-OS\tools\allow_tailnet_api.ps1'

    HVORFOR DEN TRENGS
    Workeren binder 8765 til bade 127.0.0.1 og tailnett-adressen, men
    Tailscale-adapteren ligger paa PRIVATE-profilen, og de eksisterende
    python.exe-reglene gjelder bare PUBLIC. Uten denne regelen blir
    forbindelsen fra den andre maskinen droppet av Windows-brannmuren, selv
    om socketen lytter og tokenet er riktig.

    HVA DEN AAPNER - og hva den ikke aapner
    Inbound TCP 8765, men BARE:
      * fra 100.64.0.0/10  - tailnettet (RFC 6598). Ikke hjemmenettet,
                             ikke internett.
      * til tailnett-adressen vaar - saa regelen ikke kan brukes paa
                             Ethernet-grensesnittet (192.168.x).
    To uavhengige lag: selve socketen er heller ikke bundet til 192.168.x,
    saa selv en for bred regel ville ikke naadd API-et derfra.

    Statusporten 8766 aapnes IKKE. Den er localhost-only med vilje og naas
    utenfra gjennom cloudflared. Den skal ikke ha en brannmurregel.

    Skriptet er idempotent: kjoerer du det igjen, oppdaterer det regelen i
    stedet for aa lage en ny. Det starter ingenting og stopper ingenting.
#>
$ErrorActionPreference = 'Stop'
$RULE = 'DreamPage flow-API via Tailscale'
$PORT = 8765

if (-not ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
      ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Maa kjoeres som administrator." -ForegroundColor Red
    exit 1
}

# Tailnett-adressen leses fra maskinen, ikke hardkodes: Tailscale kan dele ut
# en ny adresse, og da skal regelen foelge med naar skriptet kjoeres igjen.
$local = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -like '100.*' -and
                   [int]($_.IPAddress.Split('.')[1]) -ge 64 -and
                   [int]($_.IPAddress.Split('.')[1]) -le 127 } |
    Select-Object -First 1).IPAddress

if (-not $local) {
    Write-Host "Fant ingen tailnett-adresse (100.64.0.0/10). Er Tailscale oppe?" -ForegroundColor Red
    Write-Host "Regelen ble IKKE laget - en regel mot 'Any' ville vaert for bred."
    exit 1
}
Write-Host "tailnett-adresse: $local"

$existing = Get-NetFirewallRule -DisplayName $RULE -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "regelen finnes - oppdaterer"
    Set-NetFirewallRule -DisplayName $RULE -Enabled True -Action Allow `
        -Direction Inbound -Profile Any -Protocol TCP -LocalPort $PORT `
        -RemoteAddress '100.64.0.0/10' -LocalAddress $local
} else {
    Write-Host "lager regelen"
    New-NetFirewallRule -DisplayName $RULE -Enabled True -Action Allow `
        -Direction Inbound -Profile Any -Protocol TCP -LocalPort $PORT `
        -RemoteAddress '100.64.0.0/10' -LocalAddress $local `
        -Description 'Kontrollpanel paa annen maskin -> flow-API. Bare tailnettet.' | Out-Null
}

$r  = Get-NetFirewallRule -DisplayName $RULE
$pf = $r | Get-NetFirewallPortFilter
$af = $r | Get-NetFirewallAddressFilter
Write-Host ""
Write-Host "ferdig:" -ForegroundColor Green
Write-Host "  $($r.DisplayName)"
Write-Host "  $($r.Action) $($r.Direction)  TCP/$($pf.LocalPort)  profil=$($r.Profile)"
Write-Host "  fra   : $($af.RemoteAddress)"
Write-Host "  til   : $($af.LocalAddress)"
Write-Host ""
Write-Host "Test fra den andre PC-en:"
Write-Host "  curl -H `"Authorization: Bearer <full-token>`" http://$local`:8765/api/health"
