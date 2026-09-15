# archive/ — engangs-patcher fra n8n-tiden

44 filer. De blir verdiløse den dagen n8n er borte, men de er lagt i git først,
fordi de inntil da er den **eneste lesbare kilden** til hvorfor en node ser ut
som den gjør. Selve logikken ligger som JavaScript i en SQLite-blob; disse
skriptene er strengerstatning mot den blobben over n8n sitt REST-API.

## §7-gjennomgangen: inneholder noen av dem ekte logikk?

Oppdraget krever at dette sjekkes før arkivering. Alle 14 `patch_worker_*.py`
er lest strukturelt (`ast`) og manuelt:

| Fil | Python-funksjoner | JS-nyttelast |
|---|---|---|
| `patch_worker_add_book_egget.py` | `patch`, `main` | 0 % |
| `patch_worker_add_book_fotball_vm.py` | `patch`, `main` | 0 % |
| `patch_worker_auto_merge.py` | `find`, `main` | 25 % |
| `patch_worker_comfy_restart_resilience.py` | `main` | 1 % |
| `patch_worker_continue_fix.py` | `patch`, `main` | 27 % |
| `patch_worker_continue_qr.py` | `cmd`, `build_new_nodes`, `patch`, `main` | 17 % |
| `patch_worker_gelato_url.py` | `load_api_key`, `req`, `main` | 23 % |
| `patch_worker_job_key.py` | `load_api_key`, `req`, `slot`, `main` | 0 % |
| `patch_worker_lastpage_args.py` | `main` | 30 % |
| `patch_worker_merge_off.py` | `one`, `patch`, `main` | 37 % |
| `patch_worker_merge_orders.py` | `build_nodes`, `one`, `apply_patch`, `revert_patch`, `main` | 29 % |
| `patch_worker_next_cover_persist.py` | `load_api_key`, `req`, `main` | 0 % |
| `patch_worker_page_output_scope.py` | `main` | 34 % |
| `patch_worker_upload_mockup.py` | `main` | 7 % |

**Konklusjon: ingen av dem gjør ekte arbeid.** Python-funksjonene er i alle 14
tilfellene det samme stillaset — `load_api_key` (leser n8n-legitimasjon),
`req` (HTTP mot n8n sitt API), `find`/`one`/`slot` (finn node i JSON-treet),
`patch`/`main` (strengerstatning + PUT). Ingenting av det skal migreres til
`flow`; det forsvinner sammen med n8n.

**Men JS-nyttelasten skal migreres.** Det er dagens oppførsel, skrevet i et
format man kan lese. Disse seks er derfor spesifikasjonen for fase 2 og 5, og
må leses før stegene skrives på nytt i Python:

- `patch_worker_page_output_scope.py` (34 % JS) — «er siden ferdig?» skal
  **kun** se i ordrens egen output-mappe. Uten dette hoppet to samtidige ordre
  14.09.2026 over hverandres sider. Sidenøklene er like i alle bøker.
- `patch_worker_comfy_restart_resilience.py` — overlev at ComfyUI starter på
  nytt midt i en jobb. Etter fase 2 skal dette være strukturelt umulig å feile,
  ikke håndtert av et spesialtilfelle.
- `patch_worker_job_key.py` — `job_key` erstatter `order_id` som mappe- og
  filnøkkel. Én WooCommerce-ordre kan inneholde flere bøker.
- `patch_worker_continue_qr.py` + `patch_worker_continue_fix.py` — hele
  «fortsett eventyret»-QR-oppsettet, inkludert `page99_next`.
- `patch_worker_next_cover_persist.py` — `pdf/page99_next*` →
  `state/next_cover/`, så neste-bok-forsiden overlever ordren.
- `patch_worker_gelato_url.py` — Drive-filer over 100 MB må ha
  `drive.usercontent`-URL. `/uc`-lenka gir en HTML-advarselside, og Gelato
  henter aldri filen inn.

Den fullstendige og autoritative beskrivelsen av alle 82 noder ligger i
`docs/n8n-worker-v2.redacted.json` — eksportert fra den kjørende workflowen
`xy8qiRUzcBpH52CI` 2026-09-15, med token og API-nøkler redigert bort.

## Ikke i git

`worker-continue-qr.patched.json` (107 KB) er en rå n8n-eksport med bot-token
og Gelato-nøkkel spredt gjennom hele filen. Å redigere den ville gjort den
verdiløs som historisk dokument, så den ligger på disk og står i `.gitignore`.
Bruk den redigerte eksporten i `docs/` i stedet.

## De øvrige 30

`patch_title_tester_*` (6) patcher workflowen «DP Title Tester»
(`1BqeGkXyjbUBsR9N`, inaktiv) — samme stillas.
`fix_*` (7), `rewrite_*` (2), `tune_*` (2), `patch_*` for enkeltbøker og
`motet_story.py` skrev historier og layoutparametre inn i tekstskriptene én
gang. Resultatet står i `flow/text/<locale>/`; skriptene er kvitteringen.
