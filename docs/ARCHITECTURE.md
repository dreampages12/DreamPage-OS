# Arkitektur

Hvordan DreamPage OS henger sammen, og hvorfor det ser slik ut. Leser du dette
for å endre noe, les `CLAUDE.md` først — reglene der er ikke smakssaker.

---

## 0. Servermodus: hva denne maskinen er til

`config/flow.json` → `"mode"` avgjør to ting, og bare de to: hvilken
RabbitMQ-kø serveren lytter på, og hvilken pipeline den kjører.

```
DreamPage OS  (config/flow.json -> mode)
  ├── BOOK     -> dreampage-jobs -> DreamPage Flow: Book Generation   (kap. 1)
  └── PREVIEW  -> preview-jobs   -> DreamPage Flow: Preview Generation
```

**Denne maskinen står i `book`.** Resten av dette dokumentet beskriver den
modusen. Preview-modus har sitt eget: `docs/preview-modus.md`.

Alt annet er felles — jobb-DB, API, panel, logg, status, avbrudd, retry,
ack-semantikk og side-løkka mot ComfyUI. Det er infrastruktur, og den skal
ikke finnes i to utgaver. Det som er forskjellig er arbeidsflyten, og den
står som en liste i `pipeline.py` i begge tilfeller.

```powershell
.\dreampage.ps1 mode              # hva står den til
.\dreampage.ps1 mode preview      # bytt (krever restart)
```

### Windows og Linux

Denne maskinen kjører Windows. Nye maskiner settes opp på Linux, og det er
**samme kode** — ingen gren, ingen fork. Forskjellene ligger tre steder:

| | |
|---|---|
| `flow/dp_platform.py` | oppetid, `~/.n8n`, kjørbare filer, hvilken vaktmester |
| `dreampage.ps1` / `dreampage.sh` → `tools/dreampage.py` | supervisoren |
| `deploy/systemd/` | vaktmesteren, motstykket til Task Scheduler |

Alt annet er felles fordi stiene utledes fra `flow/paths.py` og aldri
hardkodes. `tools/check_portability.py` kjøres av `dreampage.ps1 test` og
finner de tre tingene som faktisk brekker: hardkodede stier, filnavn med feil
bokstav (usynlig på Windows, dødelig på Linux) og Windows-bare API-er.

Se `docs/SETUP-LINUX.md`.

---

## 1. Fra kjøp til trykk

```
  ┌─ WordPress / WooCommerce ──────────────────────────────────┐
  │  kunden kjøper, laster opp bilde av barnet, får            │
  │  continue_code. Publiserer SELV til RabbitMQ.              │
  └────────────────────────┬───────────────────────────────────┘
                           │  payload: source = dreampage_woocommerce
                           ▼
  ┌─ RabbitMQ  100.118.194.49:5672  vhost dreampages ──────────┐
  │  kø: dreampage-jobs      (én konsument)                    │
  └────────────────────────┬───────────────────────────────────┘
                           │  prefetch=1, manuell ack
                           ▼
  ┌─ flow/worker  (én prosess, én arbeidstråd) ────────────────┐
  │                                                            │
  │  mq.py       konsumenten. Ack først ved sjekkpunkt.        │
  │  runner.py   den interne køen. Én jobb om gangen.          │
  │  pipeline.py rekkefølgen, som DATA                         │
  │  steps.py    fram til sidene                               │
  │  steps_post  fram til Gelato-utkastet                      │
  │  jobs.py     SQLite: hvor stoppet ordren, og hvorfor       │
  │  api.py      FastAPI 8765 (alt) / status_api 8766 (status) │
  │  notify.py   Telegram: én vei ut                           │
  └────────────────────────┬───────────────────────────────────┘
                           ▼
  ComfyUI (DreamPage-image, :8189)  →  output/<bok>/orders/<job_key>/comfy/
                           ▼
  tekstscript (flow/text/<locale>/)  →  PDF-er  →  dream_pdf_guard
                           ▼
  Google Drive  →  Gelato-UTKAST  →  Telegram til operatøren
                           ▼
                    et MENNESKE bestiller
```

Pipelinen bestiller aldri. Den lager et utkast og sier fra.

---

## 2. Hvorfor `flow` finnes

Dette var n8n før. Logikken lå som 82 noder med JavaScript i en SQLite-blob —
å fikse en bug krevde et Python-script som gjorde strengerstatning og PUT-et
tilbake. Det finnes rundt 30 slike i `archive/`.

n8n kjørte executions **parallelt uten delt minne**, mens ComfyUI tåler én jobb
om gangen. Forskjellen ble håndtert av `.dreampage-comfy.lock` med
acquire/release/TTL/stale/token/eierskap — cirka 200 linjer JavaScript spredt
over fire noder. To produksjonsinsidenter på to dager lå i nøyaktig den
mekanismen:

* **14.09.2026** — to samtidige ordre stjal hverandres ferdige sider.
  Sidenøklene (`page00`..`page15`) er like i alle bøker, så hver ordre
  konkluderte med at den andres sider var dens egne og hoppet over dem. Bildene
  var ikke feil, de var *borte*.
* **15.09.2026** — en død lås blokkerte en uskyldig ordre i 50 minutter.

`flow` er én prosess med én arbeidstråd som tar én jobb av en `queue.Queue` om
gangen. **Serialiseringen er en egenskap ved konstruksjonen** og kan ikke feile
uten at koden endres. Låsen er ikke migrert — den er slettet.

Den tredje feilklassen var ack-semantikk. n8n-noden hadde riktignok
`acknowledge: laterMessageNode`, men ack-en lå langt nede i grafen og ble
hoppet over på hver gren som ikke gikk helt fram. Ordre 1499 kom tre ganger på
én dag. Her er regelen én setning:

> Meldingen ackes først når jobben har nådd et varig **sjekkpunkt**, og nackes
> tilbake på køen hvis den ikke nådde dit.

Da er en redelivery kjedelig i stedet for farlig: nådde den ikke sjekkpunktet,
er ingenting varig gjort og jobben kjøres om; nådde den det, hopper hvert steg
over seg selv.

---

## 3. Pipelinen som data

`flow/worker/pipeline.py` er en liste, ikke en funksjon med if-er. Et steg er:

```python
Step(name, run, description, retries, timeout_s, checkpoint, optional)
```

| Felt | Betyr |
|---|---|
| `retries` | ekstra forsøk ved **systemfeil**. `JobError` retries aldri |
| `checkpoint` | arbeidet er varig lagret; RabbitMQ-meldingen kan ackes |
| `optional` | feiler steget, går ordren videre (sidespor) |

`config/flow.json` kan overstyre `enabled`, `retries` og `timeout_s` per steg.
**Rekkefølgen kan den ikke endre** — den er kode, og en pipeline der stegene kan
stokkes fritt er n8n på nytt.

### De to pipelinene

`PAGES_PIPELINE` går fram til og med sidene. `FULL_PIPELINE` er den samme,
pluss veien til Gelato-utkastet. `ACTIVE` velger hvilken som er standard, og
**`ACTIVE = "full"` siden 16.09.2026** — gjennomgangen skjer i Gelato-utkastet,
slik den alltid har gjort.

En **enkelt** ordre kan alltid kjøres gjennom den andre uten å røre `ACTIVE`:

```python
QueuedJob(job_key, payload, pipeline="pages")
```
```
POST /api/jobs   {"job_key": "1530", "pipeline": "pages", ...}
```

### Stegene i rekkefølge

| # | Steg | Sjekkpunkt | Merknad |
|---|---|---|---|
| 1 | `check_assets` | | all delt kunst finnes. Står først med vilje |
| 2 | `validate_job` | | ubyggbar bok avvises her, ikke stille |
| 3 | `persist_payload` | ✔ | `state/orders/<job_key>.json` |
| 4 | `setup_dirs` | | |
| 5 | `fetch_child_image` | | finnes bildet, røres det ikke |
| 6 | `face_variants` | | sidespor |
| 7 | `render_pages` | ✔ | side-løkka. Kan ta timer |
| 8 | `verify_pages` | | fanger manglende side her, ikke i PDF-guarden |
| 9 | `notify_pages_ready` | | sidespor; hopper over seg selv når `ACTIVE != "pages"` |
| 10 | `claim_post_comfy` | | |
| 11 | `wp_book_creating` | | sidespor |
| 12 | `build_pdfs` | ✔ | tekst → QR → PDF, med sidetall-guardene |
| 13 | `validate_gelato_files` | | logger MB, så en bok over 100 MB blir synlig |
| 14 | `upload_and_draft` | ✔ | Drive + Gelato-**utkast**, verifisert |
| 15 | `auto_merge_multibook` | | sidespor |
| 16 | `telegram_approval` | | sidespor |
| 17 | `wp_quality_check` | | sidespor |
| 18 | `cleanup_comfy_folder` | | sidespor. Kjøres bare når et utkast finnes |

`render_pages` har ingen retry på hele løkka — den er idempotent per side, så
en omkjøring plukker opp der den stoppet. Retry hører inne i
`comfy.render_page`, der den kan gjelde én side.

---

## 4. En bok

```
books/<slug>/
  config.json        definisjonen
  workflow_api.json  ComfyUI-grafen
  base/              malbilder og hodemasker
  script/            prepare_order_<slug>.py
  orders/<job_key>/  input/ og pdf/ for én ordre
```

`config.json`, forkortet:

```jsonc
{
  "slug": "fotballstjernen",
  "displayName": "Fotballstjernen",
  "textScripts": { "nb": "…/flow/text/nb/fotballstjernen-text-nb.py", "sv": "…" },
  "prepareScript": "…/books/fotballstjernen/script/prepare_order_fotballstjernen.py",
  "driveFolderId": "1YLLZ…",
  "comfyOutputPrefix": "fotballstjernen/orders",
  "patchNodes": { "template": "151", "face": "121", "output": "9", "mask": "165" },
  "pages": [ { "page_key": "page00",
               "template_image": "forside(fotballstjernen).png",
               "mask_image":     "forside-headmask(fotballstjernen).png",
               "face_expression": "noytral" } ],
  "expectedInnerPages": 31
}
```

`patchNodes` peker på node-ID-ene i `workflow_api.json` som skal byttes ut per
side: malbildet, barnets ansikt, hodemasken og output-noden. `books.py` kan
også **detektere** dem hvis de mangler, men en konfigurert verdi vinner alltid.

25 bøker, 5 språk (`nb`, `nn`, `sv`, `en-GB`, `en-US`). Å legge til en ny bok er
en egen sjekkliste — se `docs/RUNBOOK.md`.

### Tekstmotoren

`flow/text/<locale>/` er **selvstendige bunter**: hver har egne kopier av
`gelato_cover.py`, `dream_pdf_guard.py`, fontene og logoen, og tekstscriptene
importerer søsknene sine bart (`from gelato_cover import …`).

**De skal aldri splittes opp.** Det ville knekt alle 80+ tekstscriptene
samtidig. Den delte kunsten (`logo/`, `bakside/`, `ryggrad/`, `lastpages/`)
ligger der scriptene leter — altså under `flow/text/` — og ikke i en pen
`assets/`-mappe på rota. Det ble prøvd, og brakk produksjonen to ganger.

Hvert tekstscript finner DreamPage-rota slik:

```python
def _dp_find_root(start):      # går OPPOVER til den finner books/
```

Ikke `dirname(dirname(...))`. Det var nettopp det som gjorde at ordre 1506 ble
bygget med feil åpningsside da mappene ble flyttet.

---

## 5. API-et

To lyttere, og skillet mellom dem er hele sikkerhetsmodellen.

| Port | Hva | Eksponering |
|---|---|---|
| **8765** | hele API-et + `/panel` | 127.0.0.1 og Tailscale. **Aldri i en tunnel** |
| **8766** | BARE `/api/status`, `/status/summary`, `/status/id` | trygg å peke en tunnel mot |

`status_api.py` er en **egen FastAPI-app** der resten av rutene ikke er montert.
Poenget: en feilkonfigurert ingress mot 8766 kan i verste fall gi 404. En
feilkonfigurert ingress mot 8765 ville gitt ut ordrelista med barnenavn.
Grensen er en egenskap ved konstruksjonen, ikke et regex noen må huske å skrive
riktig. Testen `test_status_api_har_bare_statusruter` holder løftet.

Autentisering er bearer-token fra `config/api.json`, med to scopes:

```jsonc
{ "<token>": { "name": "panel",  "scope": "full"   },
  "<token>": { "name": "flaate", "scope": "status" } }
```

Ingen tokens konfigurert betyr **ikke** «åpent for alle» — det betyr 503.

Skriveendepunkter er rate-limitert (30/min per kaller). `/api/events` er SSE, så
panelet slipper å polle.

---

## 6. Jobb-databasen

`state/jobs.sqlite`, WAL, én fil, lest av API-et i samme prosess — det finnes
ikke to kopier av tilstanden.

| Tabell | Hva |
|---|---|
| `jobs` | én rad per `job_key`. Status, steg, fremdrift, feil, hele payloaden |
| `steps` | én rad per steg per forsøk, med varighet og feiltekst |
| `events` | tidslinje: start, ack, nack, duplicate, done, failed |
| `actions` | hvem ba om hva. Skiller en retry operatøren ba om fra en systemet tok |

Status-enum er fast: `pending`, `running`, `done`, `failed`, `cancelled`.
Ingenting kan være både ferdig og mislykket — det var nettopp det n8n skrev om
ordre 1517 (`success`, på 1,3 sekunder, uten å ha bygget noe).

En jobb som stod som `running` da prosessen døde blir satt tilbake til `pending`
og lagt på køen ved oppstart (`reset_stale_running`) — motsatt av den døde
låsefila, som bare blokkerte.

---

## 7. Operatørboten

`flow/dp_bot.py` er en egen prosess med **egen bot-token**. Det er ikke
valgfritt: `gelato_merge.py` long-poller `getUpdates` på produksjonsboten under
hver ordre, og bare én prosess kan eie `getUpdates` per token. Deler de token,
spiser de hverandres svar — og det som ryker er godkjenningen av et sammenslått
Gelato-utkast på en betalt ordre.

Boten lar operatøren se sidene, bytte enkeltsider, bytte barnebildet, og bygge
boka på nytt — uten å prompte. Den har allowlist på chat-ID (`allow_all` var
`true` en periode; 14.08.2026 sendte en ukjent chat melding til boten).

Boten og workeren deler ikke tilstand i dag: boten shell-er ut til
`reprint_order.py` og holder sin egen state i `state/reprint/`. Det er den
største gjenstående arkitekturgjelden — se `docs/RUNBOOK.md`.

---

## 8. Varsling

`flow/worker/notify.py` er den ene veien ut til Telegram. Tre kilder bruker den:

* `runner.py` når en jobb **feiler** — nytt 16.09.2026. Før dette fantes det to
  varsler, og begge fyrte bare når det gikk bra.
* `steps.notify_pages_ready` og `steps_post.telegram_approval`.
* `dreampage.ps1 ensure` når vaktmesteren ikke fikk en tjeneste opp igjen.

Varsling er **alltid et sidespor**. Den kan ikke kaste, og runneren fanger den
i tillegg — kastet den fra feilgrenen, ville `on_finished` forsvunnet og
RabbitMQ aldri fått sin ack.

---

## 9. Vaktmesteren

Scheduled task **«DreamPage OS»** kjører `dreampage.ps1 ensure` hvert 5. minutt
og ved innlogging. Den er stille når alt lever, har låsefil mot overlapp, og
varsler på Telegram når den ikke får noe opp igjen.

Bakgrunnen: før dette hadde bare `dp_bot` en vaktmester. Etter en omstart kom
boten tilbake, men ComfyUI og flow gjorde det **ikke** — og da hoper ordrene seg
opp i køen uten at noe sier fra. En død bot merkes med en gang; en død worker
ser ut som stillhet.

Scheduled task **«DreamPage cleanup»** kjører daglig 05:30
(`tools/cleanup_variants.py`, fem sperrer som alle må åpne før noe slettes).
Den gikk 04:30 fram til 18.09.2026 — midt i nattbruddet, da all utgående
HTTPS er nede 04:30–05:05 — og feilet mot Gelato. Se `flow/worker/net.py`.
