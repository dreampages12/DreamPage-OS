# tunnel/ — cloudflared

Tunnelen er det eneste som slipper trafikk **inn** til maskinen. Alt utgående
— RabbitMQ over Tailscale, Gelato, Google Drive, Telegram — fungerer uten den
og skal ikke røres.

## Status: i drift, og eksponerer bare status

```
https://dp-01.hageai.com/api/status           <- Bearer-token med scope "status"
https://dp-01.hageai.com/api/status/summary
https://dp-01.hageai.com/api/status/id
alt annet                                     -> 404 i Cloudflares kant
```

Tunnel `dp-01-status` / `c6ecc2db-f411-4dec-949e-5e55cc0e99f7`, konfigurert i
`config.yml`, startet som egen prosess og holdt i live av
`dreampage.ps1 ensure` (tjenesten `tunnel-status`).

## Hvorfor hageai.com og ikke dreampage.store

Origin-sertifikatet i `~/.cloudflared/cert.pem` er scopet til **én** sone, og
det er `hageai.com` (zoneID `d8ca3e90…`). Det er samme domene som `apex`,
`godseye`, `hq`, `remote` og `ring` allerede tunnelerer gjennom — altså
infrastruktur, ikke kundeflate.

`dreampage.store` ligger i en **annen konto**. Den kjørende Windows-tjenesten
«Cloudflared» bruker en `--token` for tunnel `d9b1ec20…` der, og `--token`
betyr fjernstyrt ingress: rutene ligger i Cloudflare-dashbordet, ikke i en
lokal fil. En `config.yml` på disk blir fullstendig ignorert av en slik
tunnel, så statusruten kunne ikke legges der herfra.

Vil du ha statusen på `dreampage.store` i stedet, er det ett dashbord-steg:

> Zero Trust → Networks → Tunnels → tunnelen for `admin.dreampage.store` →
> **Public hostname** → Add: `dp-01.dreampage.store` → service
> `http://127.0.0.1:8765`.
>
> Men merk: dashbord-ingress har **ikke** sti-filteret denne fila har. Da
> ville hele port 8765 vært nåbar, inkludert `/api/jobs` og `/api/queue` som
> inneholder barnenavn og ordrenummer. Legg i så fall Cloudflare Access foran,
> eller behold `dp-01.hageai.com` for status og la dashbordet gå over
> Tailscale.

To cloudflared-prosesser side om side er helt normalt, og det er det som
kjører nå: Windows-tjenesten for `admin.dreampage.store`, og vår egen for
statusen.

## Tre lag, hvert av dem nok alene

1. **Ingress-filteret** i `config.yml`. `path` er et regex med anker, så
   `/api/statusXYZ` og `/api/status/../jobs` matcher ikke. Alt som ikke er de
   tre rutene blir 404 **før** forespørselen når maskinen.
2. **Bearer-token.** API-et krever det uansett hvor kallet kommer fra.
   Tunnelen er transport, ikke autentisering.
3. **Token-scope.** Tokenet som brukes utenfra har scope `status` og får 403
   på alt annet. Lekker det, er det ikke en kundedatalekkasje.

Verifisert utenfra 16.09.2026:

| rute | status-token | uten token | FULL token |
|---|---|---|---|
| `/api/status` | 200 | 401 | 200 |
| `/api/status/summary` | 200 | 401 | 200 |
| `/api/status/id` | 200 | 401 | 200 |
| `/api/health` | 404 | 404 | **404** |
| `/api/queue` | 404 | 404 | **404** |
| `/api/jobs` | 404 | 404 | **404** |
| `/panel` | 404 | 404 | **404** |
| `/api/statusXYZ` | 404 | 404 | **404** |

Den siste kolonnen er poenget: selv et token med full tilgang kommer ikke til
kundedata gjennom tunnelen, fordi ruten ikke finnes der.

`/api/health` er bevisst **ikke** eksponert, selv om den ser ut som et
helsesjekkepunkt: den returnerer hele ComfyUI-argv, altså filsystemstier.
Statusen er skilt ut i `flow/worker/status.py` nettopp for å ha ett svar som
er trygt å sende ut. Svaret er ~1,2 kB og inneholder ingen stier, ingen navn
og ingen ordrenummer — det er dekket av en test i
`flow/worker/tests/test_flow.py`.

ComfyUI (8189), n8n (5678), mockup-serveren (8790) og RabbitMQ har ingen regel
i `config.yml` og skal aldri få en.

## Flere servere

`server.label` i `config/flow.json` er `dp-01`, og vertsnavnet følger samme
mønster. Neste maskin blir `dp-02.hageai.com` med sin egen tunnel og sitt eget
`status`-token. `server.id` i svaret er en UUID i `state/server_id.json` som
følger maskinen, ikke vertsnavnet — så et navnebytte lager ikke en ny server i
flåtevisningen, og to PC-er som tilfeldigvis heter det samme smelter ikke
sammen til én.

En flåtestyrer poller `/api/status/summary` per server: én linje med
`server_id`, `label`, `status`, `busy`, `waiting` og `accepting_jobs`.

## Drift

```powershell
.\dreampage.ps1 ensure       # starter tunnelen hvis den er nede
.\dreampage.ps1 status       # viser tunnel-status
Get-Content state\log\tunnel.err.log -Tail 20
```

Slå den av helt:

```powershell
Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
  Where-Object { $_.CommandLine -like '*dp-01-status*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
C:\Users\tobia\Downloads\cloudflared.exe tunnel delete dp-01-status
# og slett CNAME dp-01.hageai.com i Cloudflare
```

Å slette tunnelen trekker tilbake legitimasjonen i
`~/.cloudflared/c6ecc2db-….json` — det er den eneste kopien.

`cloudflared.exe` ligger i `C:\Users\tobia\Downloads\`. Det er skjørt: en
opprydding i Downloads tar ned tunnelen. Flytt den til
`C:\Program Files\cloudflared\` og rett stien i `dreampage.ps1` når du får
anledning.

## Fallgruve som traff oss

`cloudflared tunnel route dns dp-01-status dp-01.hageai.com` opprettet CNAME-en
mot **feil tunnel** — den leste `tunnel:`-feltet i `~/.cloudflared/config.yml`
(`1506ea11…`, prosjektet `remote.hageai.com`) i stedet for tunnelen som ble
oppgitt som argument. Loggen sa det rett ut: `will route to this tunnel
tunnelID=1506ea11…`. Rettet ved å sette CNAME-innholdet direkte via
Cloudflare-API-et.

**Les alltid tunnelID-en i utskriften fra `route dns`.** Blir den feil, svarer
vertsnavnet 404 fra en tunnel som ikke har regelen — altså ingen lekkasje, men
en rute som ser død ut uten forklaring.

## Filer her

| Fil | I git | Merknad |
|---|---|---|
| `config.yml` | ja | ingress, med tunnel-id |
| `README.md` | ja | denne |

Tunnellegitimasjonen ligger i `~/.cloudflared/c6ecc2db-….json` og skal **ikke**
flyttes hit — den er en nøkkel, ikke konfigurasjon, og mappa her er i git.
