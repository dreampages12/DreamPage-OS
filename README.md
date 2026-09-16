# DreamPage OS

Produksjonssystemet for personaliserte barnebøker: kundens barn får ansiktet
sitt satt inn i ferdige bokmaler, teksten får barnets navn, det bygges PDF, og
den sendes til Gelato for trykk. Systemet selger ekte bøker til ekte kunder.

```
WooCommerce → RabbitMQ (dreampage-jobs) → flow → ComfyUI → PDF → Drive
            → Gelato-utkast → Telegram → mennesket bestiller
```

## Hvor ting er

| Mappe | Hva |
|---|---|
| `DreamPage-image/` | ComfyUI, pinnet upstream. **Innholdet redigeres aldri.** |
| `flow/` | pipeline-koden. `flow/worker/` er workeren + API-et |
| `flow/text/<locale>/` | tekstmotoren, én selvstendig bunt per språk |
| `books/<slug>/` | bokdefinisjon: `config.json`, `workflow_api.json`, `base/` |
| `nodes/` | egne ComfyUI custom nodes, symlinkes inn i `DreamPage-image/custom_nodes` |
| `flow/text/{logo,bakside,ryggrad,lastpages}/` | delt kunst. Ligger DER scriptene leter — en `assets/`-mappe på rota ble prøvd og brakk produksjonen to ganger, se `flow/paths.py` |
| `panel/` | dashbordet |
| `tunnel/` | cloudflared |
| `archive/` | utrangerte n8n-patcheskript, med §7-gjennomgangen |
| `tools/` | migrering og modellmanifest |
| `config/` | `flow.json` i git; `secrets.json`, `api.json`, `dp_bot.json` **ikke** |
| `models/ state/ output/ input/ tmp/` | ikke i git |

**`DreamPage-image/` er hellig.** Mappa har vårt navn, men innholdet er uendret
upstream ComfyUI. Den forkes ikke og filene der redigeres aldri. Alt vi vil
endre i ComfyUI skjer via `nodes/`, eller ved å gi ComfyUI andre stier på
kommandolinja (`--output-directory`, `--input-directory`,
`--extra-model-paths-config`). Dette er regelen som gjør at ComfyUI kan
oppdateres uten frykt. (ComfyUI er GPL-3.0; egen kjøring på egne maskiner er
ikke distribusjon, men å smelte den inn i vår kode ville smittet lisensen.)

## Daglig drift

```powershell
.\dreampage.ps1 up        # modellsjekk, ComfyUI, flow, mockup, bot, tunnel
.\dreampage.ps1 status    # hva lever, hva står i køen, hvilke ordre feilet
.\dreampage.ps1 down      # nekter å stoppe midt i en ordre uten -Force
.\dreampage.ps1 logs      # følg flow-loggen
.\dreampage.ps1 test      # alle testfilene + check_assets
```

Panelet: `http://127.0.0.1:8765/panel` — lim inn et token fra `config/api.json`.

Hvor stoppet ordre X, og hvorfor:

```powershell
python flow\worker\cli.py status --job-key 1515
# eller
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/jobs/1515
```

## Hvorfor flow finnes

n8n kjørte executions parallelt uten delt minne. ComfyUI tåler én jobb om
gangen. Forskjellen ble håndtert av `.dreampage-comfy.lock` med
acquire/release/TTL/stale/token/eierskap — rundt 200 linjer JavaScript spredt
over fire noder. To produksjonsinsidenter på to dager lå i nøyaktig den
mekanismen:

- **14.09.2026** — to samtidige ordre stjal hverandres ferdige sider. Sidenøklene
  (`page00`..`page15`) er like i alle bøker, så hver av dem konkluderte med at
  den andres sider var deres egne og hoppet over dem. Bildene var ikke feil,
  de var borte.
- **15.09.2026** — en død lås blokkerte en uskyldig ordre i 50 minutter.

`flow` er én prosess med én arbeidstråd som tar én jobb av en kø om gangen.
Serialiseringen er en egenskap ved konstruksjonen og kan ikke feile uten at
koden endres. Låsen er ikke migrert — den er slettet.

De to andre feilklassene: logikken lå som JavaScript i en SQLite-blob (å fikse
en bug krevde et Python-skript som gjorde strengerstatning og PUT-et tilbake —
det finnes ~30 slike, i `archive/`), og ack-semantikken var løs, så samme
ordre kunne leveres flere ganger. Ordre 1499 kom tre ganger på én dag.

## Domenekunnskap som ikke må brytes

Dette er dyrekjøpt. Bryter du noe av det, går det ut til en kunde.

- **`job_key`, ikke `order_id`.** Én WooCommerce-ordre kan inneholde flere
  bøker. Da har alle samme `order_id` (`1411`) og bare `job_key` skiller dem
  (`1411-b1`, `1411-b2`). `job_key` er mappe- og filnøkkelen overalt.
- **`continue_code` regenereres ALDRI.** Den lages bare i WordPress. En
  reprint må bruke samme kode — trykk er permanent.
- **Kun hardcover selges.** Softcover er default i koden, så `cover_type`
  sendes alltid eksplisitt.
- **«Er siden ferdig?» ser KUN i ordrens egen output-mappe.** Se 14.09 over.
- **`page99_next`** er forsidebildet til «fortsett eventyret»-siden. Den er
  ikke en vanlig side og teller ikke i `expectedInnerPages`.
- **PDF-guarden er streng:** innersider må ha nøyaktig `expectedInnerPages`
  (30 eller 31), samlet PDF nøyaktig 33. Feil antall stopper ordren. Det er en
  funksjon — en PDF med 14 innersider blir en trykt bok med 14 innersider.
- **Drive-filer over 100 MB** må bruke `drive.usercontent`-URL. `/uc`-lenka
  gir en HTML-advarselside, Gelato laster ned 2 kB HTML, og item-et står igjen
  med `files[0].id = null` uten at noe varsler. Traff ordre 1300 (105,7 MB).
- **Godkjenning er manuell, og den skjer I UTKASTET.** `flow` bygger hele
  veien til et Gelato-**utkast** og varsler. Mennesket ser gjennom boka i
  Gelato og bestiller der. Ingen kode her bekrefter en ordre.
- **Tung lokal RAM-bruk sulter ut ComfyUI sin event-loop.** En side gikk fra
  69 s til 178 s og `/prompt` timet ut. Ikke kjør minnetunge ting mens en
  ordre går.

## Status per 2026-09-16

| Fase | Status |
|---|---|
| 0 — kode i git | **ferdig** |
| 1 — ComfyUI kjører fra `DreamPage-image/` | **ferdig** (gammel instans på 8188 gjenstår, se under) |
| 2 — flow eier side-løkken | **ferdig, i produksjon** |
| 3 — jobb-DB og logging | **ferdig** |
| 4 — API | **ferdig** |
| 5 — hele veien til Gelato-utkast | **aktiv** (`ACTIVE = "full"`) |
| 6 — cloudflared | **live**: `https://dp-01.hageai.com/api/status*` |
| 7 — panel, supervisor, manifest | **ferdig** |

**n8n eier ikke lenger noen del av ordreveien.** WooCommerce publiserer selv
til RabbitMQ, og alle ordre-workflowene i n8n er deaktiverte. Dette er
verifisert mot både broker og n8n-API — se `docs/ordreveien.md`. (Tidligere
utgaver av denne fila påsto at `xy8qiRUzcBpH52CI` var «aktiv og urørt». Det var
feil, og det er en farlig ting å ta feil om.)

n8n-*prosessen* kan være nede uten at en bokordre stopper. To filer må likevel
bevares, fordi produksjonskode leser SQLite-fila direkte:
`~\.n8n\database.sqlite` (gamle ordre-payloads) og `~\.n8n\config`
(encryptionKey for Google Drive-legitimasjonen).

### Dokumentasjon

| Fil | Hva |
|---|---|
| `CLAUDE.md` | **les først.** Regler, feilklasser, konvensjoner |
| `docs/ARCHITECTURE.md` | hvordan delene henger sammen, og hvorfor |
| `docs/RUNBOOK.md` | drift, feilsøking, ny bok, kjente skjevheter |
| `docs/SETUP-NEW-PC.md` | sette opp en ny maskin |
| `docs/ordreveien.md` | hvordan en ordre faktisk kommer inn, verifisert |

### Det som gjenstår

1. **Den gamle ComfyUI-en på port 8188.** Startet elevert fra `C:\ComfyUI`,
   tom kø, men holder GPU-minne sammen med produksjonen og er en felle for
   scripts som har 8188 som fallback. Stopp den når ingen ordre rendrer — se
   `docs/RUNBOOK.md` → «Kjente skjevheter». Krever elevering.

2. **Boten mot API-et.** `dp_bot.py` shell-er ut til `reprint_order.py` og
   holder egen tilstand i `state/reprint/`. Flow har allerede løst det samme
   problemet med sjekkpunkter og jobb-DB. Den dagen boten POSTer til
   `/api/jobs`, blir et `/bygg` synlig i panelet, overlever en botrestart og
   serialiseres mot ordrekøen av konstruksjon.

3. **Rundt 60 hardkodede `C:\DreamPage-OS`-stier** i gammel kode, selv om
   `flow/paths.py` finnes for å hindre nettopp det.
