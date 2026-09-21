# Servermodus: BOOK og PREVIEW

En DreamPage-server gjør **én** ting. Hva den gjør står i
`config/flow.json` → `"mode"`:

| Modus | Kø | Pipeline | Hva den lager |
|---|---|---|---|
| `book` | `dreampage-jobs` | `full` (se `pipeline.ACTIVE`) | hele boka: sider → PDF → Drive → **Gelato-utkast** |
| `preview` | `preview-jobs` | `preview` | ett bilde til nettbutikken: én side → tittel/tekst → Supabase + callback |

```
DreamPage OS  (config/flow.json -> mode)
  ├── BOOK     -> RabbitMQ dreampage-jobs -> DreamPage Flow: Book Generation
  └── PREVIEW  -> RabbitMQ preview-jobs   -> DreamPage Flow: Preview Generation
```

**Denne maskinen står i `book`.** Den lager ekte bøker for ekte kunder.

## Bytte modus

```powershell
.\dreampage.ps1 mode              # hva står den til nå
.\dreampage.ps1 mode preview      # bytt
.\dreampage.ps1 restart           # først da virker byttet
```

`DP_MODE=preview` i miljøet overstyrer fila (brukes av testene).

En ukjent verdi er en **feil**, ikke «da tar vi book»: flow nekter å starte.
En preview-PC som stille falt tilbake til bokmodus ville koblet seg på køen
med ekte, betalte bokordre.

**Tøm køen før du bytter.** `runner.start()` legger jobber som står `pending`
eller `running` i `state/jobs.sqlite` tilbake på den interne køen — og etter
et bytte kjøres de gjennom den *nye* pipelinen. En bokordre som havner i
preview-pipelinen feiler riktignok med en gang («mangler job_id»), permanent
og synlig, så den blir ikke til en halv bok. Men den blir stående som
`failed` til noen bytter tilbake og ber om retry. Sjekk først:

```powershell
.\dreampage.ps1 status
```

## Hva modusen faktisk endrer

Nøyaktig to ting, og de står som **data** i `flow/worker/config.py`:

```python
"modes": {
    "book":    {"queue": "dreampage-jobs", "pipeline": None},
    "preview": {"queue": "preview-jobs",   "pipeline": "preview"},
}
```

* `queue` → hvilken kø `mq.Consumer` lytter på.
* `pipeline` → hvilken liste `runner` kjører. `null` betyr «bruk
  `pipeline.ACTIVE`», som er bokas eget valg mellom `pages` og `full`.

`dreampage.ps1` bruker den i tillegg til å la være å starte to tjenester i
preview-modus: **dp_bot** (to pollere på samme Telegram-token spiser
hverandres oppdateringer — det er derfor `ensure_dp_bot.ps1` finnes) og
**mockup** (lager produktbilder av ferdige bokordre; en preview-PC har ingen).

Alt annet er **delt**, fordi det er infrastruktur og ikke arbeidsflyt:
jobb-DB-en, REST-API-et, panelet, per-jobb-loggen, statusendepunktene,
avbrudd, retry, ack-semantikken mot RabbitMQ — og selve side-løkka mot
ComfyUI, med regelen om at en jobb bare får se i sin **egen** output-mappe.

## Preview Generation Flow

`flow/worker/pipeline.py` → `PREVIEW_PIPELINE`:

| Steg | Hva |
|---|---|
| `check_delivery` | Er Supabase satt opp? **Før** GPU-en brukes. |
| `validate_preview_job` | Payload → bok, marked, side, mal, tittel. Sjekker mal, maske, workflow og **line2-logoen**. |
| `status_processing` | `processing` i statusfila. Sidespor. |
| `fetch_child_image` | → `input/preview-<job_id>.jpg`. Samme nedlaster som bøker. |
| `render_preview_page` | Én side gjennom ComfyUI, i jobbens egen mappe. **Sjekkpunkt.** |
| `render_preview_text` | Tittel + logo (omslag), eller **bokas egen side** (innerside). |
| `deliver_preview` | Bilde opp → `completed` → callback. **Sjekkpunkt.** |
| `notify_preview` | Telegram, hvis `preview.notify_each`. Sidespor. |
| `cleanup_preview` | Slett den rå sida. Sidespor. |

Pipelinen inneholder **ingen** steg som koster penger: ingen PDF, ingen
Drive, ingen Gelato, ingen WooCommerce. Det er ikke en regel noen må huske —
stegene finnes ikke i listen, og `test_preview_roerer_ikke_penger` holder
det slik.

## Meldingen på `preview-jobs`

Kontrakten mot nettbutikken. JSON, publisert av WordPress.

**Påkrevd**

| Felt | |
|---|---|
| `job_id` | nøkkelen jobben lagres, logges og leveres under |
| `stored_image_url` | offentlig URL til barnets bilde |

**Leses hvis til stede**

| Felt | |
|---|---|
| `product_handle` / `book_title` | hvilken bok |
| `child_name`, `gender` | navn i tittelen; gender avgjør jente/gutt-utgaven |
| `language`, `site_language`, `market`, `language_variant` | marked: `nb`/`en`/`sv`/`uk` |
| `asset_type` | inneholder «inner» → innerside i stedet for omslag |
| `preview_callback_url` | POSTes resultatet; `/inner/` i stien betyr også innerside |
| `dp_session_id` | mappe i Supabase-stien |
| `preview_token` | sendes tilbake i callbacken |

En melding uten `job_id` forkastes (og ackes) — den blir ikke bedre av å
komme tilbake. I **bokmodus** leses `job_id` ikke i det hele tatt: en bok-PC
som godtok den kunne kjørt en preview-melding gjennom hele bokpipelinen.

## Hvor resultatet havner

| | |
|---|---|
| Statusfil | `uploads/preview-jobs/<job_id>.json` i Supabase — `processing` → `completed`/`failed`. Skrives **alltid** også til `state/preview_jobs/<job_id>.json`. |
| Bildet | `storage/previews/<dp_session_id>/<job_id>_preview.jpg` |
| Callback | POST til `preview_callback_url` med `preview_url` |

Bildet lastes opp **først**, så statusfila, så callbacken: en `completed` med
en URL som ikke finnes er verre enn en spinner.

Feiler jobben, skriver `notify.job_failed` `failed` i statusfila. Uten det
ville frontenden pollet en `processing` som aldri ble noe — samme stillhet
som ordre 1517, bare med en kunde foran seg.

Legitimasjonen står i `config/secrets.json` under `"supabase"`
(`url` + `service_key`). Mangler den, feiler jobben i **første** steg.
`preview.sink` kan settes til `"local"` for utvikling — da blir bildet
liggende på disk, og URL-en er en `file://`-sti som sier det selv.

## Per-bok-data

Se `config/preview/README.md`. Kort:

* Omslag, innersider, masker, workflow og `patchNodes` leses fra
  **`books/<slug>/config.json`** — nøyaktig det boka trykkes med.
* `line1`/`line2`/logo/font leses fra **`config/next_book_titles.json`**,
  som selv sier `"source": "preview-worker"`.
* **Historieteksten på innersider leses fra bokas eget tekstscript**,
  `flow/text/<lokale>/<bok>-text-<lokale>.py`.
* `config/preview/markets/<marked>.json` er **påkrevd** og sier språk og
  logomappe.
* `config/preview/books/<marked>/<slug>.json` er **valgfri**, og sier for
  innersider bare HVILKEN side som skal vises — ikke hva som står på den.

Ingenting er kopiert. En kopi ville gått ut av synk, og da ville
forhåndsvisningen og den trykte boka sagt to forskjellige ting.

### Innersider: side 7 er side 7

`flow/pre/render-innerpage.py` importerer bokas tekstscript, kaller
`build_pages(child_name)` og lar bokas egen `render_page()` tegne sida. Det
eneste som er byttet ut er `save_split_a5` — et preview er ett bilde, ikke to
trykksider på 2625 px.

Derfor følger alt med uten å være etterlignet: navnebyttet, de automatisk
uthevede ordene, delingen i to balanserte blokker, den mørke puta bak
teksten, venstre/høyre kolonne, y-offsets og den automatiske krympingen av
skriften. Endrer noen teksten på side 7, endrer forhåndsvisningen seg i
samme øyeblikk.

Broen mellom de to er **malfilnavnet**: `template_image` i
`books/<slug>/config.json` og `filename` i tekstscriptet er den samme
strengen (`07(dyreparken).png`). Stemmer de ikke, feiler jobben med en liste
over sidene tekstscriptet faktisk kjenner.

## Hva som ikke har stille fallback

Alt dette stopper jobben, med en setning som sier hva som mangler — og alt
skjer **før** rendringen:

* ukjent bok → hard feil, aldri en annen bok
* manglende markedsconfig → hard feil, aldri nabospråket
* manglende `line2_image` → hard feil (ordre 1510: forsiden som bare sa
  «Henry og det» — her er det kunden som ser den)
* innerside uten `innerpage`-seksjon (sidevalget) → hard feil
* innerside der malfilnavnet ikke finnes i tekstscriptet → hard feil, med en
  liste over sidene som finnes
* innerside der boka ikke har tekst på den sida → hard feil. En ren
  illustrasjonsside kan være riktig i boka, men er et dårlig valg for en
  forhåndsvisning — og valget skal tas av et menneske, ikke oppdages av en
  kunde.
* Supabase ikke satt opp → hard feil, aldri en fil på lokal disk

## Sjekk oppsettet

```powershell
.\dreampage.ps1 mode
.\dreampage.ps1 test          # 53 tester + check_assets + comfy_workflows
python tools\check_assets.py  # leser også config/preview/**/*.json
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/health
```

`/api/health` og `/api/workflows` viser `mode` (navn, kø, pipeline).
`/api/status` viser bare navnet — der slipper ingen kundedata ut.
