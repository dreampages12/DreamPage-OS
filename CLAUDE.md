# DreamPage OS — les dette først

Dette systemet selger og trykker ekte bøker til ekte kunder for ekte penger.
En feil her blir ikke en rød test. Den blir en bok i posten til et barn, med
feil navn, feil bilde eller feil antall sider — og trykk kan ikke angres.

Jobb deretter. Når du er i tvil: spør, eller la være.

---

## Hva systemet gjør

Kunden kjøper en personalisert barnebok på nettbutikken og laster opp et bilde
av barnet sitt. Systemet setter barnets ansikt inn i ferdig tegnede boksider
(ComfyUI + head-swap), skriver barnets navn inn i teksten, bygger PDF-er, og
legger et **utkast** hos trykkeriet Gelato. Et menneske ser gjennom utkastet og
bestiller.

**Ingen kode her bestiller noe.** Pipelinen stopper ved utkastet. Det er med
vilje, og det skal den fortsette å gjøre.

## Servermodus: BOOK eller PREVIEW

`config/flow.json` → `"mode"` sier hva denne maskinen er til. Den avgjør to
ting, og bare de to: hvilken RabbitMQ-kø workeren lytter på, og hvilken
pipeline den kjører.

| Modus | Kø | Pipeline |
|---|---|---|
| `book` | `dreampage-jobs` | bokproduksjon, fram til Gelato-utkastet |
| `preview` | `preview-jobs` | forhåndsvisninger til nettbutikken |

**Denne maskinen står i `book`.** Alt under gjelder den modusen.
`docs/preview-modus.md` beskriver den andre. `.\dreampage.ps1 mode` viser og
bytter; en ukjent verdi er en feil, ikke «da tar vi book».

## Ordreveien, verifisert

```
WordPress / WooCommerce
      │  publiserer SELV til RabbitMQ
      ▼
RabbitMQ  100.118.194.49:5672  vhost dreampages  kø: dreampage-jobs
      │  (én konsument: vår worker)
      ▼
flow/worker  →  ComfyUI (DreamPage-image, port 8189)  →  output/
      │
      ▼
PDF-er  →  Google Drive  →  Gelato-UTKAST  →  Telegram til operatøren
```

**n8n er IKKE i ordreveien.** Alle ordre-workflowene er deaktiverte. Dette var
en farlig feilantakelse en gang, og den er verifisert bort mot både broker og
n8n-API — se `docs/ordreveien.md`.

n8n-prosessen kan være nede uten at en bokordre stopper. Men to filer må
bevares, fordi produksjonskode leser SQLite-fila direkte for å hente gamle
ordre-payloads og for å dekryptere Google Drive-legitimasjonen:

```
C:\Users\<bruker>\.n8n\database.sqlite
C:\Users\<bruker>\.n8n\config          (encryptionKey)
```

## Hvor ting er

| Mappe | Hva |
|---|---|
| `flow/` | all pipeline-kode. `flow/worker/` er workeren + API-et |
| `flow/text/<locale>/` | tekstmotoren, én selvstendig bunt per språk |
| `books/<slug>/` | `config.json`, `workflow_api.json`, `base/`, `orders/` |
| `DreamPage-image/` | ComfyUI. **Innholdet redigeres ALDRI** |
| `nodes/` | egne ComfyUI-noder, symlinkes inn i DreamPage-image |
| `tools/` | verktøy og migrering |
| `config/` | `flow.json` i git; `secrets.json`, `api.json`, `dp_bot.json` **ikke** |
| `panel/` | dashbordet |
| `state/ output/ input/ models/ tmp/` | ikke i git |

`docs/ARCHITECTURE.md` forklarer hvordan delene henger sammen.
`docs/preview-modus.md` er PREVIEW-modus: kø, pipeline, bokdata og levering.
`docs/RUNBOOK.md` er drift og feilsøking.
`docs/SETUP-NEW-PC.md` er å sette opp en ny maskin.

---

## Regler som ikke skal brytes

Dette er dyrekjøpt. Hver linje står her fordi den ble brutt én gang.

**`DreamPage-image/` er hellig.** Mappa har vårt navn, men innholdet er uendret
upstream ComfyUI. Filene der redigeres aldri. Alt vi vil endre skjer via
`nodes/`, eller ved å gi ComfyUI andre stier på kommandolinja. Dette er regelen
som gjør at ComfyUI kan oppdateres uten frykt. (ComfyUI er GPL-3.0; å smelte
den inn i vår kode ville smittet lisensen.)

**`job_key`, ikke `order_id`.** Én WooCommerce-ordre kan inneholde flere bøker.
Da har alle samme `order_id` (`1411`) og bare `job_key` skiller dem
(`1411-b1`, `1411-b2`). `job_key` er mappe- og filnøkkelen overalt.

**`continue_code` regenereres ALDRI.** Den lages bare i WordPress, og den er
trykt i boka. En reprint må bruke samme kode.

**Kun hardcover selges.** Softcover er default i koden, så `cover_type` sendes
alltid eksplisitt.

**«Er siden ferdig?» ser KUN i ordrens egen output-mappe.** Sidenøklene
(`page00`..`page15`) er like i alle bøker. Da to samtidige ordre fikk se i
hverandres mapper (14.09.2026), hoppet de over hverandres sider — bildene var
ikke feil, de var *borte*.

**PDF-guarden er streng med vilje.** Innersider må ha nøyaktig
`expectedInnerPages` (30 eller 31), samlet PDF nøyaktig 33. Feil antall stopper
ordren. Ikke «fiks» dette: en PDF med 14 innersider blir en trykt bok med 14
innersider.

**Drive-filer over 100 MB må bruke `drive.usercontent`-URL.** `/uc`-lenka gir
en HTML-advarselside, Gelato laster ned 2 kB HTML, og item-et står igjen uten
fil. `gelato_api.verify_draft()` fanger det nå — ikke fjern den sjekken.

**Ikke kjør minnetunge ting mens en ordre går.** Tung lokal RAM-bruk sulter ut
ComfyUIs event-loop. En side gikk fra 69 s til 178 s, og `/prompt` timet ut.

**Kundedata skal aldri ut av maskinen.** `/api/jobs` og `/api/queue` inneholder
barnenavn, `/api/health` inneholder hele ComfyUI-argv. Bare `/api/status*` er
ment å nå ut, og den har sin egen port (8766) med bare tre ruter montert — se
`flow/worker/status_api.py`. Ikke monter noe nytt der.

---

## Den viktigste feilklassen: stille fallback

Fire ganger har en feil nådd et trykkeklart utkast på **nøyaktig samme måte**:
koden fant ikke en fil, valgte noe annet, og sa ingenting.

| Ordre | Hva skjedde |
|---|---|
| 1510 | line2-logoen hadde flyttet seg. Rendreren skrev «ADVARSEL» og avsluttet med 0. Forsiden sa bare «Henry og det». |
| 1506 | tekstscriptene pekte på `<rot>/flow/books/…` etter en mappeflytting. Alle bøker på alle fem språk falt tilbake på den delte, gamle åpningssida. |
| 1528 | `cleanup_comfy_folder` hadde slettet de rendrede sidene etter at utkastet ble laget. En ombygging fra Telegram kjørte `prepare_order`, som kopierer base-maler inn først og henter faceswappede sider fra `comfy/` etterpå — den fant 2 av 12. **12 råe maler gikk til Gelato.** |
| — | `build_face_variants.py` hadde port 8188 hardkodet som fallback mens vi kjører 8189. Trist-varianten gikk mot en instans uten modeller. |

Ordre 1528 la til en vri verdt å merke seg: advarselen fantes, men den var
**allerede normal**. `prepare_order_styrken.py` har `page09`, `page10` og
`page14` i kartet sitt uten at de står i `config.json`, så tre
`[ADVARSEL]`-linjer kommer på hver eneste bygging av den boka. Tolv ekte
advarsler så ut som mer av det samme.

> Et varsel som alltid står på, varsler ingenting. Er noe forventet, skal det
> ikke advares om.

Kjeden er fail-soft **med vilje**: et oppsalg skal aldri stoppe en betalt ordre.
Derfor er regelen:

> Et fallback skal **rope**. Og mangelen skal oppdages **før** rendringen, ikke
> under den.

Konkret, når du skriver kode her:

* Utleder du en sti relativt til `__file__`, gå **oppover til du finner et
  holdepunkt** (slik `_dp_find_root` leter etter `books/`). Ikke tell mapper med
  `dirname(dirname(...))` — det brekker neste gang noe flyttes.
* Bruk `flow/paths.py`: `ROOT`, `under("state/x")` for våre egne mapper, og
  `resolve()` for stier som kommer fra konfigurasjon eller payload. De 116
  hardkodede `C:\DreamPage-OS` som lå i gammel kode er borte;
  `tools/check_portability.py` fanger nye, og kjøres av `dreampage.ps1 test`.
* Legger du til en kunst- eller fontsti, sørg for at `tools/check_assets.py`
  finner den. Den leser stier ut av JSON-konfigurasjonen og ut av tekstscriptenes
  **syntakstre** — den har ingen egen liste som kan bli utdatert.
* Er noe valgfritt, `optional=True` på steget. Er det ikke det, skal det kaste.

---

## Slik kjører du ting

```powershell
.\dreampage.ps1 up        # start alt
.\dreampage.ps1 status    # hva lever, hva står i køen, hvor står ordren
.\dreampage.ps1 down      # nekter å stoppe midt i en ordre uten -Force
.\dreampage.ps1 logs      # følg flow-loggen
.\dreampage.ps1 test      # ALLE testene + check_assets + check_portability
.\dreampage.ps1 ensure    # vaktmesteren (scheduled task, hvert 5. min)
.\dreampage.ps1 mode      # book eller preview
```

På Linux heter den `./dreampage.sh` og tar de samme kommandoene
(`docs/SETUP-LINUX.md`).

Hvor stoppet ordre X, og hvorfor:

```powershell
python flow\worker\cli.py status --job-key 1515
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/jobs/1515
```

Panelet: `http://127.0.0.1:8765/panel` — lim inn et token fra `config/api.json`.

**Kjør alltid `.\dreampage.ps1 test` før du committer.** Den tar under et
minutt og kjører alle testfilene pluss `check_assets`.

---

## Konvensjoner i denne kodebasen

**Kommentarer og docstrings er på norsk**, og forklarer *hvorfor*, ikke *hva*.
Nesten hver ikke-åpenbare linje viser til ordrenummeret eller datoen som gjorde
den nødvendig. Behold det. Når du fjerner noe som ser overflødig ut, se etter
kommentaren som forteller hva det kostet sist.

**Kildekoden bruker ASCII-translitterasjon** i kommentarer: `aa` for å, `oe`
for ø, `ae` for æ (`aapningsside`, `koe`, `vaere`). Markdown-filer og tekst som
vises til mennesker bruker ekte norske tegn. Følg fila du er i.

**Linjeskift:** repoet er blandet CRLF/LF. Leser du en fil og skriver den
tilbake, **bevar linjeskiftet den hadde** — ellers blir diffen på 200 linjer til
en diff på 60 000.

**Pipelinen er data, ikke kode.** Rekkefølge, retry, timeout og sjekkpunkt står
som en liste i `flow/worker/pipeline.py`. Skal du endre oppførsel, endre steget
eller listen — ikke skriv en ny if-gren i runneren.

**Hemmeligheter ligger i `config/secrets.json`** (gitignorert), lest via
`flow/dp_secrets.py`. Aldri i kildekoden. Git-historikken er skrubbet ren én
gang allerede.

**Koden skal kjøre på Windows OG Linux.** Denne maskinen er Windows og blir
det en stund til; nye maskiner settes opp på Linux. Derfor:

* Ingen hardkodede stier. Bruk `flow/paths.py` — `ROOT`, `under("state/x")`,
  og `resolve()` for stier som kommer fra konfigurasjon eller payload.
* **En `if windows:` i produksjonskoden er en feil.** Er noe forskjellig,
  hører det hjemme i `flow/dp_platform.py`, bak et navn som sier hva det
  gjør. I dag: oppetid, `~/.n8n`, kjørbare filer, hvilken vaktmester.
* Linux bryr seg om store og små bokstaver i filnavn. Windows gjør ikke, så
  den feilen er usynlig herfra — `tools/check_portability.py` sjekker hvert
  filnavn konfigurasjonen peker på mot det disken faktisk heter, og kjøres av
  `.\dreampage.ps1 test`.
* Supervisoren finnes i to utgaver (`dreampage.ps1`, `dreampage.sh` →
  `tools/dreampage.py`). Tjenestelista må stemme i begge;
  `test_supervisorene_er_enige` holder dem sammen.

`docs/SETUP-LINUX.md` er oppsettet på Linux.

## Før du gjør noe utoverrettet

Å laste opp til Drive, lage et Gelato-utkast, sende Telegram-melding eller
publisere til WooCommerce er handlinger som treffer verden utenfor maskinen, og
noen av dem koster penger. **Spør først**, med mindre brukeren allerede har bedt
om nøyaktig den handlingen.

`reprint_order.py` lager bare et Gelato-utkast med `--gelato`, og det er med
vilje.
