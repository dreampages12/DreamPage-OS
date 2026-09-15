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
| `assets/` | fonter, logo, bakside, ryggrad, lastpages |
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
.\dreampage.ps1 test      # 14 tester
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
- **Godkjenning er manuell.** `flow` lager et Gelato-**utkast** og varsler.
  Mennesket bestiller. Ingen kode her bekrefter en ordre.
- **Tung lokal RAM-bruk sulter ut ComfyUI sin event-loop.** En side gikk fra
  69 s til 178 s og `/prompt` timet ut. Ikke kjør minnetunge ting mens en
  ordre går.

## Status per 2026-09-15

| Fase | Status |
|---|---|
| 0 — kode i git | **ferdig** |
| 1 — navnebytte `C:\ComfyUI` → `DreamPage-image` | **verktøy klart, venter på elevert kjøring** |
| 2 — flow med side-løkken | **bygget og testet, patchen ikke kjørt** |
| 3 — jobb-DB og logging | **ferdig** |
| 4 — API | **ferdig og verifisert** |
| 5 — resten av pipelinen | **bygget, ikke aktivert** (`ACTIVE = "pages"`) |
| 6 — cloudflared | **config klar, venter på Cloudflare-tilgang** |
| 7 — panel, supervisor, manifest | **ferdig** |

n8n-workflowen `xy8qiRUzcBpH52CI` er **aktiv og urørt**. Ingenting i dette
repoet har endret produksjonsoppførsel.

### Det som gjenstår, i rekkefølge

1. **Kjør navnebyttet.** Som administrator, fra et vindu som ikke står i
   `C:\ComfyUI`:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\DreamPage-OS\tools\migrate\phase1a_move.ps1
   ```
   Deretter, uten elevering:
   ```powershell
   python C:\DreamPage-OS\tools\migrate\rewrite_paths.py --dry-run
   python C:\DreamPage-OS\tools\migrate\rewrite_paths.py --apply --n8n
   ```
   Kjør så en ekte ordre gjennom n8n. Fjern til slutt junctionen
   (`C:\ComfyUI`) og kjør én ordre til — så lenge den finnes vet vi ikke om
   sti-inventaret er komplett.

2. **Sett fase 2 i drift.** Når fase 1 er verifisert:
   ```powershell
   .\dreampage.ps1 up
   python tools\migrate\patch_n8n_call_flow.py --dry-run
   python tools\migrate\patch_n8n_call_flow.py --apply
   ```
   Legg to ordre på køen samtidig og se at de kjører etter hverandre.

3. **Fase 5:** sett `ACTIVE = "full"` i `flow/worker/pipeline.py`, kjør én
   ordre, og deaktiver n8n-workflowen (ikke slett den).

4. **Fase 6:** se `tunnel/README.md`.

### To ting jeg ikke kunne gjøre

- **Navnebyttet** krever en elevert prosess, og ingen prosess kan døpe om en
  katalog som er en annens arbeidsmappe. Se punkt 1 over.
- **Tunnelen** kjører i dag med `--token`, altså fjernstyrt ingress. Å bytte
  den ut krever Cloudflare-innlogging. Se `tunnel/README.md`.

### Ett åpent produksjonsproblem

**Ordre 1517** (Ingvild, «Hestestjernen», 2026-09-15 19:00) er ikke levert.
`books/hestestjernen/` har ingen `config.json`, ingen kunst og ingen workflow —
boka er kjøpbar på nettsiden men finnes ikke i systemet. n8n-execution 2970
varte 1,3 sekund og ble markert `success`. Barnebildet er lastet ned
(`input/1517.jpg`); ingenting annet er gjort.

`books/regnbuens-skatt/` har samme mangel og vil feile likedan.

`GET /api/books` svarer nå `buildable` per bok, og `validate_job` avviser en
slik ordre med én setning som sier hva som mangler — i stedet for å dø stille.
Men selve ordren må håndteres av et menneske: enten legges boka inn (se
`dreampage-add-new-book`), eller kunden kontaktes.
