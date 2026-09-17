# Runbook — drift og feilsøking

For deg som står midt i det. `CLAUDE.md` er reglene, `ARCHITECTURE.md` er
hvorfor, dette er *hva gjør jeg nå*.

---

## Daglig

```powershell
.\dreampage.ps1 status     # hva lever, hva står i køen, hvor står ordren
.\dreampage.ps1 logs       # følg flow-loggen
.\dreampage.ps1 up         # start alt som er nede
.\dreampage.ps1 down       # nekter å stoppe midt i en ordre uten -Force
.\dreampage.ps1 test       # alle testene + check_assets. Kjør før commit
```

Panelet: `http://127.0.0.1:8765/panel`, med et token fra `config/api.json`.

**Portkart**

| Port | Hva | Hvem når den |
|---|---|---|
| 8189 | ComfyUI (produksjon) | lokalt |
| 8765 | hele API-et + panel | 127.0.0.1 + tailnet. **Aldri tunnel** |
| 8766 | bare `/api/status*` | tunnelen peker hit |
| 8790 | mockup-serveren | lokalt |
| ~~8188~~ | gammel ComfyUI | skal bort, se nederst |

---

## «Hvor står ordrene?»

Oversikt over alle, fra payload til Gelato-utkast:

```powershell
python tools\order_status.py            # de 20 nyeste
python tools\order_status.py --open     # BARE de som ikke er ferdige
python tools\order_status.py --order 1517
python tools\order_status.py --gelato   # bekreft mot Gelato (tregere)
```

`--open` er den du vil ha om morgenen: den viser ordre som har betalt og ikke
er ferdige. Ordre 1517 lå i tre døgn uten at noen visste det.

Én ordre i detalj, fra jobb-DB-en:

```powershell
python flow\worker\cli.py status --job-key 1515
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/jobs/1515
```

Du får status, hvilket steg, hvert forsøk med varighet og feiltekst. Det er
dette som erstattet n8n sin execution-historikk — og som gjør at ordre 1517 sin
«`success` på 1,3 sekunder uten å ha bygget noe» ikke kan gjenta seg.

**Siden 16.09.2026 varsler systemet selv på Telegram når en jobb feiler.** Får
du ingen melding, har ingen ordre feilet — eller varslingen er nede, og det
sier loggen.

### Kjøre en feilet ordre om igjen

```powershell
curl -X POST -H "Authorization: Bearer <token>" `
     http://127.0.0.1:8765/api/jobs/1515/retry
```

Rett **årsaken** først. En jobb merket `permanent` er jobbens egen feil (bok
uten `config.json`, ordre uten gender) og blir ikke bedre av å prøves igjen.
Den ackes med vilje, slik at den ikke spiser køen som en poison message.

---

## Vanlige feil

### «Ordren ligger i køen, ingenting skjer»

```python
# står noen på køen i det hele tatt?
import sys; sys.path.insert(0, "flow")
import dp_secrets, pika
c = dp_secrets.get("rabbitmq")
con = pika.BlockingConnection(pika.ConnectionParameters(
    host=c["hostname"], port=int(c.get("port") or 5672),
    virtual_host=c.get("vhost") or "/",
    credentials=pika.PlainCredentials(c["username"], c["password"])))
r = con.channel().queue_declare(queue="dreampage-jobs", passive=True)
print(r.method.message_count, "meldinger,", r.method.consumer_count, "konsumenter")
```

`consumer_count = 0` → workeren er nede. Det er den ene linjen som betyr mest.
`consumer_count = 2` → **to maskiner tar ordre samtidig.** Stopp den ene nå.

### «Boka fikk feil åpningsside / halv tittel på forsiden»

Dette er husets farligste feilklasse: et fail-soft fallback som ikke sa fra.

```powershell
python tools\check_assets.py --list
```

Siden 16.09.2026 er den også **steg nummer én** i pipelinen, så en ordre stopper
før rendring i stedet for å bli bygget feil. Kjør den manuelt hvis du har
flyttet på kunst, fonter eller mapper.

Se `CLAUDE.md` → «Den viktigste feilklassen».

### «Boka fikk plutselig gamle basebilder / upersonaliserte sider»

Ordre 1528. Skjer når `comfy/` er tom eller ufullstendig og noen bygger om
**uten** `--skip-prepare`: `prepare_order` kopierer base-malene over `input/`
først, og bare de sidene den finner i `comfy/` blir erstattet med de
faceswappede. Resten blir stående som råe maler, og PDF-guarden merker
ingenting — den teller sider, ikke om de er personaliserte.

`comfy/` er som regel tom fordi `cleanup_comfy_folder` sletter den når
Gelato-utkastet er laget.

Siden 17.09.2026 avgjør `assert_comfy_complete()` dette selv i `rebuild_pdfs`,
på begge veier (botten og pipelinen). Er `comfy/` ufullstendig, sjekker den
`input/`:

* **Ligger alle sidene ferdige og personaliserte der?** Da hopper den over
  `prepare` av seg selv og bygger videre. Dette er normaltilstanden for enhver
  ordre som alt har et Gelato-utkast, og krever ingenting av deg.
* **Mangler en side, eller er en av dem byte-identisk med malen?** Da stopper
  den — og da hjelper ingen `--skip-prepare` heller: sidene må gjennom ComfyUI
  igjen (`retry`, eller render fra Telegram). Se også
  `orders/<id>/backup-reprint-*/input/`, som lages før hver ombygging.

Den første utgaven stoppet i *begge* tilfellene og ba operatøren skrive
`--skip-prepare` selv. 17.09.2026 sto 1536, 1537 og 1538 samtidig og ventet på
det, og hele flyten stoppet. En guard som vet nok til å velge, skal velge.

Slik ser du om en ordres `input/` er personalisert:

```powershell
python tools\check_personalized.py 1528
```

### «Gelato-utkastet ser ferdig ut, men lar seg ikke bestille»

Nesten alltid: Gelato fikk aldri lastet ned PDF-en, og item-et står uten fil.
Klassisk årsak er en Drive-`/uc`-lenke på en fil over 100 MB — den gir en
HTML-advarselside, Gelato laster ned 2 kB HTML, og ingenting varsler.

Sjekk selv:

```python
import sys; sys.path.insert(0, "flow")
import gelato_api
print(gelato_api.verify_draft("<draft-id>"))
```

`upload_and_draft` kjører denne automatisk nå, **før** det gamle utkastet
slettes — feiler den, er det gamle utkastet fortsatt det beste vi har.

### «PDF-en har feil antall sider»

`dream_pdf_guard` godtar 30 eller 31 innersider og nøyaktig 33 samlet. Feil
antall stopper ordren, og **det er meningen**: en PDF med 14 innersider blir en
trykt bok med 14 innersider. Ikke slakk guarden — finn den manglende sida.

`verify_pages` skal fange det før PDF-en bygges. Gjør den ikke det, er det en
bug verdt å se på.

### «Drive-opplastingen feiler»

`drive_upload.py` har resumable opplasting med retry på 408/429/5xx siden
16.09.2026 (ordre 1512 døde på én HTTP 500). Feiler den likevel:

* 403 → legitimasjonsproblem, ikke transient. Sjekk `.n8n\database.sqlite`
  og `.n8n\config`.
* «feilet etter 6 forsøk» → Google er faktisk nede, eller nettet er borte.

```powershell
python flow\worker\tests\test_drive_upload.py   # logikken, uten nett
```

### «ComfyUI svarer tregt / `/prompt` timer ut»

Tung lokal RAM-bruk sulter ut ComfyUIs event-loop. En side gikk fra 69 s til
178 s. Ikke kjør minnetunge ting mens en ordre går.

Sjekk også at du snakker med **riktig** instans:

```powershell
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/status
#   → image.is_dreampage_image og image.models_visible
```

---

## Operatørboten

Egen prosess, egen bot-token, allowlist på chat-ID.

| Kommando | Hva |
|---|---|
| `/vis 1235 [3,7]` | sidene slik de ligger i boka nå |
| `/fix 1235 3,7` | render nye varianter av oppgitte sider |
| `/nyttbilde 1235` | bytt barnebildet, render alle sider på nytt |
| `/bygg 1235` | bygg PDF på nytt uten å endre sider |
| `/status 1235` | hvor ordren står |
| `/avbryt 1235` | forkast økten (ingenting er skrevet til boka enda) |
| `/chatid` | din chat-ID — slipper alltid gjennom allowlisten |
| `/hjelp` | |

Sender du et bilde mens en side venter på svar, brukes **det** bildet.
**Send det som fil (dokument)** — Telegram komprimerer vanlige bilder.

Ingenting rører boka før du har godkjent, og Gelato-utkastet lages først når du
trykker på knappen.

### Ferdigstille en ordre manuelt

```powershell
python flow\reprint_order.py --order 1512 --dry-run           # se hva som skjer
python flow\reprint_order.py --order 1512 --gelato --apply    # bygg + Drive + utkast
python flow\reprint_order.py --order 1512 --gelato --skip-prepare --apply
```

`--skip-prepare` bruker `input/` som den er — bruk den når operatøren har byttet
sider manuelt. `--no-drive` hopper over opplastingen. Uten `--gelato` lages
**ikke** noe utkast, og det er med vilje.

Kjeden avbryter på første feilende steg.

---

## Legge til en ny bok

Kortversjon; detaljene ligger i `books/<en-bok-som-virker>/`.

1. `books/<slug>/` med `config.json`, `workflow_api.json` og `base/`.
2. Filnavnkonvensjonen `…(slug).png` må følges — prepare-scriptet og
   `patchNodes` bygger på den.
3. `patchNodes` peker på node-ID-ene i `workflow_api.json`
   (`template`, `face`, `output`, `mask`).
4. Tekstscript per språk i `flow/text/<locale>/`, registrert i `textScripts`.
5. `driveFolderId` — uten den feiler `upload_and_draft`.
6. `expectedInnerPages` (30 eller 31).
7. Registrer boka i worker/Title Tester.

Verifiser **før** den selges:

```powershell
python tools\check_assets.py
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/books
#   → buildable per bok
```

> Dette står her på grunn av ordre 1517: «Hestestjernen» var kjøpbar på
> nettsiden mens `books/hestestjellet/` manglet `config.json`, kunst og
> workflow. n8n kjørte i 1,3 sekunder og skrev `success`. Kunden ventet i et
> døgn. **En bok skal ikke være kjøpbar før `buildable` er sann.**

---

## Kjente skjevheter

Ting som ikke er feil i dag, men som vil overraske deg.

**`books/det-morke-fjellet/` og `books/det-mørke-fjellet/`** er to mapper med
identisk innhold — én med ø, én uten. Begge har bare 1 side og ingen
`driveFolderId`, altså uferdige. Bare ASCII-varianten er referert fra
`config/next_book_titles.json`. Ikke selg noen av dem før én er ryddet bort.

**Rundt 60 hardkodede `C:\DreamPage-OS`-stier** ligger igjen i gammel kode, selv
om `flow/paths.py` finnes nettopp for å hindre det. Ikke legg til flere; bytt
dem ut når du likevel er inne i en fil.

**Boten og workeren deler ikke tilstand.** `dp_bot.py` shell-er ut til
`reprint_order.py` og holder sin egen state i `state/reprint/`. Derfor finnes
`INFLIGHT_DIR` og `recover_builds()` — et bygg lever i botprosessens minne og
forsvinner hvis den dør. Flow har allerede løst det problemet med sjekkpunkter.
Den dagen boten POSTer til `/api/jobs` i stedet, kan markørfilene slettes.

**Den gamle ComfyUI-en på port 8188 kjører fortsatt.** Den er startet elevert
fra `C:\ComfyUI`, har tom kø, men holder GPU-minne sammen med produksjonen
(21,1 av 24,5 GB brukt). Den er også en felle: et script som treffer 8188
snakker med en instans uten modellene — det skjedde med
`build_face_variants.py`, som hadde 8188 hardkodet som fallback, og
trist-varianten gikk stille mot en modelløs instans.

Den bør stoppes, men **ikke mens en ordre rendrer**:

```powershell
.\dreampage.ps1 status          # ingen jobb må stå som running
# så, som administrator:
Stop-Process -Id <pid-for-8188> -Force
```

Finn PID-en med:

```powershell
Get-NetTCPConnection -LocalPort 8188 -State Listen |
    Select-Object -ExpandProperty OwningProcess
```

`C:\ComfyUI`-mappa kan bli stående til du har kjørt et par ordre uten den.

---

## Backup — hva må overleve

| | Hvorfor |
|---|---|
| `state/orders/*.json` | adresse, e-post, `continue_code`. Finnes ikke andre steder |
| `state/jobs.sqlite` | ordrehistorikken |
| `state/gelato_drafts/*.json` | hvilket utkast hører til hvilken ordre |
| `config/secrets.json`, `api.json`, `dp_bot.json` | ikke i git |
| `~\.n8n\database.sqlite` + `config` | Drive-legitimasjonen |
| `books/*/orders/` | ferdige PDF-er og godkjente input-bilder |

`output/` kan gjenskapes, men koster GPU-timer.

**`continue_code` regenereres aldri.** Mister du `state/orders/`, kan en reprint
ikke lenger bruke samme kode — og koden er trykt i boka.
