# tunnel/ — cloudflared

Tunnelen er det eneste som slipper trafikk **inn** til maskinen. Alt utgående
— RabbitMQ over Tailscale, Gelato, Google Drive, Telegram — fungerer uten den
og skal ikke røres.

## Status: i drift på hageai, venter på ett dashbord-steg for dreampage.store

```
https://dp-01.hageai.com/api/status           <- VIRKER NÅ
https://dp-01.hageai.com/api/status/summary
https://dp-01.hageai.com/api/status/id
alt annet                                     -> 404 i Cloudflares kant

https://tobias-pc.dreampage.store/api/status  <- mangler public hostname
```

Origin er **`127.0.0.1:8766`**, ikke 8765. Se neste avsnitt — det er hele
grunnen til at flyttingen er trygg.

Tunnel `dp-01-status` / `c6ecc2db-f411-4dec-949e-5e55cc0e99f7`, konfigurert i
`config.yml`, startet som egen prosess og holdt i live av
`dreampage.ps1 ensure` (tjenesten `tunnel-status`).

## Porten er grensen, ikke regexet

Fram til 16.09.2026 lå forsvaret mot at kundedata slapp ut i et **sti-regex**
i `config.yml`. Det holdt så lenge tunnelen var vår egen, med ingress i en fil
vi eier.

`tobias-pc.dreampage.store` er det ikke. Den må ligge på tunnelen som allerede
står i `dreampage.store`-kontoen, og den kjører med `--token` — altså
**fjernstyrt ingress**, der en rute bare er «hostname → service», uten
sti-filter. Pekt mot 8765 ville `/api/jobs` og `/api/queue` (barnenavn,
ordrenummer) og `/api/health` (filsystemstier) fulgt med ut.

Svaret er ikke et strammere regex, men at porten som eksponeres **ikke har noe
annet å nå**:

| port | innhold | tunnel? |
|---|---|---|
| 8765 | hele API-et: jobs, queue, health, panel | **aldri** |
| 8766 | bare `/api/status*` | ja, trygt |

8766 er `flow/worker/status_api.py` — en egen uvicorn-lytter i en tråd i
worker-prosessen, med tre ruter montert og resten av API-et fraværende. En
feilkonfigurert ingress mot 8766 kan i verste fall gi 404. Grensen er en
egenskap ved konstruksjonen, ikke en regel noen må huske å skrive riktig.

Løftet holdes av `test_status_api_har_bare_statusruter` i
`flow/worker/tests/test_flow.py`, som sjekker rutelista, at ingen rute tar
annet enn GET, og at hver rute har `status_caller`. Legger noen en rute til,
feiler testen. Ikke utvid `ALLOWED_PATHS` for å få den grønn — flytt ruten til
`api.py`.

## Det som mangler: ett steg i dashbordet

`dreampage.store` ligger i en annen Cloudflare-konto. Verifisert mot API-et
16.09.2026: tokenet i `~/.cloudflared/cert.pem` ser **ett eneste** zone,
`hageai.com` (`d8ca3e90…`, konto `318433…`). En CNAME i `dreampage.store` kan
heller ikke peke på tunnelen vår, fordi tunnel og zone må ligge i samme konto.

> Zero Trust → Networks → Tunnels → tunnelen for `admin.dreampage.store`
> (`d9b1ec20…`) → **Public hostname** → Add
>
> * Subdomain: `tobias-pc`
> * Domain: `dreampage.store`
> * Service: `http://127.0.0.1:8766`   ← **8766, ikke 8765**

Verifiser etterpå, med et token med scope `status`:

```bash
curl -s -o /dev/null -w '%{http_code}
'   -H "Authorization: Bearer <status-token>"   https://tobias-pc.dreampage.store/api/status          # 200

for p in /api/jobs /api/queue /api/health /panel; do    # alle 404
  curl -s -o /dev/null -w "$p %{http_code}
"     -H "Authorization: Bearer <status-token>"     https://tobias-pc.dreampage.store$p
done
```

Først når den svarer kan `dp-01.hageai.com` ryddes bort (se nederst). Den som
virker rives ikke før den nye svarer.

Alternativet, hvis du heller vil ha sti-filteret med: `cloudflared tunnel
login` på `dreampage.store`-kontoen og en egen named tunnel der. Det krever
nettleser, og `--origincert` til en annen fil enn `cert.pem`, ellers mister du
muligheten til å administrere hageai-rutene.

## Tre lag, hvert av dem nok alene

0. **Porten.** Origin er 8766, der bare statusrutene finnes. Se over.
   Dette laget kan ikke konfigureres feil, og er derfor det viktigste.
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

ComfyUI (8189), n8n (5678), mockup-serveren (8790), RabbitMQ og det fulle
API-et (8765) har ingen regel i `config.yml` og skal aldri få en.

## Flere servere

`server.label` i `config/flow.json` er `tobias-pc`, og vertsnavnet følger
samme mønster: neste maskin får sin egen label, sitt eget vertsnavn under
`dreampage.store` og sitt eget `status`-token. Labelen er det MENNESKER leser
— den ble endret fra `dp-01` da statusen flyttet, og det endret ingenting
annet, fordi ingenting utenom `status.py` leser den. `server.id` i svaret er en UUID i `state/server_id.json` som
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
